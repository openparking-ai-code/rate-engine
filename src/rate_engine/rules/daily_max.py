"""`daily_max` -- a cap, and the rule that forced the timezone model to be real.

A cap is not additive: it replaces a bigger number with a smaller one. In the
ledger it is a NEGATIVE line saying how much it took off, which both keeps the
fee equal to the sum of its lines and shows the operator the size of the
discount -- the number a plain "daily max applied" would have hidden.

**`day_boundary` is required, with no default, and it is the interesting field.**
"Daily max 30" does not say what a day is, and the two honest answers price a
two-day stay differently:

* `calendar_day` -- a day is a local calendar date. A stay from Friday 22:00 to
  Saturday 02:00 is in two of them. Across a DST transition a calendar day is 23
  or 25 hours, and that is correct: a day is what the local clock says it is.
* `rolling_24h` -- a day is 24 hours from ENTRY. The same stay is four hours long
  and is in one. DST does not move it, because 24 hours is 24 hours whatever the
  clock did.

The specification raises exactly this ("what happens at midnight on a two-day stay") as one of
the things a rate sign does not tell you. So the engine does not decide it. A
plan that does not state `day_boundary` does not load.

**Each day is capped on its own (F59).** Decided 2026-10-16: the daily max is
per calendar day -- split the stay at the garage's local midnight and cap each
day by itself. The stay is cut at the start of each of its days, the charge for
the time is split by the day it was charged in, and each day pays at most the
max. Monday 09:00 to Tuesday 00:15 at $8 the first hour and $4 an hour after,
$30 a day: Monday's fifteen hours are $64 and pay $30, Tuesday's fifteen minutes
are the stay's sixteenth hour and pay $4. $34, where a cap of $30 times the days
touched allowed $60. A rolling day is cut at each 24 hours from entry and capped
the same way.

How the charge is split is the base's to say, not this file's: the engine hands
a cap `charged_by` (the `told_the_base` trait), what the base charges for the
stay's first so many minutes. A time-based rate charges a period on the day the
period starts, and does not start again at midnight. A type that does not
say how its charge builds up -- `charged_by` None -- is capped as one price for
the stay, at the max times the days the car is in: the cap cannot know where
its charge fell. A flat special is one: one price for the stay it covers, never
split by the day (F63, decided 2026-10-17). A $50 flat is held to $30 on a
Saturday alone and stands over Friday to Sunday, where the three days allow
$90; the engine then charges the cheaper of it and the time-based rate's whole
stay.

**A day the car is in for no time is not a day it touched.** An exit at exactly
local midnight ends on the date before, so Monday 09:00 to Tuesday 00:00 is one
calendar day, not two. A rolling window already counted that way: a stay of
exactly 24 hours is one window.

**A long stay is priced in the memory of a short one (F61).** Each day is capped
on its own, so a cap walks the stay a day at a time and its work grows with the
days in the stay. Its memory does not. The days are found as they are walked and
never listed, each day's amount goes into a running tally (`Amounts`) rather
than a list, and the cap's line spells out at most `RUNS_SPELLED_OUT` runs of
equal amounts, then says how many more there were and what they came to. As
first written this listed every day of the stay, once for each daily cap and
again inside the weekly cap, so a quote's memory grew with the stay as well as
its time. The engine refuses a stay longer than 90 days before a cap is asked
(F62), so no cap walks more than 90 days. A quote still caps the stay once for
each way of pricing it (F63, F64).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from ..breakdown import Line
from ..money import as_non_negative_minor, format_minor
from ..stages import CAP
from . import TOLD_THE_BASE, Rule, common_fields, register

DAY_BOUNDARIES: tuple[str, ...] = ("calendar_day", "rolling_24h")

EXTRA = {"max_minor", "day_boundary"}

ONE_DAY = timedelta(days=1)

#: How many runs of equal amounts a cap's line spells out, in order, before it
#: says how many more amounts there were and what they came to. An ordinary stay
#: has a handful -- "3 x 30.00 USD + 4.00 USD" is two -- and no stay's line grows
#: past this however long the stay is (F61).
RUNS_SPELLED_OUT = 20


def build(raw: dict, plan_space_classes: tuple[str, ...], where: str) -> Rule:
    from ..plan import InvalidPlan

    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)
    boundary = raw["day_boundary"]
    if boundary not in DAY_BOUNDARIES:
        raise InvalidPlan(
            f"{where}.day_boundary is {boundary!r}; expected one of "
            f"{', '.join(DAY_BOUNDARIES)}. There is no default: a cap of 30 a day "
            "prices a Friday-night-to-Saturday-morning stay at 30 or at 60 depending "
            "on the answer, and that is the owner's decision."
        )
    params = {
        "max_minor": as_non_negative_minor(raw["max_minor"], f"{where}.max_minor"),
        "day_boundary": boundary,
    }
    return Rule(
        id=rule_id, type="daily_max", stage=CAP, space_classes=space_classes, params=params
    )


def qualifies(rule: Rule, stay, plan) -> bool:
    return rule.covers(stay.space_class)


def _day_starts(rule: Rule, stay, plan, first: int = 1):
    """The start of the stay's day `first` and of every day after it, in order,
    without end. Day 0 is the entry's own and starts at entry, so `first` is 1
    or more.

    A calendar day starts at local midnight: fold=0 is the first instant of the
    date, even when midnight itself falls in a transition, so a 23- or 25-hour
    day is one day rather than 0.96 or 1.04 of one. A rolling day starts every
    24 hours from entry.
    """
    if rule.params["day_boundary"] == "rolling_24h":
        start = stay.entry_at.astimezone(UTC) + ONE_DAY * (first - 1)
        while True:
            start += ONE_DAY
            yield start
    day = stay.entry_at.astimezone(plan.timezone).date() + ONE_DAY * (first - 1)
    while True:
        day += ONE_DAY
        yield datetime.combine(day, time(0), tzinfo=plan.timezone).astimezone(UTC)


def _start_of_day(rule: Rule, stay, plan, index: int) -> datetime:
    """Where the stay's day `index` starts: entry for day 0, `_day_starts` after."""
    if index == 0:
        return stay.entry_at.astimezone(UTC)
    return next(_day_starts(rule, stay, plan, index))


