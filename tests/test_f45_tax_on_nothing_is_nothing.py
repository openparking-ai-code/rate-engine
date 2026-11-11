"""F45 -- a subtotal of zero produces no tax lines.

Tax applies to the money actually paid. A stay a validation covered in full, a
covered stay and a genuinely free one have paid nothing, so there is nothing to
tax and no line -- the same answer the platform gave one line earlier on the same
ledger, where only a priced fee above zero is discounted. A ledger of zero-valued
tax lines under a zero fee is noise of exactly the kind `space_surcharge` already
declines to emit.

The control is the same rules on a positive subtotal, which must produce lines:
without it this file would pass against a function that never produced any.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rate_engine.money import NotMinorUnits
from rate_engine.tax import load_tax_sets, tax_lines

AT = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)

SETS = load_tax_sets(
    [{"effective_from": "2026-01-01T00:00:00-05:00", "rules": [
        {"id": "city", "label": "City parking tax", "percent_bp": 1000,
         "rounding": "up", "sequence": 1},
        {"id": "state", "label": "State sales tax", "percent_bp": 500,
         "rounding": "nearest", "sequence": 2},
    ]}]
)


def _lines(subtotal):
    return tax_lines(SETS, subtotal_minor=subtotal, currency="USD", at=AT)


@pytest.mark.guarantee("F45")
def test_a_zero_subtotal_produces_NO_lines():
    assert _lines(0) == []


@pytest.mark.guarantee("F45")
def test_the_control_the_same_rules_on_a_positive_subtotal_produce_lines():
    """Even one minor unit, where `up` makes a tax out of a fraction."""
    assert [line.delta_minor for line in _lines(1)] == [1, 0]
    assert [line.delta_minor for line in _lines(1000)] == [100, 50]


@pytest.mark.guarantee("F45")
@pytest.mark.parametrize("value", [-1, 10.0, True, "1000"])
def test_a_subtotal_that_is_not_money_or_is_negative_is_REFUSED(value):
    with pytest.raises(NotMinorUnits) as caught:
        _lines(value)
    assert "subtotal_minor" in str(caught.value)
