"""A percentage of an amount of money: the ONE applier, shared.

Two things in this module take a percentage of money: a `time_window`'s `adjust`
effect, and a tax rule. They do not get one implementation each. A percentage
taken in two places is two answers to one question the day one of them is
edited, and the question is a customer's money -- so both call `percent_of_minor`
below, and the only thing that differs between them is WHICH rounding modes each
one lets a document state.

**Integer end to end.** A percentage is INTEGER BASIS POINTS -- 20% is `2000`,
12.5% is `1250` -- and the arithmetic is `amount * percent_bp` divided by 10,000.
The division is the only place a fraction of a minor unit can appear, so it is
the only place a rounding mode is read. No float is constructed at any point,
and `round()` is not used: Python's `round` is banker's rounding on a float, which
is two separate reasons it has no business deciding a cent.

**The applier refuses a mode it does not implement** rather than falling through
to one it does. The set a document may STATE is the caller's (`ADJUST_ROUNDINGS`
for an adjustment, `TAX_ROUNDINGS` for a tax), and each loader refuses anything
outside its own set by name. This function is the second line: it checks what it
IMPLEMENTS, never what a loader accepts -- the F15 disposition. It used to be an
`if down / else ceil`, which priced any mode that was not "down" as "up".
"""

from __future__ import annotations

#: 20% is 2000. Basis points, because a percent field that could be `20.5` would
#: either be refused by `money.refuse_non_integer_money` -- which rejects a float
#: anywhere in a plan -- or put a float into the pricing path.
BASIS_POINTS_PER_WHOLE: int = 10_000

#: Every mode `percent_of_minor` implements. A document may state a SUBSET of
#: these, and which subset is the loader's decision, not this file's.
IMPLEMENTED_ROUNDINGS: tuple[str, ...] = ("up", "down", "nearest")


def whole_bp(value: object, label: str, low: int, high: int) -> int:
    """A basis-point field from a plan, or refuse it by name.

    A whole number from `low` to `high`, both included. A bool is refused although
    Python calls it an int, and so is a string, a float and anything negative: the
    field is read straight into the arithmetic below, and a value that only LOOKS
    like a percentage is a fee nobody stated.
    """
    from .plan import InvalidPlan

    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidPlan(
            f"{label} must be a whole number of basis points from {low} to {high} "
            f"({percent_text(low)} to {percent_text(high)}); got {value!r}. 20% is 2000 "
            "and 12.5% is 1250."
        )
    return value


def percent_text(basis_points: int) -> str:
    """2000 -> '20%', 1250 -> '12.5%'. Integer arithmetic; no float is created."""
    whole, fraction = divmod(basis_points, 100)
    if fraction == 0:
        return f"{whole}%"
    return f"{whole}.{fraction:02d}".rstrip("0") + "%"


def percent_of_minor(amount_minor: int, percent_bp: int, rounding: str) -> int:
    """`percent_bp` basis points of `amount_minor`, rounded the way `rounding` says.

    Both inputs are non-negative whole numbers by the time they arrive here -- every
    caller validates them at load -- so the result is a non-negative magnitude, and
    the caller gives it a sign.

    * `down`    -- the fraction is dropped.
    * `up`      -- any fraction takes the next whole minor unit.
    * `nearest` -- to the closer whole minor unit, and EXACTLY HALF goes up
      (half away from zero; the amount is never negative here). Decided on the
      exact remainder, in integers: `2 * remainder >= divisor`.
    """
    product = amount_minor * percent_bp
    quotient, remainder = divmod(product, BASIS_POINTS_PER_WHOLE)
    if rounding == "down":
        return quotient
    if rounding == "up":
        return quotient + (1 if remainder else 0)
    if rounding == "nearest":
        return quotient + (1 if 2 * remainder >= BASIS_POINTS_PER_WHOLE else 0)
    raise ValueError(
        f"rounding {rounding!r} is not one this applier implements "
        f"({', '.join(IMPLEMENTED_ROUNDINGS)}). It refuses rather than pricing the "
        "amount under a different mode."
    )


def was_rounded(amount_minor: int, percent_bp: int, result_minor: int) -> bool:
    """Did taking `percent_bp` of `amount_minor` round to reach `result_minor`?

    The ONE test for whether a line gets a rounding clause, and both lines that
    can carry one -- the tax line and the adjustment line -- call it. It used to
    be written out at each of them, the same comparison twice, and a gate showed
    the two were copies rather than one thing: breaking either left the other's
    tests green. Two copies of a money test are two things that drift, and the
    line they decide is the line a disputed cent is read from.

    It lives beside `percent_of_minor` because the division there is the only
    place a fraction can appear, so it is the only place a rounding can have
    happened. Compared in integers: the unrounded product against the result
    scaled back up. 20% of 35.00 is exactly 7.00 and is not rounded; 12.5% of
    9.99 is not, and is.
    """
    return amount_minor * percent_bp != result_minor * BASIS_POINTS_PER_WHOLE


def exact_text(amount_minor: int, percent_bp: int, currency: str) -> str:
    """The UNROUNDED percentage, rendered exactly, for a line a customer can check.

    `amount * percent_bp` is an integer count of ten-thousandths of a minor unit,
    so it renders exactly with four more decimal places than the currency has --
    no float, no approximation. Trailing zeros are dropped: 85.425, not 85.425000.
    """
    from .currency import minor_unit_digits

    digits = minor_unit_digits(currency) + 4
    whole, part = divmod(amount_minor * percent_bp, 10**digits)
    decimals = f"{part:0{digits}d}".rstrip("0")
    return f"{whole}.{decimals} {currency}" if decimals else f"{whole} {currency}"
