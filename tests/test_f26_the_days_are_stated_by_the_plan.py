"""F26 -- a window applies on the days the PLAN states, and on no others.

Decided 2026-09-07: when weekends are selected, the setup shows Friday, Saturday,
Sunday and Monday with their entry and exit hours, and the rate applies to every
weekend. Weekday,
weekend, evening, morning, holiday and event rates differ in WHICH DAYS and WHAT
HOURS, so the days are a field.

**The engine never stores the word "weekend".** It is Friday-to-Monday to the
operator who asked for this and Saturday-to-Sunday elsewhere; a preset would put
a pricing decision inside the engine. The dropdown expands to actual days.

**And the day is the ENTRY's.** The specification's entry-time rule, and the owner's own event
case: a car that entered before the event pays the ordinary rate. A stay
entering Friday night and leaving Saturday is a FRIDAY stay.

Two kinds, one code path: `days_of_week` for anything recurring, `dates` for a
holiday or an event the garage types itself. There is no built-in calendar --
it would be right for one country and wrong for every other.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote

TUESDAY = "2026-03-03T07:00:00-05:00"
SATURDAY = "2026-03-07T07:00:00-05:00"
FRIDAY_NIGHT = "2026-03-06T22:00:00-05:00"

WEEKEND_PRICE = 1500
#: 7 hours on the fallback rate: 800 + 6 x 400.
TIME_BASED_7H = 3200

PLAN = {
    "plan_version": "riverside-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {
        "QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        {"id": "weekend", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Weekend rate",
         "applies_on": {"kind": "days_of_week", "days": ["fri", "sat", "sun"]},
         "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
         "day_span": "next_day", "effect": {"kind": "flat", "price_minor": WEEKEND_PRICE}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _quote(entry: str, minutes: int, plan: dict | None = None):
    from datetime import timedelta

    from rate_engine.plan import parse_instant

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
    """The control on this file's own fixture, and it runs first.

    The weekend price and the time-based price for the same stay must differ, or
    every assertion below would pass against an engine that ignored the days.
    """
    assert WEEKEND_PRICE != TIME_BASED_7H


@pytest.mark.guarantee("F26")
def test_a_day_the_plan_did_NOT_state_does_not_qualify():
    status, body = _quote(TUESDAY, 420)
    assert status == 200
    assert body["fee_minor"] == TIME_BASED_7H, (
        f"a Tuesday was given the weekend rate: {_window_line(body)['text']}"
    )


@pytest.mark.guarantee("F26")
def test_and_the_zero_LINE_NAMES_the_day_and_the_days_it_wanted():
    """The sentence an operator is read at the counter. Naming the day that
    failed is the whole value of the line; "not applied" alone answers nothing."""
    _status, body = _quote(TUESDAY, 420)
    line = _window_line(body)
    assert line["delta_minor"] == 0
    assert "Weekend rate NOT applied: Tuesday is not one of fri, sat, sun" in line["text"], (
        f"the line does not say which day failed and which days the rule wanted: "
        f"{line['text']}"
    )


@pytest.mark.guarantee("F26")
def test_a_day_the_plan_DID_state_qualifies():
    """The control on the item above: refusing a Tuesday must not be refusing
    every day."""
    status, body = _quote(SATURDAY, 420)
    assert status == 200
    assert body["fee_minor"] == WEEKEND_PRICE, _window_line(body)["text"]
    assert "NOT applied" not in _window_line(body)["text"]


@pytest.mark.guarantee("F26")
def test_the_day_is_the_ENTRYS_and_never_the_exits():
    """The specification's entry-time rule, and the owner's event case: a car that entered before
    the event pays the ordinary rate.

    Both stays below cross the same local midnight. One enters on a stated day
    and one leaves on one, and only the first qualifies.
    """
    saturday_only = copy.deepcopy(PLAN)
    saturday_only["rules"][0]["applies_on"] = {"kind": "days_of_week", "days": ["sat"]}

    _s, entered_friday = _quote(FRIDAY_NIGHT, 480)  # Fri 22:00 -> Sat 06:00
    assert entered_friday["fee_minor"] == WEEKEND_PRICE, "Friday is a stated day"

    _s, left_on_saturday = _quote(FRIDAY_NIGHT, 480, saturday_only)
    assert left_on_saturday["fee_minor"] != WEEKEND_PRICE, (
        "a stay that ENTERED on Friday was given a Saturday-only rate because it "
        "left on a Saturday -- the engine is matching the exit"
    )
    assert "Friday is not one of sat" in _window_line(left_on_saturday)["text"]


@pytest.mark.guarantee("F26")
def test_a_HOLIDAY_is_stated_as_dates_and_matches_only_those():
    """The other kind, and the reason there is no built-in calendar: the garage
    types its own dates, so the module is not wrong in every country but one."""
    holiday = copy.deepcopy(PLAN)
    holiday["rules"][0]["label"] = "Holiday rate"
    holiday["rules"][0]["applies_on"] = {"kind": "dates", "dates": ["2026-03-03", "2026-07-04"]}

    _s, on_the_date = _quote(TUESDAY, 420, holiday)
    assert on_the_date["fee_minor"] == WEEKEND_PRICE

    _s, off_the_date = _quote(SATURDAY, 420, holiday)
    assert off_the_date["fee_minor"] == TIME_BASED_7H
    assert "2026-03-07 is not one of 2026-03-03, 2026-07-04" in _window_line(off_the_date)["text"]


@pytest.mark.guarantee("F26")
@pytest.mark.parametrize(
    "applies_on,expected",
    [
        ({"kind": "weekend"}, "kind is 'weekend'"),
        ({"kind": "days_of_week", "days": ["weekend"]}, "names weekend"),
        ({"kind": "days_of_week", "days": ["sat", "sat"]}, "duplicate"),
        ({"kind": "days_of_week", "days": []}, "non-empty list of day names"),
        ({"kind": "days_of_week", "days": "sat"}, "non-empty list of day names"),
        ({"kind": "dates", "dates": []}, "non-empty list of 'YYYY-MM-DD'"),
        ({"kind": "dates", "dates": ["2026-7-4"]}, "not a 'YYYY-MM-DD' date"),
        ({"kind": "dates", "dates": ["20260704"]}, "compact and week-date spellings"),
        ({"kind": "dates", "dates": ["2026-07-04", "2026-07-04"]}, "duplicate"),
        ({"kind": "days_of_week", "days": ["sat"], "dates": ["2026-07-04"]}, "does not understand"),
        ({"days": ["sat"]}, "carrying a `kind`"),
        ("weekends", "carrying a `kind`"),
    ],
)
def test_a_shape_the_engine_cannot_read_is_REFUSED_by_name(applies_on, expected):
    """A preset, a typo and a mixed shape are all refused, and the message names
    the field. An `applies_on` the engine half-understood would be a rate an
    operator believes is live on days it is not."""
    document = copy.deepcopy(PLAN)
    document["rules"][0]["applies_on"] = applies_on
    status, body = _quote(SATURDAY, 420, document)
    assert status == 400, f"{applies_on!r} was accepted"
    assert "applies_on" in body["error"], body["error"]
    assert expected in body["error"], body["error"]
