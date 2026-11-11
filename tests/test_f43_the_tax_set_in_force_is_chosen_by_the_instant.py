"""F43 -- the tax set in force is chosen by the instant, and nothing else.

Tax rates change by law. A garage states its taxes as SETS, each taking effect at
an instant; a rate change, a new tax and a repealed tax are all one thing -- a new
set. The caller hands in every set and the instant, and the latest set taking
effect at or before that instant is the one in force. This is F10 for taxes, for
the same reason.

An instant before every set is REFUSED, never taxed at zero. And two sets taking
effect at the same instant are refused at load, both named, rather than resolved
by which one came first in the list.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from rate_engine.findings import GAP_NO_TAX_SET_IN_FORCE, Refused
from rate_engine.plan import InvalidPlan
from rate_engine.tax import load_tax_sets, tax_lines

SUBTOTAL = 1000


def _rule(bp: int, rule_id: str = "city", sequence: int = 1) -> dict:
    return {"id": rule_id, "label": "City parking tax", "percent_bp": bp,
            "rounding": "down", "sequence": sequence}


#: The city's tax was 8%, went to 10% on 1 July, and was REPEALED on 1 October.
SETS = [
    {"effective_from": "2026-01-01T00:00:00-05:00", "rules": [_rule(800)]},
    {"effective_from": "2026-07-01T00:00:00-04:00", "rules": [_rule(1000)]},
    {"effective_from": "2026-10-01T00:00:00-04:00", "rules": []},
]


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _amounts(sets: list, at: str) -> list[int]:
    return [line.delta_minor for line in
            tax_lines(load_tax_sets(sets), subtotal_minor=SUBTOTAL, currency="USD", at=_at(at))]


@pytest.mark.guarantee("F43")
def test_the_instant_picks_the_set():
    assert _amounts(SETS, "2026-03-03T12:00:00-05:00") == [80]
    assert _amounts(SETS, "2026-08-03T12:00:00-04:00") == [100]


@pytest.mark.guarantee("F43")
def test_a_set_takes_effect_AT_its_instant_not_after_it():
    assert _amounts(SETS, "2026-06-30T23:59:59-04:00") == [80]
    assert _amounts(SETS, "2026-07-01T00:00:00-04:00") == [100]


@pytest.mark.guarantee("F43")
def test_a_REPEALED_tax_is_a_new_set_without_it():
    """Per-rule versions could change a rate and could not end a tax. A set can."""
    assert _amounts(SETS, "2026-11-01T12:00:00-04:00") == []


@pytest.mark.guarantee("F43")
def test_the_list_order_of_the_sets_decides_nothing():
    for at in ("2026-03-03T12:00:00-05:00", "2026-08-03T12:00:00-04:00",
               "2026-11-01T12:00:00-04:00"):
        assert _amounts(SETS, at) == _amounts(list(reversed(SETS)), at)


@pytest.mark.guarantee("F43")
def test_an_instant_before_every_set_is_REFUSED_naming_it_never_taxed_at_zero():
    sets = load_tax_sets(SETS)
    with pytest.raises(Refused) as caught:
        tax_lines(sets, subtotal_minor=SUBTOTAL, currency="USD",
                  at=_at("2025-12-31T23:59:00-05:00"))
    (finding,) = caught.value.findings
    assert finding.code == GAP_NO_TAX_SET_IN_FORCE
    assert "tax_sets[0]" in finding.text, finding.text


@pytest.mark.guarantee("F43")
def test_the_gap_is_refused_EVEN_ON_A_ZERO_SUBTOTAL():
    """A zero subtotal produces no lines -- but a gap in what the garage stated
    is not hidden by an amount that happened to be zero."""
    with pytest.raises(Refused):
        tax_lines(load_tax_sets(SETS), subtotal_minor=0, currency="USD",
                  at=_at("2025-06-01T12:00:00-04:00"))


@pytest.mark.guarantee("F43")
def test_two_sets_taking_effect_at_the_same_instant_are_REFUSED_both_named():
    sets = [SETS[0], {"effective_from": "2026-01-01T00:00:00-05:00", "rules": [_rule(900)]}]
    with pytest.raises(InvalidPlan) as caught:
        load_tax_sets(sets)
    assert "tax_sets[0]" in str(caught.value) and "tax_sets[1]" in str(caught.value)


@pytest.mark.guarantee("F43")
def test_the_same_instant_written_in_TWO_OFFSETS_is_still_the_same_instant():
    sets = [SETS[0], {"effective_from": "2026-01-01T05:00:00+00:00", "rules": [_rule(900)]}]
    with pytest.raises(InvalidPlan):
        load_tax_sets(sets)


def test_the_control_different_instants_load():
    assert len(load_tax_sets(SETS)) == 3


@pytest.mark.guarantee("F43")
def test_an_EMPTY_list_of_sets_is_refused_it_states_nothing():
    """"No tax" is a set with no rules -- a statement. No sets at all is silence."""
    with pytest.raises(InvalidPlan):
        load_tax_sets([])


@pytest.mark.guarantee("F43")
def test_a_NAIVE_instant_is_refused():
    with pytest.raises(InvalidPlan):
        tax_lines(load_tax_sets(SETS), subtotal_minor=SUBTOTAL, currency="USD",
                  at=datetime(2026, 3, 3, 12, 0))
