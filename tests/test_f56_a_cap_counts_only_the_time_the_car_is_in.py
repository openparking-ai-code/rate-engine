"""F56 -- a cap counts only the days and weeks the car is in, and a week holds
only its own days.

Two defects, one plan. $8 the first hour, $4 an hour after, $30 a day, $100 a
week, New York:

* **A period the car is in for zero minutes added a cap.** `days_covered`
  counted the exit's own local date, so Monday 09:00 to Tuesday 00:00 was
  allowed two daily caps for no time at all on Tuesday: 60.00 instead of 30.00.
  A calendar week did the same at its start: Monday 00:00 to the next Monday
  00:00 was two weeks. A rolling window already counted this way -- exactly 24
  hours is one window -- and that is pinned here so it stays.
* **A week was capped at the weekly max times the weeks touched.** Seven days
  and an hour paid the weekly max twice, 200.00, although the hour's week
  holds one hour. A week now holds only its own days, and costs no more than
  the daily max for them.

**The figures moved again when the daily max became per calendar day (F59).**
This file was written while that was undecided, and pinned only what held
under either reading. It was decided 2026-10-16 that each day is capped on its
own, so a minute past midnight is a second day holding the stay's sixteenth
hour -- 30.00 + 4.00, not a second 30.00 -- and the hour after seven days is a
second week holding 4.00. Those figures are re-pinned here; F59 holds the rule.

**And the boundaries are pinned on one price for the whole stay too.** A rule
type that does not say how its charge builds up -- one registered with no
accrual, as a type written against the earlier `register` signature is -- is
capped at the max times the days and weeks the car is in. That is the path where
COUNTING the days decides the money, so the boundaries are measured there as well
as on the lines a time-based stay prints. A `time_window` flat special takes
this path too (F63: one price for the stay it covers); the path is reached here
through a type this file registers for the purpose and removes afterwards, so
these boundaries are measured on the cap's own path whatever a flat special does.

`scripts/fail_controls.py` puts back the exit's own date, the week start at the
exit, a rolling day counted past the week's end, and the week capped by the
weekly max alone, and requires this file to go red each time.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.breakdown import Line
from rate_engine.contract import run_quote
from rate_engine.engine import QUALIFIERS, make_stay
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import (
    RULE_ACCRUALS,
    RULE_APPLIERS,
    RULE_TRAITS,
    RULE_TYPES,
    Rule,
    common_fields,
    register,
)
from rate_engine.rules.daily_max import days_covered
from rate_engine.rules.weekly_max import weeks_covered
from rate_engine.stages import ACCUMULATE, CAP

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}


def _plan(day_boundary: str | None, week_boundary: str | None) -> dict:
    rules = [copy.deepcopy(HOURLY)]
    if day_boundary is not None:
        rules.append(
            {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
             "space_classes": ["standard"], "max_minor": 3000,
             "day_boundary": day_boundary}
        )
    if week_boundary is not None:
        rules.append(
            {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
             "space_classes": ["standard"], "max_minor": 10000,
             "week_boundary": week_boundary,
             "week_starts_on": "mon" if week_boundary == "calendar_week" else None}
        )
    return {
        "plan_version": "caps-2026-04",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": rules,
        "decisions": [],
    }


def _quote(plan: dict, entry: str, exit_: str) -> dict:
    status, body = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
         "space_class": "standard", "currency": "USD"}
    )
    assert status == 200, body
    return body


def _fee(plan: dict, entry: str, exit_: str) -> int:
    return _quote(plan, entry, exit_)["fee_minor"]


def _cap_text(body: dict, rule_id: str) -> str:
    return next(ln["text"] for ln in body["breakdown"] if ln["rule_id"] == rule_id)


#: A rule type that is one price for the whole stay and says nothing about how
#: its charge builds up: registered with no accrual. Registered for this module
#: and removed after it, so no other module's registry carries it.
ONE_PRICE = "f56_one_price"


@pytest.fixture(autouse=True, scope="module")
def _a_type_with_no_accrual():
    def build(raw, plan_space_classes, where):
        rule_id, classes = common_fields(raw, plan_space_classes, where, {"price_minor"})
        return Rule(id=rule_id, type=ONE_PRICE, stage=ACCUMULATE, space_classes=classes,
                    params={"price_minor": raw["price_minor"]})

    def apply(rule, stay, plan):
        return [Line(code="f56.one_price", rule_id=rule.id, text="One price for the stay",
                     delta_minor=rule.params["price_minor"])]

    register(ONE_PRICE, ACCUMULATE, build, apply)
    QUALIFIERS[ONE_PRICE] = lambda rule, stay, plan: rule.covers(stay.space_class)
    try:
        assert RULE_ACCRUALS[ONE_PRICE] is None, "the type must say nothing about its accrual"
        yield
    finally:
        for table in (RULE_TYPES, RULE_APPLIERS, RULE_TRAITS, RULE_ACCRUALS, QUALIFIERS):
            table.pop(ONE_PRICE, None)


#: One price for the whole stay, above every cap, for any entry and any exit. The
#: plan has no other way to price a stay, so the caps meet it every time.
FLAT = {
    "id": "flat", "type": ONE_PRICE, "stage": "ACCUMULATE",
    "space_classes": ["standard"], "price_minor": 50000,
}


def _flat_plan(day_boundary: str | None, week_boundary: str | None) -> dict:
    plan = _plan(day_boundary, week_boundary)
    plan["rules"] = [copy.deepcopy(FLAT)] + [r for r in plan["rules"] if r["id"] != "hourly"]
    return plan


# 2026-04-06 is a Monday, and no daylight-saving change falls near it.
MONDAY = "2026-04-06T09:00:00-04:00"


@pytest.mark.guarantee("F56")
def test_an_exit_at_midnight_adds_no_calendar_day():
    """15 hours, Monday 09:00 to Tuesday 00:00: 64.00 uncapped, ONE day."""
    plan = _plan("calendar_day", None)
    body = _quote(plan, MONDAY, "2026-04-07T00:00:00-04:00")
    assert body["fee_minor"] == 3000
    assert "applied over the day:" in _cap_text(body, "cap-daily"), _cap_text(body, "cap-daily")
    # One minute into Tuesday is a second day, holding the stay's sixteenth hour.
    assert _fee(plan, MONDAY, "2026-04-07T00:01:00-04:00") == 3400
    # The day before is untouched by the fix.
    assert _fee(plan, MONDAY, "2026-04-06T23:59:00-04:00") == 3000


@pytest.mark.guarantee("F56")
def test_an_exit_at_midnight_adds_no_day_to_a_flat_price():
    """A flat 500.00 is capped at 30.00 a day for the days the car is in: one day
    for Monday 09:00 to Tuesday 00:00, two from a minute later."""
    plan = _flat_plan("calendar_day", None)
    assert _fee(plan, MONDAY, "2026-04-07T00:00:00-04:00") == 3000
    assert _fee(plan, MONDAY, "2026-04-07T00:01:00-04:00") == 6000


@pytest.mark.guarantee("F56")
def test_a_part_minute_past_midnight_is_in_the_new_day():
    """The stay's own convention: a part-minute is a whole minute."""
    plan = load_plan(_plan("calendar_day", None))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    entry = parse_instant(MONDAY, "entry")
    on_midnight = make_stay(entry, parse_instant("2026-04-07T00:00:00-04:00", "x"), "standard")
    just_after = make_stay(
        entry, parse_instant("2026-04-07T00:00:00.000001-04:00", "x"), "standard"
    )
    assert days_covered(daily, on_midnight, plan) == 1
    assert days_covered(daily, just_after, plan) == 2


