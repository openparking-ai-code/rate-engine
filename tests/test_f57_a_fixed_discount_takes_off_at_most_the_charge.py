"""F57 -- fixed amounts are taken in full; the fee is floored at zero once.

A fixed-amount discount was not limited to the charge, so a stay cheaper than
the discount went below zero and the engine refused it as a negative fee:
$3 the first hour, $3 an hour after, "Weekend $5 off", and every Saturday stay
of 60 minutes or less closed unpriced.

The first fix limited each fixed discount to the charge running when it was
taken. That made the price depend on the order the specials were listed in:
"Weekend $5 off" then "Event fee $4" on a 60-minute Saturday stay at $3 was
0 + 4 = 4.00, and the other way round 7 - 5 = 2.00.

**Now (the rule "the cheapest price always wins"):**
every fixed discount and increase is taken in full, so fixed amounts commute,
and a total the adjustments take below zero is brought back to zero ONCE, after
all of them, by its own line (`adjust.floor`). The example is 2.00 whichever
way the two are listed, and a stay cheaper than its discount is priced at zero.
A percentage is never worked out on a total below zero. A total that was already
below zero before the adjustments is not floored: it is refused by its own
code (F21).
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import make_stay, quote
from rate_engine.findings import Refused
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import time_window
from rate_engine.validator import probe_stays, validate_plan

PLAN = {
    "plan_version": "weekend-off-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                   "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 300, "repeat_period_minutes": 60,
         "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "weekend", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard"], "label": "Weekend $5 off",
         "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
         "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
         "day_span": "any_span",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "fixed", "minor": 500},
                    "rounding": "down"}},
    ],
    "decisions": [],
}

SATURDAY = "2026-03-07T10:00:00-05:00"


def _quote(exit_: str, plan: dict | None = None):
    return run_quote(
        {"plans": [copy.deepcopy(plan or PLAN)], "entry_at": SATURDAY, "exit_at": exit_,
         "space_class": "standard", "currency": "USD"}
    )


def _weekend_adjust(id_: str, label: str, direction: str, amount: dict) -> dict:
    """A weekend ADJUST shaped like the plan's own, as the admin writes one."""
    return {"id": id_, "type": "time_window", "stage": "ADJUST",
            "space_classes": ["standard"], "label": label,
            "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
            "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
            "day_span": "any_span",
            "effect": {"kind": "adjust", "direction": direction, "amount": amount,
                       "rounding": "down"}}


EVENT_FEE = _weekend_adjust(
    "event", "Event fee $4", "increase", {"kind": "fixed", "minor": 400}
)


def _with(*adjusts: dict, order: list[str]) -> dict:
    plan = copy.deepcopy(PLAN)
    plan["rules"] += [copy.deepcopy(a) for a in adjusts]
    plan["adjust_order"] = order
    return plan


def _discount_line(body: dict) -> dict:
    return next(ln for ln in body["breakdown"] if ln["rule_id"] == "weekend")


def _floor_lines(body: dict) -> list[dict]:
    return [ln for ln in body["breakdown"] if ln["code"] == "adjust.floor"]


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize(
    "exit_", ["2026-03-07T10:00:00-05:00", "2026-03-07T10:59:00-05:00",
              "2026-03-07T11:00:00-05:00"],
)
def test_a_stay_cheaper_than_the_discount_is_priced_at_zero(exit_):
    status, body = _quote(exit_)
    assert status == 200, f"a stay cheaper than the discount was refused: {body}"
    assert body["fee_minor"] == 0
    assert _discount_line(body)["delta_minor"] == -500, "the discount is taken in full"
    [floor] = _floor_lines(body)
    assert floor["delta_minor"] == 200, "once, at the end, back to zero"
    assert "stops at 0.00 USD rather than -2.00 USD" in floor["text"], floor["text"]
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 0


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize(
    "exit_,fee", [("2026-03-07T11:01:00-05:00", 100), ("2026-03-07T12:01:00-05:00", 400)],
)
def test_a_discount_smaller_than_the_charge_is_taken_in_full(exit_, fee):
    """The control on the item above: past the first hour the stay costs more
    than 5.00, so the whole 5.00 comes off and nothing is floored."""
    status, body = _quote(exit_)
    assert status == 200, body
    assert body["fee_minor"] == fee
    assert _discount_line(body)["delta_minor"] == -500
    assert _floor_lines(body) == []


@pytest.mark.guarantee("F57")
def test_every_stay_the_plan_check_probes_is_priced():
    """The plan check reports this plan clean, and that is true of every stay it
    probes: none is refused at the counter."""
    plan = load_plan(copy.deepcopy(PLAN))
    assert validate_plan(plan) == []
    refused = []
    for stay in probe_stays(plan):
        try:
            quote([plan], stay)
        except Refused as refused_stay:
            codes = [f.code for f in refused_stay.findings]
            refused.append((stay.entry_at.isoformat(), stay.duration_minutes, codes))
    assert refused == []


