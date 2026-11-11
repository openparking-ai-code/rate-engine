"""The fixture corpus, and the control that proves it exercises anything.

A FIXTURE IS PART OF THE MEASUREMENT. A check measured against a reference of
flat grey with nothing in it can look like it works -- not a weak measurement,
but not a measurement at all, producing numbers that read as evidence.
The equivalent failure here is a corpus of stays
that all sit on the same side of every threshold: the suite would go green,
`increment`'s repeat branch would never run, and nothing would say so.

So every axis below is READ OUT OF THE PLANS -- the actual constants the rules
branch on -- and `test_fixture_axes.py` asserts the corpus holds a case either
side of each. An axis that cannot reach its threshold is a broken axis, not a
safe threshold.
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

from rate_engine.engine import Stay, make_stay
from rate_engine.plan import load_plan, parse_instant

PLANS_DIR = Path(__file__).parent / "plans"

#: The plan the worked example in the brief and in docs/CONTRACT.md is priced on.
DOWNTOWN_V2 = json.loads((PLANS_DIR / "downtown_v2.json").read_text())


def downtown_v1() -> dict:
    """The SAME garage, priced cheaper, in force before v2.

    Exists for F3: with only one version the engine cannot demonstrate that it
    chose by entry rather than by exit, because there is nothing to choose.
    """
    plan = copy.deepcopy(DOWNTOWN_V2)
    plan["plan_version"] = "downtown-2026-01"
    plan["effective_from"] = "2026-01-01T00:00:00-05:00"
    for rule in plan["rules"]:
        if rule["id"] == "hourly":
            rule["first_period_minor"] = 500
            rule["repeat_period_minor"] = 250
        if rule["id"] == "cap":
            rule["max_minor"] = 2000
    return plan


def plan_with(**overrides) -> dict:
    """A copy of the reference plan with top-level fields replaced."""
    plan = copy.deepcopy(DOWNTOWN_V2)
    plan.update(overrides)
    return plan


def with_rule_field(rule_id: str, **fields) -> dict:
    plan = copy.deepcopy(DOWNTOWN_V2)
    for rule in plan["rules"]:
        if rule["id"] == rule_id:
            rule.update(fields)
            return plan
    raise KeyError(f"no rule {rule_id!r} in the reference plan")


def without_rule(rule_id: str) -> dict:
    plan = copy.deepcopy(DOWNTOWN_V2)
    plan["rules"] = [r for r in plan["rules"] if r["id"] != rule_id]
    return plan


def loaded(document: dict | None = None):
    return load_plan(document if document is not None else DOWNTOWN_V2)


def stay(entry: str, minutes: int, space_class: str = "standard") -> Stay:
    entry_at = parse_instant(entry, "entry")
    return make_stay(entry_at, entry_at + timedelta(minutes=minutes), space_class)


# --- the corpus ------------------------------------------------------------
#
# Every entry names the axis it exists to put a case on. Nothing here is a round
# number chosen because it looked plausible; each is a threshold the rules read,
# or one minute either side of one.

EARLY = "2026-03-03T08:30:00-05:00"  # Tue, inside the 06:00-09:00 entry window
LATE = "2026-03-03T09:14:00-05:00"  # Tue, after the 09:00 limit -- the worked example
BEFORE_OPEN = "2026-03-03T05:59:00-05:00"  # Tue, one minute before enter_from
ON_OPEN = "2026-03-03T06:00:00-05:00"  # Tue, exactly on enter_from
SATURDAY = "2026-03-07T07:00:00-05:00"  # inside the hours, NOT one of the stated days
FRI_NIGHT = "2026-03-06T22:00:00-05:00"  # crosses local midnight into Saturday
DST_SPRING = "2026-03-07T12:00:00-05:00"  # the US spring-forward is 2026-03-08
#: 2026-11-01 is the US fall-back: that LOCAL day is 25 hours long. It is the
#: only date in the year where `calendar_day` and `rolling_24h` give different
#: answers for the same stay -- a stay can fit inside one local date and still
#: cross two 24-hour windows. An axis with only the spring side is half an axis.
DST_FALL = "2026-11-01T00:00:00-04:00"

CORPUS: dict[str, Stay] = {
    # increment: first period, either side of 60 minutes
    "first_period_under": stay(LATE, 59),
    "first_period_exact": stay(LATE, 60),
    "first_period_over": stay(LATE, 61),
    # increment: a stay with many repeat periods (the brief's example)
    "worked_example": stay(LATE, 566),
    # increment: either side of the 1440-minute stated ceiling
    "ceiling_under": stay(LATE, 1439),
    "ceiling_exact": stay(LATE, 1440),
    "ceiling_over": stay(LATE, 1441),
    # time_window: qualifies, and each condition missed by one minute. Every
    # axis the rule branches on has a case either side of it -- the entry
    # window's two ends, the exit limit, and the days it applies on.
    "window_qualifies": stay(EARLY, 240),
    "window_entry_late": stay(LATE, 60),
    "window_entry_before_open": stay(BEFORE_OPEN, 240),  # 05:59, enter_from is 06:00
    "window_entry_on_open": stay(ON_OPEN, 240),  # 06:00 exactly, so it qualifies
    "window_day_not_stated": stay(SATURDAY, 240),  # Sat: hours fine, day is not
    "window_exit_late": stay(EARLY, 511),  # 08:30 + 8h31m = 17:01
    "window_exit_on_limit": stay(EARLY, 510),  # 08:30 + 8h30m = 17:00 exactly
    # daily_max: either side of the cap, and across a local midnight
    "cap_not_reached": stay(LATE, 120),
    "cap_reached": stay(LATE, 566),
    "cap_across_midnight": stay(FRI_NIGHT, 300),
    # daily_max across BOTH DST transitions. Spring-forward shortens a local day
    # to 23 hours; fall-back stretches one to 25, and only the second separates
    # the two day-boundary rules from each other.
    "dst_day_spring": stay(DST_SPRING, 1440),
    "dst_day_fall": stay(DST_FALL, 1440),
    # space_surcharge: both sides of the space-class axis
    "vip_space": stay(LATE, 120, "vip"),
    "standard_space": stay(LATE, 120, "standard"),
    # zero and one minute: a stay is never negative, and a part-minute is a minute
    "zero_length": stay(LATE, 0),
    "one_minute": stay(LATE, 1),
}

#: (axis, the prefix its corpus keys share). A reader's index of what the corpus
#: is built to straddle.
#:
#: **NOTHING READS THIS, and it used to say `test_fixture_axes.py` did.** That
#: file derives its thresholds from the reference plan directly, which is the
#: stronger arrangement and the one the header above describes -- a list here
#: could not notice an axis somebody forgot to add to it. The comment is
#: corrected rather than the table deleted: a false sentence about a measurement
#: is the defect this repository keeps finding, and a wrong one pointing AT a
#: real test is the worst shape of it.
AXES: tuple[tuple[str, str], ...] = (
    ("increment.first_period_minutes = 60", "first_period"),
    ("increment.max_duration_minutes = 1440", "ceiling"),
    ("time_window enter_from 06:00 / enter_by 09:00 / exit_by 17:00", "window"),
    ("daily_max.max_minor = 3000", "cap"),
    ("space_class in {standard, vip}", "space"),
    ("both DST transitions", "dst_day"),
)