@pytest.mark.guarantee("F56")
def test_exactly_24_hours_is_one_rolling_window_and_a_minute_more_is_two():
    plan = _plan("rolling_24h", None)
    assert _fee(plan, MONDAY, "2026-04-07T09:00:00-04:00") == 3000
    assert _fee(plan, MONDAY, "2026-04-07T09:01:00-04:00") == 3400


@pytest.mark.guarantee("F56")
def test_an_exit_at_the_start_of_a_week_adds_no_week():
    """A weekly cap alone. Monday 00:00 to the next Monday 00:00 is one week; a
    minute more is a second week, holding the stay's 169th hour."""
    plan = _plan(None, "calendar_week")
    start = "2026-04-06T00:00:00-04:00"
    body = _quote(plan, start, "2026-04-13T00:00:00-04:00")
    assert body["fee_minor"] == 10000
    assert "applied over the week:" in _cap_text(body, "cap-weekly"), body["breakdown"]
    assert _fee(plan, start, "2026-04-13T00:01:00-04:00") == 10400
    flat = _flat_plan(None, "calendar_week")
    assert _fee(flat, start, "2026-04-13T00:00:00-04:00") == 10000
    assert _fee(flat, start, "2026-04-13T00:01:00-04:00") == 20000


@pytest.mark.guarantee("F56")
def test_exactly_seven_days_is_one_rolling_week_and_a_minute_more_is_two():
    plan = _plan(None, "rolling_7d")
    assert _fee(plan, MONDAY, "2026-04-13T09:00:00-04:00") == 10000
    assert _fee(plan, MONDAY, "2026-04-13T09:01:00-04:00") == 10400


