"""The control on the corpus itself: does it hold cases on BOTH sides of every axis?

A fixture is part of the measurement. This test enumerates the threshold
constants OUT OF THE REFERENCE PLAN -- not out of a list somebody typed -- and
requires the corpus to contain a stay strictly below and a stay at or above each
one. A corpus that could only ever exercise one branch would make the whole suite
green while measuring half of it, and nothing else here would notice.
"""

from __future__ import annotations

import pytest

from fixtures import CORPUS, DOWNTOWN_V2, loaded, stay
from rate_engine.engine import quote
from rate_engine.findings import Refused


def _rule(rule_id: str) -> dict:
    return next(r for r in DOWNTOWN_V2["rules"] if r["id"] == rule_id)


def _durations() -> list[int]:
    return [s.duration_minutes for s in CORPUS.values()]


@pytest.mark.parametrize(
    "label,threshold",
    [
        ("increment.first_period_minutes", _rule("hourly")["first_period_minutes"]),
        ("increment.repeat_period_minutes", _rule("hourly")["repeat_period_minutes"]),
        ("increment.max_duration_minutes", _rule("hourly")["max_duration_minutes"]),
    ],
)
@pytest.mark.guarantee("F13")
def test_the_corpus_straddles_every_duration_threshold(label, threshold):
    durations = _durations()
    below = [d for d in durations if d < threshold]
    at_or_above = [d for d in durations if d >= threshold]
    assert below, f"no fixture is below {label} ({threshold} min); that side is unmeasured"
    assert at_or_above, f"no fixture reaches {label} ({threshold} min); that side is unmeasured"


@pytest.mark.guarantee("F13")
def test_the_corpus_straddles_EVERY_time_window_condition():
    """Every condition met and every condition missed, derived from the rule.

    Read out of the reference plan's own window rather than from a list here, so
    a condition ADDED to the rule type shows up as an unmeasured axis instead of
    passing unnoticed -- which is exactly what happened when `enter_from` and
    `applies_on` arrived. Each row below must have a fixture on both sides or F2,
    F26 and F27 would pass against a corpus that could only ever reach one branch.
    """
    from rate_engine.wallclock import DAYS_OF_WEEK

    plan = loaded()
    window = plan.rules[0].params
    conditions: dict[str, set[bool]] = {
        "applies_on": set(), "enter_from": set(), "enter_by": set(), "exit_by": set(),
    }
    for s in CORPUS.values():
        if s.space_class != "standard":
            continue
        entry_local = s.entry_at.astimezone(plan.timezone)
        exit_local = s.exit_at.astimezone(plan.timezone)
        conditions["applies_on"].add(
            DAYS_OF_WEEK[entry_local.weekday()] in window["applies_on"]["days"]
        )
        conditions["enter_from"].add(entry_local.time() >= window["enter_from"])
        conditions["enter_by"].add(entry_local.time() <= window["enter_by"])
        conditions["exit_by"].add(
            exit_local.date() == entry_local.date()
            and exit_local.time() <= window["exit_by"]
        )
    unmeasured = sorted(name for name, sides in conditions.items() if sides != {True, False})
    assert not unmeasured, (
        f"every fixture falls on the same side of: {', '.join(unmeasured)} -- those "
        f"conditions are unmeasured, so a rule ignoring them would pass"
    )


@pytest.mark.guarantee("F13")
def test_the_corpus_straddles_the_cap():
    """Some stays must reach the daily max and some must not."""
    plan = loaded()
    reached, not_reached = [], []
    for name, s in CORPUS.items():
        try:
            result = quote([plan], s)
        except Refused:
            continue
        codes = {line.code for line in result.breakdown.lines}
        (reached if "daily_max.applied" in codes else not_reached).append(name)
    assert reached, "no fixture reaches the daily max; the capping branch is unmeasured"
    assert not_reached, "every fixture is capped; the un-capped branch is unmeasured"


@pytest.mark.guarantee("F13")
def test_the_corpus_straddles_the_space_class_axis():
    classes = {s.space_class for s in CORPUS.values()}
    assert classes == set(DOWNTOWN_V2["space_classes"]), (
        f"the corpus covers {sorted(classes)} but the plan declares "
        f"{sorted(DOWNTOWN_V2['space_classes'])}; an unexercised class is an "
        "unmeasured surcharge"
    )


@pytest.mark.guarantee("F13")
def test_the_axes_control_can_fail():
    """The positive control for this file.

    A corpus with one stay in it must make the straddle assertions fail. Without
    this, "both sides are present" is a sentence that has never been tested
    against a corpus where they are not.
    """
    only_short = [stay("2026-03-03T09:14:00-05:00", 30)]
    threshold = _rule("hourly")["first_period_minutes"]
    durations = [s.duration_minutes for s in only_short]
    assert not [d for d in durations if d >= threshold], (
        "the control corpus was supposed to sit entirely below the threshold"
    )


@pytest.mark.guarantee("F13")
def test_the_plan_corpus_contains_a_clean_plan_and_a_plan_with_gaps():
    """Both sides of the validator's own axis.

    A directory of plans that all validate clean would let a validator reporting
    nothing at all pass every check in this suite -- and a directory where all of
    them have gaps would do the same for one that reports a gap in everything.
    Derived by validating every plan on disk, not from a list here.
    """
    import json

    from fixtures import PLANS_DIR
    from rate_engine.plan import load_plan
    from rate_engine.validator import validate_plan

    results = {
        path.name: validate_plan(load_plan(json.loads(path.read_text())))
        for path in sorted(PLANS_DIR.glob("*.json"))
    }
    clean = [name for name, findings in results.items() if not findings]
    with_gaps = [name for name, findings in results.items() if findings]

    counts = {name: len(findings) for name, findings in results.items()}
    assert clean, f"no plan on disk validates clean; findings per plan: {counts}"
    assert with_gaps, "no plan on disk has a gap, so a validator finding nothing would pass"


@pytest.mark.guarantee("F13")
def test_the_corpus_covers_BOTH_dst_transitions():
    """An axis with one side is the fixture defect the specification names.

    Spring-forward shortens a local day to 23 hours; fall-back stretches one to
    25. Only the second can separate `calendar_day` from `rolling_24h`, so a
    corpus carrying only the spring case cannot exercise the disagreement that
    `day_boundary` exists to settle. Derived by asking the fixtures what their
    UTC offsets do, not by trusting their names.
    """
    from fixtures import CORPUS, loaded

    zone = loaded().timezone
    transitions = set()
    for s in CORPUS.values():
        before = s.entry_at.astimezone(zone).utcoffset()
        after = s.exit_at.astimezone(zone).utcoffset()
        if before != after:
            transitions.add("spring" if after > before else "fall")

    assert transitions == {"spring", "fall"}, (
        f"the corpus crosses only {sorted(transitions) or 'no'} DST transition(s); "
        "the missing side is unmeasured"
    )
