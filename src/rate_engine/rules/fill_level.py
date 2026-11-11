"""`fill_level` -- when the garage is at least X% full, the time costs Y% more.

The rule (2026-10-13): occupancy-based pricing is wanted, and all the cars
already inside keep the old price. So the figure this rule reads is how full the garage was **at the
moment the car came in** -- `Stay.occupancy_at_entry_bp`, set by the caller when
the stay opened -- and nothing about a stay's price changes after entry. "Full"
is every car inside against every switched-on space (all cars, 2026-10-14); the
engine does not count anything, it reads the figure it is handed.

**It runs at ADJUST**, the stage stages.py has always described as the place for
occupancy-driven multipliers, and **it raises the charge for the TIME**: the
running total when SURCHARGE began, after whichever base priced the stay and after
the caps (`ON_THE_TIME_CHARGE`), **less any discount taken before it** (10-14
20:25, "always the cheaper"): 10.00 with 20% or 2.00 off at a +20% fill rule is
8.00 + 1.60 = 9.60. Which order and which split of the discount between the
time charge and the extra is not argued here: the engine prices every order and
charges the cheapest, to the cent (`engine._adjusted`, F55), and this rule is
told what is left of each part on the order being priced. The plan loader still
holds every fill rule LAST in `adjust_order`.

**Two answers the OWNER gives, and the engine assumes neither** (2026-10-14: the
owner decides, at rate setup for dynamic pricing). Both are required, answered
`"yes"` or `"no"`, with no default, and a plan that omits either does not load.
They are words and not JSON booleans because no bool appears anywhere in a plan
(F4): a bool is an int in Python, one cent away from money.

* `raises_specials` -- when a special priced the time (a window with a `flat` or
  `rate` effect that qualified), is that charge raised too? `no`: it is not,
  and a line says so in plain words. Under `cheapest_wins` the stay is still
  priced both ways, so a car a special can price pays the cheaper of the unraised
  special and the raised time-based rate.
* `raises_vip_extra` -- is what SURCHARGE added for the stay's space class (flat
  or percent) raised by the same percent? `yes`: it gets its own line, rounded
  the rule's way. `no`: the extra stays as set.

`threshold_bp` and the stay's figure are basis points of full: 80% is 8000. The
rule qualifies AT the threshold and above. A stay with no figure, in a class this
rule covers, never reaches the applier: `find_gaps` refuses it by name
(`NEEDS_OCCUPANCY`). Below the threshold the rule SPEAKS -- "why was I not
charged the busy rate" and "why was I" are the same question -- and a class the
rule does not cover stays silent, as every rule outside QUALIFY does.
"""

from __future__ import annotations

from ..breakdown import Line
from ..percent import percent_of_minor, percent_text, was_rounded, whole_bp
from ..stages import ADJUST
from . import (
    NEEDS_OCCUPANCY,
    ON_THE_TIME_CHARGE,
    ONE_PER_STAY,
    SPEAKS_UNQUALIFIED,
    TOLD_THE_PASS,
    Rule,
    common_fields,
    register,
)

#: The owner's two answers. Required, and one of ANSWERS -- nothing else is one.
SWITCHES: tuple[str, ...] = ("raises_specials", "raises_vip_extra")
ANSWERS: tuple[str, ...] = ("yes", "no")

EXTRA = {"threshold_bp", "percent_bp", "rounding", *SWITCHES}

#: Which way a fraction of a minor unit goes -- the set an `adjust` effect may
#: state, for the same reason: this is an adjustment of the fee.
ROUNDINGS: tuple[str, ...] = ("up", "down")

#: 100% full. A figure or a threshold above it describes no garage.
FULL_BP = 10_000

#: The most the time may be raised by: 100%, double. The Lab offers 5% to 50%.
MAX_INCREASE_BP = 10_000