# --- fixed amounts commute ---------------------------------------------------


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize("order", [["weekend", "event"], ["event", "weekend"]])
def test_a_fixed_discount_and_increase_charge_the_same_in_either_order(order):
    """3.00 - 5.00 + 4.00 = 2.00, and 3.00 + 4.00 - 5.00 = 2.00."""
    status, body = _quote("2026-03-07T11:00:00-05:00", _with(EVENT_FEE, order=order))
    assert status == 200, body
    assert body["fee_minor"] == 200
    assert _discount_line(body)["delta_minor"] == -500
    event = next(ln for ln in body["breakdown"] if ln["rule_id"] == "event")
    assert event["delta_minor"] == 400, "a fixed increase is added in full"
    assert _floor_lines(body) == [], "the total never ends below zero, so nothing is floored"
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 200


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize("order", [["weekend", "event"], ["event", "weekend"]])
def test_discounts_beyond_the_charge_and_an_increase_floor_once_in_either_order(order):
    """5.00 off and 1.00 added on 3.00 is -1.00 either way: floored once to 0.00."""
    small_fee = _weekend_adjust(
        "event", "Event fee $1", "increase", {"kind": "fixed", "minor": 100}
    )
    status, body = _quote("2026-03-07T11:00:00-05:00", _with(small_fee, order=order))
    assert status == 200, body
    assert body["fee_minor"] == 0
    [floor] = _floor_lines(body)
    assert floor["delta_minor"] == 100
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 0


@pytest.mark.guarantee("F57")
def test_a_fixed_increase_larger_than_the_charge_is_added_in_full():
    """10.00 added to a 3.00 stay is 13.00."""
    big_fee = _weekend_adjust(
        "event", "Event fee $10", "increase", {"kind": "fixed", "minor": 1000}
    )
    plan = copy.deepcopy(PLAN)
    plan["rules"] = [r for r in plan["rules"] if r["id"] != "weekend"] + [big_fee]
    status, body = _quote("2026-03-07T11:00:00-05:00", plan)
    assert status == 200, body
    assert body["fee_minor"] == 1300
    event = next(ln for ln in body["breakdown"] if ln["rule_id"] == "event")
    assert event["delta_minor"] == 1000


@pytest.mark.guarantee("F57")
def test_150_percent_then_5_off_no_longer_loads():
    """A percentage over 100% does not load (F60), so it never reaches the floor."""
    over = _weekend_adjust("over", "150% off", "discount", {"kind": "percent", "percent_bp": 15000})
    status, body = _quote("2026-03-07T11:00:00-05:00", _with(over, order=["over", "weekend"]))
    assert status == 400, f"a plan with a 150% discount loaded: {body}"
    assert body["code"] == "INVALID_PERCENT_DISCOUNT_OVER_100", body


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize("running_total", [-150, 0, 300])
def test_a_fixed_discount_line_takes_its_whole_amount(running_total):
    """The line itself takes its whole amount, whatever the total it meets; the
    floor is the stage's, once, not the line's."""
    plan = load_plan(copy.deepcopy(PLAN))
    rule = next(r for r in plan.rules if r.id == "weekend")
    stay = make_stay(parse_instant(SATURDAY, "entry"),
                     parse_instant("2026-03-07T11:00:00-05:00", "exit"), "standard")
    [line] = time_window.apply(rule, stay, plan, running_total)
    assert line.delta_minor == -500, line.text
    assert "limited" not in line.text, line.text


# --- a percentage is never worked out on a total below zero ------------------

HALF_OFF = _weekend_adjust("half", "50% off", "discount", {"kind": "percent", "percent_bp": 5000})


@pytest.mark.guarantee("F57")
@pytest.mark.parametrize("direction", ["discount", "increase"])
def test_a_percentage_of_a_total_below_zero_is_a_percentage_of_nothing(direction):
    """On -2.00 a percent discount takes off nothing (it would add money) and a
    percent increase adds nothing (it would take money off)."""
    rule_doc = _weekend_adjust("pct", "50%", direction, {"kind": "percent", "percent_bp": 5000})
    plan = load_plan(_with(rule_doc, order=["weekend", "pct"]))
    rule = next(r for r in plan.rules if r.id == "pct")
    stay = make_stay(parse_instant(SATURDAY, "entry"),
                     parse_instant("2026-03-07T11:00:00-05:00", "exit"), "standard")
    [line] = time_window.apply(rule, stay, plan, -200)
    assert line.delta_minor == 0, line.text
    assert "on 0.00 USD" in line.text, line.text


@pytest.mark.parametrize(
    "order",
    [["weekend", "half", "event"], ["half", "weekend", "event"], ["event", "half", "weekend"]],
)
@pytest.mark.guarantee("F57")
def test_adding_a_discount_never_raises_the_fee_and_the_order_never_moves_it(order):
    """$5 off, 50% off and a $4 fee on a 3.00 stay: the car pays the cheapest
    order of them (F35), 0.00 whichever the plan states -- never more than the
    2.00 the same stay costs without the 50% off."""
    without = _quote("2026-03-07T11:00:00-05:00", _with(EVENT_FEE, order=["weekend", "event"]))[1]
    status, body = _quote("2026-03-07T11:00:00-05:00", _with(EVENT_FEE, HALF_OFF, order=order))
    assert status == 200, body
    assert body["fee_minor"] == 0
    assert body["fee_minor"] <= without["fee_minor"] == 200
    for line in body["breakdown"]:
        if line["code"] == "time_window.applied":
            direction = "discount" if "discount" in line["text"] else "increase"
            assert (line["delta_minor"] <= 0) == (direction == "discount"), line["text"]
