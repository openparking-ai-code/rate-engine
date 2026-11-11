"""F7 -- registering a new rule type changes no existing plan's answer.

This is what makes "customisable, and we will add new ways" a measured property
rather than a promise. The rule: adding a new way must not change what an
existing plan answers. Every plan already written keeps its fee AND its breakdown, byte
for byte, when the registry grows.

**The plugin registers at a stage a plan already uses.** A test-only rule type
parked at ADJUST -- the one stage nothing ships at -- would prove almost nothing:
no existing plan reaches that stage, so of course nothing moves. This one
registers at ACCUMULATE, beside `increment`, which is where a collision would
actually show: a pipeline that re-sorted its rules, a stage that iterated a
global registry instead of the plan's own rules, or a qualifier looked up by
position rather than by type would all break here.

**The corpus is derived, not listed.** Every plan file in tests/plans is priced
over every fixture stay. A plan added to that directory is covered by this test
the moment it exists, which a hand-written list could not manage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixtures import CORPUS, PLANS_DIR, downtown_v1
from rate_engine.contract import run_quote
from rate_engine.stages import ACCUMULATE

PLAN_DOCUMENTS = [json.loads(p.read_text()) for p in sorted(PLANS_DIR.glob("*.json"))] + [
    downtown_v1()
]


def _price_everything() -> dict[str, str]:
    """Fee and breakdown for every (plan, stay) pair, as JSON strings."""
    answers = {}
    for document in PLAN_DOCUMENTS:
        for name, s in CORPUS.items():
            status, body = run_quote(
                {
                    "plans": [document],
                    "entry_at": s.entry_at.isoformat(),
                    "exit_at": s.exit_at.isoformat(),
                    "space_class": s.space_class,
                    "currency": document["currency"],
                }
            )
            answers[f"{document['plan_version']}::{name}"] = f"{status} {json.dumps(body)}"
    return answers


def test_the_corpus_this_guarantee_protects_is_not_empty():
    """The control. F7 over zero plans or zero stays is green and vacuous."""
    answers = _price_everything()
    assert len(PLAN_DOCUMENTS) >= 2, "fewer than two plan documents were discovered"
    assert len(answers) >= 2 * len(CORPUS)
    assert any('"fee_minor"' in v for v in answers.values()), "no stay was actually priced"
    assert any('"refused": true' in v for v in answers.values()), "no stay was refused"


@pytest.mark.guarantee("F7")
def test_registering_a_new_rule_type_changes_nothing_byte_for_byte():
    before = _price_everything()

    from rate_engine.breakdown import Line
    from rate_engine.rules import Rule, common_fields, register

    def build(raw, plan_space_classes, where):
        rule_id, space_classes = common_fields(raw, plan_space_classes, where, {"flat_minor"})
        return Rule(
            id=rule_id,
            type="test_only_flat",
            stage=ACCUMULATE,
            space_classes=space_classes,
            params={"flat_minor": raw["flat_minor"]},
        )

    def apply(rule, stay, plan):
        return [
            Line(
                code="test_only_flat.applied",
                rule_id=rule.id,
                text="a rule type that did not exist a moment ago",
                delta_minor=rule.params["flat_minor"],
            )
        ]

    from rate_engine.engine import QUALIFIERS

    register("test_only_flat", ACCUMULATE, build, apply)
    QUALIFIERS["test_only_flat"] = lambda rule, stay, plan: rule.covers(stay.space_class)
    try:
        from rate_engine.rules import RULE_TYPES

        assert "test_only_flat" in RULE_TYPES, "the plugin did not actually register"
        after = _price_everything()
    finally:
        from rate_engine.rules import RULE_APPLIERS, RULE_TYPES

        RULE_TYPES.pop("test_only_flat", None)
        RULE_APPLIERS.pop("test_only_flat", None)
        QUALIFIERS.pop("test_only_flat", None)

    assert after == before, (
        "an existing plan's answer moved when a new rule type was registered: "
        f"{[k for k in before if before[k] != after.get(k)]}"
    )


@pytest.mark.guarantee("F7")
def test_the_new_rule_type_is_genuinely_usable_once_a_plan_asks_for_it():
    """The other half, and without it the test above is satisfied by a no-op.

    A registration that did nothing at all would keep every existing answer
    identical for the most boring possible reason. So the plugin has to be shown
    working: a plan that names it prices differently from one that does not.
    """
    from rate_engine.breakdown import Line
    from rate_engine.engine import QUALIFIERS
    from rate_engine.rules import RULE_APPLIERS, RULE_TYPES, Rule, common_fields, register

    def build(raw, plan_space_classes, where):
        rule_id, space_classes = common_fields(raw, plan_space_classes, where, {"flat_minor"})
        return Rule(
            id=rule_id,
            type="test_only_flat",
            stage=ACCUMULATE,
            space_classes=space_classes,
            params={"flat_minor": raw["flat_minor"]},
        )

    def apply(rule, stay, plan):
        return [
            Line(
                code="test_only_flat.applied",
                rule_id=rule.id,
                text="flat charge",
                delta_minor=rule.params["flat_minor"],
            )
        ]

    register("test_only_flat", ACCUMULATE, build, apply)
    QUALIFIERS["test_only_flat"] = lambda rule, stay, plan: rule.covers(stay.space_class)
    try:
        document = json.loads((PLANS_DIR / "downtown_v2.json").read_text())
        document["rules"] = [
            r for r in document["rules"] if r["id"] not in ("hourly", "eb-weekday")
        ] + [
            {
                "id": "flat",
                "type": "test_only_flat",
                "stage": "ACCUMULATE",
                "space_classes": ["standard", "vip"],
                "flat_minor": 777,
            }
        ]
        s = CORPUS["worked_example"]
        status, body = run_quote(
            {
                "plans": [document],
                "entry_at": s.entry_at.isoformat(),
                "exit_at": s.exit_at.isoformat(),
                "space_class": "standard",
                "currency": "USD",
            }
        )
        assert status == 200, body
        assert body["fee_minor"] == 777, "the new rule type did not actually price anything"
    finally:
        RULE_TYPES.pop("test_only_flat", None)
        RULE_APPLIERS.pop("test_only_flat", None)
        QUALIFIERS.pop("test_only_flat", None)


def test_no_test_only_rule_type_survives_this_file():
    from rate_engine.rules import RULE_TYPES

    assert not [name for name in RULE_TYPES if name.startswith("test_only")], (
        "a test-only rule type leaked into the registry and would change other tests"
    )


def test_the_plans_directory_is_what_the_corpus_reads():
    assert Path(PLANS_DIR).is_dir()
    assert list(PLANS_DIR.glob("*.json")), "no plan documents were discovered"
