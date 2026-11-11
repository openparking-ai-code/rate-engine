"""The contract's generated blocks must DERIVE what they assert.

GENERATION IS NOT VERIFICATION. Moving a sentence from a document into a template
does not stop it being hand-written: everywhere except the holes it is still
prose nobody checks, and a generated block asserts only what it derives from its
values. Anything else is a fixed string that no measurement can falsify.

So each test below plants a value that CONTRADICTS the document and requires the
document to change. A block that does not move under its own input is a hard-coded
sentence wearing a template's clothes, and this is the only thing that can tell
the two apart.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from plant import ROOT, planted

CONTRACT = ROOT / "docs" / "CONTRACT.md"
GENERATOR = ROOT / "scripts" / "generate_contract.py"


def _render() -> str:
    """Render the contract in a fresh interpreter, without writing it."""
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.argv=['g']; "
         f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
         "import generate_contract as g; print(g.render())"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.mark.guarantee("F9")
def test_the_committed_contract_matches_the_code():
    """A hand-edited number or sentence in docs/CONTRACT.md turns this red."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


#: Registering an EXTRA rule type, rather than renaming one, is what a plant here
#: has to do. A rename breaks the example plan -- the engine refuses a rule type
#: it does not know, correctly -- so the generator stops before it reaches the
#: table, and the control would then be reporting a refusal rather than a
#: document that failed to move. An addition leaves every existing plan valid,
#: which is also the property F7 guarantees.
ADD_A_RULE_TYPE = (
    "rules/space_surcharge.py",
    'register("space_surcharge", SURCHARGE, build, apply, traits=(ON_THE_TIME_CHARGE,))',
    'register("space_surcharge", SURCHARGE, build, apply, traits=(ON_THE_TIME_CHARGE,))\n'
    "from ..stages import ADJUST as _PLANTED_STAGE  # noqa: E402\n"
    'register("planted_extra", _PLANTED_STAGE, build, apply)',
)


@pytest.mark.guarantee("F9")
def test_the_rule_type_table_is_derived_from_the_registry():
    """PLANT: register an extra rule type. The table must grow a row."""
    baseline = _render()
    assert "| `space_surcharge` | SURCHARGE |" in baseline
    assert "planted_extra" not in baseline

    with planted(*ADD_A_RULE_TYPE):
        planted_render = _render()

    assert "| `planted_extra` | ADJUST |" in planted_render, (
        "the rule-type table did not grow when a rule type was registered, so it is a "
        "hand-written list rather than a reading of the registry"
    )


#: The plant for the note beside the table, and it is the MIRROR of the one
#: above: it takes ADJUST away rather than adding to it.
#:
#: **The plant this replaces is dead and was replaced rather than argued with.**
#: It registered an extra rule type AT ADJUST and required the note to stop
#: saying ADJUST was empty. That worked while ADJUST shipped nothing. The second version put
#: `time_window`'s `adjust` effect there, so both renderings now say "every
#: stage", the sentence cannot move, and the control could only ever pass --
#: which is worse than no control. Narrowing the type's registered stages empties
#: ADJUST again while leaving every existing plan valid, because the example
#: plan's window is a base and runs at QUALIFY either way.
NARROW_A_RULE_TYPE = (
    "rules/time_window.py",
    'register("time_window", STAGES_RUN_AT, build, apply, traits=(SPEAKS_UNQUALIFIED,), '
    "accrual=accrual)",
    'register("time_window", (QUALIFY,), build, apply, traits=(SPEAKS_UNQUALIFIED,), '
    "accrual=accrual)  # PLANTED",
)

#: And since the fill-rule round ADJUST has a second type, so emptying it takes
#: both: `fill_level` moved to SURCHARGE alongside the window narrowed. The
#: example plan has no fill rule, so nothing it renders depends on where one runs.
NARROW_THE_FILL_RULE = (
    "rules/fill_level.py",
    '    "fill_level", ADJUST, build, apply,',
    '    "fill_level", "SURCHARGE", build, apply,  # PLANTED',
)


@pytest.mark.guarantee("F9")
def test_the_empty_stage_note_is_derived_and_not_a_fixed_sentence():
    """The same idea, on the sentence beside the table.

    A true sentence sitting next to a checked table, borrowing its credit, is one
    of the named failures in this project's process notes. Every stage now
    carries a rule type and the document says so because it COUNTED -- so the
    moment a stage goes back to being empty, the sentence has to stop saying it.
    """
    baseline = _render()
    assert "Every stage has at least one rule type in this version." in baseline

    with planted(*NARROW_A_RULE_TYPE), planted(*NARROW_THE_FILL_RULE):
        planted_render = _render()

    assert "Every stage has at least one rule type in this version." not in planted_render, (
        "the note about empty stages did not change when ADJUST went back to empty"
    )
    assert "Stages with no rule type in this version: ADJUST." in planted_render


