"""`weekly_max` -- a cap on the week, and `daily_max`'s shape one unit up.

The specification names it in the owner's list of rate types, beside the daily maximum. It is
the same mechanism: a ceiling on the running total, expressed in the ledger as a
NEGATIVE line saying how much it took off, so the fee stays equal to the sum of
its lines and the operator sees the size of the reduction rather than a bare
"cap applied".

**`week_boundary` is required with no default, for exactly `daily_max`'s
reason.** "Weekly max 100" does not say what a week is, and the two honest
answers price a Saturday-to-Tuesday stay differently:

* `calendar_week` -- the cap is per local week the stay touches, and the week
  starts on the day the plan names. There is no universal answer to which day
  that is: it is Monday in most of Europe, Sunday in the United States, and
  Saturday in parts of the Middle East. The engine will not pick.
* `rolling_7d` -- the cap is per seven days from ENTRY. The starting day is
  irrelevant, so `week_starts_on` is `null` and the null has to be TYPED.

**`week_starts_on` is required in BOTH cases**, the way `max_duration_minutes`
is: null is a statement, and a field that may be absent is a field somebody can
forget while believing they set it.

**TWO caps on one plan are not a conflict.** They compose, and the lower ceiling
wins -- which falls out of applying them in sequence rather than being arranged,
and is why CAP is a composing stage rather than a resolving one. See stages.py:
`find_conflicts` used to refuse whenever more than one rule qualified anywhere,
so this rule type's arrival would have made every plan carrying a daily AND a
weekly cap refuse every stay in the garage.

**Each week is capped on its own, after the daily max for each of its days.**
The week follows the daily max's calendar logic (F59): the stay is cut at its
week boundaries -- a `calendar_week` at local midnight on the day the plan
names, a `rolling_7d` every seven days from entry, both as before -- and each
week pays what the time in it was charged, with each of its days capped by the
plan's daily max, or the weekly max where that is less. Seven days and an hour
at $8 then $4 an hour, $30 a day and $100 a week, is $100 for the first week
and $4 for the hour. This reads the daily caps' terms from the plan, never their
lines, and works from the base rather than the running total, so the two caps
still compose in either order. And like a day, a week the car is in for no time
is not a week it touched: an exit at exactly the start of a week adds no cap.

A type that does not say how its charge builds up is one price with nothing to
split by the week, so it is capped as before: each week is allowed the weekly
max, or the daily max times the days the car is in that week where that is
lower. A flat special is one: one price for the stay it covers (F63).

**A long stay is priced in the memory of a short one (F61).** The weeks are found
as they are walked, each week's days are found from the week's own start rather
than from a list of every day of the stay, and each week's ceiling goes into
`daily_max.Amounts`, a running tally. The work grows with the days in the stay;
the memory does not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import CAP
from ..wallclock import DAYS_OF_WEEK
from . import TOLD_THE_BASE, Rule, common_fields, daily_max, register

WEEK_BOUNDARIES: tuple[str, ...] = ("calendar_week", "rolling_7d")

#: Which boundary requires a starting day, and which requires it to be null.
#: A table rather than two `if`s, so the refusal messages below cannot disagree
#: with what the builder actually accepts.
NEEDS_A_STARTING_DAY: dict[str, bool] = {"calendar_week": True, "rolling_7d": False}

DAYS_IN_A_WEEK = 7

EXTRA = {"max_minor", "week_boundary", "week_starts_on"}


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    boundary = raw["week_boundary"]
    if boundary not in WEEK_BOUNDARIES:
        raise InvalidPlan(
            f"{where}.week_boundary is {boundary!r}; expected one of "
            f"{', '.join(WEEK_BOUNDARIES)}. There is no default: a cap of 100 a week "
            "prices a Saturday-to-Tuesday stay at 100 or at 200 depending on the "
            "answer, and that is the owner's decision."
        )

    starts_on = raw["week_starts_on"]
    if NEEDS_A_STARTING_DAY[boundary]:
        if starts_on not in DAYS_OF_WEEK:
            raise InvalidPlan(
                f"{where}.week_starts_on is {starts_on!r}; a 'calendar_week' cap needs "
                f"a day name from {', '.join(DAYS_OF_WEEK)}. There is no universal "
                "first day of the week -- it is Monday in most of Europe, Sunday in "
                "the United States, and Saturday in parts of the Middle East -- so the "
                "plan says which, and the engine does not pick."
            )
    elif starts_on is not None:
        raise InvalidPlan(
            f"{where}.week_starts_on is {starts_on!r}, but this rule states "
            "'rolling_7d', where a week runs from the stay's own entry and no starting "
            "day applies. Write null: a value that cannot affect the fee would read as "
            "a decision somebody made and the engine ignored."
        )

    return Rule(
        id=rule_id, type="weekly_max", stage=CAP, space_classes=space_classes,
        params={
            "max_minor": as_non_negative_minor(raw["max_minor"], f"{where}.max_minor"),
            "week_boundary": boundary,
            "week_starts_on": starts_on,
        },
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class)


def _week_start(day: date, starts_on: str) -> date:
    """The first day of the local week `day` falls in, for a plan's chosen start."""
    offset = (day.weekday() - DAYS_OF_WEEK.index(starts_on)) % DAYS_IN_A_WEEK
    return day - timedelta(days=offset)


