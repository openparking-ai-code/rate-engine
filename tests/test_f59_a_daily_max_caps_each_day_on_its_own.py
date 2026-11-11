"""F59 -- a daily max caps each calendar day on its own, and a weekly max each week.

Decided 2026-10-16: the daily max is per calendar
day. Split the stay at the garage's local midnight and cap each day by itself;
a day the stay touches for zero minutes adds nothing. Until this, a cap took
the WHOLE stay's charge down to the max times the days it touched, so fifteen
minutes past midnight unlocked a second full day's cap for the fifteen hours
before it.

$8 the first hour and $4 an hour after, $30 a day, New York, as in F56:

* Monday 09:00 to Tuesday 00:15 is 30.00 for Monday's 64.00 and 4.00 for
  Tuesday's fifteen minutes -- the stay's sixteenth hour. 34.00, not 60.00.
* The rate does not start again at midnight: Tuesday's fifteen minutes are a
  repeat hour at 4.00, not a new first hour at 8.00 (that would be 38.00).
* A period is charged on the day it STARTS. The minute a car enters a period it
  owes all of it, which is what `ceil` means; an hour from 23:30 to 00:30 is
  Monday's.
* A 23- or 25-hour day is one day: the cut is at local midnight, never 24 hours
  after the last one.
* A weekly max caps each week the same way -- by the plan's own week, from the
  day it names -- after the daily max for each of its days.
* A flat special is one price for the stay it covers, so it is not split by
  the day: it is held to the max times the days the car is in, and compared
  whole with the time-based rate (the rule since 2026-10-17: compare
  whole-stay alternatives), pinned in F63. A rule type that says nothing about
  its accrual is capped the same way (F56).

The caps learn how the time was charged from the engine (`charged_by`, the
`told_the_base` trait), and the engine checks that what the base says it charged
is what its lines charged, on every quote.

`scripts/fail_controls.py` puts back the whole-stay cap, charges every day from
entry, makes a day 24 hours long, lets a week ignore the daily max, allows a
week the whole weekly max, tells the caps the wrong base, and turns the ledger
check off, and requires this file to go red each time.
"""

from __future__ import annotations

import copy
import json
import os
import time
from datetime import timedelta

import pytest

from rate_engine.breakdown import Line
from rate_engine.contract import run_quote
from rate_engine.engine import QUALIFIERS, make_stay, quote
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
from rate_engine.rules.daily_max import capped_days, days_covered
from rate_engine.stages import ACCUMULATE, CAP

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}


def _daily(max_minor: int = 3000, boundary: str = "calendar_day") -> dict:
    return {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
            "space_classes": ["standard"], "max_minor": max_minor, "day_boundary": boundary}


def _weekly(starts_on: str | None = "mon", boundary: str = "calendar_week") -> dict:
    return {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
            "space_classes": ["standard"], "max_minor": 10000,
            "week_boundary": boundary, "week_starts_on": starts_on}


def _plan(*rules: dict) -> dict:
    return {
        "plan_version": "per-day-2026-10",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [copy.deepcopy(r) for r in rules],
        "decisions": [],
    }


PER_DAY = _plan(HOURLY, _daily())


def _quote(plan: dict, entry: str, exit_: str) -> dict:
    status, body = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
         "space_class": "standard", "currency": "USD"}
    )
    assert status == 200, body
    return body


def _line(body: dict, rule_id: str) -> dict:
    return next(ln for ln in body["breakdown"] if ln["rule_id"] == rule_id)


# 2026-04-06 is a Monday, and no daylight-saving change falls near it.
MONDAY = "2026-04-06T09:00:00-04:00"


# --- the decision's own example, and what it rules out ---------------------


@pytest.mark.guarantee("F59")
def test_monday_0900_to_tuesday_0015_is_monday_capped_plus_tuesdays_fifteen_minutes():
    """15 hours 15 minutes: 68.00 by the hour. Monday's 64.00 pays 30.00 and
    Tuesday's fifteen minutes pay 4.00. The max times the days touched was 60.00."""
    body = _quote(PER_DAY, MONDAY, "2026-04-07T00:15:00-04:00")
    assert body["fee_minor"] == 3400
    cap = _line(body, "cap-daily")
    assert cap["code"] == "daily_max.applied"
    assert cap["delta_minor"] == -3400, "68.00 reduced to 34.00"
    assert "30.00 USD + 4.00 USD: each day is capped on its own" in cap["text"], cap["text"]
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 3400


@pytest.mark.guarantee("F59")
def test_the_rate_does_not_start_again_at_midnight():
    """Tuesday's fifteen minutes are the stay's sixteenth hour, a repeat period
    at 4.00. Priced as a new stay they would be a first hour at 8.00: 38.00."""
    fee = _quote(PER_DAY, MONDAY, "2026-04-07T00:15:00-04:00")["fee_minor"]
    assert fee != 3800
    assert fee == 3000 + 400


