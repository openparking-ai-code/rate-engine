"""F28 -- `next_day` is BOUNDED, and that is the whole reason it exists.

A stay that leaves the day after entry is one night and should get the rate.
`same_day` refuses it. `any_span` accepts it -- and accepts the car that left two
days later under the same flat price, which is the same class of hole `day_span`
itself was created to close: the engine pricing a stay under a rule whose author
never imagined it.

So there is a middle value, and it is bounded at one local day.

**The three spans are compared on ONE stay.** Three scenarios each shown under
one span would prove that three plans price three stays; only the same stay under
all three makes `day_span` an axis, and only an axis can show that the middle
value is genuinely between the other two.

**Why this fixture changed, and it is part of the fix rather than collateral.**
This module used to prove the axis on `enter_from 18:00` / `exit_by 06:00` -- a
window whose limit WRAPS past midnight. It was one of the only two modules in the
suite using an after-midnight `exit_by`, and both entered late in the evening and
measured stays that crossed midnight. That shared shape is exactly what hid the
defect F39 now covers: no test had ever asked what an evening window does for a
car that leaves the SAME evening, and the answer was that it silently refused it.

Two things follow. A wrapping limit is now refused at load under `same_day` and
`any_span` -- neither can say where the limit falls -- so the old fixture cannot
be built for two of the three spans it needs. And proving the span axis on a
wrapping window conflated two questions. So the axis is proven here on a window
that does not wrap, and F39 owns the wrap.

March 2026 dates are chosen away from the US daylight-saving transition on the
8th, so nothing below turns on a 23-hour day.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

DAY_RATE_PRICE = 1800
FRIDAY_0800 = "2026-03-13T08:00:00-04:00"
#: Fri 08:00 -> Sat 09:00. Twenty-five hours: 800 + 24 x 400.
TO_SATURDAY_MINUTES, TIME_BASED_SATURDAY = 1500, 10400
#: Fri 08:00 -> Sun 09:00. Forty-nine hours: 800 + 48 x 400.
TO_SUNDAY_MINUTES, TIME_BASED_SUNDAY = 2940, 20000

PLAN = {
    "plan_version": "overnight-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {
        "QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        # A window that does NOT wrap: the limit is later in the day than the
        # entry range, so it means the same thing under all three spans and the
        # only variable left is the span itself. That is what makes this an axis.
        {"id": "day-rate", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Day rate",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "06:00", "enter_by": "10:00", "exit_by": "23:00",
         "day_span": "next_day", "effect": {"kind": "flat", "price_minor": DAY_RATE_PRICE}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _fee(day_span: str, minutes: int) -> tuple[int, str]:
    document = copy.deepcopy(PLAN)
    document["rules"][0]["day_span"] = day_span
    entry_at = parse_instant(FRIDAY_0800, "entry")
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": FRIDAY_0800,
            "exit_at": (entry_at + timedelta(minutes=minutes)).isoformat(),
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200, body
    line = [ln for ln in body["breakdown"] if ln["code"].startswith("time_window")][0]
    return body["fee_minor"], line["text"]


def test_the_fixture_can_tell_the_outcomes_apart():
    """The control on the fixture. Three prices, all different, or the table
    below would pass without measuring the span at all."""
    assert len({DAY_RATE_PRICE, TIME_BASED_SATURDAY, TIME_BASED_SUNDAY}) == 3


@pytest.mark.guarantee("F28")
def test_the_THREE_SPANS_on_ONE_STAY_are_an_axis():
    """The whole guarantee in one table.

    The same two stays under all three spans. `next_day` must sit strictly
    between the other two -- accepting what `same_day` refuses and refusing what
    `any_span` accepts -- or it is a spelling of one of them.
    """
    to_saturday = {span: _fee(span, TO_SATURDAY_MINUTES)[0] for span in
                   ("same_day", "next_day", "any_span")}
    to_sunday = {span: _fee(span, TO_SUNDAY_MINUTES)[0] for span in
                 ("same_day", "next_day", "any_span")}

    assert to_saturday == {
        "same_day": TIME_BASED_SATURDAY,
        "next_day": DAY_RATE_PRICE,
        "any_span": DAY_RATE_PRICE,
    }, f"the day-after stay: {to_saturday}"

    assert to_sunday == {
        "same_day": TIME_BASED_SUNDAY,
        "next_day": TIME_BASED_SUNDAY,
        "any_span": DAY_RATE_PRICE,
    }, f"the day-after-that stay: {to_sunday}"

    assert to_saturday["next_day"] != to_saturday["same_day"], (
        "next_day accepts nothing same_day refuses -- it is same_day with another name"
    )
    assert to_sunday["next_day"] != to_sunday["any_span"], (
        "next_day refuses nothing any_span accepts -- it is any_span with another name"
    )


@pytest.mark.guarantee("F28")
def test_the_line_says_the_stay_ran_PAST_the_span_and_names_the_field():
    """The counter question is "why is a two-night stay not the overnight rate?",
    and the answer has to be in the breakdown."""
    _fee_minor, text = _fee("next_day", TO_SUNDAY_MINUTES)
    assert "is more than one local day after entry" in text, text
    assert "day_span 'next_day'" in text, (
        f"the line does not name the field that decided it: {text}"
    )


@pytest.mark.guarantee("F28")
def test_same_day_still_says_what_it_always_said():
    """The control on the wording: generalising the message must not have changed
    the sentence the shipped span prints."""
    _fee_minor, text = _fee("same_day", TO_SATURDAY_MINUTES)
    assert "is not the same local day as entry" in text, text
    assert "day_span 'same_day'" in text, text
