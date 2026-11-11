"""F61 -- a long stay is priced in the memory of a short one, and its work grows
by a step a day.

Capping each day on its own (F59) makes a cap walk the stay a day at a time. As
first written it also LISTED every day of the stay -- once for each daily cap
and again inside the weekly cap -- and the base remembered every minute a cap
asked it about. So the memory a quote took grew with the length of the stay as
well as its time: with a daily and a weekly cap, a one-year stay peaked at about
84 KB and a twenty-year stay at about 1.9 MB.

What this file pins:

* **Memory.** The days and weeks are found as they are walked and never listed,
  each day's or week's amount goes into a running tally, and the base remembers
  only its last few answers. Twenty years peak within a fixed allowance of one
  year, measured by `tracemalloc`, with a daily and a weekly cap, calendar and
  rolling -- an allowance a list holding eight bytes a day would pass.
* **Work.** It still grows with the stay, by a step a day. Ten years ask the
  base, and find day starts, ten times as often as one year, and a century
  does no more per day than a year: each week's days are found from the week's
  own start, so no week walks the days before it. Counted, not timed, so the
  pin is the same on every machine.
* **The jump.** The day holding a week's start is found from its date and then
  checked against the day starts themselves, and it is the day a walk from
  entry finds -- across clock changes, a date a zone skipped (Apia, 2011) and a
  date a zone lived twice (Juneau, 1867) -- and, in a made-up zone, a clock
  that skips over midnight.
* **The line.** A cap's line spells out at most `RUNS_SPELLED_OUT` runs of equal
  amounts, then says how many more there were and what they came to, and the
  runs and the rest add up to the figure on the line.
* **The fee.** A century's stay prices exactly as it did before this change.

**The engine now refuses a stay longer than 90 days (F62)**, before any of this
work is done. This file LIFTS that limit, for its own tests only, and measures
the caps on stays far past it: the properties below hold for the caps whatever
the limit is set to, and the limit is not what keeps them true. F62 measures
the limit.

`scripts/fail_controls.py` puts back each part of the cost -- every minute the
base was asked about remembered, the days of the stay listed, each week's days
walked from entry, the date's guess at a day left unchecked, every run spelled
out -- and requires this file to go red each time.
"""

from __future__ import annotations

import copy
import re
import tracemalloc
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, tzinfo
from types import SimpleNamespace

import pytest

from rate_engine import engine
from rate_engine.contract import run_quote
from rate_engine.engine import make_stay
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import RULE_ACCRUALS, daily_max, weekly_max
from rate_engine.rules.daily_max import RUNS_SPELLED_OUT

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}

#: A daily and a weekly cap of each kind: the plan's own calendar, or rolling
#: windows from entry.
CAPS = {
    "calendar": [
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000, "day_boundary": "calendar_day"},
        {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 10000,
         "week_boundary": "calendar_week", "week_starts_on": "mon"},
    ],
    "rolling": [
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000, "day_boundary": "rolling_24h"},
        {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 10000,
         "week_boundary": "rolling_7d", "week_starts_on": None},
    ],
}