@pytest.mark.guarantee("F59")
def test_a_day_under_the_cap_pays_what_it_cost():
    """Monday 20:00 to Tuesday 08:00: Monday's four hours are 20.00, under the
    cap, and Tuesday's eight are 32.00, capped at 30.00. 50.00, where the whole
    stay's 52.00 under a 60.00 ceiling was charged in full."""
    body = _quote(PER_DAY, "2026-04-06T20:00:00-04:00", "2026-04-07T08:00:00-04:00")
    assert body["fee_minor"] == 5000
    assert "20.00 USD + 30.00 USD" in _line(body, "cap-daily")["text"]


@pytest.mark.guarantee("F59")
def test_72_hours_at_a_40_dollar_max_pays_at_most_40_each_day_it_is_there():
    """The owner's own figure. Monday 09:00 to Thursday 09:00 is in four calendar
    days: 64.00, 96.00 and 96.00 pay 40.00 each, and Thursday's nine hours 36.00."""
    body = _quote(_plan(HOURLY, _daily(4000)), MONDAY, "2026-04-09T09:00:00-04:00")
    assert body["fee_minor"] == 15600
    assert "3 x 40.00 USD + 36.00 USD" in _line(body, "cap-daily")["text"]


# --- midnight ---------------------------------------------------------------


@pytest.mark.guarantee("F59")
def test_a_stay_ending_exactly_at_midnight_adds_no_day():
    """Monday 09:00 to Tuesday 00:00 is one day; to Wednesday 00:00, two, both
    at the cap; Sunday 20:00 to Monday 00:00 is one day under it."""
    one = _quote(PER_DAY, MONDAY, "2026-04-07T00:00:00-04:00")
    assert one["fee_minor"] == 3000
    assert "applied over the day:" in _line(one, "cap-daily")["text"]
    two = _quote(PER_DAY, MONDAY, "2026-04-08T00:00:00-04:00")
    assert two["fee_minor"] == 6000
    assert "applied over 2 days:" in _line(two, "cap-daily")["text"]
    evening = _quote(PER_DAY, "2026-04-05T20:00:00-04:00", "2026-04-06T00:00:00-04:00")
    assert evening["fee_minor"] == 2000
    assert _line(evening, "cap-daily")["code"] == "daily_max.not_reached"


@pytest.mark.guarantee("F59")
def test_a_stay_from_midnight_to_midnight_is_one_day():
    body = _quote(PER_DAY, "2026-04-07T00:00:00-04:00", "2026-04-08T00:00:00-04:00")
    assert body["fee_minor"] == 3000
    assert "applied over the day:" in _line(body, "cap-daily")["text"]


@pytest.mark.guarantee("F59")
def test_a_period_is_charged_on_the_day_it_starts():
    """Monday 09:30 to Tuesday 00:15: the hour that covers Tuesday's fifteen
    minutes began at 23:30 on Monday, so Tuesday was charged nothing and the
    stay is Monday's 30.00 alone."""
    body = _quote(PER_DAY, "2026-04-06T09:30:00-04:00", "2026-04-07T00:15:00-04:00")
    assert body["fee_minor"] == 3000
    assert "30.00 USD + 0.00 USD" in _line(body, "cap-daily")["text"]


@pytest.mark.guarantee("F59")
def test_a_rolling_day_is_capped_on_its_own_too():
    """`rolling_24h` stays the plan's choice, and its windows are capped the same
    way: Monday 09:00 to Tuesday 09:15 is 30.00 + the 25th hour, 4.00."""
    body = _quote(_plan(HOURLY, _daily(boundary="rolling_24h")), MONDAY,
                  "2026-04-07T09:15:00-04:00")
    assert body["fee_minor"] == 3400
    assert "each 24-hour window is capped on its own" in _line(body, "cap-daily")["text"]


# --- a clock change -----------------------------------------------------------


