"""F35 -- two adjustments both apply, and the ORDER is the plan's to state.

**Not a choice between them. A sequence.** Twenty per cent off then five dollars
off is not five dollars off then twenty per cent off, and the difference is money
on a receipt. So this is neither the QUALIFY case -- where one rule wins and the
resolution mode picks -- nor the CAP case, where both apply and the total comes
out the same whichever ran first. It is a third thing, and it carries its own
finding code so a consumer routing on codes can tell "settle which of these is
the price" from "tell me what order to apply both in".

`adjust_order` deliberately does NOT live inside `resolution`. That field records
CHOICES, and an order is not a choice. It is required-and-nullable like
`max_duration_minutes` and `week_starts_on`, because a field that may simply be
absent is a field somebody forgets while believing they set it.

**A rule missing from a stated order is a refusal, not a silent position.** That
is the array-order disease this module already refuses at `select_plan`, where
two plan versions sharing a date used to be settled by whichever the caller put
first.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.findings import CONFLICT_UNORDERED_ADJUSTMENTS

RESOLUTION = {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}}
EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}

BASE = 3200  # 800 + 6 x 400, seven hours on the rate below

PERCENT_OFF = {
    "id": "pct", "type": "time_window", "stage": "ADJUST",
    "space_classes": ["standard"], "label": "Midweek 20% off",
    "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
    "exit_by": "23:59", "day_span": "any_span",
    "effect": {"kind": "adjust", "direction": "discount",
               "amount": {"kind": "percent", "percent_bp": 2000}, "rounding": "down"},
}
FIVE_OFF = {
    "id": "voucher", "type": "time_window", "stage": "ADJUST",
    "space_classes": ["standard"], "label": "Voucher 5.00 off",
    "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
    "exit_by": "23:59", "day_span": "any_span",
    "effect": {"kind": "adjust", "direction": "discount",
               "amount": {"kind": "fixed", "minor": 500}, "rounding": "down"},
}

#: percent first: 3200 - 640 = 2560, then -500 = 2060.
PERCENT_THEN_FIXED = 2060
#: fixed first: 3200 - 500 = 2700, then 20% of 2700 = 540 off = 2160.
FIXED_THEN_PERCENT = 2160


def _plan(adjust_order=None) -> dict:
    return {
        "plan_version": "order-2026-03",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD",
        "space_classes": ["standard"],
        "resolution": RESOLUTION,
        "adjust_order": adjust_order,
        "rules": [
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 800, "repeat_period_minutes": 60,
             "repeat_period_minor": 400, "rounding": "ceil",
             "max_duration_minutes": None},
            copy.deepcopy(PERCENT_OFF),
            copy.deepcopy(FIVE_OFF),
        ],
        "decisions": [],
    }


def _quote(plan: dict):
    return run_quote(
        {
            "plans": [plan], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T16:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def test_the_two_ORDERS_genuinely_disagree():
    """The control on the fixture, and it runs first. If these matched, the car
    paying the cheapest order would be ceremony rather than arithmetic."""
    assert PERCENT_THEN_FIXED != FIXED_THEN_PERCENT


@pytest.mark.guarantee("F35")
def test_no_stated_order_is_REFUSED_and_names_BOTH():
    status, body = _quote(_plan(adjust_order=None))
    assert status == 422, body
    finding = body["findings"][0]
    assert finding["code"] == CONFLICT_UNORDERED_ADJUSTMENTS
    assert set(finding["rule_ids"]) == {"pct", "voucher"}
    assert "pct" in finding["text"] and "voucher" in finding["text"]
    assert "adjust_order" in finding["text"], finding["text"]


@pytest.mark.guarantee("F35")
@pytest.mark.parametrize("order", [["pct", "voucher"], ["voucher", "pct"]])
def test_either_stated_order_charges_the_cheapest_order(order):
    """The car pays the cheapest order of the specials that apply (the owner's
    rule "the cheapest price always wins", read by Claude, as the fill rule
    already is): 20% off then 5.00 off, 20.60, whichever the plan states."""
    status, body = _quote(_plan(adjust_order=order))
    assert status == 200, body
    assert body["fee_minor"] == PERCENT_THEN_FIXED
    [said] = [ln for ln in body["breakdown"] if ln["code"] == "adjust.order"]
    assert "pct, voucher" in said["text"] and "21.60 USD" in said["text"], said["text"]
    assert said["delta_minor"] == 0


@pytest.mark.guarantee("F35")
def test_the_BREAKDOWN_follows_the_order_taken():
    """The receipt reads in the order the money moved, so the second adjustment
    names the total the first one left behind."""
    _s, body = _quote(_plan(adjust_order=["voucher", "pct"]))
    adjustments = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"]
    assert [ln["rule_id"] for ln in adjustments] == ["pct", "voucher"]
    assert "on 25.60 USD" in adjustments[1]["text"], adjustments[1]["text"]


@pytest.mark.guarantee("F35")
def test_where_the_order_changes_nothing_the_stated_order_is_kept():
    """Two fixed amounts commute: the plan's own order is the one on the
    receipt, never the rule ids' order."""
    plan = _plan(adjust_order=["voucher", "a-member"])
    member = copy.deepcopy(FIVE_OFF)
    member.update(id="a-member", label="Member 2.00 off")
    member["effect"]["amount"]["minor"] = 200
    plan["rules"] = [r for r in plan["rules"] if r["id"] != "pct"] + [member]
    status, body = _quote(plan)
    assert status == 200, body
    assert body["fee_minor"] == BASE - 500 - 200
    adjustments = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"]
    assert [ln["rule_id"] for ln in adjustments] == ["voucher", "a-member"]
    assert [ln for ln in body["breakdown"] if ln["code"] == "adjust.order"] == []


