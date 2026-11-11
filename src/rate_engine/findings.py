"""Gaps and conflicts: ONE registry, read by the validator and by the engine.

A gap is a stay the plan cannot price. A conflict is two rules qualifying at one
stage whose resolution the plan does not state. The validator reports them so an
owner can decide; the engine REFUSES on them so a stay is never priced by a
guess. Those are two behaviours of one mechanism, and the whole point of this
file is that they cannot drift apart -- both sides key off the identifiers
below, and ``tests/test_f1_never_guesses.py`` requires every identifier here to
be reachable from a fixture.

**Keyed by identifier, never matched by substring.** A validator that reported
"nothing prices a stay past 24 hours" and an engine that refused with a
differently-worded sentence would agree to a human reader and to no test. The
sentence is for the operator; ``code`` is what anything mechanical uses.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- gap codes -------------------------------------------------------------
#: The stay's space class is not one the plan declares.
GAP_UNDECLARED_SPACE_CLASS = "GAP_UNDECLARED_SPACE_CLASS"
#: Nothing accumulates time for this stay: no ACCUMULATE rule covers the space
#: class, and no QUALIFY special took over the pricing.
GAP_NO_ACCUMULATE_RULE = "GAP_NO_ACCUMULATE_RULE"
#: An ACCUMULATE rule covers the space class but states a maximum duration this
#: stay exceeds. This is the specification's own example -- "nothing prices a stay past 24
#: hours" -- and it is expressible only because `max_duration_minutes` is a
#: required field on the rule rather than an assumed infinity.
GAP_STAY_EXCEEDS_MAX_DURATION = "GAP_STAY_EXCEEDS_MAX_DURATION"
#: The stay is longer than this engine prices: more than `MAX_STAY_DAYS` (90)
#: days of 24 hours from entry to exit (decided 2026-10-16). Refused before the
#: plan is read or a day of the stay is walked, so it costs nothing however long
#: the stay is (F62). **A gap no rule can close**: the limit is the engine's, the
#: same for every plan, so `validate-plan` never reports it -- it publishes the
#: limit instead, as `max_stay_minutes`. A door that closes a stay unpriced on a
#: refusal shows this one as needing an operator.
GAP_STAY_LONGER_THAN_MAX_STAY = "GAP_STAY_LONGER_THAN_MAX_STAY"
#: No plan version was in force at the stay's ENTRY time.
GAP_NO_PLAN_IN_FORCE_AT_ENTRY = "GAP_NO_PLAN_IN_FORCE_AT_ENTRY"
#: No tax set the garage stated was in force at the instant the tax was asked
#: for. REFUSED, never taxed at zero: a garage with no set in force at that
#: instant has not said "no tax" there -- it has said nothing -- and zero is a
#: tax position somebody would have had to state. Stating "no tax" is a set with
#: no rules, which is a statement; see tax.py.
#:
#: Not reported by `validate-plan`, which validates a PLAN, and a tax set is the
#: garage's rather than a plan's. F1 reaches it from a tax fixture.
GAP_NO_TAX_SET_IN_FORCE = "GAP_NO_TAX_SET_IN_FORCE"

# --- conflict codes --------------------------------------------------------
#: **`CONFLICT_MULTIPLE_RULES_AT_STAGE` was removed in schema version 4.** It
#: named two rules qualifying at a RESOLVING stage that the plan could not
#: settle, and after the second version the only such case left was a tie at the cheapest charge
#: under `cheapest_wins`. The engine now prices that tie -- the driver pays the same either
#: way -- so nothing could produce the code any more, and a registered code
#: nothing can produce is a promise with no mechanism behind it. See
#: docs/CONTRACT.md, "What changed in version 4".
#: Two or more plan versions share the latest `effective_from` at or before the
#: stay's entry, so "the version in force at entry" names more than one document.
#:
#: This was a LIVE DEFECT, not a hypothetical. `select_plan` used
#: `max(in_force, key=...effective_from)`, and `max` returns the FIRST maximal
#: element -- so two versions carrying the same date priced the same car at 300
#: or at 2700 minor units depending only on which the caller happened to put
#: first in a JSON array, with nothing said. Deciding money by the order of a
#: list, silently, is the exact opposite of this project's standing acceptance,
#: and the answer is the same as everywhere else here: refuse, and name both.
CONFLICT_AMBIGUOUS_PLAN_SELECTION = "CONFLICT_AMBIGUOUS_PLAN_SELECTION"

#: The rules between them produced a NEGATIVE total. Refused rather than handing a
#: customer a negative amount.
#:
#: It used to be raised as CONFLICT_MULTIPLE_RULES_AT_STAGE (removed in version
#: 4), which was documented exclusively for two rules qualifying at one stage.
#: Nothing was mispriced -- the refusal is correct and the SENTENCE said what
#: really happened -- but the CODE named a cause that had not occurred, and the
#: code is what anything mechanical keys off. A consumer routing on it would
#: have told an operator to settle a resolution order that was not the problem.
#:
#: Every money field goes through `as_non_negative_minor`, and a cap reduces the
#: total to a ceiling that is never below zero (`daily_max`: the sum of its
#: days, each capped at `max_minor`; `weekly_max`: the sum of its weeks). A fixed
#: discount takes off at most the running total, and nothing once the total is at
#: or below zero, so it never adds money. This said "unreachable" while a fixed
#: discount larger than a short stay's charge reached it, and that stay was
#: refused rather than priced at zero. A percentage discount over 100% reached
#: it too until it stopped loading (INVALID_PERCENT_DISCOUNT_OVER_100), so no
#: rule type this version ships can reach it. It is registered either way because a rule type is the
#: unit of growth here, and the first one that can return a negative Line should
#: meet a named refusal rather than a mislabelled one.
CONFLICT_NEGATIVE_TOTAL = "CONFLICT_NEGATIVE_TOTAL"

#: Two or more ADJUST rules qualify and the plan does not say in what order to
#: apply them.
#:
#: This is a DIFFERENT question from two rules qualifying at QUALIFY, which is
#: "which one is the price" -- an either/or the plan always settles with its
#: resolution mode. Two adjustments is not
#: an either/or at all: BOTH apply, and the only open question is the sequence.
#: 20% off then 5.00 off is not 5.00 off then 20% off, and the difference is
#: money, so the engine will not pick -- for the same reason it will not pick
#: between two specials.
#:
#: Caps and surcharges raise no such question: they compose in any order and the
#: total is the same, which is why CAP and SURCHARGE are order-INDEPENDENT and
#: two of them together are not reported at all.
CONFLICT_UNORDERED_ADJUSTMENTS = "CONFLICT_UNORDERED_ADJUSTMENTS"

#: A plan carries a fill rule covering this stay's space class, and the stay
#: arrived without `occupancy_at_entry_bp`. The rule prices on how full the
#: garage was when the car came in, and with no figure there is nothing to read:
#: the stay is refused rather than priced as if the garage were empty or full.
#: A plan with no fill rule never asks for the figure.
GAP_NO_OCCUPANCY_AT_ENTRY = "GAP_NO_OCCUPANCY_AT_ENTRY"

#: Two fill rules covering one space class both qualify for a stay. They are two
#: answers to the same question -- how much more the time costs when the garage
#: is full -- and `adjust_order` cannot settle it, because an order would charge
#: both. The plan states one rule per class.
CONFLICT_OVERLAPPING_FILL_RULES = "CONFLICT_OVERLAPPING_FILL_RULES"

# --- fault codes -----------------------------------------------------------
#: A registered rule type returned something that is not a list of Lines.
#:
#: This is a THIRD kind, and it is deliberately not filed under the other two.
#: A gap is a stay the plan cannot price and a conflict is two rules the plan
#: does not order -- both are questions for the OWNER, and both are things
#: `validate-plan` reports. This is neither: it is a defect in a rule type's
#: implementation, which no owner can decide and no plan can fix. Filing it as a
#: conflict would have been the same mistake the negative-fee refusal makes --
#: a refusal whose code names something that did not happen.
FAULT_RULE_RETURNED_NOT_LINES = "FAULT_RULE_RETURNED_NOT_LINES"

# --- invalid codes ---------------------------------------------------------
#: A `time_window` discount states a `percent_bp` above 10000: more than 100%
#: off, which would take the fee below zero and pay the driver to park.
#:
#: **Not a finding about a stay, and that is why it is a fourth tuple.** A gap,
#: a conflict and a fault are each about a stay the engine was asked to price; a
#: plan carrying this does not LOAD, so no stay is ever priced on it, and
#: `validate-plan`, `quote` and every door answer 400 with this code beside the
#: sentence (`code`, next to `error`). Most load refusals name their field in a
#: sentence and carry no code. This one carries one because the owner's
#: decision (2026-10-16) is that a percent discount can never exceed
#: 100% and that every place a plan is saved refuses it -- and a plan store
#: routes on a code, never on a sentence. It used to load, and a stay it priced
#: below zero was refused at the counter as `CONFLICT_NEGATIVE_TOTAL`.
INVALID_PERCENT_DISCOUNT_OVER_100 = "INVALID_PERCENT_DISCOUNT_OVER_100"

GAP_CODES: tuple[str, ...] = (
    GAP_UNDECLARED_SPACE_CLASS,
    GAP_NO_ACCUMULATE_RULE,
    GAP_STAY_EXCEEDS_MAX_DURATION,
    GAP_NO_PLAN_IN_FORCE_AT_ENTRY,
    GAP_NO_TAX_SET_IN_FORCE,
    GAP_NO_OCCUPANCY_AT_ENTRY,
    GAP_STAY_LONGER_THAN_MAX_STAY,
)

CONFLICT_CODES: tuple[str, ...] = (
    CONFLICT_AMBIGUOUS_PLAN_SELECTION,
    CONFLICT_NEGATIVE_TOTAL,
    CONFLICT_UNORDERED_ADJUSTMENTS,
    CONFLICT_OVERLAPPING_FILL_RULES,
)

#: Faults are never produced by the validator: it probes a plan against stays and
#: never runs an applier, so a fault can only arise while actually pricing.
FAULT_CODES: tuple[str, ...] = (FAULT_RULE_RETURNED_NOT_LINES,)

ALL_CODES: tuple[str, ...] = GAP_CODES + CONFLICT_CODES + FAULT_CODES

#: Codes a plan that does not load is refused with. Never a Finding -- see
#: INVALID_PERCENT_DISCOUNT_OVER_100 -- so not in ALL_CODES, and a Finding
#: built with one is refused like any unregistered code.
INVALID_CODES: tuple[str, ...] = (INVALID_PERCENT_DISCOUNT_OVER_100,)


@dataclass(frozen=True)
class Finding:
    """A gap or a conflict, in a form an owner can act on and a test can key off."""

    code: str
    #: Plain English. What is missing, and what the engine would have had to
    #: invent to answer anyway.
    text: str
    #: The rule ids involved, where the finding is about rules.
    rule_ids: tuple[str, ...] = ()
    #: The stay that found it, as `(entry_at, exit_at)` ISO instants -- set by
    #: `validate-plan`, which probes stays the plan's own boundaries make
    #: interesting, and None on a refusal at quote time, where the caller
    #: already holds the stay. An owner reading "nothing prices this" needs to
    #: know which car it was about: when it came in and when it left.
    #: A third element, the probe's `occupancy_at_entry_bp`, only where the plan
    #: has a fill rule and the probe therefore carried a figure: the same car at
    #: 79% and at 80% full is two different stays to such a plan.
    probe: tuple | None = None

    def __post_init__(self) -> None:
        if self.code not in ALL_CODES:
            raise ValueError(
                f"{self.code!r} is not a registered finding code. Add it to "
                "findings.py so the validator, the engine and the contract all "
                "learn about it at once."
            )

    @property
    def is_gap(self) -> bool:
        return self.code in GAP_CODES

    @property
    def kind(self) -> str:
        """Which of the three this is, decided by membership rather than by an else.

        It used to be ``"gap" if self.is_gap else "conflict"``, which was true
        while there were exactly two kinds and would have quietly labelled the
        third one a conflict the day it was added. A two-way branch over a
        three-way registry is a wrong answer with no way to notice it.
        """
        for codes, name in (
            (GAP_CODES, "gap"),
            (CONFLICT_CODES, "conflict"),
            (FAULT_CODES, "fault"),
        ):
            if self.code in codes:
                return name
        raise AssertionError(f"{self.code!r} is registered but belongs to no kind.")

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {
            "code": self.code,
            "kind": self.kind,
            "text": self.text,
            "rule_ids": list(self.rule_ids),
        }
        # Only where it was set, so a refusal at quote time is the bytes it was.
        if self.probe is not None:
            out["probe"] = {"entry_at": self.probe[0], "exit_at": self.probe[1]}
            if len(self.probe) > 2:
                out["probe"]["occupancy_at_entry_bp"] = self.probe[2]
        return out


class Refused(Exception):
    """The engine will not price this stay, and this is exactly what is missing.

    Carries the findings rather than a message, so a caller can show the owner
    the same objects `validate-plan` would have shown them.
    """

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        joined = " · ".join(f.text for f in findings)
        super().__init__(f"refused, nothing was guessed: {joined}")

    def to_json(self) -> dict[str, object]:
        return {
            "refused": True,
            "findings": [f.to_json() for f in self.findings],
        }
