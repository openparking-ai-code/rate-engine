"""F20 -- both time roundings are declared, and every duration comparison reads one value.

money.py said *"The only rounding in the engine is TIME into periods, it is stated
per rule rather than assumed"*. There are TWO time roundings and the sentence was
false about the first of them:

* `Stay.duration_minutes` rounds a part-minute UP, module-wide, with no plan field
  reaching it -- ASSUMED, not stated per rule;
* `increment.rounding` turns minutes into periods -- genuinely stated per rule.

The outside pass found this was not merely a wording defect: a stay one
millisecond past a stated 24-hour ceiling is 1441 minutes against a 1440 limit and
is REFUSED rather than priced. The behaviour is kept -- it is the ordinary garage
convention, and the specification wants a stay nothing prices to reach the owner as a gap -- but
it is a pricing decision, so it is now stated where an operator reads it.

**What this file does NOT do is change the rounding.** It pins the behaviour and
pins the coherence: every comparison against a duration reads the same rounded
value, so the ceiling edge cannot drift away from the pricing edge.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote
from rate_engine.engine import make_stay
from rate_engine.plan import parse_instant

ONE_MINUTE_RULE = {
    "id": "by-the-minute", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 1, "first_period_minor": 100,
    "repeat_period_minutes": 1, "repeat_period_minor": 100, "rounding": "ceil",
    "max_duration_minutes": None,
}


def _stay(entry: str, exit_: str):
    return make_stay(parse_instant(entry, "e"), parse_instant(exit_, "x"), "standard")


@pytest.mark.guarantee("F20")
@pytest.mark.parametrize(
    "entry,exit_,expected",
    [
        ("2026-03-03T09:00:00-05:00", "2026-03-03T09:00:00-05:00", 0),
        ("2026-03-03T09:00:00-05:00", "2026-03-03T09:01:00-05:00", 1),
        ("2026-03-03T09:00:00-05:00", "2026-03-03T09:01:00.000001-05:00", 2),
        ("2026-03-03T09:00:00-05:00", "2026-03-03T09:00:00.000001-05:00", 1),
    ],
)
def test_a_part_minute_is_a_whole_minute(entry, exit_, expected):
    assert _stay(entry, exit_).duration_minutes == expected


@pytest.mark.guarantee("F20")
def test_the_assumed_rounding_HAS_A_PRICE_and_it_is_pinned():
    """One millisecond doubles the fee on a one-minute rule. Documented, not fixed."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["space_classes"] = ["standard"]
    document["rules"] = [copy.deepcopy(ONE_MINUTE_RULE)]

    def fee(exit_: str) -> int:
        status, body = run_quote(
            {
                "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
                "exit_at": exit_, "space_class": "standard", "currency": "USD",
            }
        )
        assert status == 200
        return body["fee_minor"]

    assert fee("2026-03-03T09:01:00-05:00") == 100
    assert fee("2026-03-03T09:01:00.000001-05:00") == 200


@pytest.mark.guarantee("F20")
def test_the_CEILING_reads_the_same_rounded_value_the_rules_price_on():
    """The coherence property. A ceiling compared against raw microseconds while
    the rules priced on minutes would put the refusal edge in a different place
    from the pricing edge, and an operator could not reason about either."""
    document = copy.deepcopy(DOWNTOWN_V2)

    exactly = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-04T09:00:00-05:00", "space_class": "standard",
            "currency": "USD",
        }
    )
    assert exactly[0] == 200, "24 hours exactly is inside a 1440-minute ceiling"
    assert "1440 minutes" in exactly[1]["breakdown"][0]["text"]

    over = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-04T09:00:00.000001-05:00", "space_class": "standard",
            "currency": "USD",
        }
    )
    assert over[0] == 422, "one millisecond past the ceiling must not be priced"
    finding = over[1]["findings"][0]
    assert finding["code"] == "GAP_STAY_EXCEEDS_MAX_DURATION"
    assert "1441 minutes" in finding["text"], (
        f"the refusal reports a different duration from the one that priced: {finding['text']}"
    )


@pytest.mark.guarantee("F20")
def test_the_rule_stated_rounding_is_the_OTHER_one_and_still_governs_periods():
    """The half of the sentence that was always true, kept true.

    `increment.rounding` turns MINUTES into PERIODS. It is declared per rule and
    the applier refuses a mode it does not implement -- that is F15. This asserts
    the two roundings are distinct: the plan's field cannot reach the part-minute.
    """
    from rate_engine.rules.increment import PERIOD_COUNTERS, ROUNDING_MODES

    assert set(ROUNDING_MODES) == {"ceil"}
    assert set(PERIOD_COUNTERS) == {"ceil"}
    # 61 minutes on a 60-minute rule is two periods under ceil. The part-minute
    # rounding is not involved: 61 whole minutes in, 61 whole minutes out.
    assert _stay("2026-03-03T09:00:00-05:00", "2026-03-03T10:01:00-05:00").duration_minutes == 61


def test_money_py_no_longer_claims_the_only_rounding_is_stated_per_rule():
    """The control on the DOCUMENTATION half of this item.

    A wording fix with no check is a sentence that drifts back. This fails if the
    false clause returns, and it is keyed on the CLAIM rather than on a phrase
    somebody might reword: the file must not say the rounding is stated per rule
    without also saying one of them is assumed.
    """
    import rate_engine.money as money

    text = " ".join((money.__doc__ or "").split())
    assert "stated per rule rather than assumed" not in text, (
        "money.py claims again that the only rounding is stated per rule"
    )
    assert "ASSUMED" in text and "duration_minutes" in text, (
        "money.py no longer says which rounding is assumed, so the correction has "
        "been reworded away"
    )
