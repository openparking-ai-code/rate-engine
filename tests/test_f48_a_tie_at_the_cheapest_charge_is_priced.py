"""F48 -- a tie at the cheapest charge is priced, not refused. Replaces F11.

**F11 refused it, and that was the last thing the resolution modes could not
settle.** An earlier change made `cheapest_wins` and `stated_order` decide between two specials
at different prices; what was left was two rules that both qualify and charge
the SAME amount, and F11 refused that stay naming both. The plan store calls the
validator before it keeps a plan, so a garage with a weekday early bird at 12.00
and a "come in before 10" rate at 12.00 could not save its rates at all.

The rule (2026-10-11): **the cheaper way always goes first**. At a tie there is no
cheaper -- the driver pays 12.00 whichever rule is named -- so there is nothing
for an owner to decide and nothing the engine would be guessing. The stay is
priced at that amount. The receipt still names ONE rule, and it is the lowest
rule id: stated by the operator, stable, never the caller's array position. The
others say they charged the same, which is the true reason they were not named.

`stated_order` never had a tie while it chose outright: the plan named who won,
the dearer included. Since F63 it charges the cheapest too, so two rules there
CAN charge the same, and the stated order names the one the receipt shows -- the
same tie, priced the same way, named by the plan's order instead of the id.

The fixtures are F11's, kept on purpose: the same two windows and the same two
increments that used to be refused are the ones that must now price.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2, stay
from rate_engine.contract import run_validate
from rate_engine.engine import find_conflicts, quote
from rate_engine.plan import load_plan

THREE_HOURS = stay("2026-03-03T09:14:00-05:00", 180)
#: Inside both windows below: a Tuesday, in at 08:30, out at 12:30.
EARLY = stay("2026-03-03T08:30:00-05:00", 240)


def _with_extra(rule: dict) -> dict:
    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"] = document["rules"] + [rule]
    return document


def _late_bird(price_minor: int) -> dict:
    return {
        "id": "eb-late",
        "type": "time_window",
        "stage": "QUALIFY",
        "space_classes": ["standard"],
        "label": "Late bird",
        "applies_on": {"kind": "days_of_week", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "enter_from": "06:00",
        "enter_by": "10:00",
        "exit_by": "17:00",
        "day_span": "same_day",
        "effect": {"kind": "flat", "price_minor": price_minor},
    }


#: Two windows that both qualify for EARLY at the SAME price as the reference
#: plan's early bird (12.00). F11 refused this stay.
TWO_WINDOWS = _with_extra(_late_bird(1200))

#: The same shape at the other resolving stage, so the rule is a property of the
#: pipeline rather than of one rule type: same periods and prices as `hourly`.
TWO_INCREMENTS = _with_extra(
    {
        "id": "hourly-alternative",
        "type": "increment",
        "stage": "ACCUMULATE",
        "space_classes": ["standard"],
        "first_period_minutes": 60,
        "first_period_minor": 800,
        "repeat_period_minutes": 60,
        "repeat_period_minor": 400,
        "rounding": "ceil",
        "max_duration_minutes": None,
    }
)


def _applied(result) -> list[str]:
    return [ln.rule_id for ln in result.breakdown.lines if ln.code == "time_window.applied"]


def _resolved(result) -> list:
    return [ln for ln in result.breakdown.lines if ln.code == "resolved"]


def test_the_reference_plan_has_no_conflict_to_find():
    """The control: the plan every other test uses already prices cleanly."""
    assert find_conflicts(load_plan(DOWNTOWN_V2), THREE_HOURS) == []


@pytest.mark.guarantee("F48")
def test_two_specials_TIED_on_price_validate_clean():
    """What the store asks before it keeps a plan. A tie is no finding at all."""
    status, body = run_validate({"plan": copy.deepcopy(TWO_WINDOWS)})
    assert status == 200, body
    conflicts = [f for f in body["findings"] if f["kind"] == "conflict"]
    assert conflicts == [], f"a tie is still reported as a conflict: {conflicts}"


@pytest.mark.guarantee("F48")
def test_a_stay_inside_both_PRICES_at_that_amount_and_names_the_winner():
    result = quote([load_plan(copy.deepcopy(TWO_WINDOWS))], EARLY)
    assert result.fee_minor == 1200
    # The lowest rule id is named: "eb-late" < "eb-weekday".
    assert _applied(result) == ["eb-late"]
    loser = _resolved(result)
    assert [ln.rule_id for ln in loser] == ["eb-weekday"]
    assert "charged the same as Late bird" in loser[0].text, loser[0].text
    assert loser[0].delta_minor == 0


@pytest.mark.guarantee("F48")
def test_the_winner_does_not_depend_on_the_order_the_rules_arrived_in():
    document = copy.deepcopy(TWO_WINDOWS)
    document["rules"] = list(reversed(document["rules"]))
    result = quote([load_plan(document)], EARLY)
    assert result.fee_minor == 1200
    assert _applied(result) == ["eb-late"]


@pytest.mark.guarantee("F48")
def test_a_CHEAPER_special_still_wins_and_the_dearer_is_named_as_dearer():
    """The control on the tie: the rule is "cheaper goes first", and a tie is only
    the case where nothing is cheaper. A cheaper rule with the HIGHER id must win,
    or the tie-break has swallowed the comparison."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"] = document["rules"] + [
        {**_late_bird(1000), "id": "zz-cheaper", "label": "Cheaper bird"}
    ]
    result = quote([load_plan(document)], EARLY)
    assert result.fee_minor == 1000
    assert _applied(result) == ["zz-cheaper"]
    loser = _resolved(result)
    assert [ln.rule_id for ln in loser] == ["eb-weekday"]
    assert "applied instead" in loser[0].text
    assert "charged the same" not in loser[0].text

    # And the dearer one at the LOWER id never wins.
    dearer = copy.deepcopy(DOWNTOWN_V2)
    dearer["rules"] = dearer["rules"] + [{**_late_bird(1500), "id": "aa-dearer"}]
    assert quote([load_plan(dearer)], EARLY).fee_minor == 1200