def _day_holding(rule: Rule, stay, plan, instant: datetime) -> int:
    """Which of the stay's days `instant` falls in, counted from 0 at entry: the
    day that starts at or before it and ends after it.

    Found from the date (or the time since entry, for a rolling day) rather
    than by walking from entry, so asking about a day late in a long stay costs
    what asking about the first does. The guess is then checked against the
    starts `_day_starts` gives, both ways, so the day found is the day `days_of`
    cuts even where the date misleads: a date a zone lived twice puts an instant
    in the day before its own, and a clock that skips over midnight dates an
    instant to a day that has not started.
    """
    entry = stay.entry_at.astimezone(UTC)
    if instant <= entry:
        return 0
    if rule.params["day_boundary"] == "rolling_24h":
        index = (instant - entry) // ONE_DAY
    else:
        entry_date = stay.entry_at.astimezone(plan.timezone).date()
        index = max(0, (instant.astimezone(plan.timezone).date() - entry_date).days)
    while index > 0 and _start_of_day(rule, stay, plan, index) > instant:
        index -= 1
    while _start_of_day(rule, stay, plan, index + 1) <= instant:
        index += 1
    return index


def days_of(rule: Rule, stay, plan, after: datetime | None = None):
    """The stay cut at this cap's day boundaries: one (start, end) for each day
    the car is in for more than zero time, in order, as UTC instants -- from the
    entry, or from the day holding `after` when it is given. A stay of zero
    length is in one day.

    The days are found as they are asked for and never listed, so walking a long
    stay takes the memory of one day (F61).

    THE one place a day is found. The cap's own count, the days it caps one by
    one, and the days `weekly_max` reads inside each week all come from here, so
    they cannot disagree about where a day starts.
    """
    entry = stay.entry_at.astimezone(UTC)
    exit_at = stay.exit_at.astimezone(UTC)
    first = 0 if after is None else _day_holding(rule, stay, plan, after)
    cut = _start_of_day(rule, stay, plan, first)
    if exit_at > entry:
        for start in _day_starts(rule, stay, plan, first + 1):
            if start >= exit_at:
                break
            yield cut, start
            cut = start
    yield cut, exit_at


def days_covered(rule: Rule, stay, plan) -> int:
    """How many days the stay is in. Never zero -- any stay touches one day."""
    return sum(1 for _ in days_of(rule, stay, plan))


def pieces(rule: Rule, stay, plan, start: datetime, end: datetime):
    """This cap's days cut down to the part of the stay from `start` to `end`, in
    order, as they are found.

    One (start, end) for each day the car is in for more than zero time inside
    that part. `weekly_max` asks this of each week a stay is cut into: a
    calendar day sits inside a calendar week, and a rolling day that runs past a
    week's end is split there, so each week holds only its own part of it. A
    stay of zero length is one piece, as it is one day.

    The walk starts at the day holding `start`, so a week late in a long stay is
    cut into its days without walking the days before it.
    """
    if end <= start:
        yield start, end
        return
    for day_start, day_end in days_of(rule, stay, plan, after=start):
        if not (day_start < end and day_end > start):
            break
        yield max(day_start, start), min(day_end, end)


def _minutes_into(stay, instant: datetime) -> int:
    """How many minutes of the stay have passed at `instant`, counted the way the
    stay's own length is: a part-minute is a whole minute. The stay's own
    `duration_minutes` arithmetic, asked of the stay as if it ended there."""
    return stay.minutes_until(instant)


def charge_in(stay, charged_by, start: datetime, end: datetime) -> int:
    """What the base charged for the part of the stay from `start` to `end`.

    What it charges for a stay ending at `end`, less what it charges for one
    ending at `start` -- nothing, when `start` is the entry: the first period is
    owed from the first instant, which is why a stay of zero length pays it (F24).
    The parts of a stay therefore add up to its charge exactly.
    """
    before = 0 if start == stay.entry_at else charged_by(_minutes_into(stay, start))
    return charged_by(_minutes_into(stay, end)) - before


