"""Taxes, surcharges and city fees: a percentage of the money actually paid.

**Tax applies to the money actually paid -- after every discount and validation.**
That is the rule, and it is the only base there is. A tax rule states no
base, because there is nothing to choose: the caller hands in `subtotal_minor`,
the running total after every discount and validation line, and every rule in
the set is a percentage of that one number.

**Percentage only.** A flat tax amount is not expressible. That is a stated limit,
not a hidden one: no field for it exists, and a key this module does not
understand is REJECTED and named, never ignored -- so `fixed`, `minor` or `base`
on a tax rule is refused at load by the same mechanism that refuses an unknown
key anywhere in a plan.

**No compounding.** A tax is never taken of another tax. There is no way to write
one -- no rule names a base -- and there is no way to COMPUTE one either: the
applier is handed the subtotal and nothing else, and never sees the lines it has
already produced. See `tax_lines`.

**Every tax is its own line.** Several rules produce several lines, in the order
the garage states with each rule's `sequence` -- never the order the caller's
list happened to carry them, which decided money in this module once already.

**The set in force is chosen by the instant.** A garage's taxes change by law, so
it states them as SETS, each with an `effective_from`. A rate changing, a tax
added and a tax repealed are all one thing: a new set. The caller hands in every
set and the instant; this module picks, and does not ask the caller to filter --
the same argument the plan versions make. An instant before every set is
REFUSED, never taxed at zero. A set with no rules is how a garage STATES that it
charges no tax, and it is a statement rather than an absence.

**What this does not know.** No stay, no garage, no validation, no monthly
agreement, no card, and no storage. It is not a stage of the pricing pipeline:
`quote()` never sees a validation, and tax runs after one. It takes an amount, a
currency, an instant and the sets, and returns lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .breakdown import Line
from .currency import is_known
from .findings import GAP_NO_TAX_SET_IN_FORCE, Finding, Refused
from .money import as_non_negative_minor, format_minor, refuse_non_integer_money
from .percent import (
    BASIS_POINTS_PER_WHOLE,
    exact_text,
    percent_of_minor,
    percent_text,
    was_rounded,
)
from .plan import InvalidPlan, _require_keys, parse_instant

#: Which way a fractional minor unit goes on a tax line. Stated per rule, with NO
#: default. A tax's own set: tax is conventionally taken to the nearest minor
#: unit, which the adjustment's `ADJUST_ROUNDINGS` cannot express -- and widening
#: that set would change what a PLAN may state, which nobody asked for. Two named
#: sets, one applier (`percent.percent_of_minor`).
TAX_ROUNDINGS: tuple[str, ...] = ("up", "down", "nearest")

#: Every field a tax set carries. All required.
TAX_SET_KEYS: frozenset[str] = frozenset({"effective_from", "rules"})

#: Every field a tax rule carries. All required, and there is no `base`.
TAX_RULE_KEYS: frozenset[str] = frozenset({"id", "label", "percent_bp", "rounding", "sequence"})

APPLIED = "tax.applied"


@dataclass(frozen=True)
class TaxRule:
    id: str
    label: str
    percent_bp: int
    rounding: str
    sequence: int


@dataclass(frozen=True)
class TaxSet:
    effective_from: datetime
    rules: tuple[TaxRule, ...]
    #: Where it sat in the document, for naming it in a refusal. Never used to
    #: decide anything.
    where: str


def _whole(value: object, label: str, *, positive: bool) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise InvalidPlan(
            f"{label} must be a {'positive ' if positive else ''}whole number, got {value!r}."
        )
    return value


def _rule(raw: object, where: str) -> TaxRule:
    if not isinstance(raw, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(raw).__name__}.")
    _require_keys(raw, TAX_RULE_KEYS, where)

    rule_id = raw["id"]
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise InvalidPlan(f"{where}.id must be a non-empty string.")
    label = raw["label"]
    if not isinstance(label, str) or not label.strip():
        raise InvalidPlan(
            f"{where}.label must be a non-empty string. It is what a driver and an "
            "operator both read on the line."
        )
    percent_bp = _whole(raw["percent_bp"], f"{where}.percent_bp", positive=True)
    rounding = raw["rounding"]
    if rounding not in TAX_ROUNDINGS:
        raise InvalidPlan(
            f"{where}.rounding is {rounding!r}; expected one of "
            f"{', '.join(TAX_ROUNDINGS)}. There is no default: a percentage lands on "
            "a fraction of a minor unit, and who keeps that fraction is the garage's "
            "to state."
        )
    sequence = _whole(raw["sequence"], f"{where}.sequence", positive=False)
    return TaxRule(rule_id, label, percent_bp, rounding, sequence)


def _set(raw: object, where: str) -> TaxSet:
    if not isinstance(raw, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(raw).__name__}.")
    _require_keys(raw, TAX_SET_KEYS, where)
    effective_from = parse_instant(raw["effective_from"], f"{where}.effective_from")

    raw_rules = raw["rules"]
    if not isinstance(raw_rules, list):
        raise InvalidPlan(
            f"{where}.rules must be a list. An EMPTY list is how a garage states that "
            "it charges no tax from this set's effective_from."
        )
    rules = tuple(_rule(r, f"{where}.rules[{i}]") for i, r in enumerate(raw_rules))

    by_id: dict[str, TaxRule] = {}
    by_sequence: dict[int, TaxRule] = {}
    for rule in rules:
        if rule.id in by_id:
            raise InvalidPlan(f"{where}.rules contains two rules with id {rule.id!r}.")
        by_id[rule.id] = rule
        other = by_sequence.get(rule.sequence)
        if other is not None:
            raise InvalidPlan(
                f"{where}.rules: {other.id!r} and {rule.id!r} both state sequence "
                f"{rule.sequence}. The order of a set's taxes is the garage's to state, "
                "and two rules in one place is an order nobody stated."
            )
        by_sequence[rule.sequence] = rule
    return TaxSet(effective_from, rules, where)


def load_tax_sets(document: object, where: str = "tax_sets") -> tuple[TaxSet, ...]:
    """Validate a garage's tax sets and return them, or refuse and name the field.

    Refused at load, before any amount exists: a float, a bool or a Decimal
    anywhere (the same plan-wide walk a plan gets); a missing field; an unknown
    one -- `base` included, because there is only one base and it is not
    stated; a rounding outside `TAX_ROUNDINGS`; two rules in one set sharing an
    id or a `sequence`; and two sets taking effect at the same instant.
    """
    refuse_non_integer_money(document, where, document_name="tax set")
    if not isinstance(document, list) or not document:
        raise InvalidPlan(
            f"{where} must be a non-empty list of tax sets. A garage that charges no "
            "tax states a set with no rules; a garage that has stated nothing has "
            "not said it charges no tax."
        )
    sets = tuple(_set(raw, f"{where}[{i}]") for i, raw in enumerate(document))

    # Compared as INSTANTS: `10:00-05:00` and `15:00+00:00` are one moment, and two
    # sets taking effect then are ambiguous whichever way the offsets are written.
    for i, first in enumerate(sets):
        for second in sets[i + 1:]:
            if first.effective_from == second.effective_from:
                raise InvalidPlan(
                    f"{first.where} and {second.where} both take effect at "
                    f"{first.effective_from.isoformat()}. Which one is in force would "
                    "be decided by their order in the list, and this module does not "
                    "decide money by list order: refused, both named."
                )
    return sets


def select_tax_set(sets: tuple[TaxSet, ...], at: datetime) -> TaxSet:
    """The set in force at `at`: the latest one taking effect at or before it.

    Unambiguous by construction -- `load_tax_sets` refuses two sets sharing an
    instant. An instant before every set is REFUSED, never taxed at zero.
    """
    in_force = [s for s in sets if s.effective_from <= at]
    if not in_force:
        earliest = min(sets, key=lambda s: s.effective_from)
        raise Refused(
            [
                Finding(
                    code=GAP_NO_TAX_SET_IN_FORCE,
                    text=(
                        f"no tax set is in force at {at.isoformat()}: the earliest, "
                        f"{earliest.where}, takes effect at "
                        f"{earliest.effective_from.isoformat()}. Not taxed at zero -- "
                        "zero is a position the garage would have to state, with a "
                        "set that has no rules."
                    ),
                )
            ]
        )
    return max(in_force, key=lambda s: s.effective_from)


def _tax_line(rule: TaxRule, subtotal_minor: int, currency: str) -> Line:
    """One rule's line. `subtotal_minor` is the ONLY amount this ever sees.

    Tax of the tax is extremely unusual, and that is the reason this
    takes the subtotal by name and never a running total. The adjustment applier
    it shares its arithmetic with takes `running_total_minor`, because an
    adjustment IS defined on the total so far; a tax is not, and a copy carrying
    that name is how a compounding tax gets built without anybody deciding to.
    """
    amount = percent_of_minor(subtotal_minor, rule.percent_bp, rule.rounding)
    unrounded = subtotal_minor * rule.percent_bp
    measure = f"{percent_text(rule.percent_bp)} of {format_minor(subtotal_minor, currency)} paid"
    if was_rounded(subtotal_minor, rule.percent_bp, amount):
        # The exact figure and the direction, so a driver disputing a cent is
        # shown the answer rather than told it. `nearest` also says which way
        # it went, because the mode alone does not.
        went = "up" if amount * BASIS_POINTS_PER_WHOLE > unrounded else "down"
        mode = f"nearest ({went})" if rule.rounding == "nearest" else rule.rounding
        measure += (
            f" is {exact_text(subtotal_minor, rule.percent_bp, currency)}, rounded {mode}"
        )
    return Line(
        code=APPLIED,
        rule_id=rule.id,
        text=f"{rule.label}: {measure} -- {format_minor(amount, currency)} added",
        delta_minor=amount,
    )


def tax_lines(
    sets: tuple[TaxSet, ...], *, subtotal_minor: int, currency: str, at: datetime
) -> list[Line]:
    """The tax lines for `subtotal_minor` at `at`, one per rule, in `sequence` order.

    `subtotal_minor` is the money actually paid: the running total after every
    discount and validation line. The caller adds the returned lines to its own
    ledger; this function never sees that ledger's total, and every rule is a
    percentage of the SAME subtotal. That is where no-compounding lives -- in the
    arithmetic, because there is no longer any way to write it down and so
    nothing for a grammar refusal to catch.

    **A subtotal of zero produces no lines.** Tax on nothing is nothing, and a
    ledger of zero-valued tax lines under a zero fee is noise. The set in force
    is still selected first, so an instant no set covers is refused even then --
    a gap in what the garage stated is not hidden by an amount that happened to
    be zero.
    """
    subtotal = as_non_negative_minor(subtotal_minor, "subtotal_minor")
    if not isinstance(currency, str) or not is_known(currency):
        raise InvalidPlan(
            f"currency is {currency!r}, which is not an ISO 4217 currency this module "
            "renders."
        )
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise InvalidPlan(
            f"at must be an offset-aware datetime, got {at!r}. A naive instant would "
            "be read in whatever zone the server runs in, and the set in force could "
            "differ by machine."
        )

    chosen = select_tax_set(sets, at)
    if subtotal == 0:
        return []

    lines: list[Line] = []
    for rule in sorted(chosen.rules, key=lambda r: r.sequence):
        lines.append(_tax_line(rule, subtotal, currency))
    return lines


__all__ = [
    "TAX_ROUNDINGS",
    "TAX_RULE_KEYS",
    "TAX_SET_KEYS",
    "TaxRule",
    "TaxSet",
    "load_tax_sets",
    "select_tax_set",
    "tax_lines",
]