@pytest.mark.guarantee("F48")
def test_a_tie_at_the_OTHER_resolving_stage_prices_the_same_way():
    base = quote([load_plan(DOWNTOWN_V2)], THREE_HOURS).fee_minor
    result = quote([load_plan(copy.deepcopy(TWO_INCREMENTS))], THREE_HOURS)
    assert result.fee_minor == base
    loser = _resolved(result)
    assert [ln.rule_id for ln in loser] == ["hourly-alternative"]
    assert "charged the same" in loser[0].text


@pytest.mark.guarantee("F48")
def test_under_stated_order_a_tie_is_priced_and_the_ORDER_names_the_rule():
    """Since F63 `stated_order` charges the cheapest too, so a tie is a tie there:
    priced at that amount, the first rule in the order named -- not the lowest
    id -- and the other says it charged the same, and why it was not named."""
    document = copy.deepcopy(TWO_WINDOWS)
    document["resolution"]["QUALIFY"] = {
        "mode": "stated_order", "order": ["eb-weekday", "eb-late"],
    }
    result = quote([load_plan(document)], EARLY)
    assert result.fee_minor == 1200
    assert _applied(result) == ["eb-weekday"], "the lowest id was named, not the stated first"
    loser = _resolved(result)
    assert [ln.rule_id for ln in loser] == ["eb-late"]
    assert "charged the same as Early bird" in loser[0].text, loser[0].text
    assert "the plan's stated order puts it first" in loser[0].text, loser[0].text


@pytest.mark.guarantee("F48")
def test_two_rules_at_one_stage_that_cannot_both_qualify_still_price():
    """Carried from F11: a second window on days the stay does not fall on changes
    nothing, and on its own day it is the one that qualifies."""
    document = _with_extra(
        {
            "id": "eb-weekend",
            "type": "time_window",
            "stage": "QUALIFY",
            "space_classes": ["standard"],
            "label": "Weekend rate",
            "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
            "enter_from": "06:00",
            "enter_by": "09:00",
            "exit_by": "17:00",
            "day_span": "same_day",
            "effect": {"kind": "flat", "price_minor": 1500},
        }
    )
    plan = load_plan(document)
    base = quote([load_plan(DOWNTOWN_V2)], THREE_HOURS).fee_minor
    assert quote([plan], THREE_HOURS).fee_minor == base
    saturday = stay("2026-03-07T07:00:00-05:00", 240)
    assert quote([plan], saturday).fee_minor == 1500