def weeks_of(rule: Rule, stay, plan):
    """The stay cut at this cap's week boundaries: one (start, end) for each week
    the car is in for more than zero time, in order, found as they are asked for
    and never listed. A stay of zero length is in one week, as it is in one day.

    The calendar boundaries are local midnights at the start of each week, so a
    week containing a daylight-saving transition is one week rather than 0.99 of
    one -- `daily_max.days_covered`'s reasoning one unit up.
    """
    entry = stay.entry_at.astimezone(UTC)
    exit_at = stay.exit_at.astimezone(UTC)
    if stay.duration_minutes == 0:
        yield entry, exit_at
        return

    cut = entry
    if rule.params["week_boundary"] == "rolling_7d":
        weeks = -(-stay.duration_minutes // (DAYS_IN_A_WEEK * 24 * 60))  # ceil, integer only
        for k in range(1, weeks):
            start = entry + timedelta(days=DAYS_IN_A_WEEK * k)
            yield cut, start
            cut = start
    else:
        local_entry = stay.entry_at.astimezone(plan.timezone).date()
        week = _week_start(local_entry, rule.params["week_starts_on"])
        while True:
            week += timedelta(days=DAYS_IN_A_WEEK)
            # fold=0 is the first instant of the date, even when midnight itself
            # falls in a transition.
            boundary = datetime.combine(week, time(0), tzinfo=plan.timezone)
            boundary = boundary.astimezone(UTC)
            if boundary >= exit_at:
                break
            yield cut, boundary
            cut = boundary
    yield cut, exit_at


def weeks_covered(rule: Rule, stay, plan) -> int:
    """How many caps this stay is allowed. Never zero -- any stay touches one week."""
    return sum(1 for _ in weeks_of(rule, stay, plan))


def week_ceilings(rule: Rule, stay, plan, charged_by):
    """The most each week of the stay costs, in order, one week at a time.

    Split by the week (`charged_by` given): what the time in that week was
    charged, each of its days capped by every daily cap covering the stay, and
    no more than the weekly max. One price for the whole stay (`charged_by` is
    None): the weekly max, or the daily max times the days the car is in that
    week where the plan caps the day too and that is lower.

    Each week's days are found from the week's own start (`daily_max.pieces`),
    so no list of the stay's days is kept and no week walks the days before it.
    """
    day_rules = [
        r for r in plan.rules_for_stage(CAP)
        if r.type == "daily_max" and daily_max.qualifies(r, stay, plan)
    ]
    for start, end in weeks_of(rule, stay, plan):
        if charged_by is None:
            ceiling = rule.params["max_minor"]
            for day_rule in day_rules:
                count = sum(1 for _ in daily_max.pieces(day_rule, stay, plan, start, end))
                ceiling = min(ceiling, day_rule.params["max_minor"] * count)
        else:
            charged = daily_max.charge_in(stay, charged_by, start, end)
            for day_rule in day_rules:
                by_day = daily_max.capped_days(day_rule, stay, plan, charged_by, start, end)
                charged = min(charged, sum(by_day))
            ceiling = min(rule.params["max_minor"], charged)
        yield ceiling


def apply(rule: Rule, stay, plan, running_total_minor: int, *, charged_by) -> list[Line]:
    """Take the excess off, or say the cap was not reached.

    Shown the running total, like every CAP rule, and like every rule it can only
    return a Line -- it cannot set the total. The ceiling is worked out from the
    BASE (`charged_by`), with the daily caps' terms read from the plan, so when a
    daily cap has already run the total this sees is at or above that ceiling
    and is taken down to it, and when this runs first the daily cap then finds
    itself reached: the LOWER standing whichever order they ran in. `charged_by`
    has no default, for `daily_max.apply`'s reason.
    """
    # Tallied week by week, never listed: a long stay in a short one's memory.
    weeks = daily_max.Amounts(week_ceilings(rule, stay, plan, charged_by))
    caps = weeks.count
    ceiling = weeks.total
    currency = plan.currency
    span = f"{caps} weeks" if caps != 1 else "the week"
    by_days = ""
    if weeks.smallest < rule.params["max_minor"]:
        if charged_by is None:
            why = "a week costs no more than the daily max for the days the car is in it"
        elif any(
            r.type == "daily_max" and daily_max.qualifies(r, stay, plan)
            for r in plan.rules_for_stage(CAP)
        ):
            why = "each week is capped on its own, after the daily max for each of its days"
        else:
            why = "each week is capped on its own"
        by_days = f" ({daily_max.amounts_text(weeks, currency)}: {why})"

    if running_total_minor <= ceiling:
        return [
            Line(
                code="weekly_max.not_reached",
                rule_id=rule.id,
                text=(
                    f"Weekly max {format_minor(rule.params['max_minor'], currency)} "
                    f"({rule.params['week_boundary']}, {span}) not reached: the charge "
                    f"so far is {format_minor(running_total_minor, currency)}"
                ),
                delta_minor=0,
            )
        ]
    return [
        Line(
            code="weekly_max.applied",
            rule_id=rule.id,
            text=(
                f"Weekly max {format_minor(rule.params['max_minor'], currency)} "
                f"({rule.params['week_boundary']}) applied over {span}: "
                f"{format_minor(running_total_minor, currency)} reduced to "
                f"{format_minor(ceiling, currency)}{by_days}"
            ),
            delta_minor=ceiling - running_total_minor,
        )
    ]


register("weekly_max", CAP, build, apply, traits=(TOLD_THE_BASE,))
