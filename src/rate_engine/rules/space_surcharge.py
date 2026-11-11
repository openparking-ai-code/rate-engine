"""`space_surcharge` -- base plus a fixed amount, or a percent, for a space class.

The specification's consequence, and it is the reason this rule type exists in the first
version at all: **the module prices a SPACE, not a garage.** A VIP area and a reserved spot are the
same mechanism -- a class of space that costs the base plus a stated amount --
and so is the nested-area pricing a later round will need. Getting the space
identifier onto the contract from day one is most of that work.

It runs AFTER the cap, deliberately. A surcharge applied before the cap would be
capped away, so the customer would pay the same for a VIP space as for a standard
one on any stay long enough to hit the maximum -- which is not what an operator
who charges extra for VIP means. See stages.py: the order is load-bearing.

A stay in a space class this rule does not cover produces NO line. That is the
one place in this module where a non-qualifying rule stays silent, and it is
deliberate: a standard-space receipt listing every VIP tier the garage does not
charge for is noise, not clarity. A rule that could have applied to THIS space
and did not is a different thing and does emit a line.

**Two forms, one rule type.** A flat amount per stay, `surcharge_minor`, as it has
always been; or a PERCENT of the stay's time-based charge, `amount: {kind:
"percent", percent_bp}` with its `rounding` (10-14: "we will need to do %"). The
percent is taken of the charge for the TIME -- the running total when SURCHARGE
began, after the base and the caps (`ON_THE_TIME_CHARGE`) -- and never of another
surcharge, so two surcharges still compose in any order with the same total.
A rule states one form or the other, never both.
"""

from __future__ import annotations

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..percent import percent_of_minor, percent_text, was_rounded, whole_bp
from ..stages import SURCHARGE
from . import ON_THE_TIME_CHARGE, Rule, common_fields, register

EXTRA = {"surcharge_minor"}
PERCENT_EXTRA = {"amount", "rounding"}

#: Which way a fraction of a minor unit goes, as an `adjust` effect states it.
ROUNDINGS: tuple[str, ...] = ("up", "down")

#: The most a percent surcharge may add: 100%, double the time-based charge.
MAX_PERCENT_BP = 10_000


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    if isinstance(raw, dict) and "amount" in raw:
        if "surcharge_minor" in raw:
            raise InvalidPlan(
                f"{where} states both `surcharge_minor` and `amount`. A surcharge is a "
                "flat amount per stay OR a percent of the time-based charge; with both, "
                "which one the garage charges would be the engine's guess."
            )
        rule_id, space_classes = common_fields(raw, plan_space_classes, where, PERCENT_EXTRA)
        amount = raw["amount"]
        if not isinstance(amount, dict) or amount.get("kind") != "percent":
            raise InvalidPlan(
                f"{where}.amount must be {{\"kind\": \"percent\", \"percent_bp\": ...}}. "
                "A flat surcharge is written as `surcharge_minor`."
            )
        unknown = sorted(set(amount) - {"kind", "percent_bp"})
        if unknown:
            raise InvalidPlan(
                f"{where}.amount carries key(s) this version does not understand: "
                f"{', '.join(unknown)}. Rejected, not ignored."
            )
        if "percent_bp" not in amount:
            raise InvalidPlan(f"{where}.amount is missing required field(s): percent_bp.")
        rounding = raw["rounding"]
        if rounding not in ROUNDINGS:
            raise InvalidPlan(
                f"{where}.rounding is {rounding!r}; expected one of {', '.join(ROUNDINGS)}. "
                "There is no default: a percentage of a fee lands on a fraction of a "
                "cent, and who keeps it is the owner's to say."
            )
        params = {
            "percent_bp": whole_bp(
                amount["percent_bp"], f"{where}.amount.percent_bp", 1, MAX_PERCENT_BP
            ),
            "rounding": rounding,
        }
    else:
        rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
        params = {
            "surcharge_minor": as_non_negative_minor(
                raw["surcharge_minor"], f"{where}.surcharge_minor"
            )
        }
    return Rule(
        id=rule_id, type="space_surcharge", stage=SURCHARGE,
        space_classes=space_classes, params=params,
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class)


def apply(rule: Rule, stay, plan, time_charge_minor: int | None = None) -> list[Line]:
    if "surcharge_minor" in rule.params:
        amount = rule.params["surcharge_minor"]
        return [
            Line(
                code="space_surcharge.applied",
                rule_id=rule.id,
                text=(
                    f"Space class {stay.space_class!r}: "
                    f"{format_minor(amount, plan.currency)} on top of the base"
                ),
                delta_minor=amount,
            )
        ]
    if time_charge_minor is None:
        from ..plan import InvalidPlan

        raise InvalidPlan(
            f"rule {rule.id!r} is a percent surcharge and was applied without the "
            "time-based charge. A wiring fault in the caller, not a plan that is wrong."
        )
    percent_bp = rule.params["percent_bp"]
    amount = percent_of_minor(time_charge_minor, percent_bp, rule.params["rounding"])
    measure = (
        f"{percent_text(percent_bp)} of the time-based charge "
        f"{format_minor(time_charge_minor, plan.currency)}"
    )
    if was_rounded(time_charge_minor, percent_bp, amount):
        measure += f" (rounded {rule.params['rounding']})"
    return [
        Line(
            code="space_surcharge.applied",
            rule_id=rule.id,
            text=(
                f"Space class {stay.space_class!r}: {measure} -- "
                f"{format_minor(amount, plan.currency)} on top of the base"
            ),
            delta_minor=amount,
        )
    ]


register("space_surcharge", SURCHARGE, build, apply, traits=(ON_THE_TIME_CHARGE,))
