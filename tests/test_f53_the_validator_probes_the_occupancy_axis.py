"""F53 -- `validate-plan` probes the occupancy axis a fill rule brings.

The README's standing rule: a rule type that qualifies on something the validator
does not probe "would need its own probe axis, and adding one is part of adding
the rule type". `fill_level` qualifies on how full the garage was at entry, so the
axis arrives with it: each threshold one basis point below, on it, and 100% full.

**The fixture is a collision that ONLY exists when the garage is nearly full.**
Two fill rules on the standard class at 90% and 95%: at 90% to 94.99% one applies,
and only from 95% do both. A validator probing no figure, or one figure, reports
the plan clean -- and the engine then refuses the 96%-full car.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_validate
from rate_engine.findings import (
    CONFLICT_OVERLAPPING_FILL_RULES,
    GAP_NO_OCCUPANCY_AT_ENTRY,
)
from rate_engine.plan import load_plan
from rate_engine.validator import probe_stays, validate_plan

BASE = {
    "plan_version": "fill-validate-2026",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard", "vip"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _fill(rule_id: str, threshold_bp: int, classes=("standard",)) -> dict:
    return {"id": rule_id, "type": "fill_level", "stage": "ADJUST",
            "space_classes": list(classes), "threshold_bp": threshold_bp,
            "percent_bp": 1000, "rounding": "up",
            "raises_specials": "no", "raises_vip_extra": "no"}


def _plan(*rules, **changes) -> dict:
    document = copy.deepcopy(BASE)
    document["rules"].extend(copy.deepcopy(list(rules)))
    document.update(changes)
    return document


def _codes(document: dict) -> list[str]:
    return [f.code for f in validate_plan(load_plan(copy.deepcopy(document)))]


@pytest.mark.guarantee("F53")
def test_one_fill_rule_validates_clean_and_no_figure_is_not_a_gap():
    assert _codes(_plan(_fill("busy", 8000))) == []
    assert GAP_NO_OCCUPANCY_AT_ENTRY not in _codes(_plan(_fill("busy", 8000)))


@pytest.mark.guarantee("F53")
def test_two_fill_rules_colliding_only_near_full_are_reported_with_the_figure():
    document = _plan(_fill("busy", 9000), _fill("very-busy", 9500),
                     adjust_order=["busy", "very-busy"])
    findings = validate_plan(load_plan(document))
    assert [f.code for f in findings] == [CONFLICT_OVERLAPPING_FILL_RULES]
    assert findings[0].rule_ids == ("busy", "very-busy")
    probe = findings[0].to_json()["probe"]
    assert probe["occupancy_at_entry_bp"] >= 9500, probe


@pytest.mark.guarantee("F53")
def test_the_same_two_rules_on_DIFFERENT_classes_do_not_collide():
    document = _plan(_fill("busy", 9000, ("standard",)), _fill("vip-busy", 9500, ("vip",)))
    assert _codes(document) == []


@pytest.mark.guarantee("F53")
def test_the_axis_is_each_side_of_every_threshold_and_full():
    document = load_plan(_plan(_fill("busy", 8000), _fill("vip-busy", 6000, ("vip",))))
    figures = {s.occupancy_at_entry_bp for s in probe_stays(document)}
    assert figures == {5999, 6000, 7999, 8000, 10000}


@pytest.mark.guarantee("F53")
def test_a_plan_with_no_fill_rule_is_probed_exactly_as_before():
    stays = probe_stays(load_plan(_plan()))
    assert stays and {s.occupancy_at_entry_bp for s in stays} == {None}
    # And its findings carry no figure in the probe they name.
    gap = _plan()
    gap["space_classes"] = ["standard", "vip", "reserved"]
    findings = validate_plan(load_plan(gap))
    assert findings, "the control plan must have a finding to name a probe"
    for finding in findings:
        assert "occupancy_at_entry_bp" not in finding.to_json()["probe"]


@pytest.mark.guarantee("F53")
def test_the_door_reports_the_collision_by_the_same_identifier():
    document = _plan(_fill("busy", 9000), _fill("very-busy", 9500),
                     adjust_order=["busy", "very-busy"])
    status, body = run_validate({"plan": document})
    assert status == 200
    assert [f["code"] for f in body["findings"]] == [CONFLICT_OVERLAPPING_FILL_RULES]
