"""F19 -- the validator probes the boundaries the plan declares, entry included.

The defect, settled by execution in the outside review: every probe entered at
07:00 and varied only the duration. Two `early_bird` rules -- the rule type now
called `time_window` -- that both qualify only
for an entry before 06:00 therefore never overlapped in any probe --
`validate-plan` printed "no gaps, no conflicts" and exited 0, and a real stay
entering at 05:00 was then REFUSED for a conflict. The published sentence said it
"reports every such gap, and every conflict between rules, before a plan goes
live", and the validator is the product.

The fix is not exhaustiveness and not a weaker sentence. A rule that names a time
makes that time interesting, and the plan is where those times live -- so ENTRY
became a derived axis alongside duration, and the sentence now says what the
mechanism does.

**The counterexample below is the outside review's own, with one change forced by a later fix.** A
fix verified against a new test written to pass would prove nothing; the specification requires
the exact probe that failed. Its two windows, their days, their entry and exit
limits and the probe stay are unchanged. What moved is the STAGE: two specials
overlapping at QUALIFY are no longer a conflict at all (the cheaper wins, and a
tie is priced -- F48), so the same two windows are now two DISCOUNTS at ADJUST
with no order stated, which is the conflict a plan can still contain. The
property measured is the same: they collide only for an entry before 05:30, and
a validator probing one entry time never sees it.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import parse_validate_request, run_quote, run_validate
from rate_engine.findings import CONFLICT_UNORDERED_ADJUSTMENTS
from rate_engine.validator import probe_stays

#: Two rules that both qualify only for an entry before 05:30, on a plan with no
#: ceiling so no unrelated gap masks the result. The outside review's counterexample, carried
#: forward onto `time_window` unchanged in everything it measures: the two rules
#: apply on every day, so the day axis cannot be what makes them overlap.
#:
#: **They are DISCOUNTS at ADJUST with no `adjust_order`, and that is not
#: cosmetic.** Two specials at QUALIFY are settled by `cheapest_wins` whatever
#: they charge (F48), so they are no longer a conflict the validator could miss.
#: Two discounts that both apply with no order stated are -- and this file is
#: about whether the VALIDATOR sees what the engine would refuse. A fixture the
#: engine no longer refuses would have made it pass while measuring nothing.
DAWN_CONFLICT = {
    "plan_version": "r3-counterexample",
    "effective_from": "2026-02-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {
        "QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        {"id": "eb-dawn-a", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard"], "label": "Dawn A",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "00:00", "enter_by": "06:00", "exit_by": "17:00",
         "day_span": "same_day",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "fixed", "minor": 100}, "rounding": "down"}},
        {"id": "eb-dawn-b", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard"], "label": "Dawn B",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "00:00", "enter_by": "05:30", "exit_by": "16:00",
         "day_span": "same_day",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "fixed", "minor": 100}, "rounding": "down"}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


@pytest.mark.guarantee("F19")
def test_the_conflict_the_validator_used_to_miss_is_now_REPORTED():
    status, body = run_validate({"plan": copy.deepcopy(DAWN_CONFLICT)})
    assert status == 200
    codes = [f["code"] for f in body["findings"]]
    assert CONFLICT_UNORDERED_ADJUSTMENTS in codes, (
        f"validate-plan still reports this plan clean: {body['findings']}"
    )


@pytest.mark.guarantee("F19")
def test_and_the_engine_refuses_the_SAME_finding_by_identifier():
    """The property the whole item is about: what the owner approved is what the
    lane enforces. A validator that agreed with the engine only sometimes is the
    defect, not a weaker version of it."""
    _s, validated = run_validate({"plan": copy.deepcopy(DAWN_CONFLICT)})
    status, quoted = run_quote(
        {
            "plans": [copy.deepcopy(DAWN_CONFLICT)],
            "entry_at": "2026-03-03T05:00:00-05:00",
            "exit_at": "2026-03-03T12:00:00-05:00",
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 422
    from_engine = {f["code"] for f in quoted["findings"]}
    from_validator = {f["code"] for f in validated["findings"]}
    assert from_engine <= from_validator, (
        "the engine refused with a code the validator never reports, so an owner "
        "could approve this plan and still meet that refusal in production"
    )


@pytest.mark.guarantee("F19")
def test_entry_is_an_AXIS_and_its_marks_come_from_THE_PLAN():
    """Derived, not a written list: the marks must move when the plan's times do."""
    plan = parse_validate_request({"plan": copy.deepcopy(DAWN_CONFLICT)})
    entries = {s.entry_at.astimezone(plan.timezone).strftime("%H:%M") for s in probe_stays(plan)}
    assert len(entries) > 1, f"every probe still enters at one time: {entries}"
    assert {"06:00", "05:30"} <= entries, (
        f"the plan's own enter_by limits are not probed: {sorted(entries)}"
    )

    moved = copy.deepcopy(DAWN_CONFLICT)
    moved["rules"][0]["enter_by"] = "04:15"
    moved_plan = parse_validate_request({"plan": moved})
    moved_entries = {
        s.entry_at.astimezone(moved_plan.timezone).strftime("%H:%M")
        for s in probe_stays(moved_plan)
    }
    assert "04:15" in moved_entries and "06:00" not in moved_entries, (
        "the entry marks did not follow the plan, so they are a list, not a derivation"
    )


@pytest.mark.guarantee("F19")
def test_a_clean_plan_is_still_clean():
    """The control. Probing more must not manufacture findings in a sound plan --
    a validator that cries wolf is one an owner stops reading."""
    status, body = run_validate({"plan": copy.deepcopy(DOWNTOWN_V2)})
    assert status == 200
    assert [f["code"] for f in body["findings"]] == ["GAP_STAY_EXCEEDS_MAX_DURATION"], (
        f"probing the declared boundaries produced findings this plan should not have: "
        f"{body['findings']}"
    )


@pytest.mark.guarantee("F19")
def test_exit_limits_are_probed_RELATIVE_TO_EACH_ENTRY():
    """An exit limit is a wall-clock time, so the duration that lands on it depends
    on when the stay began. Deriving those durations against one fixed entry was
    the same defect as the fixed entry, one level down."""
    plan = parse_validate_request({"plan": copy.deepcopy(DAWN_CONFLICT)})
    landing_on_a_limit = {
        (s.entry_at.astimezone(plan.timezone).strftime("%H:%M"),
         s.exit_at.astimezone(plan.timezone).strftime("%H:%M"))
        for s in probe_stays(plan)
    }
    for entry in ("05:30", "06:00"):
        assert any(e == entry and x == "16:00" for e, x in landing_on_a_limit), (
            f"no probe entering {entry} exits exactly on the 16:00 limit"
        )
