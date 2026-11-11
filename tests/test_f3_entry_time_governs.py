"""F3 -- the plan in force at ENTRY prices the whole stay.

The rule: the price is always calculated with the entry-time fee. A rate
change mid-stay never splits the stay. A car that entered on Friday under the old
card leaves on Sunday paying Friday's prices, and a garage that put its rates up
on Saturday morning does not reach back into it.

**This test is why `/v1/quote` takes a LIST of plan versions.** Handed exactly one
plan, an engine cannot demonstrate that it selected by entry rather than by exit
-- there is nothing to select, and the guarantee would be a sentence with no
mechanism behind it. Nothing is stored: the versions arrive on the call, and the
plan STORE is round B.
"""

from __future__ import annotations

import pytest

from fixtures import DOWNTOWN_V2, downtown_v1, stay
from rate_engine.engine import quote
from rate_engine.findings import GAP_NO_PLAN_IN_FORCE_AT_ENTRY, Refused
from rate_engine.plan import load_plan

#: v1 takes effect 2026-01-01 and prices at 500 + 250/h, capped at 2000.
#: v2 takes effect 2026-02-01 and prices at 800 + 400/h, capped at 3000.
VERSIONS = [load_plan(downtown_v1()), load_plan(DOWNTOWN_V2)]

#: Enters under v1, ten hours before v2 takes effect, and leaves under v2.
STRADDLES_THE_CHANGE = stay("2026-01-31T14:00:00-05:00", 20 * 60)


def test_the_two_versions_price_differently():
    """The control for this whole file: if they agreed, nothing below measures anything."""
    entirely_v1 = stay("2026-01-15T09:14:00-05:00", 240)
    entirely_v2 = stay("2026-03-03T09:14:00-05:00", 240)
    assert quote(VERSIONS, entirely_v1).fee_minor == 1250  # 500 + 3 x 250
    assert quote(VERSIONS, entirely_v2).fee_minor == 2000  # 800 + 3 x 400


@pytest.mark.guarantee("F3")
def test_a_stay_spanning_a_rate_change_prices_entirely_on_the_entry_version():
    result = quote(VERSIONS, STRADDLES_THE_CHANGE)

    assert result.plan_version == "downtown-2026-01", (
        "the stay exited under v2 and must still be priced by v1"
    )
    # v1: 500 + 19 x 250 = 5250, capped at 2000 x 2 calendar days = 4000.
    # Under v2 it would have been 800 + 19 x 400 = 8400 capped at 6000.
    assert result.fee_minor == 4000
    assert all(
        "downtown-2026-02" not in line.text for line in result.breakdown.lines
    ), "the breakdown mentions a version that did not price this stay"


@pytest.mark.guarantee("F3")
def test_the_stay_is_never_split_across_the_change():
    """No line prices part of the stay at the other version's rate."""
    result = quote(VERSIONS, STRADDLES_THE_CHANGE)
    repeats = next(
        line for line in result.breakdown.lines if line.code == "increment.repeat_periods"
    )
    assert "2.50 USD" in repeats.text, "the additional hours are all at v1's rate"
    assert "4.00 USD" not in repeats.text


@pytest.mark.guarantee("F3")
def test_an_entry_before_every_supplied_version_is_refused_not_backdated():
    """The engine does not reach for the oldest plan it happens to have."""
    with pytest.raises(Refused) as caught:
        quote(VERSIONS, stay("2025-12-25T09:14:00-05:00", 120))
    assert caught.value.findings[0].code == GAP_NO_PLAN_IN_FORCE_AT_ENTRY