APPLIED = "fill_level.applied"
NOT_APPLIED = "fill_level.not_applied"
#: Qualified, but a special priced the time and the plan does not raise specials.
SPECIAL_NOT_RAISED = "fill_level.special_not_raised"
#: The extra for the stay's space class, raised by the same percent.
EXTRA_RAISED = "fill_level.extra_raised"


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    rounding = raw["rounding"]
    if rounding not in ROUNDINGS:
        raise InvalidPlan(
            f"{where}.rounding is {rounding!r}; expected one of {', '.join(ROUNDINGS)}. "
            "There is no default: a percentage of a fee lands on a fraction of a cent, "
            "and who keeps it is the owner's to say."
        )
    for switch in SWITCHES:
        if raw[switch] not in ANSWERS:
            raise InvalidPlan(
                f"{where}.{switch} must be \"yes\" or \"no\"; got {raw[switch]!r}. It is "
                "the owner's answer and there is no default: the engine does not "
                "decide for the owner what the fill rule raises."
            )
    params = {
        "threshold_bp": whole_bp(raw["threshold_bp"], f"{where}.threshold_bp", 0, FULL_BP),
        "percent_bp": whole_bp(raw["percent_bp"], f"{where}.percent_bp", 1, MAX_INCREASE_BP),
        "rounding": rounding,
        **{switch: raw[switch] == "yes" for switch in SWITCHES},
    }
    return Rule(
        id=rule_id, type="fill_level", stage=ADJUST,
        space_classes=space_classes, params=params,
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    figure = stay.occupancy_at_entry_bp
    return (
        rule.covers(stay.space_class)
        and figure is not None
        and figure >= rule.params["threshold_bp"]
    )


def _raised(rule: Rule, amount_minor: int, currency: str) -> tuple[int, str]:
    """The rule's percent of an amount, and the words for it. One place, so the
    time line and the extra line cannot round two different ways."""
    from ..money import format_minor

    percent_bp = rule.params["percent_bp"]
    added = percent_of_minor(amount_minor, percent_bp, rule.params["rounding"])
    measure = f"+{percent_text(percent_bp)} on {format_minor(amount_minor, currency)}"
    if was_rounded(amount_minor, percent_bp, added):
        measure += f" (rounded {rule.params['rounding']})"
    return added, measure


def apply(
    rule: Rule, stay, plan, running_total_minor: int | None = None,
    time_charge_minor: int | None = None, priced_by_special=None, extras_minor: int = 0,
    discounted_minor: int = 0,
) -> list[Line]:
    """`priced_by_special` is the special that priced the time on this pass, or
    None when the time-based rate did; `extras_minor` is what SURCHARGE added for
    this stay. Both are handed in by the engine with the time charge.

    `time_charge_minor` and `extras_minor` are what is LEFT of each after the
    discounts that ran before this rule (`discounted_minor` in all): the fill
    rule's percent is taken of what the customer still pays, never of the price
    before the discount (10-14 20:25, "always the cheaper")."""
    from ..money import format_minor
    from ..plan import InvalidPlan

    figure = stay.occupancy_at_entry_bp
    if figure is None or time_charge_minor is None:
        raise InvalidPlan(
            f"rule {rule.id!r} (fill_level) was applied without "
            + ("the stay's occupancy at entry" if figure is None else "the time-based charge")
            + ". The engine refuses such a stay before pricing it; reaching here is a "
            "wiring fault in the caller, not a plan that is wrong."
        )
    threshold = rule.params["threshold_bp"]
    full = f"Garage was {percent_text(figure)} full at entry"
    # `qualifies` is THE comparison. The applier asks it rather than comparing
    # again: a second copy of "at or above the threshold" is a second answer the
    # day one of them is edited, and the fail-controls found exactly that here.
    if not qualifies(rule, stay, plan):
        return [
            Line(
                code=NOT_APPLIED,
                rule_id=rule.id,
                text=(
                    f"{full} (below {percent_text(threshold)}): time-based charge not raised"
                ),
                delta_minor=0,
            )
        ]

    lines: list[Line] = []
    if priced_by_special is not None and not rule.params["raises_specials"]:
        lines.append(
            Line(
                code=SPECIAL_NOT_RAISED,
                rule_id=rule.id,
                text=(
                    f"{priced_by_special.display_name} special: fill rule not applied "
                    f"(garage was {percent_text(figure)} full at entry, at or above "
                    f"{percent_text(threshold)}; this plan does not raise specials)"
                ),
                delta_minor=0,
            )
        )
    else:
        added, measure = _raised(rule, time_charge_minor, plan.currency)
        what = "time-based charge after discounts" if discounted_minor else "time-based charge"
        lines.append(
            Line(
                code=APPLIED,
                rule_id=rule.id,
                text=(
                    f"{full} (at or above {percent_text(threshold)}): {what} "
                    f"{measure} -- {format_minor(added, plan.currency)} added"
                ),
                delta_minor=added,
            )
        )

    if extras_minor and rule.params["raises_vip_extra"]:
        added, measure = _raised(rule, extras_minor, plan.currency)
        lines.append(
            Line(
                code=EXTRA_RAISED,
                rule_id=rule.id,
                text=(
                    f"Space class {stay.space_class!r} extra"
                    f"{' after discounts' if discounted_minor else ''} {measure} (garage was "
                    f"{percent_text(figure)} full at entry) -- "
                    f"{format_minor(added, plan.currency)} added"
                ),
                delta_minor=added,
            )
        )
    return lines


register(
    "fill_level", ADJUST, build, apply,
    traits=(
        SPEAKS_UNQUALIFIED, ON_THE_TIME_CHARGE, NEEDS_OCCUPANCY, ONE_PER_STAY,
        TOLD_THE_PASS,
    ),
)