#: The plant for the exit-limit block, and it ADDS a span rather than renaming
#: one -- the same reason the rule-type plant adds a type. Renaming `next_day`
#: would make the example plan's own rules invalid, the generator would stop
#: before it reached this block, and the control would then be reporting a
#: refusal rather than a document that failed to move.
ADD_A_DAY_SPAN = (
    "rules/time_window.py",
    'DAY_SPAN_LIMITS: dict[str, int | None] = {"same_day": 0, "next_day": 1, "any_span": None}',
    'DAY_SPAN_LIMITS: dict[str, int | None] = {"same_day": 0, "next_day": 1, '
    '"any_span": None, "planted_span": 2}  # PLANTED',
)


@pytest.mark.guarantee("F9")
def test_the_exit_limit_table_is_derived_from_the_day_span_table():
    """PLANT: add a `day_span`. The published table and the sentence beside it
    must both grow it.

    The sentence is checked as well as the table on purpose. A derived table
    with a hand-written sentence next to it -- "refused under `same_day` and
    `any_span`" typed once and left -- is the failure this whole file exists to
    catch: it reads as checked because the table above it is.
    """
    baseline = _render()
    assert "| `next_day` | `exit_by` 1 local day after the entry date |" in baseline
    assert "planted_span" not in baseline
    assert "carried under `next_day`." in baseline

    with planted(*ADD_A_DAY_SPAN):
        planted_render = _render()

    assert "| `planted_span` | `exit_by` 2 local days after the entry date |" in planted_render, (
        "the exit-limit table did not grow a row when a day_span was added, so it "
        "is a hand-written table rather than a reading of DAY_SPAN_LIMITS"
    )
    assert "carried under `next_day` and `planted_span`." in planted_render, (
        "the table moved but the sentence beside it did not, which is a fixed "
        "sentence borrowing a derived table's credit"
    )


@pytest.mark.guarantee("F9")
def test_the_published_partial_dead_window_limit_was_PRICED():
    """The stated limit is a MEASUREMENT, not a sentence.

    `gen_window_limits` builds the partial dead window and prices two stays
    through it, and refuses to generate if the dead one fires or the live one
    does not. So breaking the exit limit must stop the contract generating at
    all -- a published limit that quietly stopped being true is the thing a follow-up review
    asked for a guard against.
    """
    baseline = _render()
    assert "is dead for every entry after 20:00 and alive for every entry before it" in baseline

    # Relax the exit condition entirely: now the "dead" late entry DOES fire.
    with planted(
        "rules/time_window.py",
        "    exit_side = _exit_failure(rule, entry_local, exit_local)\n"
        "    if exit_side is not None:",
        "    exit_side = _exit_failure(rule, entry_local, exit_local)\n"
        "    if False:  # PLANTED: the exit condition can no longer fail",
    ):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=ROOT, capture_output=True, text=True,
        )

    assert result.returncode != 0, (
        "the contract generated cleanly while the window it publishes as DEAD for a "
        "late entry was firing, so the published limit is prose rather than a "
        "measurement"
    )
    assert "FIRED for an entry after 20:00" in result.stdout + result.stderr, (
        "generation failed, but not because the published limit stopped being true:\n"
        + (result.stdout + result.stderr)[-1500:]
    )


@pytest.mark.guarantee("F9")
def test_the_gap_table_is_derived_from_the_findings_registry():
    """PLANT: rename a gap code. The table must follow it."""
    with planted(
        "findings.py",
        'GAP_NO_ACCUMULATE_RULE = "GAP_NO_ACCUMULATE_RULE"',
        'GAP_NO_ACCUMULATE_RULE = "GAP_PLANTED_CODE"',
    ):
        planted_render = _render()

    assert "GAP_PLANTED_CODE" in planted_render
    assert "`GAP_NO_ACCUMULATE_RULE`" not in planted_render