@pytest.mark.guarantee("F56")
def test_a_week_with_a_clock_change_ends_at_the_next_local_midnight():
    """2026-03-08 springs forward, so this week is 167 hours. Leaving at the next
    Monday's local midnight is still one calendar week and seven calendar days."""
    plan = load_plan(_plan("calendar_day", "calendar_week"))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    weekly = next(r for r in plan.rules if r.id == "cap-weekly")
    entry = parse_instant("2026-03-02T00:00:00-05:00", "entry")
    exit_at = parse_instant("2026-03-09T00:00:00-04:00", "exit")
    stay = make_stay(entry, exit_at, "standard")
    assert stay.duration_minutes == 167 * 60, "the fixture must cross the transition"
    assert days_covered(daily, stay, plan) == 7
    assert weeks_covered(weekly, stay, plan) == 1


SEVEN_DAYS_AND_AN_HOUR = [
    ("rolling_24h", "rolling_7d", MONDAY, "2026-04-13T10:00:00-04:00"),
    ("calendar_day", "calendar_week",
     "2026-04-06T00:00:00-04:00", "2026-04-13T01:00:00-04:00"),
]


@pytest.mark.guarantee("F56")
@pytest.mark.parametrize("day_boundary,week_boundary,entry,exit_", SEVEN_DAYS_AND_AN_HOUR)
def test_seven_days_and_an_hour_pay_one_week_and_the_hour(
    day_boundary, week_boundary, entry, exit_
):
    """169 hours: 680.00 uncapped, and two weeks at 100.00 was 200.00. The second
    week holds one hour, the stay's 169th, at 4.00: 100.00 + 4.00."""
    body = _quote(_plan(day_boundary, week_boundary), entry, exit_)
    assert body["fee_minor"] == 10400
    weekly = next(ln for ln in body["breakdown"] if ln["rule_id"] == "cap-weekly")
    assert weekly["code"] == "weekly_max.applied"
    assert "100.00 USD + 4.00 USD" in weekly["text"], weekly["text"]


@pytest.mark.guarantee("F56")
@pytest.mark.parametrize("day_boundary,week_boundary,entry,exit_", SEVEN_DAYS_AND_AN_HOUR)
def test_a_flat_price_over_seven_days_and_an_hour_pays_one_week_and_one_day(
    day_boundary, week_boundary, entry, exit_
):
    """One price for the stay, so the second week is allowed the daily max for
    the one day the car is in it: 100.00 + 30.00, not 100.00 twice."""
    body = _quote(_flat_plan(day_boundary, week_boundary), entry, exit_)
    assert body["fee_minor"] == 13000
    assert "100.00 USD + 30.00 USD" in _cap_text(body, "cap-weekly"), body["breakdown"]