@pytest.fixture(autouse=True, scope="module")
def _the_engines_limit_lifted():
    """The caps measured on stays past the engine's 90-day limit (F62): lifted
    to about 2,700 years for this module, and put back after it."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine, "MAX_STAY_DAYS", 1_000_000)
        yield


def _plan(*rules: dict) -> dict:
    return {
        "plan_version": "long-stay-2026-10",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [copy.deepcopy(r) for r in rules],
        "decisions": [],
    }


# 2026-04-06 is a Monday. Every stay below leaves at the same wall-clock time
# some whole number of years later.
ENTRY = "2026-04-06T09:00:00-04:00"


def _exit(years: int) -> str:
    return f"{2026 + years}-04-06T09:00:00-04:00"


def _days(years: int) -> int:
    return (parse_instant(_exit(years), "exit") - parse_instant(ENTRY, "entry")).days


def _quote(plan: dict, years: int) -> dict:
    status, body = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": ENTRY, "exit_at": _exit(years),
         "space_class": "standard", "currency": "USD"}
    )
    assert status == 200, body
    return body


def _line(body: dict, rule_id: str) -> dict:
    return next(ln for ln in body["breakdown"] if ln["rule_id"] == rule_id)


#: The most a cap pair may ask the base, and the most day starts it may find,
#: for each day of the stay. Measured on this tree: 4.3 asks and 3.6 starts a
#: day, the same at one year, ten and a hundred.
BUDGET_PER_DAY = {"asked": 5, "starts": 4}


# --- memory -------------------------------------------------------------------

#: How much more a twenty-year stay may allocate at its peak than a one-year
#: stay. Measured on this tree: 13 to 19 KB at every length from one year to
#: fifty, on 3.11 and 3.12. As first written, twenty years held about 1.9 MB
#: more. A list holding one pointer a day of a twenty-year stay is 58 KB, and
#: fails this; one pointer a WEEK is 8 KB, and passes it -- the pin catches
#: anything that keeps five bytes or more for each day of the stay.
ALLOWANCE_BYTES = 32 * 1024


def _peak(plan: dict, years: int) -> int:
    """The most a quote of this stay had allocated at once, in bytes. Inside the
    work budget, so a walk gone quadratic stops here in a moment too."""
    days = _days(years)
    with _counted(BUDGET_PER_DAY, days):
        _quote(plan, years)  # zone data and imports settle outside the measurement
    with _counted(BUDGET_PER_DAY, days):
        tracemalloc.start()
        try:
            _quote(plan, years)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    return peak


@pytest.mark.guarantee("F61")
@pytest.mark.parametrize("kind", sorted(CAPS))
def test_twenty_years_are_priced_in_the_memory_of_one(kind):
    plan = _plan(HOURLY, *CAPS[kind])
    one, twenty = _peak(plan, 1), _peak(plan, 20)
    assert twenty - one < ALLOWANCE_BYTES, (
        f"{kind}: a twenty-year stay peaked at {twenty} bytes and a one-year stay at {one}. "
        "The memory of a quote grows with the stay again: the days are being listed, "
        "or the base is remembering every minute it was asked about."
    )


# --- work -----------------------------------------------------------------------


@contextmanager
def _counted(budget_per_day: dict[str, int] | None = None, days: int = 0):
    """Count, for the quotes inside, the times the caps asked the base what it
    charged and the day starts found. With a budget, stop the quote as soon as
    either count passes its budget for that many days, so a walk that has gone
    quadratic fails in a moment instead of running for minutes."""
    counts = {"asked": 0, "starts": 0}
    limits = (
        {name: per_day * days + 64 for name, per_day in budget_per_day.items()}
        if budget_per_day else {}
    )

    def tick(name: str) -> None:
        counts[name] += 1
        if name in limits and counts[name] > limits[name]:
            raise AssertionError(
                f"{name} passed {limits[name]} for {days} days "
                f"({budget_per_day[name]} a day): the work no longer grows by a step a day"
            )

    accrual = RULE_ACCRUALS["increment"]
    starts = daily_max._day_starts

    def counted_accrual(rule, stay, plan):
        by = accrual(rule, stay, plan)

        def counted(minutes: int) -> int:
            tick("asked")
            return by(minutes)

        return counted

    def counted_starts(*args, **kwargs):
        for start in starts(*args, **kwargs):
            tick("starts")
            yield start

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(RULE_ACCRUALS, "increment", counted_accrual)
        patch.setattr(daily_max, "_day_starts", counted_starts)
        yield counts


@pytest.mark.guarantee("F61")
@pytest.mark.parametrize("kind", sorted(CAPS))
def test_the_work_grows_by_a_step_a_day(kind):
    """Ten years are 3,653 days and one year 365: ten times the days, and ten
    times the asks of the base and the day starts found -- not a hundred."""
    plan = _plan(HOURLY, *CAPS[kind])
    with _counted(BUDGET_PER_DAY, _days(1)) as one:
        _quote(plan, 1)
    with _counted(BUDGET_PER_DAY, _days(10)) as ten:
        _quote(plan, 10)
    days = _days(10) / _days(1)
    for name in ("asked", "starts"):
        ratio = ten[name] / one[name]
        assert days * 0.9 <= ratio <= days * 1.1, (
            f"{kind}: {name} {one[name]} for a year and {ten[name]} for ten years, "
            f"{ratio:.1f} times for {days:.1f} times the days"
        )




@pytest.mark.guarantee("F61")
@pytest.mark.parametrize("kind", sorted(CAPS))
def test_a_centurys_stay_prices_as_before_within_a_budget_a_day(kind):
    """A hundred years from Monday 2026-04-06 09:00 is 36,524 days. Every day the
    car is in is at least 23 hours at $4 an hour after the first, so each day
    pays the $30 max and each full week the $100 one: 521,800.00, the figure the
    caps gave before this change. And no more work a day than a year takes."""
    plan = _plan(HOURLY, *CAPS[kind])
    days = _days(100)
    assert days == 36524
    with _counted(BUDGET_PER_DAY, days) as counts:
        body = _quote(plan, 100)
    assert body["fee_minor"] == 52180000
    assert _line(body, "cap-weekly")["code"] == "weekly_max.applied"
    for name, per_day in BUDGET_PER_DAY.items():
        assert counts[name] <= per_day * days, (name, counts[name])


# --- the jump -------------------------------------------------------------------

#: A zone, and an instant a few days before something happens to its dates.
UNUSUAL_DATES = [
    ("America/New_York", "2026-03-05T00:00:00+00:00"),  # 23 hours on 8 March
    ("America/New_York", "2026-10-29T00:00:00+00:00"),  # 25 hours on 1 November
    ("America/Santiago", "2026-04-01T00:00:00+00:00"),  # back an hour at midnight
    ("Australia/Lord_Howe", "2026-04-02T00:00:00+00:00"),  # back half an hour
    ("Pacific/Apia", "2011-12-27T00:00:00+00:00"),  # 30 December 2011 never happened
    ("America/Juneau", "1867-10-15T00:00:00+00:00"),  # 18 October 1867 happened twice
]


def _caps_in(zone: str, around: str, boundary: str):
    document = _plan(
        HOURLY,
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000, "day_boundary": boundary},
        CAPS["calendar"][1],
        {**CAPS["rolling"][1], "id": "cap-rolling-week"},
    )
    document["timezone"] = zone
    document["effective_from"] = (
        parse_instant(around, "around") - timedelta(days=30)
    ).isoformat()
    plan = load_plan(document)
    rules = {rule.id: rule for rule in plan.rules}
    return plan, rules["cap-daily"], (rules["cap-weekly"], rules["cap-rolling-week"])


@pytest.mark.guarantee("F61")
@pytest.mark.parametrize("boundary", ["calendar_day", "rolling_24h"])
@pytest.mark.parametrize("zone,around", UNUSUAL_DATES)
def test_the_day_found_from_its_date_is_the_day_a_walk_from_entry_finds(zone, around, boundary):
    """Every half hour of a ten-day stay, from four entries: the day found by
    its date is the day a walk from entry finds it in, and each week -- both
    kinds -- and each 31-hour window is cut into the days the walk cuts."""
    plan, daily, weeklies = _caps_in(zone, around, boundary)
    base = parse_instant(around, "around")
    for offset in (timedelta(0), timedelta(hours=7), timedelta(hours=13, minutes=30),
                   timedelta(hours=23, minutes=45)):
        entry = base + offset
        stay = make_stay(entry, entry + timedelta(days=10), "standard")
        walked = list(daily_max.days_of(daily, stay, plan))

        def walk(start, end, walked=walked):
            return [(max(s, start), min(e, end)) for s, e in walked if s < end and e > start]

        instant = entry
        while instant < stay.exit_at:
            expected = next(i for i, (_s, e) in enumerate(walked) if e > instant)
            found = daily_max._day_holding(daily, stay, plan, instant)
            assert found == expected, (zone, boundary, entry, instant, found, expected)
            window_end = min(instant + timedelta(hours=31), stay.exit_at)
            assert list(daily_max.pieces(daily, stay, plan, instant, window_end)) == walk(
                instant, window_end
            ), (zone, boundary, entry, instant)
            instant += timedelta(minutes=30)
        for weekly in weeklies:
            for start, end in weekly_max.weeks_of(weekly, stay, plan):
                assert list(daily_max.pieces(daily, stay, plan, start, end)) == walk(
                    start, end
                ), (zone, boundary, weekly.id, entry, start)


class _SkipsMidnight(tzinfo):
    """A made-up zone whose clocks go forward an hour at 23:30 on 30 April 2026,
    from UTC-4 to UTC-3, so they read 23:29 and then 00:30: midnight on 1 May
    never shows. Midnight at fold 0 is then read at the old offset (PEP 495),
    half an hour AFTER the first instants dated 1 May -- the one case where the
    date guesses a day too late, and the check down from the guess is needed.
    """

    JUMP_LOCAL = datetime(2026, 4, 30, 23, 30)
    JUMP_UTC = datetime(2026, 5, 1, 3, 30, tzinfo=UTC)
    BEFORE, AFTER = timedelta(hours=-4), timedelta(hours=-3)

    def utcoffset(self, dt):
        if dt is None:
            return self.BEFORE
        local = dt.replace(tzinfo=None)
        if local < self.JUMP_LOCAL:
            return self.BEFORE
        if local >= self.JUMP_LOCAL + timedelta(hours=1):
            return self.AFTER
        return self.BEFORE if dt.fold == 0 else self.AFTER  # inside the gap

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return None

    def fromutc(self, dt):
        utc = dt.replace(tzinfo=UTC)
        offset = self.BEFORE if utc < self.JUMP_UTC else self.AFTER
        return (dt + offset).replace(tzinfo=self)


@pytest.mark.guarantee("F61")
def test_the_day_found_from_its_date_is_checked_where_a_clock_skips_midnight():
    zone = _SkipsMidnight()
    plan = SimpleNamespace(timezone=zone)
    daily = daily_max.build(
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000, "day_boundary": "calendar_day"},
        ("standard",), "rules[0]",
    )
    entry = datetime(2026, 4, 30, 20, 0, tzinfo=zone)
    stay = make_stay(entry, entry + timedelta(days=3), "standard")
    walked = list(daily_max.days_of(daily, stay, plan))
    midnight = walked[1][0]
    assert midnight == datetime(2026, 5, 1, 4, 0, tzinfo=UTC), midnight
    dated_may_first_early = datetime(2026, 5, 1, 3, 45, tzinfo=UTC)
    assert dated_may_first_early.astimezone(zone).date().day == 1, "the zone must skip midnight"
    instant = entry.astimezone(UTC)
    while instant < stay.exit_at:
        expected = next(i for i, (_s, e) in enumerate(walked) if e > instant)
        assert daily_max._day_holding(daily, stay, plan, instant) == expected, instant
        instant += timedelta(minutes=5)


# --- the line -------------------------------------------------------------------

#: Seven-minute periods: 1,440 minutes hold 205 or 206 period starts, so with a
#: max of 20.55 a day some days pay 20.50 and the rest are capped, and the
#: amounts alternate all year. Spelled out in full, a year's line ran to
#: hundreds of runs.
ODD = {
    "id": "odd", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 45,
    "first_period_minor": 500, "repeat_period_minutes": 7,
    "repeat_period_minor": 10, "rounding": "ceil", "max_duration_minutes": None,
}
ODD_DAILY = {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
             "space_classes": ["standard"], "max_minor": 2055,
             "day_boundary": "calendar_day"}


#: What a daily cap's line lists after its figure: "... reduced to 7499.20 USD
#: (17.30 USD + ... : each day is capped on its own)".
LISTED = r"reduced to \d+\.\d\d USD \((.*): each day is capped on its own\)$"


def _minor(text: str) -> int:
    """'20.55 USD' as 2055, without a float."""
    amount = text.removesuffix(" USD")
    whole, cents = amount.split(".")
    return int(whole) * 100 + int(cents)


@pytest.mark.guarantee("F61")
def test_a_long_stays_line_spells_out_a_bounded_number_of_runs():
    body = _quote(_plan(ODD, ODD_DAILY), 1)
    line = _line(body, "cap-daily")
    assert line["code"] == "daily_max.applied"
    days = _days(1) + 1  # entry's own day and the exit's, both part days
    assert f"applied over {days} days:" in line["text"], line["text"]

    listed = re.search(LISTED, line["text"])
    assert listed, line["text"]
    *runs, rest = listed.group(1).split(" + ")
    more = re.fullmatch(r"(\d+) more coming to (\d+\.\d\d USD)", rest)
    assert more, f"the line does not say how many more amounts there were: {rest!r}"
    assert len(runs) == RUNS_SPELLED_OUT, len(runs)
    assert len(line["text"]) < 1000, len(line["text"])

    counted, total = int(more.group(1)), _minor(more.group(2))
    for run in runs:
        count, _, amount = run.rpartition(" x ")
        counted += int(count) if count else 1
        total += (int(count) if count else 1) * _minor(amount)
    assert counted == days, "the runs and the rest are not every day of the stay"
    assert total == body["fee_minor"], "the runs and the rest do not add up to the line's figure"


@pytest.mark.guarantee("F61")
def test_a_short_stays_line_is_spelled_out_in_full():
    """Under the bound nothing changes: two weeks of the same plan list every run."""
    body = run_quote(
        {"plans": [_plan(ODD, ODD_DAILY)], "entry_at": ENTRY,
         "exit_at": "2026-04-20T09:00:00-04:00", "space_class": "standard", "currency": "USD"}
    )[1]
    text = _line(body, "cap-daily")["text"]
    assert "more coming to" not in text, text
    listed = re.search(LISTED, text).group(1)
    assert len(listed.split(" + ")) <= RUNS_SPELLED_OUT
