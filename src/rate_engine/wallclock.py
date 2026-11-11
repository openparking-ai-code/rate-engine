"""Wall-clock limits and the granularity they are compared at. ONE place.

**The defect this closes.** `time_window` -- then called `early_bird` -- compared
`entry_local.time()` against an `enter_by` of `09:00` at full `datetime.time`
precision, so an entry at `09:00:00.001` failed -- and the breakdown, which
renders both sides with `%H:%M`, said *"entry 09:00 is after the 09:00 entry
limit"*. A sentence that contradicts itself on its face, deciding an $18
difference on a microsecond nobody can see.
The specification's first requirement is that this module is EXTREMELY CLEAR; that line is the
worst available failure of it.

**The fix is granularity, not more digits.** "In by nine" means the minute 09:00,
to an operator and to a customer, and a limit written `HH:MM` cannot express
anything finer. So the STAY is truncated to the minute before it is compared, and
the rendered sentence becomes true rather than merely better-punctuated.

**AND THE LIMIT IS NOT TRUNCATED -- IT IS REFUSED.** The first version of this fix
truncated both sides. That is wrong, and it is wrong in this module's most
expensive direction: `time.fromisoformat` accepts `09:00:30`, a plan can state it
TODAY, and it decides the fee. Truncating the limit would silently discard a
pricing decision an operator wrote -- the engine overriding the plan, which is the
exact defect the early-bird day-span condition is being fixed for. A limit finer
than the minute is refused at load, naming the field, like every other thing this
module cannot honour.

**What is NOT a wall-clock comparison, and must never adopt this.**
`select_plan` compares `plan.effective_from <= stay.entry_at`: two absolute
INSTANTS, not times of day. Truncating there would change which plan version is in
force at a boundary -- a different rate card, not a rounder sentence. The date
comparisons in `time_window` and `daily_max.days_covered` are likewise unaffected:
truncating seconds cannot move a calendar date.
"""

from __future__ import annotations

from datetime import datetime, time

#: Day names a plan may state, in week order. **The index IS the weekday index
#: `datetime.weekday()` returns**, which is what lets a stated day become a real
#: date and back again without a second table.
#:
#: It lives here rather than on a rule type because three unrelated things read
#: it -- `time_window` matches a stay's day against it, `weekly_max` turns a
#: stated first-day-of-the-week into an offset, and `validator` turns a stated
#: day back into a probe date. It began on `time_window` and `weekly_max` had to
#: import it from there, which coupled a CAP rule to a QUALIFY rule's module for
#: no reason except where the constant happened to be typed first.
DAYS_OF_WEEK: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_limit(raw: dict, key: str, where: str) -> time:
    """A plan's `HH:MM` wall-clock limit, or a refusal naming the field.

    Refuses an offset (it would fight the plan's own zone across a DST
    transition) and refuses anything finer than a minute (it cannot be rendered,
    and a limit whose decisive digits are invisible in the breakdown is the
    defect this module exists to prevent).
    """
    from .plan import InvalidPlan

    value = raw[key]
    if not isinstance(value, str):
        raise InvalidPlan(f"{where}.{key} must be a 'HH:MM' local time string.")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise InvalidPlan(f"{where}.{key} is not a 'HH:MM' time: {value!r} ({exc}).") from exc
    if parsed.tzinfo is not None:
        raise InvalidPlan(
            f"{where}.{key} must not carry an offset. It is a wall-clock time read in "
            "the plan's own timezone; an offset here would fight the plan's zone across "
            "a DST transition."
        )
    if parsed.second or parsed.microsecond:
        raise InvalidPlan(
            f"{where}.{key} is {value!r}, which states seconds. A wall-clock limit is "
            "'HH:MM': the breakdown renders it to the minute, so a finer limit would "
            "decide the fee on digits the explanation cannot show. Refused rather than "
            "rounded, because rounding it would silently discard a limit you wrote."
        )
    return parsed


def local_minute(instant: datetime, timezone) -> datetime:
    """The stay's local wall clock, truncated to the minute it falls in.

    Truncation, never rounding: 09:00:59 is in the minute 09:00, and a customer
    who arrived during the 09:00 minute arrived at nine. Applied to the STAY only
    -- see this module's header for why the limit is refused instead.
    """
    return instant.astimezone(timezone).replace(second=0, microsecond=0)
