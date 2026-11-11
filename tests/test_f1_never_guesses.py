"""F1 -- the engine never guesses.

A stay the plan cannot price is REFUSED, naming the gap. This is the project's
standing acceptance ("never wrong silently") in the one module where it is also
the entire commercial argument: an operator who cannot check the engine's work
can still trust a system that refuses when it is unsure.

The planted defect makes the gap detection stop looking, and the control requires
a NUMBER to come back where a refusal should have -- which is the exact failure
this guarantee exists to prevent, not a proxy for it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fixtures import loaded, plan_with, stay, with_rule_field, without_rule
from rate_engine.engine import quote
from rate_engine.findings import (
    GAP_NO_ACCUMULATE_RULE,
    GAP_NO_OCCUPANCY_AT_ENTRY,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
    GAP_NO_TAX_SET_IN_FORCE,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_STAY_LONGER_THAN_MAX_STAY,
    GAP_UNDECLARED_SPACE_CLASS,
    Refused,
)
from rate_engine.tax import load_tax_sets, tax_lines
from rate_engine.validator import validate_plan

LATE = "2026-03-03T09:14:00-05:00"

#: The reference plan with a fill rule on its standard spaces: 80% full, +20%.
FILL_PLAN = plan_with(adjust_order=None)
FILL_PLAN["rules"].append({
    "id": "busy", "type": "fill_level", "stage": "ADJUST", "space_classes": ["standard"],
    "threshold_bp": 8000, "percent_bp": 2000, "rounding": "up",
    "raises_specials": "no", "raises_vip_extra": "no",
})


@pytest.mark.guarantee("F1")
def test_a_stay_past_the_stated_ceiling_is_refused_not_priced():
    """The specification's own example of a gap: nothing prices a stay past 24 hours."""
    plan = loaded()
    with pytest.raises(Refused) as caught:
        quote([plan], stay(LATE, 1441))
    codes = [f.code for f in caught.value.findings]
    assert codes == [GAP_STAY_EXCEEDS_MAX_DURATION]
    assert "1441 minutes" in caught.value.findings[0].text
    assert "1440" in caught.value.findings[0].text

    # One minute less is priced. Without this the test would pass against an
    # engine that refuses everything.
    assert quote([plan], stay(LATE, 1440)).fee_minor > 0


@pytest.mark.guarantee("F1")
def test_every_registered_gap_code_is_reachable_from_a_fixture():
    """A code nothing can produce is a promise with no mechanism behind it.

    Derived from the registry rather than from a list here, so a gap code added
    to findings.py with no way to reach it fails this immediately.
    """
    reached: set[str] = set()

    with pytest.raises(Refused) as e:
        quote([loaded()], stay(LATE, 120, "motorcycle"))
    reached.add(e.value.findings[0].code)

    with pytest.raises(Refused) as e:
        quote([loaded()], stay(LATE, 1441))
    reached.add(e.value.findings[0].code)

    with pytest.raises(Refused) as e:
        quote([loaded(without_rule("hourly"))], stay(LATE, 120, "vip"))
    reached.add(e.value.findings[0].code)

    with pytest.raises(Refused) as e:
        quote([loaded()], stay("2026-01-05T09:14:00-05:00", 120))
    reached.add(e.value.findings[0].code)

    # The tax gap, from a tax fixture: an instant before every stated set.

    sets = load_tax_sets([{"effective_from": "2026-01-01T00:00:00-05:00", "rules": []}])
    with pytest.raises(Refused) as e:
        tax_lines(sets, subtotal_minor=1000, currency="USD",
                  at=datetime(2025, 6, 1, tzinfo=UTC))
    reached.add(e.value.findings[0].code)

    # The occupancy gap: a plan with a fill rule, and a stay with no figure.
    with pytest.raises(Refused) as e:
        quote([loaded(FILL_PLAN)], stay(LATE, 120))
    reached.add(e.value.findings[0].code)

    # The engine's own limit: a stay a minute longer than 90 days (F62).
    with pytest.raises(Refused) as e:
        quote([loaded()], stay(LATE, 90 * 24 * 60 + 1))
    reached.add(e.value.findings[0].code)

    from rate_engine.findings import GAP_CODES

    assert reached == set(GAP_CODES), (
        f"gap codes with no fixture that reaches them: {sorted(set(GAP_CODES) - reached)}"
    )
    assert reached == {
        GAP_UNDECLARED_SPACE_CLASS,
        GAP_STAY_EXCEEDS_MAX_DURATION,
        GAP_NO_ACCUMULATE_RULE,
        GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
        GAP_NO_TAX_SET_IN_FORCE,
        GAP_NO_OCCUPANCY_AT_ENTRY,
        GAP_STAY_LONGER_THAN_MAX_STAY,
    }


@pytest.mark.guarantee("F1")
def test_the_validator_and_the_engine_report_the_same_gap_by_identifier():
    """One mechanism, two places -- keyed by code, never matched on the sentence."""
    document = with_rule_field("hourly", max_duration_minutes=120)
    plan = loaded(document)

    from_validator = {f.code for f in validate_plan(plan)}
    with pytest.raises(Refused) as caught:
        quote([plan], stay(LATE, 300))
    from_engine = {f.code for f in caught.value.findings}

    assert GAP_STAY_EXCEEDS_MAX_DURATION in from_validator
    assert from_engine <= from_validator, (
        "the engine refused with a code the validator never reports, so an owner "
        "could approve a plan and still meet that refusal in production"
    )