@pytest.mark.guarantee("F9")
def test_the_worked_example_is_priced_not_transcribed():
    """PLANT: change the example plan's hourly rate. Every number must move.

    This is the block most likely to rot into prose, because it reads like a
    transcript. It is not one -- it is the engine's actual output, so a rate
    change rewrites the lines AND the total AND the sentence about the sum.
    """
    baseline = _render()
    assert "FEE  3000 minor units" in baseline

    plan_path = ROOT / "tests" / "plans" / "downtown_v2.json"
    original = plan_path.read_text()
    document = json.loads(original)
    for rule in document["rules"]:
        if rule["id"] == "cap":
            rule["max_minor"] = 9999
    try:
        plan_path.write_text(json.dumps(document, indent=2))
        planted_render = _render()
    finally:
        plan_path.write_text(original)
        assert plan_path.read_text() == original

    assert "FEE  3000 minor units" not in planted_render, (
        "the worked example did not change when the plan it prices changed, so it is "
        "a transcript rather than a run"
    )
    assert "FEE  4400 minor units" in planted_render
    assert "The lines above sum to 4400" in planted_render, (
        "the sentence about the sum did not follow the numbers -- it is a fixed "
        "string borrowing their credibility"
    )


@pytest.mark.guarantee("F9")
def test_the_guarantee_table_is_derived_from_the_registry():
    """PLANT: change a guarantee's wording. The published table must follow."""
    registry = Path(ROOT / "tests" / "_guarantees.py")
    original = registry.read_text()
    try:
        registry.write_text(
            original.replace(
                '"F1": (\n        "The engine never guesses.',
                '"F1": (\n        "PLANTED SENTENCE.',
            )
        )
        planted_render = _render()
    finally:
        registry.write_text(original)
        assert registry.read_text() == original

    assert "PLANTED SENTENCE" in planted_render, (
        "the guarantee table is not read from tests/_guarantees.py"
    )


#: Blocks this file proves are ASSERTIONS -- it reaches two renderings of each
#: and requires the non-numeric text to differ. Compared against the kind=2 set
#: parsed out of the published document, so a new asserting block cannot arrive
#: without a control.
CONTROLLED_ASSERTIONS = {"rule_types", "findings", "example", "window_limits"}


def _blocks() -> dict[str, int]:
    """Every generated block and its declared kind, read from the document."""
    return {
        name: int(kind)
        for name, kind in re.findall(r"<!--gen:([a-z_]+) kind=([12])-->", CONTRACT.read_text())
    }


@pytest.mark.guarantee("F9")
def test_every_generated_block_is_closed_and_declares_a_kind():
    text = CONTRACT.read_text()
    blocks = _blocks()
    assert blocks, "no generated blocks were found; the marker format has changed"
    for name in blocks:
        assert f"<!--/gen:{name}-->" in text, f"{name} is not closed"


@pytest.mark.guarantee("F9")
def test_every_ASSERTING_block_has_a_control_in_this_file():
    """The check that stops K4 from having to be done again by hand.

    A kind-2 block says something ABOUT its values, so it has two reachable
    renderings and needs a control that reaches both. This derives that set from
    the document rather than from a list somebody remembers to update: add an
    asserting block with no control and this goes red naming it.
    """
    asserting = {name for name, kind in _blocks().items() if kind == 2}
    assert asserting == CONTROLLED_ASSERTIONS, (
        f"asserting blocks with no control: {sorted(asserting - CONTROLLED_ASSERTIONS)}; "
        f"controls for blocks that no longer assert: "
        f"{sorted(CONTROLLED_ASSERTIONS - asserting)}"
    )


@pytest.mark.guarantee("F9")
def test_interpolation_blocks_are_marked_as_such_and_not_given_invented_controls():
    """The other half, and it is a real rule rather than bookkeeping.

    A block with exactly one possible wording cannot be falsified by a
    contradicting-prose test, and writing one anyway produces something shaped
    like evidence that can only ever pass. Those blocks are marked kind 1 and
    left alone -- deliberately, and this records the decision where a later
    session will find it.
    """
    interpolation = {name for name, kind in _blocks().items() if kind == 1}
    assert interpolation == {
        "schema_version", "stages", "resolution", "guarantees", "max_stay",
    }
    assert not (interpolation & CONTROLLED_ASSERTIONS)


# --- K4: the two ASSERTING blocks that had no prose control -------------------
#
# `rule_types` already had one (above): it plants a registration and requires
# "Stages with no rule type in this version: ADJUST." to become "Every stage has
# at least one rule type in this version." The other two asserting blocks did
# not. Both were checked only on their NUMBERS or their IDENTIFIERS, which is
# interpolation -- a moving number is not a changed assertion.


