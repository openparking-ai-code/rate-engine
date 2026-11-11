"""F39 -- a window's exit limit runs to the day its `day_span` allows.

The defect this closes, in one stay. An event window: in between 16:00 and 21:00,
out by 02:00, `day_span next_day`, flat $40. A car in at 18:30 and out at 00:30
got the $40. The same car out at 23:45 -- *earlier*, and on the same evening --
was refused it and billed the hourly rate, because the exit test read a bare
clock: 23:45 is a larger reading than 02:00. The receipt said "exit 23:45 is
after the 02:00 limit", a sentence that contradicts itself in front of the
operator, and `validate-plan` called the plan clean first.

That is every evening, overnight and weekend-night window whose limit is past
midnight, not only event rates.

**The fixture is the point, not the assertions.** Before this module the suite
had exactly two tests using an after-midnight `exit_by` -- F27 and F28 -- and
both entered late in the evening and measured stays that CROSSED midnight. Not
one asked what happens to the car that leaves before it. Extending either would
have re-tested the same hole from the same angle, so this is a new fixture with
an evening entry and a before-midnight exit, which is the case that was never
written down.

**What a bounded span buys.** The limit is `exit_by` on the entry date plus
`DAY_SPAN_LIMITS[day_span]` days -- a moment, with a date on it. `same_day` puts
that on the entry date and is unchanged. `next_day` puts it on the day after,
which is the fix. `any_span` names no last day, so it keeps the wall-clock
reading; a limit that would have to WRAP to be reached is refused at load there
and under `same_day`, because neither can say where it falls.

October 2026 dates sit away from the US daylight-saving transition on the 1st of
November, so nothing below turns on a 25-hour day. **That is a deliberate
exclusion, not coverage:** what the limit does when the clocks change is F40's,
proven on the transition itself, because a module that both fixes the comparison
and tests it on the one night it could be decided by an offset would be proving
two things with one fixture.

**WHAT THIS GUARANTEE DOES NOT COVER, AS A DERIVED FRACTION: 1 of 3.** A wrapping
`exit_by` -- one earlier in the day than `enter_from` -- can exist in exactly one
of the three `day_span` values, because `same_day` and `any_span` refuse it at
load; crossed with the three effect kinds that leaves THREE cells it can occupy,
and this module builds only `flat`. So `next_day` x `rate` and `next_day` x
`adjust` are never exercised here. The exit test reads `day_span` and `exit_by`
and never the effect -- see `_exit_failure`, which is handed neither -- so the
two unexercised cells share its code path exactly and were measured correct by
hand. The fraction is recorded rather than left implied because a guarantee that
reads broader than it is will be trusted broader than it is.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import InvalidPlan, load_plan, parse_instant
from rate_engine.rules.time_window import DAY_SPAN_LIMITS
from rate_engine.validator import probe_stays
from rate_engine.wallclock import local_minute

#: The story above is told at $40. The fixture's window is 5.00, below every
#: hourly total a stay below reaches (6.00 and up), because the cheapest way is
#: charged under either mode (F63): only a window cheaper than the hour is
#: charged where it qualifies, and only then does the fee say whether it did.
EVENT_PRICE = 500
#: In at 18:30 on the event date. Every stay below starts here.
SATURDAY_1830 = "2026-10-17T18:30:00-04:00"

#: 90 minutes: out 20:00, the same evening. Hourly would be 300 + 300.
TO_2000_MINUTES, TIME_BASED_2000 = 90, 600
#: 315 minutes: out 23:45, still the same evening. Hourly 300 + 5 x 300.
TO_2345_MINUTES, TIME_BASED_2345 = 315, 1800
#: 360 minutes: out 00:30, over midnight and inside the limit.
TO_0030_MINUTES = 360
#: 510 minutes: out 03:00, PAST the 02:00 limit. Hourly 300 + 8 x 300.
PAST_LIMIT_MINUTES, TIME_BASED_PAST_LIMIT = 510, 2700

PLAN = {
    "plan_version": "event-2026-10",
    "effective_from": "2026-01-01T00:00:00-04:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    # `stated_order` at QUALIFY. It used to let the window REPLACE the hourly
    # rate whatever it cost, which is how this fixture's fee said whether the
    # window qualified. Under either mode the cheapest way is charged now
    # (F63), so the window is priced below the hour (EVENT_PRICE) and the fee
    # says it the same way. The mode is kept so a stated order is exercised.
    "resolution": {
        "QUALIFY": {"mode": "stated_order", "order": ["event-night"]},
        "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        {"id": "event-night", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Event night",
         "applies_on": {"kind": "dates", "dates": ["2026-10-17", "2026-10-18"]},
         "enter_from": "16:00", "enter_by": "21:00", "exit_by": "02:00",
         "day_span": "next_day", "effect": {"kind": "flat", "price_minor": EVENT_PRICE}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 300, "repeat_period_minutes": 60,
         "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _fee(minutes: int, *, plan: dict | None = None) -> tuple[int, str]:
    document = copy.deepcopy(plan if plan is not None else PLAN)
    entry_at = parse_instant(SATURDAY_1830, "entry")
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": SATURDAY_1830,
            "exit_at": (entry_at + timedelta(minutes=minutes)).isoformat(),
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200, body
    line = [ln for ln in body["breakdown"] if ln["code"].startswith("time_window")][0]
    return body["fee_minor"], line["text"]


def test_the_fixture_can_tell_the_outcomes_apart():
    """The control on the fixture. The window price and every hourly total below
    must differ, or the table passes without measuring anything -- and the window
    must be the cheaper way wherever it qualifies, or it is not charged there."""
    assert len({EVENT_PRICE, TIME_BASED_2000, TIME_BASED_2345, TIME_BASED_PAST_LIMIT}) == 4
    assert EVENT_PRICE < min(TIME_BASED_2000, TIME_BASED_2345, TIME_BASED_PAST_LIMIT)


@pytest.mark.guarantee("F39")
def test_a_car_that_leaves_the_SAME_EVENING_gets_the_rate():
    """The defect, as a table. Out at 20:00 and out at 23:45 are both before the
    02:00 limit that falls the NEXT day, so both get the window."""
    assert _fee(TO_2000_MINUTES)[0] == EVENT_PRICE, "the 20:00 stay"
    assert _fee(TO_2345_MINUTES)[0] == EVENT_PRICE, "the 23:45 stay"


@pytest.mark.guarantee("F39")
def test_a_car_that_leaves_AFTER_midnight_and_before_the_limit_still_gets_it():
    """The case that always worked, kept as the control on the other direction:
    the fix must not have traded one side of midnight for the other."""
    assert _fee(TO_0030_MINUTES)[0] == EVENT_PRICE


@pytest.mark.guarantee("F39")
def test_a_car_that_leaves_PAST_the_limit_is_refused_and_the_line_names_the_DAY():
    """Out at 03:00 is past 02:00 on the day the span allows, so the window does
    not apply -- and the sentence has to carry the limit's date, or it reads as
    the same contradiction with the numbers swapped."""
    fee, text = _fee(PAST_LIMIT_MINUTES)
    assert fee == TIME_BASED_PAST_LIMIT
    assert "exit 03:00 on Sun 18 Oct" in text, text
    assert "02:00 limit on Sun 18 Oct" in text, (
        f"the line does not say WHICH DAY the limit fell on: {text}"
    )


@pytest.mark.guarantee("F39")
def test_same_day_is_unchanged_and_still_ends_at_the_entry_date():
    """`same_day` puts the limit on the entry date, which is what it always did.
    A non-wrapping window is used because a wrapping one is refused at load under
    this span -- see the refusal tests below."""
    document = copy.deepcopy(PLAN)
    document["rules"][0].update({"enter_from": "16:00", "exit_by": "22:00",
                                 "day_span": "same_day"})
    assert _fee(TO_2000_MINUTES, plan=document)[0] == EVENT_PRICE, "out 20:00, inside"
    fee, text = _fee(TO_2345_MINUTES, plan=document)
    assert fee == TIME_BASED_2345, "out 23:45, past a 22:00 same-day limit"
    assert "22:00 limit on Sat 17 Oct" in text, text


@pytest.mark.guarantee("F39")
def test_any_span_keeps_the_wall_clock_reading_and_says_so():
    """`any_span` names no last day, so the limit has no date and the clock
    reading is the whole test. Stated here rather than left implied."""
    document = copy.deepcopy(PLAN)
    document["rules"][0].update({"enter_from": "16:00", "exit_by": "22:00",
                                 "day_span": "any_span"})
    fee, text = _fee(TO_2345_MINUTES, plan=document)
    assert fee == TIME_BASED_2345
    assert "names no last day" in text, (
        f"the line does not say why there is no date on the limit: {text}"
    )


@pytest.mark.guarantee("F39")
def test_a_limit_that_would_have_to_WRAP_is_refused_at_load():
    """`same_day` and `any_span` cannot say where an `exit_by` before
    `enter_from` falls, so the combination is refused rather than assumed --
    naming the rule and BOTH fields."""
    for span, why in (("same_day", "leave before it arrived"),
                      ("any_span", "names no last day")):
        document = copy.deepcopy(PLAN)
        document["rules"][0]["day_span"] = span
        with pytest.raises(InvalidPlan) as raised:
            load_plan(document)
        message = str(raised.value)
        assert "exit_by is 02:00" in message, message
        assert "enter_from (16:00)" in message, message
        assert f"day_span '{span}'" in message, message
        assert why in message, message


@pytest.mark.guarantee("F39")
def test_the_ordinary_EVENING_window_is_NOT_caught_by_that_refusal():
    """The control on the refusal. `next_day` with a limit past midnight is the
    normal evening case and is the whole point of the fix -- if the refusal
    caught it, the refusal would have eaten the feature."""
    load_plan(copy.deepcopy(PLAN))          # exit_by 02:00, enter_from 16:00, next_day
    assert _fee(TO_2345_MINUTES)[0] == EVENT_PRICE


def _qualified_before_the_fix(rule, stay, plan) -> bool:
    """The PRE-FIX exit predicate, kept here and nowhere else.

    `exit_local.time() > exit_by` -- a bare clock reading, with the day-span test
    ahead of it exactly as it shipped. It exists so the sweep below can compare
    the two, and it must never be imported by the engine.
    """
    entry_local = local_minute(stay.entry_at, plan.timezone)
    exit_local = local_minute(stay.exit_at, plan.timezone)
    days_after = (exit_local.date() - entry_local.date()).days
    span_limit = DAY_SPAN_LIMITS[rule.params["day_span"]]
    if span_limit is not None and days_after > span_limit:
        return False
    return not exit_local.time() > rule.params["exit_by"]


@pytest.mark.guarantee("F39")
def test_the_change_is_ONE_DIRECTIONAL_across_the_validator_probe_matrix():
    """Every stay that qualified BEFORE must still qualify after.

    The property holds by argument -- with the span check retained, a stay
    landing strictly inside the span has an exit date before the limit's date,
    and one landing ON the last allowed day compares times exactly as it used
    to -- so this sweep is not a hunt for a counterexample. It is the check that
    the code matches that argument. A hit here means the implementation diverged
    from the design, which is the only thing worth catching.

    Swept over the validator's own probe matrix rather than a written list: the
    probes are the plan's stated boundaries, each side of each.
    """
    from rate_engine.rules.time_window import _exit_failure

    checked = gained = 0
    for span in ("same_day", "next_day", "any_span"):
        for exit_by in ("02:00", "06:00", "22:00", "23:00"):
            document = copy.deepcopy(PLAN)
            document["rules"][0].update({"exit_by": exit_by, "day_span": span})
            try:
                plan = load_plan(document)
            except InvalidPlan:
                continue                     # refused at load; there is nothing to sweep
            rule = [r for r in plan.rules if r.type == "time_window"][0]
            for stay in probe_stays(plan):
                entry_local = local_minute(stay.entry_at, plan.timezone)
                exit_local = local_minute(stay.exit_at, plan.timezone)
                before = _qualified_before_the_fix(rule, stay, plan)
                after = _exit_failure(rule, entry_local, exit_local) is None
                checked += 1
                assert not (before and not after), (
                    f"a stay STOPPED qualifying: span={span} exit_by={exit_by} "
                    f"entry={stay.entry_at} exit={stay.exit_at}"
                )
                gained += after and not before

    assert checked > 0, "the sweep measured nothing"
    assert gained > 0, (
        "no stay started qualifying, so this sweep could not have seen the fix at "
        "all -- it is passing on a matrix that never reaches the defect"
    )

# --- the same window under `cheapest_wins` ---------------------
#
# The fixture above moved to `stated_order` in an earlier fix, because under
# `cheapest_wins` its 40.00 window was dearer than the hour and is not used though
# it qualifies. That left `cheapest_wins` with no test of this window at all.
# (Since F63 the fixture above prices its window below the hour, so it is charged
# under either mode; this section stays as the `cheapest_wins` plan of it.) So
# here the window is CHEAPER than the hour -- 10.00 against 3.00 an hour -- and
# the car that leaves the same evening, at 23:45, must get it: the hour would be
# 18.00. A bare-clock exit test refuses it (and charges 18.00); so does a
# comparison that charges the hour.

CHEAP_EVENT_PRICE = 1000


def _cheapest_wins_plan() -> dict:
    document = copy.deepcopy(PLAN)
    document["resolution"] = {"QUALIFY": {"mode": "cheapest_wins"},
                              "ACCUMULATE": {"mode": "cheapest_wins"}}
    document["rules"][0]["effect"]["price_minor"] = CHEAP_EVENT_PRICE
    return document


def _codes_of(minutes: int, document: dict) -> tuple[int, list[str]]:
    entry_at = parse_instant(SATURDAY_1830, "entry")
    status, body = run_quote(
        {
            "plans": [copy.deepcopy(document)],
            "entry_at": SATURDAY_1830,
            "exit_at": (entry_at + timedelta(minutes=minutes)).isoformat(),
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200, body
    return body["fee_minor"], [ln["code"] for ln in body["breakdown"]]


def test_the_cheapest_wins_fixture_puts_the_window_below_the_hour():
    """The control: at 23:45 and at 00:30 the hour costs more than the window."""
    assert CHEAP_EVENT_PRICE < TIME_BASED_2345
    # 00:30 is six hours: 3.00 + 5 x 3.00.
    assert CHEAP_EVENT_PRICE < 300 + 5 * 300


@pytest.mark.guarantee("F39")
def test_under_cheapest_wins_the_car_out_at_2345_gets_the_cheaper_window():
    fee, codes = _codes_of(TO_2345_MINUTES, _cheapest_wins_plan())
    assert fee == CHEAP_EVENT_PRICE, (
        f"out at 23:45 under an after-midnight limit, charged {fee}: the window was "
        "refused or the hour charged"
    )
    assert "time_window.applied" in codes and "special_used" in codes, codes


@pytest.mark.guarantee("F39")
def test_under_cheapest_wins_the_car_out_after_midnight_gets_it_too():
    fee, codes = _codes_of(TO_0030_MINUTES, _cheapest_wins_plan())
    assert fee == CHEAP_EVENT_PRICE
    assert "time_window.applied" in codes and "special_used" in codes, codes


@pytest.mark.guarantee("F39")
def test_under_cheapest_wins_past_the_limit_the_hour_is_charged():
    """The positive control: out at 03:00 is past the limit, so no window and no
    comparison -- the hour's 27.00."""
    fee, codes = _codes_of(PAST_LIMIT_MINUTES, _cheapest_wins_plan())
    assert fee == TIME_BASED_PAST_LIMIT
    assert "time_window.not_applied" in codes and "special_used" not in codes, codes
