"""F15 -- `increment.rounding` is CONSULTED, and a mode this version does not
implement is refused rather than priced as something else.

The field was validated at load, stored on the rule, and read by nothing.
`apply()` hardcoded ceil, so setting `rounding` to `floor`, `nearest`, `banana`
or `null` produced a byte-identical fee. Nothing noticed, because the loader only
ever let `ceil` through and `ceil` is what the hardcoded arithmetic did.

**The defect is a forward one, and that is what makes it worth a guarantee.** The second version
adds `floor` to the modes a plan may state. The moment it does, a plan saying
`floor` prices as `ceil` — silently, with a document that reads correctly to the
operator who wrote it and a fee that is simply wrong. There is nothing an
operator can inspect to catch that: their plan says what they meant.

So the applier asks what IT implements, never what the loader accepts. Those are
two different questions and the whole guarantee lives in the difference:
`test_the_applier_checks_what_it_IMPLEMENTS_not_what_the_loader_ACCEPTS` below is
the second version's exact scenario, run today.
"""

from __future__ import annotations

import pytest

from fixtures import loaded, stay, with_rule_field
from rate_engine.engine import quote
from rate_engine.plan import InvalidPlan, load_plan
from rate_engine.rules import Rule, increment
from rate_engine.stages import ACCUMULATE

LATE = "2026-03-03T09:14:00-05:00"


def _rule(rounding: str | None) -> Rule:
    """An `increment` rule built directly, so a mode the LOADER would reject can
    still be handed to the applier -- which is the only way to reach the
    applier's own guard while the two lists agree."""
    return Rule(
        id="hourly",
        type="increment",
        stage=ACCUMULATE,
        space_classes=("standard",),
        params={
            "first_period_minutes": 60,
            "first_period_minor": 800,
            "repeat_period_minutes": 60,
            "repeat_period_minor": 400,
            "rounding": rounding,
            "max_duration_minutes": 1440,
        },
    )


@pytest.mark.guarantee("F15")
def test_the_applier_prices_the_mode_it_does_implement():
    """The positive control, first. Without it, an applier that refused EVERY
    mode would satisfy every assertion below."""
    lines = increment.apply(_rule("ceil"), stay(LATE, 61), loaded())
    assert sum(line.delta_minor for line in lines) == 1200, (
        "61 minutes on a 60-minute first period at 800 plus one repeat at 400 is "
        "1200 under ceil; the mode this version implements must still price"
    )


@pytest.mark.parametrize("mode", ["floor", "nearest", "banana", None])
@pytest.mark.guarantee("F15")
def test_the_applier_refuses_a_mode_it_does_not_implement(mode):
    """Each of these used to produce 1200 -- the ceil answer -- in silence."""
    with pytest.raises(InvalidPlan) as caught:
        increment.apply(_rule(mode), stay(LATE, 61), loaded())
    message = str(caught.value)
    assert repr(mode) in message, "the refusal must name the mode that was asked for"
    assert "ceil" in message, "and must say what it can actually do"


@pytest.mark.guarantee("F15")
def test_the_applier_checks_what_it_IMPLEMENTS_not_what_the_loader_ACCEPTS(monkeypatch):
    """The second version's EXACT scenario, run today, and the reason for two separate lists.

    A later round widens the modes a plan may state. If the applier validated
    against that same widened list it would accept the new mode and go on doing
    ceil -- a wrong fee behind a correct-looking plan, which is the failure this
    module exists to prevent. Here the loader is widened and the applier is not,
    and the stay must come back REFUSED rather than priced.
    """
    monkeypatch.setattr(increment, "ROUNDING_MODES", ("ceil", "floor"))

    document = with_rule_field("hourly", rounding="floor")
    plan = load_plan(document)  # the widened loader accepts it, as the second version's would
    assert plan.rules_for_stage(ACCUMULATE)[0].params["rounding"] == "floor"

    with pytest.raises(InvalidPlan) as caught:
        quote([plan], stay(LATE, 61))
    assert "floor" in str(caught.value), (
        "a plan the loader accepted was priced under a rounding mode it did not "
        "ask for -- the silent mispricing this guarantee exists to make impossible"
    )


@pytest.mark.guarantee("F15")
def test_every_mode_the_loader_accepts_is_implemented_by_the_applier():
    """Derived from both tables, so the round that widens one without the other
    fails here instead of shipping. This is the check that turns the refusal
    above from a safety net into a statement about the version."""
    assert set(increment.ROUNDING_MODES) == set(increment.PERIOD_COUNTERS), (
        f"modes a plan may state but nothing implements: "
        f"{sorted(set(increment.ROUNDING_MODES) - set(increment.PERIOD_COUNTERS))}; "
        f"modes implemented that no plan may state: "
        f"{sorted(set(increment.PERIOD_COUNTERS) - set(increment.ROUNDING_MODES))}"
    )
