"""F44 -- taxes come out in the `sequence` the garage states, never in list order.

Each rule carries a required `sequence`, a whole number unique within its set.
Array position decides nothing: a JSON list always HAS an order, so "the order
was not stated" is not something a list can express -- and the caller's array
position deciding money is the defect this module has already had to remove once.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rate_engine.plan import InvalidPlan
from rate_engine.tax import load_tax_sets, tax_lines

AT = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)

RULES = [
    {"id": "state", "label": "State sales tax", "percent_bp": 500,
     "rounding": "down", "sequence": 2},
    {"id": "city", "label": "City parking tax", "percent_bp": 1000,
     "rounding": "down", "sequence": 1},
    {"id": "district", "label": "District levy", "percent_bp": 200,
     "rounding": "down", "sequence": 7},
]


def _ids(rules: list) -> list[str]:
    sets = load_tax_sets([{"effective_from": "2026-01-01T00:00:00-05:00", "rules": rules}])
    return [line.rule_id for line in
            tax_lines(sets, subtotal_minor=1000, currency="USD", at=AT)]


def test_the_fixture_is_NOT_already_in_sequence_order():
    """The control on the fixture: a list that happened to be sorted would pass
    against an applier that ignored `sequence` entirely."""
    listed = [rule["id"] for rule in RULES]
    assert listed != ["city", "state", "district"]
    assert list(reversed(listed)) != ["city", "state", "district"]


@pytest.mark.guarantee("F44")
def test_the_lines_follow_the_sequence_whatever_order_the_list_arrives_in():
    assert _ids(RULES) == ["city", "state", "district"]
    assert _ids(list(reversed(RULES))) == ["city", "state", "district"]


@pytest.mark.guarantee("F44")
def test_a_rule_with_no_sequence_is_REFUSED():
    rules = [dict(r) for r in RULES]
    del rules[1]["sequence"]
    with pytest.raises(InvalidPlan) as caught:
        _ids(rules)
    assert caught.value.missing_keys == ("sequence",)


@pytest.mark.guarantee("F44")
def test_sequence_ZERO_is_accepted_and_ordered_first_while_an_ABSENT_one_is_refused():
    """0 is a whole number and a sequence the garage stated. A truthiness test --
    `raw["sequence"] or None` -- would read it as missing, and nothing noticed
    when one was planted: the behaviour was right and unguarded.

    Both sides in one set, so a check that got either one wrong fails here.
    """
    rules = [dict(r) for r in RULES]
    rules[2]["sequence"] = 0
    assert _ids(rules) == ["district", "city", "state"]

    rules.append({"id": "levy", "label": "Stadium levy", "percent_bp": 100,
                  "rounding": "down"})
    with pytest.raises(InvalidPlan) as caught:
        _ids(rules)
    assert caught.value.missing_keys == ("sequence",)
    assert "rules[3]" in str(caught.value), str(caught.value)


@pytest.mark.guarantee("F44")
def test_two_rules_sharing_a_sequence_are_REFUSED_both_named():
    rules = [dict(r) for r in RULES]
    rules[2]["sequence"] = 2
    with pytest.raises(InvalidPlan) as caught:
        _ids(rules)
    assert "'state'" in str(caught.value) and "'district'" in str(caught.value)


@pytest.mark.guarantee("F44")
@pytest.mark.parametrize("value", [-1, "1", None, 1.0, True])
def test_a_sequence_that_is_not_a_whole_number_is_REFUSED(value):
    rules = [dict(r) for r in RULES]
    rules[0]["sequence"] = value
    with pytest.raises(Exception) as caught:
        _ids(rules)
    assert "rules[0].sequence" in str(caught.value), str(caught.value)
