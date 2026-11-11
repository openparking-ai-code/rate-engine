"""F42 -- taxes never compound. Every rule is a percentage of the same subtotal.

Tax of the tax is extremely unusual. The guarantee has two
halves, and they are held in two different places:

* **The arithmetic.** Every rule in a set is computed from `subtotal_minor`, the
  money actually paid, and never from a total that already includes another tax
  line. There is no way left to WRITE a compounding rule, so this is where the
  guarantee actually lives, and it is held by a figure that differs if the bug
  is present.
* **The grammar.** A rule cannot state a base at all. `base` is refused by the
  same unknown-key rejection every field in this module gets -- no bespoke
  refusal, because a bespoke refusal for a key nobody may write is a field
  somebody eventually reads.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rate_engine.plan import InvalidPlan
from rate_engine.tax import load_tax_sets, tax_lines

AT = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)

SUBTOTAL = 1000

RULES = [
    {"id": "city", "label": "City parking tax", "percent_bp": 1000,
     "rounding": "down", "sequence": 1},
    {"id": "state", "label": "State sales tax", "percent_bp": 500,
     "rounding": "down", "sequence": 2},
]


def _sets(rules: list) -> list:
    return [{"effective_from": "2026-01-01T00:00:00-05:00", "rules": rules}]


def test_the_fixture_SEPARATES_compounding_from_not():
    """The control on the fixture, and it runs first.

    5% of 1000 is 50; 5% of 1100 is 55. If the two figures were equal the
    assertion below could not see a compounding implementation.
    """
    first = SUBTOTAL * 1000 // 10_000
    assert SUBTOTAL * 500 // 10_000 != (SUBTOTAL + first) * 500 // 10_000


@pytest.mark.guarantee("F42")
def test_the_second_tax_is_taken_of_the_SUBTOTAL_not_of_the_subtotal_plus_the_first():
    lines = tax_lines(load_tax_sets(_sets(RULES)), subtotal_minor=SUBTOTAL,
                      currency="USD", at=AT)
    assert [line.delta_minor for line in lines] == [100, 50], (
        "the second line is not 5% of 1000 -- a compounding implementation gives 55, "
        "5% of 1100"
    )
    assert "of 10.00 USD paid" in lines[1].text, lines[1].text


@pytest.mark.guarantee("F42")
def test_three_taxes_are_all_taken_of_the_same_subtotal():
    rules = RULES + [{"id": "district", "label": "District levy", "percent_bp": 200,
                      "rounding": "down", "sequence": 3}]
    lines = tax_lines(load_tax_sets(_sets(rules)), subtotal_minor=SUBTOTAL,
                      currency="USD", at=AT)
    assert [line.delta_minor for line in lines] == [100, 50, 20]


@pytest.mark.guarantee("F42")
@pytest.mark.parametrize("base", ["city", "subtotal", "fee_before_discounts", {"rule": "city"}])
def test_a_rule_stating_a_BASE_of_any_kind_is_refused_by_the_unknown_key_rejection(base):
    """By the refusal's own data, never by its wording: the key it names."""
    rules = [dict(RULES[0]), dict(RULES[1], base=base)]
    with pytest.raises(InvalidPlan) as caught:
        load_tax_sets(_sets(rules))
    assert caught.value.unknown_keys == ("base",)
    assert "tax_sets[0].rules[1]" in str(caught.value)


def test_the_control_the_same_rule_without_a_base_loads_and_produces_its_line():
    lines = tax_lines(load_tax_sets(_sets([RULES[0]])), subtotal_minor=SUBTOTAL,
                      currency="USD", at=AT)
    assert [line.delta_minor for line in lines] == [100]


@pytest.mark.guarantee("F42")
@pytest.mark.parametrize("shape", [{"fixed": 50}, {"minor": 50}, {"amount": {"kind": "fixed"}}])
def test_a_FLAT_amount_is_not_expressible(shape):
    """Percentage only, and that is a stated limit. A flat field is refused the
    same way a base is -- there is no field for it to be read from."""
    rules = [dict(RULES[0], **shape)]
    with pytest.raises(InvalidPlan) as caught:
        load_tax_sets(_sets(rules))
    assert caught.value.unknown_keys == tuple(sorted(shape))
