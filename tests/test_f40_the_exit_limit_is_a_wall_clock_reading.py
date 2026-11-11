"""F40 -- the exit limit is a WALL-CLOCK reading, so a window survives the night
the clocks change.

**The state this closes was not a wrong answer. It was an unguarded right one.**
The L review of the round that added F39 measured the behaviour correct and the
guarantee absent: it built the counter-model this module's fail control now uses
-- a TRUE instant comparison, through `.timestamp()` -- watched it misprice the
repeated hour 40.00 -> 24.00, and then watched **all 338 tests stay green with it
installed**, over 17,565 bounded exit comparisons of which not one was decided
differently. The suite contained no stay on which the two readings disagree, so
nothing in it could tell a wall-clock limit from an instant one.

Both of the modules that could have held this deliberately look away: F39 says
"October 2026 dates sit away from the US daylight-saving transition", F28 says
the same of March. Correctly -- neither is about DST -- but the effect was that a
US garage met this every November and the suite did not.

**Why the repeated hour is the whole fixture.** On 2026-11-01 in
America/New_York, 01:00-01:59 happens TWICE: once at UTC-4 and again, an hour
later in real time, at UTC-5. A window whose `exit_by` falls inside that hour is
therefore the one case where "the same clock reading" and "the same instant" are
different questions, and the plan states a clock reading. Two stays leaving at
01:00 -- one on each pass, one hour apart in elapsed time -- must BOTH get the
rate, because the plan says out by 01:30 and both left at one.

The spring boundary is the mirror: on 2026-03-08 the wall time 02:00 never
occurs at all, so a window with `exit_by 02:00` states a limit that has no
instant. It still has a READING, and the stay that left at 01:59 is inside it
while the one that left at 03:00 -- one real minute later -- is not.

**The fail control is the counter-model, not a mutation of a number.** A DST test
that stays green when the comparison is switched to instants is measuring
nothing, and that is precisely the state the suite was in before this module. See
`scripts/fail_controls.py`, control F40.
"""

from __future__ import annotations

import copy
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules.time_window import _exit_limit
from rate_engine.wallclock import local_minute

ZONE = "America/New_York"
NY = ZoneInfo(ZONE)

#: The story above is told at 40.00. The fixture's window is 15.00, below every
#: hourly total a stay below reaches where it qualifies (21.00 and up), because
#: the cheapest way is charged under either mode (F63): only then is the window
#: charged where it qualifies, and the fee says whether it did.
WINDOW_PRICE = 1500

#: The fall-back night. In at 18:30 on the Saturday, out by 01:30 -- a limit that
#: falls INSIDE the hour that happens twice.
FALL_ENTRY = "2026-10-31T18:30:00-04:00"
FALL_EXIT_BY = "01:30"
FALL_DATES = ["2026-10-31", "2026-11-01"]

#: 01:00 on the FIRST pass (UTC-4) and on the SECOND (UTC-5). Same reading, one
#: hour apart in real time. Both are inside a 01:30 limit.
FIRST_PASS_0100 = "2026-11-01T01:00:00-04:00"
SECOND_PASS_0100 = "2026-11-01T01:00:00-05:00"
SECOND_PASS_0129 = "2026-11-01T01:29:00-05:00"
#: One minute and one hour past it. Both must be refused, or "inside" means
#: nothing.
SECOND_PASS_0131 = "2026-11-01T01:31:00-05:00"
SECOND_PASS_0230 = "2026-11-01T02:30:00-05:00"
TIME_BASED_0131, TIME_BASED_0230 = 2700, 2700

#: The spring-forward night. `exit_by 02:00` is a wall time that DOES NOT OCCUR.
SPRING_ENTRY = "2026-03-07T18:30:00-05:00"
SPRING_EXIT_BY = "02:00"
SPRING_DATES = ["2026-03-07", "2026-03-08"]
BEFORE_THE_GAP_0159 = "2026-03-08T01:59:00-05:00"
AFTER_THE_GAP_0300 = "2026-03-08T03:00:00-04:00"
AFTER_THE_GAP_0400 = "2026-03-08T04:00:00-04:00"
TIME_BASED_0300, TIME_BASED_0400 = 2400, 2700