@pytest.mark.guarantee("F35")
def test_ONE_qualifying_adjustment_needs_no_order():
    """The control on the refusal: it must fire on ambiguity, not on the presence
    of an ADJUST rule."""
    single = _plan(adjust_order=None)
    single["rules"] = [r for r in single["rules"] if r["id"] != "voucher"]
    status, body = _quote(single)
    assert status == 200, body
    assert body["fee_minor"] == BASE - 640


@pytest.mark.guarantee("F35")
def test_two_adjustments_that_cannot_BOTH_qualify_need_no_order_either():
    """Refusing on rule COUNT rather than on what QUALIFIES would reject a plan
    with a weekday discount and a weekend one, which is an ordinary garage."""
    weekday_and_weekend = _plan(adjust_order=None)
    for rule in weekday_and_weekend["rules"]:
        if rule["id"] == "pct":
            rule["applies_on"] = {"kind": "days_of_week", "days": ["mon", "tue"]}
        if rule["id"] == "voucher":
            rule["applies_on"] = {"kind": "days_of_week", "days": ["sat", "sun"]}
    status, body = _quote(weekday_and_weekend)
    assert status == 200, body
    assert body["fee_minor"] == BASE - 640


@pytest.mark.guarantee("F35")
@pytest.mark.parametrize(
    "order,expected",
    [
        (["pct"], "Missing: voucher"),
        (["pct", "voucher", "hourly"], "Not an ADJUST rule in this plan: hourly"),
        (["pct", "pct"], "names a rule more than once"),
        ("pct,voucher", "must be a list of rule ids"),
        ([1, 2], "must be a list of rule ids"),
    ],
)
def test_an_order_that_does_not_name_every_adjustment_EXACTLY_ONCE_is_REFUSED(order, expected):
    """Named explicitly and exhaustively, never by position: a rule left out
    would otherwise take a silent place in the sequence."""
    status, body = _quote(_plan(adjust_order=order))
    assert status == 400, f"{order!r} was accepted"
    assert "adjust_order" in body["error"], body["error"]
    assert expected in body["error"], body["error"]


# --- beyond five specials, and the work a plan can make -----------------------

import itertools  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402

from rate_engine import engine  # noqa: E402
from rate_engine.engine import make_stay, quote  # noqa: E402
from rate_engine.plan import load_plan, parse_instant  # noqa: E402
from rate_engine.rules import RULE_APPLIERS  # noqa: E402


def _special(rule_id, direction, kind, value, rounding="down", days=None):
    amount = (
        {"kind": kind, "minor": value} if kind == "fixed" else {"kind": kind, "percent_bp": value}
    )
    return {
        "id": rule_id, "type": "time_window", "stage": "ADJUST", "space_classes": ["standard"],
        "label": rule_id,
        "applies_on": {"kind": "days_of_week", "days": days or EVERY_DAY["days"]},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "adjust", "direction": direction, "amount": amount,
                   "rounding": rounding},
    }


#: Six specials that all apply: two percent increases, a fixed increase, two
#: percent discounts and a fixed discount -- every kind, so the order matters.
SIX = [
    _special("p-up-a", "increase", "percent", 2500, "up"),
    _special("p-up-b", "increase", "percent", 1000, "down"),
    _special("f-up", "increase", "fixed", 400),
    _special("p-off-a", "discount", "percent", 3333, "down"),
    _special("p-off-b", "discount", "percent", 1000, "up"),
    _special("f-off", "discount", "fixed", 800),
]

FILL = {"id": "zz-fill", "type": "fill_level", "stage": "ADJUST", "space_classes": ["standard"],
        "threshold_bp": 8000, "percent_bp": 2000, "rounding": "up",
        "raises_specials": "yes", "raises_vip_extra": "no"}


def _with_specials(specials, order):
    plan = _plan(adjust_order=order)
    plan["rules"] = [plan["rules"][0]] + [copy.deepcopy(s) for s in specials]
    return plan


def _fee(plan, occupancy=None):
    doc = {"plans": [plan], "entry_at": "2026-03-03T09:00:00-05:00",
           "exit_at": "2026-03-03T16:00:00-05:00", "space_class": "standard", "currency": "USD"}
    if occupancy is not None:
        doc["occupancy_at_entry_bp"] = occupancy
    status, body = run_quote(doc)
    assert status == 200, body
    return body["fee_minor"]


