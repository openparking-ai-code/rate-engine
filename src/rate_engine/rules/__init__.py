"""The rule registry. Adding a rule type is how this module grows.

"In every state they have a different way to handle" -- so the list of ways to
calculate a fee GROWS, and the property that makes that safe is F7: registering
a new rule type changes no existing plan's answer, fee AND breakdown, byte for
byte. A registry whose members cannot see each other is what buys that; no rule
reads another rule's output, and none of them can reach the running total except
by returning a Line.

**The contract every rule type keeps, and the engine enforces on every quote:**

1. It returns LINES. Not a total, not a delta applied by side effect. A rule
   that changes the fee without saying so in words an operator can read is the
   failure this module exists to prevent, and it is unrepresentable here.
2. It is a pure function of (stay, plan, rule). No clock, no randomness, no
   ambient state -- F5.
3. Its money is integer minor units at every step -- F4.
4. It declares whether it qualified -- **and whether a non-qualifying rule SPEAKS
   depends on its stage.** A QUALIFY rule always returns a line: at delta zero,
   saying which condition failed. That is not politeness: "why didn't early bird
   apply?" is the question operators ask, and a breakdown that answers it only
   when the answer is good news is a breakdown nobody trusts. A rule at any other
   stage that does not cover the stay returns NOTHING -- the engine skips it --
   because a standard-space receipt listing every VIP tier the garage does not
   charge for is noise, not clarity.

   **This item used to say a non-qualifying rule ALWAYS returns a zero line, full
   stop, and that was false for every stage except QUALIFY.** `space_surcharge`
   documented the opposite in its own docstring, so the framework contract and a
   shipped rule type contradicted each other and nothing measured either. The
   distinction is real and worth keeping -- "this special could have applied to
   you and did not" is information; "a tier that was never about your space
   exists" is not -- but it is a rule about STAGES, not a blanket one.
   `tests/test_f22_the_silence_rule_is_per_stage.py` holds both halves.

   **AND THE STAGE IS NOT THE WHOLE ANSWER EITHER, which the second version had to find out.**
   The reasoning above is about the two KINDS of silence, and it used the stage as
   the proxy for them because in the first version the stage was a perfect proxy: the only rule
   type outside QUALIFY that could fail to apply failed by not covering the space.
   `time_window` broke that. A window with an `adjust` effect runs at ADJUST and
   can decline for a reason that has nothing to do with the space -- it is a
   Tuesday and the rule says weekends -- which is squarely the FIRST kind, the
   informative one, at a stage the old rule called silent. "Why didn't I get the
   weekend discount?" had no answer in the breakdown.

   So a type DECLARES it, with the `SPEAKS_UNQUALIFIED` trait, and the engine
   calls such a rule's applier even when it did not qualify -- **provided the rule
   COVERS the stay**, which is the half that was always right. A tier that was
   never about this space is still silent, whatever it declares.

5. It declares the STAGE OR STAGES it may run at, and a type that may run at
   more than one DERIVES each rule's stage from that rule's own shape. This
   exists because `time_window` is one condition with three effects and two of
   them are bases while the third modifies the total: a window with a `flat` or
   `rate` effect replaces the time-based charge and runs at QUALIFY, and one with
   an `adjust` effect is a percentage or an amount ON the whole fee and therefore
   runs at ADJUST, after the caps and the surcharges. Splitting that into two
   rule types would have split one operator decision -- "the weekend is
   different" -- across two documents, and the day-and-hours condition is
   identical in both.

   The plan still STATES each rule's stage, so the document is readable on its
   own, and `check_stated_stage` makes the statement and the derivation agree.
   Registering with a single stage is still the ordinary case and still works
   unchanged: `register("daily_max", CAP, ...)` takes a bare string.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..stages import STAGES


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    stage: str
    space_classes: tuple[str, ...]
    #: Type-specific, already validated by the builder that produced it.
    params: dict[str, Any]
    #: What the OPERATOR calls this rule, where its type lets them say. None for a
    #: type that has no such field, and every type that does not set it behaves
    #: exactly as it did.
    #:
    #: **It is a framework field rather than a `params` entry because the ENGINE
    #: needs it.** A rule beaten by a terminal one gets a line saying so, and no
    #: rule can write that line -- the rule that lost does not know it lost. The
    #: engine had only the id to name it by, so a receipt read "'eb-weekday' also
    #: qualified", which is a database key on a document a customer is handed.
    label: str | None = None

    @property
    def display_name(self) -> str:
        """What to call this rule in a sentence a customer reads.

        The operator's own label where there is one, and otherwise their own rule
        id -- which they also wrote, so it is never a name this module invented.
        """
        return self.label or self.id

    def covers(self, space_class: str) -> bool:
        return space_class in self.space_classes


# --- traits ----------------------------------------------------------------
#
# What a rule type declares about ITSELF at registration, rather than what the
# engine hardcodes about it by name. There has been exactly one rule in this
# module that needed the pipeline to behave differently, and the tempting fix was
# `if rule.type == "grace"` in engine.py -- which is the engine holding a pricing
# decision no plan can see or change, the defect `day_span` was created to undo.

#: When a rule of this type QUALIFIES, the pipeline stops after QUALIFY: nothing
#: at CAP, SURCHARGE or ADJUST is applied, and this rule prices the stay alone.
#: `grace` is the first one. Free means free -- a graced stay in a VIP space must
#: not pick up the surcharge, and must not pick up anything at CAP.
TERMINAL = "terminal"

#: A rule of this type is asked for lines even when it did NOT qualify, at any
#: stage, provided it covers the stay's space class. See item 4 above: the stage
#: was a proxy for "could this have applied to you", and it stopped being one.
SPEAKS_UNQUALIFIED = "speaks_unqualified"

#: A rule of this type is handed `time_charge_minor`: the charge for the TIME,
#: which is the running total when SURCHARGE begins -- after whichever base priced
#: the stay (the time-based rate or a special) and after the caps, before any
#: surcharge or adjustment. A percent VIP surcharge and the fill rule are both
#: "a percent of the time-based charge", and handing them the RUNNING total
#: instead would make two percent surcharges depend on which ran first, at a
#: stage this module promises is order-independent.
ON_THE_TIME_CHARGE = "on_the_time_charge"

#: A rule of this type qualifies on how full the garage was when the car came in,
#: so a stay it covers must carry `occupancy_at_entry_bp`. One that does not is
#: refused with GAP_NO_OCCUPANCY_AT_ENTRY -- the engine never assumes a figure.
#: A plan with no such rule ignores the figure entirely.
NEEDS_OCCUPANCY = "needs_occupancy_at_entry"

#: At most one rule of this type may qualify for a stay. Two fill rules on one
#: class both raising the same charge is not an order to state -- it is two
#: answers to "how much more when the garage is full", and the plan has to give
#: one. Reported as CONFLICT_OVERLAPPING_FILL_RULES, whatever `adjust_order` says.
ONE_PER_STAY = "one_per_stay"

#: A rule of this type is also told HOW the time was priced on this pass:
#: `priced_by_special`, the special that priced it (None when the time-based rate
#: did), and `extras_minor`, what SURCHARGE added for the stay's space class. The
#: fill rule needs both to honour the owner's two answers -- raise specials or
#: not, raise the VIP extra or not -- and no other type reads them.
TOLD_THE_PASS = "told_the_pass"

#: A rule of this type is handed `charged_by`: how the charge for the time built
#: up over the stay on this pass. It is a function of a number of minutes into
#: the stay, returning what the base that priced the time (the time-based rate
#: or a special) charges for the stay's first that many minutes -- or None when
#: the base's type does not say how its charge builds up. The daily and weekly
#: caps need it to cap each day and each week on its
#: own (F59): a cap that sees only the running total cannot tell which day the
#: money was charged in.
TOLD_THE_BASE = "told_the_base"

TRAITS: tuple[str, ...] = (
    TERMINAL, SPEAKS_UNQUALIFIED, ON_THE_TIME_CHARGE, NEEDS_OCCUPANCY, ONE_PER_STAY,
    TOLD_THE_PASS, TOLD_THE_BASE,
)

#: type name -> the traits it declared. Every registered type has an entry, so a
#: lookup is never a `.get` with a default that quietly means "no".
RULE_TRAITS: dict[str, frozenset[str]] = {}

#: type name -> (the stages it may run at, builder). The builder validates and
#: returns a Rule; the applier lives beside it and is looked up by type at
#: pipeline time.
#:
#: The stages are a TUPLE even when there is one of them, because the answer to
#: "where does this type run" stopped being a single value the moment one type
#: could be a base or an adjustment depending on its effect. A single registered
#: stage is still the ordinary case -- see `register`.
RULE_TYPES: dict[str, tuple[tuple[str, ...], Callable[..., Rule]]] = {}
RULE_APPLIERS: dict[str, Callable[..., Any]] = {}

#: type name -> how a rule of this type that prices the time builds its charge
#: up over the stay, or None. Called as `accrual(rule, stay, plan)`, it returns
#: the `charged_by` function `TOLD_THE_BASE` describes -- minutes into the stay
#: to what the rule charges for that many minutes -- or None when the type does
#: not say. Every registered type has an entry, so a lookup is never a `.get`
#: with a default. A flat special says None on purpose: it is one price for the
#: stay it covers, never split by the day (`time_window`, F63).
#:
#: **None is the safe answer, not the precise one.** A cap handed None caps the
#: whole charge at the daily max times the days the car is in, which is what a
#: cap did before it capped each day on its own. A type that prices the time by
#: the minute and registers no accrual is therefore capped as one price for the
#: stay; a type of that kind declares its accrual when it is added.
RULE_ACCRUALS: dict[str, Callable[..., Any] | None] = {}


def register(
    rule_type: str,
    stage: str | tuple[str, ...],
    builder: Callable[..., Rule],
    applier: Callable[..., Any],
    traits: tuple[str, ...] = (),
    accrual: Callable[..., Any] | None = None,
):
    """Register a rule type at the stage, or the stages, it may run at.

    `stage` is a bare string for the ordinary case -- a type that runs in exactly
    one place -- and a tuple for a type whose stage depends on the rule. Both
    spellings are accepted rather than the tuple alone because `register` is this
    module's published extension point: a rule type written against the earlier
    signature must keep working, which is F7 applied to the framework itself.

    `traits` is how a type tells the ENGINE that the pipeline must treat it
    differently, rather than the engine knowing its name. It defaults to none, so
    a type registered against the earlier signature declares nothing and behaves
    exactly as it did.

    `accrual` is how a type that prices the time says how its charge builds up
    over the stay (see `RULE_ACCRUALS`). It defaults to None, which a cap reads
    as one price for the whole stay, so a type registered against the earlier
    signature is capped exactly as it was.
    """
    stages = (stage,) if isinstance(stage, str) else tuple(stage)
    if not stages:
        raise ValueError(f"{rule_type} declares no stage at all.")
    declared = frozenset(traits)
    unknown_traits = sorted(declared - set(TRAITS))
    if unknown_traits:
        raise ValueError(
            f"{rule_type} declares trait(s) {', '.join(map(repr, unknown_traits))}, "
            f"which this version does not know. Registered traits: {', '.join(TRAITS)}."
        )
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        raise ValueError(
            f"{rule_type} declares stage(s) {', '.join(map(repr, unknown))}, "
            "which are not pipeline stages."
        )
    if rule_type in RULE_TYPES:
        # A module RELOAD re-runs its register() call, and the fail-controls
        # reload rule modules to plant defects in them. Re-registration from the
        # module that already owns the type is that, and is allowed. Registration
        # of the same name from a DIFFERENT module is two rule types fighting over
        # one name, which is the collision this guard exists for.
        incumbent = RULE_TYPES[rule_type][1].__module__
        if incumbent != builder.__module__:
            raise ValueError(
                f"rule type {rule_type!r} is registered by {incumbent} and "
                f"{builder.__module__} is trying to claim it."
            )
    RULE_TYPES[rule_type] = (stages, builder)
    RULE_APPLIERS[rule_type] = applier
    RULE_TRAITS[rule_type] = declared
    RULE_ACCRUALS[rule_type] = accrual


def build_rule(raw: object, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan  # circular by design: one refusal type for a plan

    if not isinstance(raw, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(raw).__name__}.")
    if "type" not in raw:
        raise InvalidPlan(f"{where} has no `type`.")
    rule_type = raw["type"]
    if rule_type not in RULE_TYPES:
        raise InvalidPlan(
            f"{where}.type is {rule_type!r}, which this version does not know. "
            f"Registered: {', '.join(sorted(RULE_TYPES))}. An unknown rule type is "
            "rejected rather than skipped -- a skipped rule is a rate an operator "
            "believes is live and that nothing applies."
        )
    _stages, builder = RULE_TYPES[rule_type]
    return builder(raw, plan_space_classes, where)


def check_stated_stage(raw: dict, where: str, stage: str) -> None:
    """The plan STATES a rule's stage; the code DERIVES it. This is where they meet.

    Both exist on purpose. The statement is what makes a plan document readable
    without this package in front of you; the derivation is what stops a document
    from claiming a rule runs somewhere it does not. Neither is redundant, and a
    disagreement between them is refused rather than resolved in favour of one.
    """
    from ..plan import InvalidPlan

    if raw["stage"] != stage:
        raise InvalidPlan(
            f"{where}.stage is {raw['stage']!r} but rule type {raw['type']!r} runs at "
            f"{stage}. The stage is stated in the plan so the document is "
            "readable on its own, and checked here so the two cannot disagree. A "
            "type that may run at more than one stage derives it from the rule's own "
            "shape, so this is not a list to look up -- it is what this rule does."
        )


def common_fields(raw: dict, plan_space_classes: tuple[str, ...], where: str, extra: set[str]):
    """Validate the fields every rule has, and reject unknown keys by name."""
    from ..plan import InvalidPlan

    required = {"id", "type", "stage", "space_classes"} | extra
    present = set(raw)
    missing = sorted(required - present)
    unknown = sorted(present - required)
    if missing:
        raise InvalidPlan(f"{where} is missing required field(s): {', '.join(missing)}.")
    if unknown:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown)}. Rejected, not ignored."
        )

    rule_id = raw["id"]
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise InvalidPlan(f"{where}.id must be a non-empty string.")

    stages, _builder = RULE_TYPES[raw["type"]]
    if len(stages) == 1:
        # A type with one stage needs nothing from the rule to know which. One
        # that may run at several derives it from the rule's own shape and calls
        # check_stated_stage itself, because the derivation is the rule type's
        # business and not the framework's -- see rules/time_window.py.
        check_stated_stage(raw, where, stages[0])

    space_classes = raw["space_classes"]
    if (
        not isinstance(space_classes, list)
        or not space_classes
        or not all(isinstance(s, str) for s in space_classes)
    ):
        raise InvalidPlan(f"{where}.space_classes must be a non-empty list of strings.")
    unknown_classes = sorted(set(space_classes) - set(plan_space_classes))
    if unknown_classes:
        raise InvalidPlan(
            f"{where}.space_classes names {', '.join(unknown_classes)}, which the plan "
            "does not declare in its own space_classes."
        )
    return rule_id, tuple(space_classes)