@pytest.mark.guarantee("F59")
@pytest.mark.parametrize(
    "entry,exit_,sunday_hours",
    [
        # 2026-03-08 springs forward: Sunday is 23 hours.
        ("2026-03-07T22:00:00-05:00", "2026-03-09T02:00:00-04:00", 23),
        # 2026-11-01 falls back: Sunday is 25 hours.
        ("2026-10-31T22:00:00-04:00", "2026-11-02T02:00:00-05:00", 25),
    ],
)
def test_a_day_with_a_clock_change_is_one_day_cut_at_local_midnight(entry, exit_, sunday_hours):
    """Saturday 22:00 to Monday 02:00: Saturday's two hours are 12.00, Sunday is
    capped at 30.00 however long it is, and Monday's two hours are 8.00. Cut at 24
    hours after Sunday's midnight instead, Monday would hold one hour or three."""
    plan = load_plan(copy.deepcopy(PER_DAY))
    stay = make_stay(parse_instant(entry, "entry"), parse_instant(exit_, "exit"), "standard")
    assert stay.duration_minutes == (2 + sunday_hours + 2) * 60, "must cross the change"
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    hourly = next(r for r in plan.rules if r.id == "hourly")
    charged_by = RULE_ACCRUALS["increment"](hourly, stay, plan)
    assert days_covered(daily, stay, plan) == 3
    assert capped_days(daily, stay, plan, charged_by) == [1200, 3000, 800]
    body = _quote(PER_DAY, entry, exit_)
    assert body["fee_minor"] == 5000
    assert "12.00 USD + 30.00 USD + 8.00 USD" in _line(body, "cap-daily")["text"]


@pytest.mark.guarantee("F59")
def test_the_same_stay_prices_the_same_every_time_and_in_every_server_zone():
    """F5's two properties on the stays this changes: byte-identical answers on
    a second run, and the server's own timezone never moves the cut at midnight."""
    stays = [
        (MONDAY, "2026-04-07T00:15:00-04:00"),
        ("2026-03-07T22:00:00-05:00", "2026-03-09T02:00:00-04:00"),
        ("2026-10-31T22:00:00-04:00", "2026-11-02T02:00:00-05:00"),
    ]
    plan = _plan(HOURLY, _daily(), _weekly())

    def answers() -> list[str]:
        out = []
        for entry, exit_ in stays:
            status, body = run_quote(
                {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
                 "space_class": "standard", "currency": "USD"}
            )
            out.append(json.dumps([status, body], sort_keys=False))
        return out

    baseline = answers()
    assert answers() == baseline
    original = os.environ.get("TZ")
    try:
        for zone in ("UTC", "Asia/Kolkata", "Pacific/Kiritimati", "America/Los_Angeles"):
            os.environ["TZ"] = zone
            time.tzset()
            assert answers() == baseline, f"the answer moved with the server in {zone}"
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


# --- the week -----------------------------------------------------------------


@pytest.mark.guarantee("F59")
def test_a_calendar_week_pays_only_the_time_in_it():
    """A weekly max alone, by the plan's week (Monday): Monday 00:00 to the next
    Monday 00:15 is 100.00 for the first week and the 169th hour, 4.00."""
    body = _quote(_plan(HOURLY, _weekly()), "2026-04-06T00:00:00-04:00",
                  "2026-04-13T00:15:00-04:00")
    assert body["fee_minor"] == 10400
    assert "100.00 USD + 4.00 USD: each week is capped on its own" in _line(
        body, "cap-weekly")["text"]


@pytest.mark.guarantee("F59")
def test_a_week_is_capped_after_the_daily_max_for_each_of_its_days():
    """Nine days from Monday 00:00. The first week's seven days are 210.00 at the
    daily max and pay 100.00; the second week holds Monday and Tuesday, 30.00
    each. 160.00 -- the weekly max on that week would allow 100.00."""
    body = _quote(_plan(HOURLY, _daily(), _weekly()), "2026-04-06T00:00:00-04:00",
                  "2026-04-15T00:00:00-04:00")
    assert body["fee_minor"] == 16000
    assert "100.00 USD + 60.00 USD" in _line(body, "cap-weekly")["text"]
    assert "after the daily max for each of its days" in _line(body, "cap-weekly")["text"]


@pytest.mark.guarantee("F59")
def test_the_week_is_the_plans_own_week():
    """The same nine days with a Sunday week: Monday to Saturday is the first
    week (six days, 180.00, pays 100.00), Sunday to Tuesday the second (90.00)."""
    body = _quote(_plan(HOURLY, _daily(), _weekly("sun")), "2026-04-06T00:00:00-04:00",
                  "2026-04-15T00:00:00-04:00")
    assert body["fee_minor"] == 19000


@pytest.mark.guarantee("F59")
def test_the_two_caps_compose_in_either_order_by_the_day():
    """The total after CAP is the same whichever cap runs first: both work from
    how the time was charged, never from the running total."""
    plan = load_plan(_plan(HOURLY, _daily(), _weekly()))
    entry = parse_instant("2026-04-06T00:00:00-04:00", "entry")
    stay = make_stay(entry, entry + timedelta(days=9), "standard")
    hourly = next(r for r in plan.rules if r.id == "hourly")
    charged_by = RULE_ACCRUALS["increment"](hourly, stay, plan)
    caps = list(plan.rules_for_stage(CAP))
    totals = set()
    for order in (caps, list(reversed(caps))):
        running = charged_by(stay.duration_minutes)
        for rule in order:
            for line in RULE_APPLIERS[rule.type](rule, stay, plan, running, charged_by=charged_by):
                running += line.delta_minor
        totals.add(running)
    assert totals == {16000}