@pytest.mark.guarantee("F35")
def test_beyond_five_the_listing_order_never_moves_the_price_and_never_beats_it(monkeypatch):
    """Six specials, all 720 listings: one price. And it is never dearer than
    any listing priced in its own order (what the engine charged before)."""
    ids = [s["id"] for s in SIX]
    fees = {_fee(_with_specials(SIX, list(order))) for order in itertools.permutations(ids)}
    assert len(fees) == 1, f"the listing order moved the price: {sorted(fees)}"
    [charged] = fees
    monkeypatch.setattr(engine, "_kind_orders", lambda applying, **_: None)
    own_orders = {_fee(_with_specials(SIX, list(order))) for order in itertools.permutations(ids)}
    assert charged <= min(own_orders), (charged, min(own_orders))
    assert charged < max(own_orders), "the fixture must have orders that cost more"


@pytest.mark.guarantee("F35")
def test_five_applying_beside_a_hundred_that_do_not_with_the_fill_rule_stays_cheap():
    """A garage's saved rates never slow an exit: five specials that apply, a
    hundred that do not (Mondays only, on a Tuesday) and the fill rule. Each
    rule that does not apply is asked for its line once a pass, never once per
    order tried, and the quote is well within a fixed time."""
    idle = [_special(f"idle-{i:03d}", "discount", "fixed", 100, days=["mon"]) for i in range(100)]
    five = SIX[:3] + SIX[3:5]
    rules = five + idle + [FILL]
    plan = load_plan(_with_specials(rules, [r["id"] for r in rules]))
    stay = make_stay(parse_instant("2026-03-03T09:00:00-05:00", "entry"),
                     parse_instant("2026-03-03T19:00:00-05:00", "exit"), "standard",
                     occupancy_at_entry_bp=9000)
    asked = Counter()
    original = RULE_APPLIERS["time_window"]

    def counting(rule, *args, **kwargs):
        asked[rule.id] += 1
        return original(rule, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(RULE_APPLIERS, "time_window", counting)
        started = time.perf_counter()
        quote([plan], stay)
        took = time.perf_counter() - started
    passes = 2  # one way, priced, then again with the losers' lines
    assert max(asked[f"idle-{i:03d}"] for i in range(100)) <= passes, asked.most_common(3)
    assert took < 2.0, f"{took:.2f} s"


def _flat(i):
    return {"id": f"flat-{i:03d}", "type": "time_window", "stage": "QUALIFY",
            "space_classes": ["standard"], "label": f"Flat {i}",
            "applies_on": {"kind": "days_of_week", "days": ["tue"]},
            "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
            "day_span": "any_span", "effect": {"kind": "flat", "price_minor": 5000 + i}}


def _worst(flats):
    """Five specials that apply, 300 that do not, the fill rule, and `flats` that apply."""
    idle = [_special(f"idle-{i:03d}", "discount", "fixed", 100, days=["mon"]) for i in range(300)]
    adjusting = SIX[:3] + SIX[3:5] + idle + [FILL]
    plan = _with_specials(adjusting, [r["id"] for r in adjusting])
    plan["rules"] += [_flat(i) for i in range(flats)]
    return load_plan(plan)


@pytest.mark.guarantee("F35")
@pytest.mark.parametrize("flats", [200, 400])
def test_many_applying_flats_beside_five_specials_and_the_fill_rule_stay_well_within_10_s(flats):
    """Each flat special that applies is another way to price the stay, and each
    way would search the orders again; the quote's budget for that search
    (ADJUST_SEARCH_BUDGET) keeps the whole quote far inside the platform's 10 s
    wait for the engine."""
    plan = _worst(flats)
    stay = make_stay(parse_instant("2026-03-03T09:00:00-05:00", "entry"),
                     parse_instant("2026-03-03T19:00:00-05:00", "exit"), "standard",
                     occupancy_at_entry_bp=9000)
    started = time.perf_counter()
    result = quote([plan], stay)
    took = time.perf_counter() - started
    assert took < 5.0, f"{took:.2f} s"
    assert sum(line.delta_minor for line in result.breakdown.lines) == result.fee_minor


@pytest.mark.guarantee("F35")
def test_past_the_budget_a_way_takes_one_order_and_its_receipt_says_so(monkeypatch):
    """With no budget left, the specials are taken in rule id order with the fill
    rule last, the stay is still priced, and one line says the limit was reached."""
    monkeypatch.setattr(engine, "ADJUST_SEARCH_BUDGET", 0)
    five = SIX[:3] + SIX[3:5]
    plan = load_plan(_with_specials(five + [FILL], [r["id"] for r in five] + ["zz-fill"]))
    stay = make_stay(parse_instant("2026-03-03T09:00:00-05:00", "entry"),
                     parse_instant("2026-03-03T19:00:00-05:00", "exit"), "standard",
                     occupancy_at_entry_bp=9000)
    result = quote([plan], stay)
    said = [line for line in result.breakdown.lines if line.code == "adjust.budget"]
    assert len(said) == 1 and said[0].delta_minor == 0, [ln.code for ln in result.breakdown.lines]
    assert "40,000" not in said[0].text and "0 pricings" in said[0].text