PLAN = {
    "plan_version": "dst-2026",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": ZONE,
    "currency": "USD",
    "space_classes": ["standard"],
    # `stated_order` at QUALIFY. It used to let the window REPLACE the hourly
    # rate whatever it cost, which is how this fixture's fee said whether the
    # window qualified. Under either mode the cheapest way is charged now
    # (F63), so the window is priced below the hour (WINDOW_PRICE) and the fee
    # says it the same way. The mode is kept so a stated order is exercised.
    "resolution": {
        "QUALIFY": {"mode": "stated_order", "order": ["night"]},
        "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        {"id": "night", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Night rate",
         "applies_on": {"kind": "dates", "dates": FALL_DATES},
         "enter_from": "16:00", "enter_by": "21:00", "exit_by": FALL_EXIT_BY,
         "day_span": "next_day", "effect": {"kind": "flat", "price_minor": WINDOW_PRICE}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 300, "repeat_period_minutes": 60,
         "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _plan_for(entry_dates: list[str], exit_by: str) -> dict:
    document = copy.deepcopy(PLAN)
    document["rules"][0]["applies_on"]["dates"] = list(entry_dates)
    document["rules"][0]["exit_by"] = exit_by
    return document


def _fee(entry_at: str, exit_at: str, *, entry_dates: list[str], exit_by: str) -> tuple[int, str]:
    """Price a REAL stay. The exit is an absolute instant, deliberately: the
    whole subject of this module is that elapsed time and the wall clock
    disagree here, so a duration in minutes could not express the fixture."""
    document = _plan_for(entry_dates, exit_by)
    load_plan(copy.deepcopy(document))
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": entry_at,
            "exit_at": exit_at,
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200, body
    line = [ln for ln in body["breakdown"] if ln["code"].startswith("time_window")][0]
    # NOT `endswith("applied")`: "time_window.not_applied" ends with it too, and
    # a predicate that cannot tell the two apart reported every refusal in this
    # fixture as a pass once already.
    assert line["code"] in ("time_window.applied", "time_window.not_applied"), line["code"]
    return body["fee_minor"], line["code"]


def _applied(entry_at: str, exit_at: str, **kw) -> bool:
    return _fee(entry_at, exit_at, **kw)[1] == "time_window.applied"


def _elapsed_hours(entry_at: str, exit_at: str) -> float:
    elapsed = parse_instant(exit_at, "exit") - parse_instant(entry_at, "entry")
    return elapsed.total_seconds() / 3600


# --- the two controls on the fixture, and they run first --------------------


def test_the_fixture_dates_really_ARE_dst_transitions():
    """Without this, every assertion below is ordinary arithmetic about an
    ordinary night and says nothing about a clock change. F5 makes the same
    check of its own DST fixture, for the same reason."""
    for day, wanted in (("2026-11-01", "the fall back"), ("2026-03-08", "the spring forward")):
        names = {
            datetime.fromisoformat(f"{day}T0{hour}:00:00").replace(tzinfo=NY, fold=fold).tzname()
            for hour in range(6)
            for fold in (0, 1)
        }
        assert names == {"EST", "EDT"}, (
            f"{day} is not {wanted} in {ZONE}: the local clock reads {sorted(names)} "
            "all night, so this fixture does not cross a transition at all"
        )

    repeated = [
        datetime.fromisoformat("2026-11-01T01:00:00").replace(tzinfo=NY, fold=fold)
        for fold in (0, 1)
    ]
    assert repeated[0].utcoffset() != repeated[1].utcoffset(), (
        "01:00 on 2026-11-01 does not occur twice, so the repeated hour this "
        "module is built on does not exist"
    )
    gap = datetime.fromisoformat("2026-03-08T02:00:00").replace(tzinfo=NY)
    assert gap.tzname() == "EST" and gap.utcoffset() != gap.replace(fold=1).utcoffset(), (
        "02:00 on 2026-03-08 is an ordinary wall time in this zone, so "
        f"{SPRING_EXIT_BY} is not the non-existent limit this module states"
    )


def test_the_fixture_can_tell_the_outcomes_apart():
    """The window price and every time-based total below must differ, or the
    tables pass whether or not the rule was applied."""
    assert len({WINDOW_PRICE, TIME_BASED_0131, TIME_BASED_0300}) == 3
    # And the window is the cheaper way on every stay it qualifies for: the
    # shortest, out at 01:00 on the first pass, is 6.5 hours -- 3.00 + 6 x 3.00.
    assert WINDOW_PRICE < 300 + 6 * 300
    assert TIME_BASED_0131 == TIME_BASED_0230 != WINDOW_PRICE
    assert TIME_BASED_0400 != WINDOW_PRICE


def test_the_repeated_hour_stays_are_an_HOUR_APART_in_real_time():
    """The other half of the fixture control. If these two stays were the same
    length, the test below would not be about a clock change either."""
    first = _elapsed_hours(FALL_ENTRY, FIRST_PASS_0100)
    second = _elapsed_hours(FALL_ENTRY, SECOND_PASS_0100)
    assert second - first == 1.0, (
        f"the two 01:00 exits are {second - first}h apart, not 1h, so they are not "
        "the two passes through the repeated hour"
    )


# --- the guarantee ---------------------------------------------------------


@pytest.mark.guarantee("F40")
def test_BOTH_passes_through_the_repeated_hour_get_the_rate():
    """The heart of it. Out by 01:30, and two cars left at 01:00 -- one before
    the clocks went back and one after. They are an hour apart in elapsed time
    and identical on the wall clock, which is what the plan states."""
    first, code_first = _fee(FALL_ENTRY, FIRST_PASS_0100,
                             entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY)
    second, code_second = _fee(FALL_ENTRY, SECOND_PASS_0100,
                               entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY)

    assert (first, code_first) == (WINDOW_PRICE, "time_window.applied"), "the FIRST pass"
    assert (second, code_second) == (WINDOW_PRICE, "time_window.applied"), (
        "the SECOND pass through the repeated hour was refused a rate its own wall "
        "clock earned -- the limit was decided by a UTC offset"
    )
    assert first == second, (
        "the same wall-clock exit priced two different ways on the night the "
        "clocks changed"
    )
    assert _applied(FALL_ENTRY, SECOND_PASS_0129,
                    entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY), "01:29 on the second pass"


@pytest.mark.guarantee("F40")
def test_the_same_night_still_REFUSES_a_stay_past_the_limit():
    """The positive control, and it is not optional: a run in which every stay
    qualifies cannot tell a working limit from an absent one. These two left
    after 01:30 on the same night and are priced on the time-based rate."""
    assert _fee(FALL_ENTRY, SECOND_PASS_0131,
                entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY) == (
        TIME_BASED_0131, "time_window.not_applied"), "one minute past the limit"
    assert _fee(FALL_ENTRY, SECOND_PASS_0230,
                entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY) == (
        TIME_BASED_0230, "time_window.not_applied"), "an hour past the limit"


@pytest.mark.guarantee("F40")
def test_a_limit_at_a_wall_time_that_NEVER_OCCURS_still_reads():
    """Spring forward. `exit_by 02:00` on a night when 02:00 does not exist has
    no instant, and the comparison does not need one: 01:59 is inside the
    reading and 03:00 -- one real minute later -- is not."""
    assert _fee(SPRING_ENTRY, BEFORE_THE_GAP_0159,
                entry_dates=SPRING_DATES, exit_by=SPRING_EXIT_BY) == (
        WINDOW_PRICE, "time_window.applied"), "01:59, the last instant before the gap"
    assert _fee(SPRING_ENTRY, AFTER_THE_GAP_0300,
                entry_dates=SPRING_DATES, exit_by=SPRING_EXIT_BY) == (
        TIME_BASED_0300, "time_window.not_applied"), "03:00, the first instant after it"
    assert _fee(SPRING_ENTRY, AFTER_THE_GAP_0400,
                entry_dates=SPRING_DATES, exit_by=SPRING_EXIT_BY) == (
        TIME_BASED_0400, "time_window.not_applied"), "04:00, well past it"

    assert _elapsed_hours(SPRING_ENTRY, AFTER_THE_GAP_0300) - _elapsed_hours(
        SPRING_ENTRY, BEFORE_THE_GAP_0159
    ) == pytest.approx(1 / 60), (
        "01:59 and 03:00 are not one real minute apart, so this is not the gap"
    )


def _the_instant_model_would_apply(entry_at: str, exit_at: str, exit_by: str) -> bool:
    """The REJECTED reading, kept here and nowhere else, and never imported by
    the engine.

    A TRUE instant comparison. Note what it is NOT: attaching the zone with
    `limit.replace(tzinfo=...)` and comparing the two aware datetimes directly
    would silently agree with the wall-clock reading, because PEP 495 compares
    same-zone aware datetimes by their naive fields and ignores `fold`. The
    review of F39 wrote it that way first and was told the counter-model changed
    nothing. So this goes through `.timestamp()`, which is the only spelling that
    actually puts an offset in the middle of the comparison.
    """
    entry_local = local_minute(parse_instant(entry_at, "entry"), NY)
    exit_local = local_minute(parse_instant(exit_at, "exit"), NY)
    limit_local = _exit_limit(entry_local, time.fromisoformat(exit_by), 1)
    return exit_local.timestamp() <= limit_local.replace(tzinfo=NY).timestamp()


@pytest.mark.guarantee("F40")
def test_the_INSTANT_reading_would_answer_DIFFERENTLY_on_this_fixture():
    """The control that makes the module a measurement rather than a table of
    numbers that happen to be right.

    If the two readings agreed on every stay above, F40 would pass under either
    and would be guarding nothing -- which is exactly how 17,565 exit
    comparisons in the pre-F40 suite failed to notice the difference. So the
    fixture is required to SEPARATE them: the second pass through the repeated
    hour is inside the wall-clock limit and outside the instant one.
    """
    assert _the_instant_model_would_apply(FALL_ENTRY, FIRST_PASS_0100, FALL_EXIT_BY), (
        "the instant reading refuses the FIRST pass too, so the disagreement below "
        "is not specific to the repeated hour"
    )
    assert not _the_instant_model_would_apply(FALL_ENTRY, SECOND_PASS_0100, FALL_EXIT_BY), (
        "the instant reading agrees with the wall-clock one on the second pass, so "
        "this fixture cannot tell them apart and F40 measures nothing"
    )
    assert _applied(FALL_ENTRY, SECOND_PASS_0100, entry_dates=FALL_DATES,
                    exit_by=FALL_EXIT_BY), "the engine must take the wall-clock reading"
    assert not _the_instant_model_would_apply(FALL_ENTRY, SECOND_PASS_0129, FALL_EXIT_BY)


@pytest.mark.guarantee("F40")
def test_the_naive_replace_spelling_is_NOT_a_counter_model():
    """Recorded as a test because it cost a review an hour and a false result.

    `limit.replace(tzinfo=zone)` compared against the exit's own aware datetime
    looks like an instant comparison and is not one: PEP 495 makes two aware
    datetimes sharing a `tzinfo` compare by their naive fields, `fold` and all
    offsets ignored. Anyone re-deriving F40's control needs this to be written
    down, or they will write the version that cannot fail.
    """
    entry_local = local_minute(parse_instant(FALL_ENTRY, "entry"), NY)
    exit_local = local_minute(parse_instant(SECOND_PASS_0100, "exit"), NY)
    limit_local = _exit_limit(entry_local, time.fromisoformat(FALL_EXIT_BY), 1)

    naive_aware = exit_local <= limit_local.replace(tzinfo=NY)
    wall_clock = (exit_local.date(), exit_local.time()) <= (limit_local.date(), limit_local.time())
    through_utc = exit_local.timestamp() <= limit_local.replace(tzinfo=NY).timestamp()

    assert naive_aware == wall_clock, (
        "the `.replace(tzinfo=...)` comparison no longer agrees with the wall-clock "
        "reading on the repeated hour -- if Python's rules changed here, the "
        "docstring in `_exit_limit` is now wrong and must be corrected"
    )
    assert through_utc != wall_clock, (
        "the UTC comparison agrees with the wall-clock one, so F40's fail control "
        "cannot break anything"
    )


# --- the same night under `cheapest_wins` ----------------------
#
# The module moved to `stated_order` in an earlier fix (its 40.00 window is dearer
# than the hour, so under `cheapest_wins` it would not be used though it
# qualified). That left `cheapest_wins` with no test on the night the clocks
# change. Here the window is CHEAPER: 10.00, against the hour's 3.00 + 7 x 3.00 =
# 24.00 for the second pass out at 01:00. An instant reading of the limit refuses
# that pass and charges 24.00; so does a comparison that charges the hour.

CHEAP_WINDOW_PRICE = 1000
TIME_BASED_SECOND_PASS_0100 = 2400


def _cheapest_wins_fee(entry_at: str, exit_at: str, *, entry_dates: list[str],
                       exit_by: str) -> tuple[int, list[str]]:
    document = _plan_for(entry_dates, exit_by)
    document["resolution"] = {"QUALIFY": {"mode": "cheapest_wins"},
                              "ACCUMULATE": {"mode": "cheapest_wins"}}
    document["rules"][0]["effect"]["price_minor"] = CHEAP_WINDOW_PRICE
    status, body = run_quote(
        {
            "plans": [document],
            "entry_at": entry_at,
            "exit_at": exit_at,
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200, body
    return body["fee_minor"], [ln["code"] for ln in body["breakdown"]]


def test_the_cheapest_wins_fixture_puts_the_window_below_the_hour():
    """The control: 18:30 EDT to 01:00 EST is seven and a half hours."""
    assert _elapsed_hours(FALL_ENTRY, SECOND_PASS_0100) == 7.5
    assert TIME_BASED_SECOND_PASS_0100 == 300 + 7 * 300 > CHEAP_WINDOW_PRICE


@pytest.mark.guarantee("F40")
def test_under_cheapest_wins_BOTH_passes_get_the_cheaper_window():
    for exit_at in (FIRST_PASS_0100, SECOND_PASS_0100, SECOND_PASS_0129):
        fee, codes = _cheapest_wins_fee(FALL_ENTRY, exit_at,
                                        entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY)
        assert fee == CHEAP_WINDOW_PRICE, (
            f"out at {exit_at}, charged {fee}: the window was refused or the hour charged"
        )
        assert "time_window.applied" in codes and "special_used" in codes, codes


@pytest.mark.guarantee("F40")
def test_under_cheapest_wins_the_skipped_wall_time_still_reads():
    fee, codes = _cheapest_wins_fee(SPRING_ENTRY, BEFORE_THE_GAP_0159,
                                    entry_dates=SPRING_DATES, exit_by=SPRING_EXIT_BY)
    assert fee == CHEAP_WINDOW_PRICE and "time_window.applied" in codes, (fee, codes)
    fee, codes = _cheapest_wins_fee(SPRING_ENTRY, AFTER_THE_GAP_0300,
                                    entry_dates=SPRING_DATES, exit_by=SPRING_EXIT_BY)
    assert fee == TIME_BASED_0300 and "time_window.not_applied" in codes, (fee, codes)


@pytest.mark.guarantee("F40")
def test_under_cheapest_wins_past_the_limit_the_hour_is_charged():
    fee, codes = _cheapest_wins_fee(FALL_ENTRY, SECOND_PASS_0131,
                                    entry_dates=FALL_DATES, exit_by=FALL_EXIT_BY)
    assert fee == TIME_BASED_0131 and "special_used" not in codes, (fee, codes)
