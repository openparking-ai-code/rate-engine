"""The plan document: data, validated on load, never code.

Every field below is REQUIRED. There is no default anywhere in this file, and
that is the module's whole disposition rather than a style preference -- a
default is a pricing decision made by whoever wrote the engine, applied to a
garage whose owner never saw it. Where a plan is silent, the engine refuses and
says which field would have had to be invented.

**An unknown key is REJECTED and named, never ignored.** The specification versions a commercial
contract on the assumption it will GAIN fields, and that assumption is only safe
in one direction: a NEW engine must tolerate an OLD plan, but an OLD engine must
never silently accept a key it does not understand. An operator who adds
`weekend_rate` to a plan running on a version that has no weekend rule has a
garage pricing weekends wrong and a document saying it does not. So a key this
version does not know is a refusal that names the key.

**TIME. The plan states its timezone and every stay is an aware instant.**
This is not incidental. `time_window` speaks of "enter by 09:00"; `daily_max`
speaks of a day. Both are wall-clock ideas and neither means anything without a
zone -- and a day is 23 or 25 hours across a DST transition, so "24 hours" and
"a calendar day" are genuinely different rules rather than two spellings of one.
The plan names an IANA zone, entry and exit arrive as offset-aware ISO 8601, and
a naive timestamp is refused. `zoneinfo` is standard library, so this costs no
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .currency import excluded_reason, is_known
from .money import refuse_non_integer_money
from .rules import RULE_TYPES, Rule, build_rule
from .stages import ADJUST, RESOLVING


class InvalidPlan(ValueError):
    """The plan document cannot be loaded. The message names the field.

    `missing_keys` and `unknown_keys` carry, as data, the fields `_require_keys`
    refused -- so a caller or a test keys off WHICH field rather than off the
    wording of the sentence. Empty on every other refusal.

    `code` is one of `findings.INVALID_CODES` where the refusal has one, and
    None everywhere else. It reaches the caller beside the sentence, so a plan
    store can route on it.
    """

    def __init__(
        self,
        message: str,
        *,
        missing_keys: tuple[str, ...] = (),
        unknown_keys: tuple[str, ...] = (),
        code: str | None = None,
    ) -> None:
        from .findings import INVALID_CODES

        if code is not None and code not in INVALID_CODES:
            raise ValueError(
                f"{code!r} is not a registered invalid code. Add it to findings.py "
                "so the contract learns about it."
            )
        super().__init__(message)
        self.missing_keys = missing_keys
        self.unknown_keys = unknown_keys
        self.code = code


#: Resolution modes a plan may state, and the second version is where they finally DECIDE
#: something. The first version validated this field, required it on every plan, published it in
#: the contract -- and acted on it nowhere. `find_conflicts` said so in its own
#: docstring. A required field that changes no answer is a decision the owner
#: made and the software ignored, which this module has shipped once before.
#:
#: * `cheapest_wins` -- the LOWEST FEE FOR THE CUSTOMER wins. Compared on what
#:   the competing rules themselves charge for this stay, which is the only
#:   comparison available before the rest of the pipeline has run. Two rules at
#:   the SAME price cannot be separated by it and are REFUSED, naming both, the
#:   way two plan versions sharing an effective date already are.
#: * `stated_order` -- the plan names the rule ids, in order, and the first one
#:   that qualifies wins. It must name every rule at that stage exactly once: a
#:   rule left out would take a silent position, and array position deciding
#:   money is the disease `select_plan` exists to refuse.
RESOLUTION_MODES: tuple[str, ...] = ("cheapest_wins", "stated_order")

#: `adjust_order` is a LIST OF RULE IDS, or null, and the null has to be typed.
#:
#: **It is deliberately not part of `resolution`, and that is not tidiness.**
#: A resolution mode answers "which of these is the price" -- an either/or, at a
#: stage where only one rule can win. Two adjustments are not an either/or: BOTH
#: apply, and the only open question is the sequence, because 20% off then 5.00
#: off is not 5.00 off then 20% off. An order is not a choice, so it does not
#: live in the field that records choices.
#:
#: Required-and-nullable, like `max_duration_minutes` and `week_starts_on`: a
#: field that may simply be absent is a field somebody forgets while believing
#: they set it. A plan with fewer than two adjustments writes null.

PLAN_KEYS: frozenset[str] = frozenset(
    {
        "plan_version",
        "effective_from",
        "timezone",
        "currency",
        "space_classes",
        "resolution",
        "adjust_order",
        "rules",
        "decisions",
    }
)


def _require_keys(document: dict, keys: frozenset[str], where: str) -> None:
    present = set(document)
    missing = sorted(keys - present)
    unknown = sorted(present - keys)
    if missing:
        raise InvalidPlan(
            f"{where} is missing required field(s): {', '.join(missing)}. "
            "This module has no defaults; a field it cannot read is a pricing "
            "decision nobody made.",
            missing_keys=tuple(missing),
        )
    if unknown:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown)}. They are REJECTED rather than ignored -- an "
            "ignored key is how a plan an operator believes is live prices "
            "something else. Upgrade the engine, or remove the key.",
            unknown_keys=tuple(unknown),
        )


def _resolution(document: dict, where: str) -> dict[str, dict]:
    """How this plan settles two rules qualifying at one stage.

    **Keyed by the RESOLVING stages and by nothing else.** It used to require an
    entry for all five, and the three it could never act on were decisions that
    did nothing -- a mode stated for CAP cannot choose between two caps, because
    both of them apply. A key for a stage that cannot resolve is refused by name,
    the way every unknown key here is.

    ADJUST is the one that looks like an exception and is not: two adjustments do
    need an order, but an order is not a choice, so it is stated separately in
    `adjust_order`.
    """
    resolution = document["resolution"]
    if not isinstance(resolution, dict):
        raise InvalidPlan(f"{where}.resolution must be an object keyed by stage.")
    _require_keys(resolution, frozenset(RESOLVING), f"{where}.resolution")

    parsed: dict[str, dict] = {}
    for stage in sorted(RESOLVING):
        settings = resolution[stage]
        at = f"{where}.resolution.{stage}"
        if not isinstance(settings, dict) or "mode" not in settings:
            raise InvalidPlan(
                f"{at} must be an object carrying a `mode` of "
                f"{', '.join(RESOLUTION_MODES)}."
            )
        mode = settings["mode"]
        if mode not in RESOLUTION_MODES:
            raise InvalidPlan(
                f"{at}.mode is {mode!r}; expected one of {', '.join(RESOLUTION_MODES)}. "
                "There is no default: which rule wins differs by state, so the engine "
                "will not choose one for you."
            )
        allowed = {"mode", "order"} if mode == "stated_order" else {"mode"}
        unknown = sorted(set(settings) - allowed)
        if unknown:
            raise InvalidPlan(
                f"{at} carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
                + (" `order` belongs to `stated_order` and means nothing to "
                   "`cheapest_wins`." if "order" in unknown else "")
            )
        if mode == "cheapest_wins":
            parsed[stage] = {"mode": mode}
            continue
        if "order" not in settings:
            raise InvalidPlan(
                f"{at} is missing required field(s): order. `stated_order` is an "
                "order, and it has to be stated."
            )
        order = settings["order"]
        if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
            raise InvalidPlan(f"{at}.order must be a list of rule ids.")
        if len(set(order)) != len(order):
            raise InvalidPlan(f"{at}.order names a rule more than once.")
        parsed[stage] = {"mode": mode, "order": tuple(order)}
    return parsed


def _check_stated_orders(resolution: dict[str, dict], rules, where: str) -> None:
    """A stated order names every rule at its stage EXACTLY ONCE, or it is refused.

    Checked here rather than in `_resolution` because it needs the rules, and
    checked at LOAD rather than at quote time because it is a property of the
    plan: an owner should meet it when they write the document, not when a
    particular car leaves.
    """
    for stage, settings in resolution.items():
        if settings["mode"] != "stated_order":
            continue
        at_stage = sorted(rule.id for rule in rules if rule.stage == stage)
        missing = sorted(set(at_stage) - set(settings["order"]))
        extra = sorted(set(settings["order"]) - set(at_stage))
        if missing or extra:
            raise InvalidPlan(
                f"{where}.resolution.{stage}.order must name every rule at {stage} "
                "exactly once. "
                + (f"Missing: {', '.join(missing)}. " if missing else "")
                + (f"Not a {stage} rule in this plan: {', '.join(extra)}. " if extra else "")
                + "A rule left out of the order would take a silent position in it, "
                "and array position deciding money is what this module refuses "
                "everywhere else."
            )


def parse_instant(value: object, label: str) -> datetime:
    """Parse an offset-aware ISO 8601 instant, or refuse."""
    if not isinstance(value, str):
        raise InvalidPlan(f"{label} must be an ISO 8601 string, got {type(value).__name__}.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidPlan(f"{label} is not ISO 8601: {value!r} ({exc}).") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidPlan(
            f"{label} has no UTC offset ({value!r}). A naive timestamp is refused: it "
            "would be read in whatever zone the server happens to run in, which is a "
            "different fee on a different machine."
        )
    return parsed


@dataclass(frozen=True)
class Plan:
    plan_version: str
    effective_from: datetime
    timezone: ZoneInfo
    timezone_name: str
    currency: str
    space_classes: tuple[str, ...]
    resolution: dict[str, dict]
    adjust_order: tuple[str, ...] | None
    rules: tuple[Rule, ...]
    decisions: tuple[dict, ...]

    def rules_for_stage(self, stage: str) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.stage == stage)


def load_plan(document: object, where: str = "plan") -> Plan:
    """Validate a plan document and return it, or refuse and name the field."""
    if not isinstance(document, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(document).__name__}.")

    # Before any field is read. A float in a key this version ignores is still a
    # float in a live plan; see money.refuse_non_integer_money.
    refuse_non_integer_money(document, where, document_name="plan")
    _require_keys(document, PLAN_KEYS, where)

    plan_version = document["plan_version"]
    if not isinstance(plan_version, str) or not plan_version.strip():
        raise InvalidPlan(f"{where}.plan_version must be a non-empty string.")

    effective_from = parse_instant(document["effective_from"], f"{where}.effective_from")

    timezone_name = document["timezone"]
    if not isinstance(timezone_name, str):
        raise InvalidPlan(f"{where}.timezone must be an IANA zone name, e.g. 'America/New_York'.")
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidPlan(
            f"{where}.timezone {timezone_name!r} is not an IANA zone ({exc}). "
            "'EST' and 'UTC-5' are refused: they cannot express a DST transition, "
            "and a daily cap has to know whether a day was 23 hours or 25."
        ) from exc

    currency = document["currency"]
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
        raise InvalidPlan(
            f"{where}.currency must be a three-letter uppercase ISO 4217 code, "
            f"got {currency!r}."
        )
    # AND IT MUST BE ONE THIS MODULE CAN RENDER. The sentence above said "ISO
    # 4217" and the check tested only shape, so `ZZZ` loaded and priced. That was
    # half of one defect: the other half was `format_minor` assuming every
    # currency has two decimal places. Both need the same thing -- the currency's
    # minor-unit exponent -- so membership is checked here and the exponent is
    # read there, from one table. See currency.py for what is excluded and why.
    if not is_known(currency):
        # A code refused BY DECISION says which decision. One that is merely
        # absent gets the generic sentence -- it may be a real currency this
        # table is missing, and inventing a reason would be a confident wrong
        # answer about somebody's money.
        reason = excluded_reason(currency)
        because = (
            f" It is refused because {reason}."
            if reason
            else (
                " If it is a real ISO 4217 currency, this module's table is missing it:"
                " that is a defect to report rather than something to work around."
            )
        )
        raise InvalidPlan(
            f"{where}.currency is {currency!r}, which is not an ISO 4217 currency this "
            f"module prices in.{because} The number of minor units in a major one would "
            "have to be guessed to render any amount, and a guessed exponent renders "
            "money wrong by a factor of ten or a hundred."
        )

    space_classes = document["space_classes"]
    if (
        not isinstance(space_classes, list)
        or not space_classes
        or not all(isinstance(s, str) and s for s in space_classes)
    ):
        raise InvalidPlan(f"{where}.space_classes must be a non-empty list of strings.")
    if len(set(space_classes)) != len(space_classes):
        raise InvalidPlan(f"{where}.space_classes contains a duplicate.")

    resolution = _resolution(document, where)

    raw_rules = document["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise InvalidPlan(f"{where}.rules must be a non-empty list.")
    rules = tuple(
        build_rule(raw, tuple(space_classes), f"{where}.rules[{i}]")
        for i, raw in enumerate(raw_rules)
    )
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise InvalidPlan(f"{where}.rules contains two rules with id {rule.id!r}.")
        seen.add(rule.id)

    _check_stated_orders(resolution, rules, where)

    adjust_order = document["adjust_order"]
    if adjust_order is not None:
        adjustments = sorted(r.id for r in rules if r.stage == ADJUST)
        if (
            not isinstance(adjust_order, list)
            or not all(isinstance(item, str) for item in adjust_order)
        ):
            raise InvalidPlan(
                f"{where}.adjust_order must be a list of rule ids, or null. It is the "
                "sequence the ADJUST rules are applied in, and an order is not a "
                "choice -- see resolution, which records choices."
            )
        if len(set(adjust_order)) != len(adjust_order):
            raise InvalidPlan(f"{where}.adjust_order names a rule more than once.")
        if sorted(adjust_order) != adjustments:
            # Named explicitly and exhaustively, never by position. A rule missing
            # from the order would otherwise take a silent place in it, which is
            # the array-order disease this module refuses at `select_plan`.
            missing = sorted(set(adjustments) - set(adjust_order))
            extra = sorted(set(adjust_order) - set(adjustments))
            raise InvalidPlan(
                f"{where}.adjust_order must name every ADJUST rule exactly once. "
                + (f"Missing: {', '.join(missing)}. " if missing else "")
                + (f"Not an ADJUST rule in this plan: {', '.join(extra)}. " if extra else "")
                + "A rule left out of the order would take a silent position in it."
            )
        # The fill rule raises what is left after every discount (10-14 20:25,
        # "always the cheaper"): raising first and discounting after charges the
        # customer more on a flat discount, so no plan may state it.
        fills = [r.id for r in rules if r.type == "fill_level"]
        tail = adjust_order[len(adjust_order) - len(fills):] if fills else []
        if fills and sorted(tail) != sorted(fills):
            raise InvalidPlan(
                f"{where}.adjust_order must put the fill rule ({', '.join(sorted(fills))}) "
                "after every other ADJUST rule. It raises what is left after the "
                "discounts, which is always the cheaper way for the customer; raised "
                "first and discounted after, a flat discount would cost them more."
            )

    decisions = document["decisions"]
    if not isinstance(decisions, list):
        raise InvalidPlan(
            f"{where}.decisions must be a list (empty is fine). It records the owner's "
            "answer to each gap and conflict, with who and when."
        )
    for i, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise InvalidPlan(f"{where}.decisions[{i}] must be an object.")
        _require_keys(
            decision,
            frozenset({"code", "decided_by", "decided_at", "note"}),
            f"{where}.decisions[{i}]",
        )

    return Plan(
        plan_version=plan_version,
        effective_from=effective_from,
        timezone=timezone,
        timezone_name=timezone_name,
        currency=currency,
        space_classes=tuple(space_classes),
        resolution=resolution,
        adjust_order=tuple(adjust_order) if adjust_order is not None else None,
        rules=rules,
        decisions=tuple(decisions),
    )


__all__ = ["InvalidPlan", "Plan", "load_plan", "parse_instant", "RESOLUTION_MODES", "RULE_TYPES"]