@pytest.mark.guarantee("F9")
def test_the_findings_table_asserts_a_KIND_not_just_a_code():
    """PLANT: move a code from the gap registry to the conflict registry.

    The code string is interpolated; the word beside it — `gap` or `conflict` —
    is DERIVED from which tuple the code sits in, and it is the part an
    integrator writing error handling actually reads. The earlier control renamed
    a code and watched the name change, which proves the table is generated and
    says nothing about the classification.
    """
    baseline = _render()
    assert "| `GAP_NO_ACCUMULATE_RULE` | gap |" in baseline

    with planted(
        "findings.py",
        "GAP_CODES: tuple[str, ...] = (\n    GAP_UNDECLARED_SPACE_CLASS,\n"
        "    GAP_NO_ACCUMULATE_RULE,",
        "GAP_CODES: tuple[str, ...] = (\n    GAP_UNDECLARED_SPACE_CLASS,",
    ):
        with planted(
            "findings.py",
            "CONFLICT_CODES: tuple[str, ...] = (\n    CONFLICT_AMBIGUOUS_PLAN_SELECTION,",
            "CONFLICT_CODES: tuple[str, ...] = (\n    GAP_NO_ACCUMULATE_RULE,\n"
            "    CONFLICT_AMBIGUOUS_PLAN_SELECTION,",
        ):
            planted_render = _render()

    assert "| `GAP_NO_ACCUMULATE_RULE` | conflict |" in planted_render, (
        "the published KIND did not follow the registry the code was moved into, so "
        "the table interpolates codes and asserts nothing about them"
    )
    assert "| `GAP_NO_ACCUMULATE_RULE` | gap |" not in planted_render


@pytest.mark.guarantee("F9")
def test_the_worked_example_asserts_IN_WORDS_what_the_rules_did():
    """PLANT: raise the cap out of reach. The cap's SENTENCE must change, not its number.

    The earlier control changed the same value and asserted the totals moved —
    3000 to 4400 — which a transcript with the numbers swapped would also satisfy.
    What makes the block an assertion is that the cap line stops saying it was
    APPLIED and starts saying it was NOT REACHED, and that the early-bird line
    keeps saying which condition failed.
    """
    baseline = _render()
    assert "Daily max 30.00 USD (calendar_day) applied over the day" in baseline
    assert "not reached" not in baseline

    plan_path = ROOT / "tests" / "plans" / "downtown_v2.json"
    original = plan_path.read_text()
    document = json.loads(original)
    for rule in document["rules"]:
        if rule["id"] == "cap":
            rule["max_minor"] = 999999
    try:
        plan_path.write_text(json.dumps(document, indent=2))
        planted_render = _render()
    finally:
        plan_path.write_text(original)
        assert plan_path.read_text() == original

    assert "applied over the day" not in planted_render, (
        "the cap line still claims it applied while the cap was out of reach"
    )
    assert "not reached: the charge so far" in planted_render, (
        "the block reported new numbers but the same words, which is interpolation "
        "wearing an assertion's clothes"
    )


@pytest.mark.guarantee("F9")
def test_a_size_preserving_plant_is_actually_loaded():
    """The control on the PLANT HELPER, which nothing else here covers.

    CPython validates a cached `.pyc` against the source's (mtime in whole
    seconds, size). A plant that leaves the file the same LENGTH inside the same
    second as the previous write is invisible to a subprocess: it imports the
    stale bytecode and behaves as though nothing was planted.

    The findings-table control above is exactly that shape — one line moves out
    of `GAP_CODES` and the identical line moves into `CONFLICT_CODES` — and it
    reported a false finding until `plant.py` started advancing the mtime. This
    proves the fix, using a plant whose replacement is the same length by
    construction rather than by accident.

    The mtime advance alone was NOT enough, and this test is what said so: it
    failed on 3 runs in 6, and twice took its whole module red before anything
    was planted. `plant.py` writes mtimes in the FUTURE, so a `.pyc` surviving an
    earlier run can collide with a later plant in whole seconds while the size is
    identical by construction. `_write` now deletes the cached bytecode as well —
    bytecode that does not exist cannot be served stale.
    """
    import subprocess

    original = (ROOT / "src" / "rate_engine" / "stages.py").read_text()
    frm, to = 'ADJUST = "ADJUST"', 'ADJUST = "ADJUSX"'
    assert len(frm) == len(to), "this control is only meaningful if the size is unchanged"

    def adjust_seen_by_a_subprocess() -> str:
        return subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); "
             "import rate_engine.stages as s; print(s.ADJUST)"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.strip()

    assert adjust_seen_by_a_subprocess() == "ADJUST"
    with planted("stages.py", frm, to):
        assert (ROOT / "src" / "rate_engine" / "stages.py").read_text() != original
        assert adjust_seen_by_a_subprocess() == "ADJUSX", (
            "a same-length plant was written to disk but a subprocess still imported "
            "the old value -- plant.py is serving stale bytecode and every control "
            "whose replacement happens to match its anchor's length is dead"
        )
    assert adjust_seen_by_a_subprocess() == "ADJUST"
