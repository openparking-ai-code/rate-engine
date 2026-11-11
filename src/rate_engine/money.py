"""Money is a Python ``int`` of minor units. Nothing else is money here.

A float, a bool or a ``Decimal`` is refused at ANY depth of a plan or a rule --
by ``refuse_non_integer_money``, whether or not the field is one this version
reads. A string is refused wherever money is expected, by ``as_minor``; strings
are of course ordinary elsewhere in a plan. A rate that cannot be expressed in
minor units is a rate this module refuses, and it refuses it at load rather than
at the point the arithmetic goes wrong.

Three traps this file exists to close, all of them things that pass a naive
``isinstance(value, int)``:

* **``bool`` is a subclass of ``int`` in Python.** ``isinstance(True, int)`` is
  ``True``, so ``True`` sails through an integer check and then prices a stay at
  one minor unit. It is rejected explicitly, first, before the int check.
* **JSON exponent form parses to a float.** ``json.loads("1e2")`` is ``100.0``,
  not ``100`` -- a plan author writing ``1e2`` for a dollar rate produces a float
  that happens to be integral. ``float`` is rejected whatever its value, so
  ``100.0`` is refused exactly as ``100.5`` is. There is no "but it is a whole
  number" branch, because that branch is how floats get in.
* **``Decimal`` looks like the safe choice and is not, here.** It is refused too.
  Not because it is inaccurate -- it is not -- but because two money types in
  one codebase means every function has to handle both, and the one that
  eventually forgets is the one that ships. One type, all the way down.

Nothing in this module rounds money, and that half of the sentence has always
been true. **There are TWO time roundings, and only one of them is stated per
rule** -- the original wording claimed only one existed and that the plan decided
it, which was false in the direction that costs money:

* **A part-minute is a whole minute.** ``engine.Stay.duration_minutes`` rounds a
  partial minute UP before any rule sees the stay. This is ASSUMED, module-wide,
  and no plan field reaches it. It is the ordinary garage convention and it is
  kept -- but it is a pricing decision, so it is stated here rather than left to
  be discovered. A stay of 09:00:00 to 09:01:00.001 is TWO minutes, and on a rule
  with one-minute periods that is twice the fee.
* **Minutes into periods is STATED PER RULE**, by ``increment.rounding``, and the
  applier refuses a mode it does not implement rather than pricing under another.

The second is what "stated per rule" was ever true of. Both happen before any
amount is touched, so no money is rounded either way.

**Where the first one is visible, and it is not only cosmetic:** a stated ceiling
is compared against the SAME rounded value the rules price on, so a stay of
24 hours and one millisecond is 1441 minutes and a 1440-minute ceiling does not
cover it -- the stay is REFUSED rather than priced. That is coherent, and it is
the behaviour the specification asks for (nothing prices it, so the owner is asked), but an
operator reading "the only rounding is time into periods" would not have predicted
it. See ``rules/increment.py`` and ``engine.Stay.duration_minutes``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .currency import minor_unit_digits


class NotMinorUnits(TypeError):
    """A value that was supposed to be money is not an integer of minor units."""


def as_minor(value: Any, label: str) -> int:
    """Return ``value`` as minor units, or refuse and say which field was wrong.

    The label is the plan's own path to the field (``rules[2].first_period_minor``),
    because a refusal that does not say where to look is a refusal the operator
    cannot act on.
    """
    if isinstance(value, bool):
        raise NotMinorUnits(
            f"{label} is a boolean ({value!r}). Money is an integer of minor units; "
            "`bool` is an `int` subclass in Python and would otherwise price this "
            "at 0 or 1 without complaint."
        )
    if isinstance(value, float):
        raise NotMinorUnits(
            f"{label} is a float ({value!r}). Money is an integer of minor units -- "
            "800 means 8.00, not 8.0. Note that JSON exponent form (1e2) parses as a "
            "float even though it looks whole."
        )
    if not isinstance(value, int):
        raise NotMinorUnits(
            f"{label} is {type(value).__name__} ({value!r}). Money is an integer of "
            "minor units. Decimal and str are refused deliberately: one money type, "
            "all the way down."
        )
    return value


def as_non_negative_minor(value: Any, label: str) -> int:
    minor = as_minor(value, label)
    if minor < 0:
        raise NotMinorUnits(f"{label} is negative ({minor}). A price is not negative.")
    return minor


def refuse_non_integer_money(node: Any, path: str = "plan", *, document_name: str) -> None:
    """Walk a loaded plan and refuse a float, a bool or a Decimal ANYWHERE in it.

    **This function used to be called `refuse_floats`, and the old name was the
    honest one: a bool hit an early `return` and a Decimal fell off the end.**
    Four published sites nevertheless said "a float, a bool or a Decimal anywhere
    in a plan is refused at load" -- docs/CONTRACT.md twice, README.md, and this
    module's own header. Measured: a bool and a Decimal were ACCEPTED at every
    one of the four `decisions[]` fields, which are the only leaves in a plan
    that no other check types.

    Every individual F4 test was true. The sentence over them was not, and the
    fix is to make the sentence true rather than to narrow it -- so the walk now
    refuses all three, and the name says which three.

    ``as_minor`` guards the fields the engine reads. This guards the fields it
    does not -- a float sitting in a rule parameter the current version ignores
    is a float that starts being read the round somebody adds the rule type that
    reads it, and by then it is in a plan an operator believes is live.

    The check is on the type, not on the value: ``3.0`` is refused. A plan is
    data an integrator wrote, and the moment this makes an exception for a float
    that happens to be whole, every float becomes one bug away from whole.

    **`document_name` is what the refusal calls the document**, and it has no
    default. A tax set is walked by this same function, and it used to be told it
    was a plan: "No float appears anywhere in a plan" sends an operator to the
    wrong document. Each loader names its own.
    """
    if isinstance(node, bool):
        raise NotMinorUnits(
            f"{path} is a boolean ({node!r}). No bool appears anywhere in a "
            f"{document_name}, at any depth. `bool` is an `int` subclass in Python, "
            "so one sitting in a "
            "field this version does not read is an integer waiting for the round "
            "that starts reading it."
        )
    if isinstance(node, float):
        raise NotMinorUnits(
            f"{path} is a float ({node!r}). No float appears anywhere in a "
            f"{document_name}, at any depth -- not in a field this version reads, "
            "and not in one it ignores."
        )
    if isinstance(node, dict):
        for key, value in node.items():
            refuse_non_integer_money(value, f"{path}.{key}", document_name=document_name)
        return
    if isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            refuse_non_integer_money(value, f"{path}[{index}]", document_name=document_name)
        return
    if isinstance(node, Decimal):
        raise NotMinorUnits(
            f"{path} is a Decimal ({node!r}). Accurate, and still refused: two money "
            "types in one codebase means every function has to handle both, and the "
            "one that eventually forgets is the one that ships. `as_minor` catches a "
            "Decimal in a field that asks for money and names the field; this catches "
            "one anywhere else and names the path."
        )
    # Anything else -- str, int, None -- is what a plan document is made of.
    # `as_minor` decides whether a given int is money when a field actually asks
    # for money. Note this is a DENY list of the three types the published
    # sentence names, not an allow-list of the types JSON can produce: an
    # allow-list would be a larger claim than the contract makes.


def format_minor(minor: int, currency: str) -> str:
    """For a breakdown line's text. Never feed the result back into arithmetic.

    **The divisor comes from the CURRENCY, not from the number 100.** This used to
    be `divmod(abs(minor), 100)` for everything, so a fee of 800 minor units in a
    zero-decimal currency was returned correctly as 800 and rendered "8.00" -- a
    correct number with an explanation a hundred times wrong, in the breakdown
    this module exists to make trustworthy. A zero-decimal currency now renders
    "800 JPY" with no decimal point at all, because a yen has no minor unit to
    show; a three-decimal one renders three places.

    Currencies are validated at load, so an unknown code cannot reach here from a
    plan. If one does, `minor_unit_digits` raises rather than falling back to 2 --
    a guessed exponent is the defect, not the mitigation.
    """
    digits = minor_unit_digits(currency)
    sign = "-" if minor < 0 else ""
    if digits == 0:
        return f"{sign}{abs(minor)} {currency}"
    divisor = 10**digits
    whole, part = divmod(abs(minor), divisor)
    return f"{sign}{whole}.{part:0{digits}d} {currency}"