@pytest.mark.guarantee("F56")
def test_a_week_counts_the_rolling_days_it_holds_and_no_more():
    """Eight days exactly, rolling: the second week holds one 24-hour window, not
    two, so it is 30.00 and the stay is 130.00 -- by the hour, and as a flat
    price, where the count of days IS the ceiling."""
    assert _fee(_plan("rolling_24h", "rolling_7d"), MONDAY, "2026-04-14T09:00:00-04:00") == 13000
    flat = _flat_plan("rolling_24h", "rolling_7d")
    assert _fee(flat, MONDAY, "2026-04-14T09:00:00-04:00") == 13000


@pytest.mark.guarantee("F56")
def test_a_short_first_week_holds_only_its_own_days():
    """Saturday 00:00 to Friday 12:00, Monday weeks. The first week is Saturday and
    Sunday, 60.00; it ends where Monday starts and Monday is not in it. The
    second week's five days pay the weekly max, 100.00. 160.00 by the hour and
    as a flat price -- counting Monday in the first week too makes the flat
    price 190.00."""
    entry, exit_ = "2026-04-04T00:00:00-04:00", "2026-04-10T12:00:00-04:00"
    for plan in (_plan("calendar_day", "calendar_week"),
                 _flat_plan("calendar_day", "calendar_week")):
        body = _quote(plan, entry, exit_)
        assert body["fee_minor"] == 16000, body["breakdown"]
        assert "60.00 USD + 100.00 USD" in _cap_text(body, "cap-weekly"), body["breakdown"]


@pytest.mark.guarantee("F56")
def test_a_full_week_still_pays_the_weekly_max():
    """The control on the item above: a week whose daily caps add up to more
    than the weekly max is capped at the weekly max, so the change is the short
    week and nothing else. Fourteen days: two full weeks."""
    body = _quote(_plan("rolling_24h", "rolling_7d"), MONDAY, "2026-04-20T09:00:00-04:00")
    assert body["fee_minor"] == 20000
    weekly = next(ln for ln in body["breakdown"] if ln["rule_id"] == "cap-weekly")
    assert "+" not in weekly["text"], weekly["text"]


@pytest.mark.guarantee("F56")
def test_without_a_daily_cap_a_short_week_pays_what_it_holds():
    """No daily cap: the second week holds one hour, 4.00. A flat price has no
    hour to hold and nothing to bound the short week by, so it is two weeks at
    100.00."""
    assert _fee(_plan(None, "rolling_7d"), MONDAY, "2026-04-13T10:00:00-04:00") == 10400
    assert _fee(_flat_plan(None, "rolling_7d"), MONDAY, "2026-04-13T10:00:00-04:00") == 20000


@pytest.mark.guarantee("F56")
def test_the_two_caps_still_compose_in_either_order():
    """F33's property on the stay this file changes: the weekly cap reads the
    daily caps' TERMS, and both work from how the time was charged rather than
    from the running total, so the total after CAP is the same whichever runs
    first."""
    plan = load_plan(_plan("rolling_24h", "rolling_7d"))
    entry = parse_instant(MONDAY, "entry")
    stay = make_stay(entry, entry + timedelta(hours=169), "standard")
    hourly = next(r for r in plan.rules if r.id == "hourly")
    charged_by = RULE_ACCRUALS[hourly.type](hourly, stay, plan)
    caps = list(plan.rules_for_stage(CAP))
    totals = set()
    for order in (caps, list(reversed(caps))):
        running = 68000
        for rule in order:
            for line in RULE_APPLIERS[rule.type](rule, stay, plan, running, charged_by=charged_by):
                running += line.delta_minor
        totals.add(running)
    assert totals == {10400}


@pytest.mark.guarantee("F56")
def test_a_zero_length_stay_is_still_one_day_and_one_week():
    """F24: a stay of zero minutes pays the first period, so it is in one day."""
    plan = load_plan(_plan("calendar_day", "calendar_week"))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    weekly = next(r for r in plan.rules if r.id == "cap-weekly")
    entry = parse_instant("2026-04-13T00:00:00-04:00", "entry")
    stay = make_stay(entry, entry, "standard")
    assert days_covered(daily, stay, plan) == 1
    assert weeks_covered(weekly, stay, plan) == 1
    assert _fee(_plan("calendar_day", "calendar_week"), entry.isoformat(), entry.isoformat()) == 800