@pytest.mark.guarantee("F59")
def test_no_cap_charges_more_than_the_max_times_the_days_touched():
    """Capping each day on its own can only LOWER a fee: every day pays at most
    the max, and no more than it cost. Across entries every half hour of a day
    and stays up to ten days, the fee is never above the old ceiling and never
    above the uncapped charge, and no day pays more than the max."""
    plan = load_plan(copy.deepcopy(PER_DAY))
    daily = next(r for r in plan.rules if r.id == "cap-daily")
    hourly = next(r for r in plan.rules if r.id == "hourly")
    start = parse_instant("2026-03-06T00:00:00-05:00", "entry")  # across the spring change
    checked = 0
    for half_hour in range(48):
        entry = start + timedelta(minutes=30 * half_hour)
        for minutes in (0, 1, 59, 61, 600, 900, 1439, 1440, 1441, 2000, 4321, 14400):
            stay = make_stay(entry, entry + timedelta(minutes=minutes), "standard")
            charged_by = RULE_ACCRUALS["increment"](hourly, stay, plan)
            uncapped = charged_by(stay.duration_minutes)
            old_ceiling = min(uncapped, 3000 * days_covered(daily, stay, plan))
            fee = quote([plan], stay).fee_minor
            assert fee <= old_ceiling, (entry, minutes, fee, old_ceiling)
            assert all(day <= 3000 for day in capped_days(daily, stay, plan, charged_by))
            checked += 1
    assert checked == 48 * 12


# --- what the base is -----------------------------------------------------------


@pytest.mark.guarantee("F59")
def test_a_weekend_rate_is_split_by_the_day_like_the_ordinary_one():
    """A `rate` special -- $2 an hour at the weekend, $10 a day -- is a time-based
    rate and is split the same way: Saturday 20:00 to Sunday 12:00 is Saturday's
    8.00 and Sunday's 24.00 capped at 10.00. 18.00, not 20.00."""
    weekend = {
        "id": "weekend", "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": "Weekend rate",
        "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
        "day_span": "any_span",
        "effect": {"kind": "rate", "first_period_minutes": 60, "first_period_minor": 200,
                   "repeat_period_minutes": 60, "repeat_period_minor": 200,
                   "rounding": "ceil", "max_duration_minutes": None},
    }
    body = _quote(_plan(weekend, _daily(1000)), "2026-04-11T20:00:00-04:00",
                  "2026-04-12T12:00:00-04:00")
    assert body["fee_minor"] == 1800
    assert "8.00 USD + 10.00 USD" in _line(body, "cap-daily")["text"]


# --- the engine checks what a base says it charged ------------------------------

MISMATCH = "f59_mismatch"


def _register_a_base_whose_accrual_disagrees_with_its_lines():
    def build(raw, plan_space_classes, where):
        rule_id, classes = common_fields(raw, plan_space_classes, where, set())
        return Rule(id=rule_id, type=MISMATCH, stage=ACCUMULATE, space_classes=classes,
                    params={})

    def apply(rule, stay, plan):
        return [Line(code="f59.flat", rule_id=rule.id, text="7.77 for the stay",
                     delta_minor=777)]

    def accrual(rule, stay, plan):
        return lambda minutes: 0

    register(MISMATCH, ACCUMULATE, build, apply, accrual=accrual)
    QUALIFIERS[MISMATCH] = lambda rule, stay, plan: rule.covers(stay.space_class)


@pytest.mark.guarantee("F59")
def test_a_base_whose_accrual_disagrees_with_its_lines_stops_the_quote():
    """The caps split the charge by what the base SAYS it charged. A base that
    says one thing and charges another would have them capping a charge that is
    not on the receipt, so the quote stops instead of pricing it."""
    _register_a_base_whose_accrual_disagrees_with_its_lines()
    try:
        plan = load_plan(_plan(
            {"id": "odd", "type": MISMATCH, "stage": "ACCUMULATE",
             "space_classes": ["standard"]},
            _daily(),
        ))
        entry = parse_instant(MONDAY, "entry")
        stay = make_stay(entry, entry + timedelta(hours=2), "standard")
        with pytest.raises(AssertionError, match="charges 0 for this stay"):
            quote([plan], stay)
    finally:
        for table in (RULE_TYPES, RULE_APPLIERS, RULE_TRAITS, RULE_ACCRUALS, QUALIFIERS):
            table.pop(MISMATCH, None)
