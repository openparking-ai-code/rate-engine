"""F2 -- a special rate is all-conditions-or-nothing.

The rule: an early bird applies only if the stay meets all its conditions. Miss one
condition and the rate does not apply AT ALL -- the stay prices on the time-based
rate. No stacking, no partial credit, no pro-rating. An early bird missed by an
hour is a full time-based day. (Where it DOES qualify, the driver pays the
cheaper of it and the time-based rate under `cheapest_wins`: F50.)

The fixture is chosen so that the early-bird price and the time-based price are
DIFFERENT for the same stay. That is not incidental: if the two happened to
agree, every assertion below would pass whether or not the rule was applied, and
the control would be measuring nothing.
"""

from __future__ import annotations

import pytest

from fixtures import loaded, stay
from rate_engine.engine import quote

EARLY = "2026-03-03T08:30:00-05:00"  # before the 09:00 limit
LATE = "2026-03-03T09:14:00-05:00"  # after it


def _fee(entry: str, minutes: int) -> int:
    return quote([loaded()], stay(entry, minutes)).fee_minor


def test_the_fixture_can_tell_the_two_prices_apart():
    """The control on this file's own fixture, and it runs first.

    Early bird is 1200. The same stay priced on increments is 800 + 3 x 400 =
    2000. If these were equal, F2 would pass against an engine that ignored the
    rule entirely.
    """
    qualifying = _fee(EARLY, 240)
    same_stay_but_late_entry = _fee(LATE, 240)
    assert qualifying == 1200
    assert same_stay_but_late_entry == 2000
    assert qualifying != same_stay_but_late_entry


@pytest.mark.guarantee("F2")
def test_exit_one_minute_past_the_limit_prices_as_a_full_time_based_stay():
    """08:30 + 8h31m = 17:01. One minute over, and the special is simply not there."""
    over = quote([loaded()], stay(EARLY, 511))
    on_limit = quote([loaded()], stay(EARLY, 510))  # exits at exactly 17:00

    assert on_limit.fee_minor == 1200, "the on-limit stay should still qualify"

    # Not pro-rated, not a partial credit, not capped at the early-bird price:
    # priced as though the rule did not exist. 800 + 8 x 400 = 4000, then the
    # daily max takes it to 3000.
    assert over.fee_minor == 3000
    codes = [line.code for line in over.breakdown.lines]
    assert "time_window.applied" not in codes
    assert "time_window.not_applied" in codes
    assert "increment.first_period" in codes


@pytest.mark.guarantee("F2")
def test_the_breakdown_says_which_condition_failed_and_by_how_much():
    """The line an operator most wants: why they are NOT getting the cheap rate."""
    result = quote([loaded()], stay(EARLY, 511))
    line = next(x for x in result.breakdown.lines if x.code == "time_window.not_applied")
    assert "17:01" in line.text
    assert "17:00" in line.text
    assert line.delta_minor == 0, "a rule that did not apply must not move the fee"


@pytest.mark.guarantee("F2")
def test_missing_the_entry_condition_alone_is_enough():
    """Both conditions are load-bearing, so both are exercised separately."""
    result = quote([loaded()], stay(LATE, 60))  # exits 10:14, well inside exit_by
    line = next(x for x in result.breakdown.lines if x.code == "time_window.not_applied")
    assert "09:14 is after the 09:00 entry limit" in line.text
    assert result.fee_minor == 800, "priced on increments, not on the early-bird rate"


