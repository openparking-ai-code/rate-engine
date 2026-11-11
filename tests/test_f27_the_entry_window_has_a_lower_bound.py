"""F27 -- `enter_from` is CONSULTED, and it is what makes an evening rate possible.

A window stating only "enter by 23:59" catches the seven-a.m. car as well as the
seven-p.m. one, so an evening rate written with one bound is not an evening rate
at all -- it is the standard rate with extra words. Both ends are stated.

**This is the `increment.rounding` shape, and that one shipped.** A field the
loader validates, the plan states, the document displays, and the applier never
reads: every value produces the same fee, nothing notices, and the operator
cannot catch it by reading their own plan because their plan is right. It cost a
round here once already. So the control for this guarantee plants exactly that --
ignore `enter_from` -- and requires red.

A garage that genuinely does not care about the lower bound writes `00:00`, in
its own document, where it can be seen.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

EVENING_PRICE = 2000
#: Nine hours on the fallback rate: 800 + 8 x 400.
TIME_BASED_9H = 4000

PLAN = {
    "plan_version": "evening-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {
        "QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        {"id": "evening", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Evening rate",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "18:00", "enter_by": "23:59", "exit_by": "06:00",
         "day_span": "next_day", "effect": {"kind": "flat", "price_minor": EVENING_PRICE}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _quote(entry: str, minutes: int, plan: dict | None = None):
    entry_at = parse_instant(entry, "entry")
    return run_quote(
        {
            "plans": [copy.deepcopy(plan if plan is not None else PLAN)],
            "entry_at": entry,
            "exit_at": (entry_at + timedelta(minutes=minutes)).isoformat(),
            "space_class": "standard",
            "currency": "USD",
        }
    )


def _window_line(body: dict) -> dict:
    return [ln for ln in body["breakdown"] if ln["code"].startswith("time_window")][0]


def test_the_fixture_can_tell_the_two_prices_apart():
    """The control on the fixture: if these agreed, nothing below would measure."""
    assert EVENING_PRICE != TIME_BASED_9H


@pytest.mark.guarantee("F27")
def test_one_minute_BEFORE_the_window_opens_does_not_qualify():
    """17:59 to 02:59. Inside every other condition the rule states."""
    status, body = _quote("2026-03-03T17:59:00-05:00", 540)
    assert status == 200
    assert body["fee_minor"] == TIME_BASED_9H, (
        f"a stay entering before the window opened was given the evening rate: "
        f"{_window_line(body)['text']}"
    )


@pytest.mark.guarantee("F27")
def test_and_the_line_names_the_bound_that_stopped_it():
    _status, body = _quote("2026-03-03T17:59:00-05:00", 540)
    line = _window_line(body)
    assert line["delta_minor"] == 0
    assert "entry 17:59 is before the 18:00 entry window opens" in line["text"], line["text"]


@pytest.mark.guarantee("F27")
def test_ON_the_opening_minute_it_qualifies():
    """The control. A lower bound that refused everything would pass the test
    above and be just as wrong."""
    status, body = _quote("2026-03-03T18:00:00-05:00", 540)
    assert status == 200
    assert body["fee_minor"] == EVENING_PRICE, _window_line(body)["text"]


@pytest.mark.guarantee("F27")
def test_the_SAME_STAY_qualifies_once_the_plan_opens_the_window_earlier():
    """The field is what decides it, proven by moving the field and nothing else.

    Same stay, same rule, same hours at the other end: only `enter_from` moves.
    A rule ignoring the field would price these two identically.
    """
    opened_early = copy.deepcopy(PLAN)
    opened_early["rules"][0]["enter_from"] = "00:00"

    _s, refused = _quote("2026-03-03T17:59:00-05:00", 540)
    _s, accepted = _quote("2026-03-03T17:59:00-05:00", 540, opened_early)
    assert refused["fee_minor"] == TIME_BASED_9H
    assert accepted["fee_minor"] == EVENING_PRICE, (
        "moving enter_from changed nothing, so the field is stored and never read"
    )


@pytest.mark.guarantee("F27")
def test_a_window_that_would_WRAP_PAST_MIDNIGHT_is_REFUSED_by_name():
    """"Enter between 22:00 and 02:00" is not one rule, and the engine will not
    guess how to split it: which days each half applies on is a pricing decision.
    Recorded in docs/CONTRACT.md as a stated gap rather than left to surface as a
    wrong fee."""
    wrapping = copy.deepcopy(PLAN)
    wrapping["rules"][0]["enter_from"] = "22:00"
    wrapping["rules"][0]["enter_by"] = "02:00"
    status, body = _quote("2026-03-03T23:00:00-05:00", 240, wrapping)
    assert status == 400
    assert "enter_from" in body["error"] and "enter_by" in body["error"]
    assert "TWO rules" in body["error"], body["error"]


@pytest.mark.guarantee("F27")
def test_the_two_bounds_may_be_EQUAL_which_is_a_one_minute_window():
    """The control on the refusal above: it must reject wrapping, not narrowness."""
    narrow = copy.deepcopy(PLAN)
    narrow["rules"][0]["enter_from"] = "18:00"
    narrow["rules"][0]["enter_by"] = "18:00"
    status, body = _quote("2026-03-03T18:00:00-05:00", 540, narrow)
    assert status == 200
    assert body["fee_minor"] == EVENING_PRICE
