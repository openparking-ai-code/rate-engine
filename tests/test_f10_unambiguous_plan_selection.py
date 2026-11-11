"""F10 -- plan selection is never ambiguous, and never decided by list order.

**This was a live defect on the branch, not a hypothetical.** `select_plan` used
`max(in_force, key=...effective_from)`, and `max` returns the FIRST maximal
element. Two plan versions carrying the same `effective_from` therefore priced
the same car at **300 or at 2700 minor units** depending only on which one the
caller happened to put first in a JSON array — a nine-fold difference in the fee,
decided by something no operator would think of as an input, and reported
nowhere.

The entry-time rule (F3) says the version in force at entry prices the stay.
That sentence assumes there is exactly one such version, and nothing was checking
the assumption. Where there is more than one, this module does what it does
everywhere else: it refuses and names them, rather than picking.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2, stay
from rate_engine.contract import run_quote
from rate_engine.engine import quote, select_plan
from rate_engine.findings import CONFLICT_AMBIGUOUS_PLAN_SELECTION, Refused
from rate_engine.plan import load_plan

ENTRY = "2026-03-03T09:14:00-05:00"
THREE_HOURS = stay(ENTRY, 180)


def _priced_at(version: str, per_hour: int) -> dict:
    """The same garage at two prices, deliberately sharing one effective date."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["plan_version"] = version
    for rule in document["rules"]:
        if rule["id"] == "hourly":
            rule["first_period_minor"] = per_hour
            rule["repeat_period_minor"] = per_hour
    return document


CHEAP = _priced_at("same-date-CHEAP", 100)
DEAR = _priced_at("same-date-DEAR", 900)


def test_the_two_versions_really_do_share_a_date_and_really_do_differ():
    """The control for this whole file, and it runs first.

    If the dates differed, selection would be unambiguous and there would be
    nothing to refuse. If the prices agreed, order-dependence would be invisible
    and the original defect would have been undetectable by any assertion here.
    """
    assert CHEAP["effective_from"] == DEAR["effective_from"]
    assert CHEAP["plan_version"] != DEAR["plan_version"]

    only_cheap = quote([load_plan(CHEAP)], THREE_HOURS).fee_minor
    only_dear = quote([load_plan(DEAR)], THREE_HOURS).fee_minor
    assert (only_cheap, only_dear) == (300, 2700), (
        "these are the two fees the original defect chose between by array order"
    )


@pytest.mark.guarantee("F10")
def test_two_versions_sharing_a_date_are_refused_and_both_are_named():
    with pytest.raises(Refused) as caught:
        quote([load_plan(CHEAP), load_plan(DEAR)], THREE_HOURS)

    finding = caught.value.findings[0]
    assert finding.code == CONFLICT_AMBIGUOUS_PLAN_SELECTION
    assert "same-date-CHEAP" in finding.text
    assert "same-date-DEAR" in finding.text, "a refusal naming one of two is half an answer"


@pytest.mark.guarantee("F10")
def test_the_refusal_is_byte_identical_in_either_order():
    """The half a fix could easily miss.

    Refusing instead of pricing removes the wrong FEE. It does not, on its own,
    remove the order-dependence — a message that listed the versions in arrival
    order would still be two different answers to the same question.
    """
    first = run_quote(_request([CHEAP, DEAR]))
    second = run_quote(_request([DEAR, CHEAP]))
    assert first == second, "the refusal still depends on the order of the array"
    assert first[0] == 422


@pytest.mark.guarantee("F10")
def test_an_unambiguous_selection_still_prices_normally():
    """The refusal must not have been bought by refusing more widely.

    Distinct dates: the later one governs, and the fee is the one it names. If
    this went red the fix would have closed the defect by breaking F3.
    """
    later = copy.deepcopy(DEAR)
    later["effective_from"] = "2026-02-15T00:00:00-05:00"
    result = quote([load_plan(CHEAP), load_plan(later)], THREE_HOURS)
    assert result.plan_version == "same-date-DEAR"
    assert result.fee_minor == 2700

    assert select_plan([load_plan(CHEAP)], THREE_HOURS).plan_version == "same-date-CHEAP"


@pytest.mark.guarantee("F10")
def test_a_tie_that_is_not_the_latest_does_not_refuse():
    """Two versions may share a date harmlessly if a later one supersedes both.

    The ambiguity is only ever about which version is IN FORCE. Refusing on any
    duplicate date at all would reject plan histories that are perfectly clear,
    and this is the case that proves the check is scoped to the question.
    """
    superseding = copy.deepcopy(DOWNTOWN_V2)
    superseding["plan_version"] = "later-and-unambiguous"
    superseding["effective_from"] = "2026-02-20T00:00:00-05:00"

    result = quote(
        [load_plan(CHEAP), load_plan(DEAR), load_plan(superseding)], THREE_HOURS
    )
    assert result.plan_version == "later-and-unambiguous"


def _request(documents: list[dict]) -> dict:
    return {
        "plans": documents,
        "entry_at": THREE_HOURS.entry_at.isoformat(),
        "exit_at": THREE_HOURS.exit_at.isoformat(),
        "space_class": THREE_HOURS.space_class,
        "currency": "USD",
    }