def each_capped_day(rule: Rule, stay, plan, charged_by, start=None, end=None):
    """What each of this cap's days pays, from `start` to `end` (the whole stay
    by default), one at a time: the charge in that day, or the max where the
    charge is more."""
    start = stay.entry_at.astimezone(UTC) if start is None else start
    end = stay.exit_at.astimezone(UTC) if end is None else end
    most = rule.params["max_minor"]
    for day_start, day_end in pieces(rule, stay, plan, start, end):
        yield min(most, charge_in(stay, charged_by, day_start, day_end))


def capped_days(rule: Rule, stay, plan, charged_by, start=None, end=None) -> list[int]:
    """`each_capped_day` as a list. For a part of a stay -- a week holds at most
    eight pieces of days -- or a test; the cap tallies a whole stay instead."""
    return list(each_capped_day(rule, stay, plan, charged_by, start, end))


class Amounts:
    """What a cap's days or weeks paid, tallied one at a time and not kept.

    Pricing needs only the count, the sum and the smallest. The line needs the
    amounts in order, a run of equal ones said once, and only the first
    `RUNS_SPELLED_OUT` runs are kept for it; after them the tally counts how
    many more amounts there were and what they came to. So a long stay is
    priced, and its line written, in the memory of a short one (F61).
    """

    def __init__(self, amounts=()):
        self.count = 0
        self.total = 0
        self.smallest: int | None = None
        self.runs: list[list[int]] = []
        self.more = 0
        self.more_total = 0
        for amount in amounts:
            self.add(amount)

    def add(self, amount: int) -> None:
        self.count += 1
        self.total += amount
        if self.smallest is None or amount < self.smallest:
            self.smallest = amount
        if not self.more and self.runs and self.runs[-1][0] == amount:
            self.runs[-1][1] += 1
        elif not self.more and len(self.runs) < RUNS_SPELLED_OUT:
            self.runs.append([amount, 1])
        else:
            self.more += 1
            self.more_total += amount


def amounts_text(amounts: Amounts, currency: str) -> str:
    """'3 x 30.00 USD + 4.00 USD': the amounts in order, a run of equal ones said
    once. Past `RUNS_SPELLED_OUT` runs, how many more there were and what they
    came to: '... + 1200 more coming to 34500.00 USD'."""
    text = " + ".join(
        format_minor(amount, currency) if count == 1
        else f"{count} x {format_minor(amount, currency)}"
        for amount, count in amounts.runs
    )
    if amounts.more:
        text += f" + {amounts.more} more coming to {format_minor(amounts.more_total, currency)}"
    return text


def apply(rule: Rule, stay, plan, running_total_minor: int, *, charged_by) -> list[Line]:
    """Take the excess off, or say the cap was not reached.

    This is one of the rule types shown the running total, because a cap is
    defined in terms of it. It still cannot SET the total -- it returns a line
    like everything else, and the engine adds it. The read is one-way.

    The most the stay may cost is worked out from the BASE (`charged_by`), never
    from the running total, so a second cap that ran first cannot change it: the
    caps leave the lowest ceiling standing in either order (F33). `charged_by`
    has no default. A cap applied without being told how the time was charged is
    a wiring fault, and a default would hide it by capping the stay some other
    way.
    """
    caps = days_covered(rule, stay, plan)
    most = rule.params["max_minor"]
    currency = plan.currency
    calendar = rule.params["day_boundary"] == "calendar_day"
    if charged_by is None:
        # One price for the whole stay: no day it can be split by.
        amounts = None
        ceiling = most * caps
    else:
        # Tallied day by day, never listed: a long stay in a short one's memory.
        amounts = Amounts(each_capped_day(rule, stay, plan, charged_by))
        ceiling = amounts.total
    span = f"{caps} days" if caps != 1 else ("the day" if calendar else "24 hours")

    if running_total_minor <= ceiling:
        return [
            Line(
                code="daily_max.not_reached",
                rule_id=rule.id,
                text=(
                    f"Daily max {format_minor(most, currency)} "
                    f"({rule.params['day_boundary']}, {span}) not reached: the charge so "
                    f"far is {format_minor(running_total_minor, currency)}"
                ),
                delta_minor=0,
            )
        ]
    by_day = ""
    if amounts is not None and caps > 1 and amounts.smallest < most:
        unit = "day" if calendar else "24-hour window"
        by_day = f" ({amounts_text(amounts, currency)}: each {unit} is capped on its own)"
    return [
        Line(
            code="daily_max.applied",
            rule_id=rule.id,
            text=(
                f"Daily max {format_minor(most, currency)} "
                f"({rule.params['day_boundary']}) applied over {span}: "
                f"{format_minor(running_total_minor, currency)} reduced to "
                f"{format_minor(ceiling, currency)}{by_day}"
            ),
            delta_minor=ceiling - running_total_minor,
        )
    ]


register("daily_max", CAP, build, apply, traits=(TOLD_THE_BASE,))
