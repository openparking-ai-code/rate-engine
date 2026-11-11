"""F33 -- two caps leave the LOWER ceiling standing, in either order.

A cap is not a competing base. Two ceilings on one stay are not a contradiction
the owner has to settle -- they are two ceilings, and the lower one wins. That
falls out of applying them in sequence rather than being arranged, which is
exactly why CAP is a COMPOSING stage and not a resolving one.

**This is the property that had to exist before `weekly_max` could.**
`find_conflicts` refused whenever more than one rule qualified at ANY stage, so
the first plan carrying a daily AND a weekly cap would have refused every stay in
the garage. The bug was latent while no second CAP rule type existed; the rule
type is what detonates it.

**Order-independence is PROVEN, not asserted.** The totals after CAP must agree
whichever cap runs first -- and they are genuinely different computations: one
takes 44.00 down to 30.00 and then to 25.00; the other takes it to 25.00 and then
finds the daily cap already satisfied. The LINES differ; the total does not.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import make_stay
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import RULE_ACCRUALS, RULE_APPLIERS
from rate_engine.stages import CAP

RESOLUTION = {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}}

PLAN = {
    "plan_version": "twocaps-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": RESOLUTION,
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000,
         "day_boundary": "calendar_day"},
        {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 2500,
         "week_boundary": "calendar_week", "week_starts_on": "mon"},
    ],
    "decisions": [],
}

ENTRY = "2026-03-03T09:00:00-05:00"
EXIT = "2026-03-03T19:00:00-05:00"  # ten hours

UNCAPPED = 4400   # 800 + 9 x 400
DAILY = 3000
WEEKLY = 2500     # the lower ceiling


def _quote(plan: dict | None = None):
    return run_quote(
        {
            "plans": [copy.deepcopy(plan if plan is not None else PLAN)],
            "entry_at": ENTRY, "exit_at": EXIT,
            "space_class": "standard", "currency": "USD",
        }
    )


def test_the_fixture_can_tell_the_three_outcomes_apart():
    """The control on the fixture. Uncapped, daily-capped and weekly-capped must
    be three different numbers, or "the lower ceiling stands" is unmeasurable."""
    assert len({UNCAPPED, DAILY, WEEKLY}) == 3
    assert WEEKLY < DAILY < UNCAPPED


@pytest.mark.guarantee("F33")
def test_two_caps_are_NOT_a_conflict_and_the_stay_prices():
    status, body = _quote()
    assert status == 200, (
        f"a plan with a daily and a weekly cap refused the stay: {body}"
    )
    assert body["fee_minor"] == WEEKLY


@pytest.mark.guarantee("F33")
def test_the_BREAKDOWN_NAMES_BOTH_of_them():
    """Composing means both applied, so both are on the receipt. A cap that
    silently did nothing would leave an operator unable to see it was there."""
    _status, body = _quote()
    by_rule = {ln["rule_id"]: ln["code"] for ln in body["breakdown"] if ln["rule_id"]}
    assert by_rule["cap-daily"].startswith("daily_max.")
    assert by_rule["cap-weekly"].startswith("weekly_max.")


@pytest.mark.guarantee("F33")
def test_the_total_after_CAP_is_the_SAME_IN_BOTH_ORDERS():
    """The property test, run over the appliers directly.

    Applying the caps through the pipeline can only ever exercise ONE order --
    the engine's -- so the order-independence claim would rest on the sentence
    that asserts it. This applies them both ways round and compares.
    """
    plan = load_plan(copy.deepcopy(PLAN))
    entry_at = parse_instant(ENTRY, "entry")
    stay = make_stay(entry_at, parse_instant(EXIT, "exit"), "standard")
    caps = list(plan.rules_for_stage(CAP))
    assert len(caps) == 2
    # How the time was charged, as the engine tells the caps (F59): the hourly
    # rate's own accrual.
    hourly = next(r for r in plan.rules if r.id == "hourly")
    charged_by = RULE_ACCRUALS[hourly.type](hourly, stay, plan)
    assert charged_by(stay.duration_minutes) == UNCAPPED

    outcomes = {}
    for order in (caps, list(reversed(caps))):
        running = UNCAPPED
        lines = []
        for rule in order:
            applied = RULE_APPLIERS[rule.type](rule, stay, plan, running, charged_by=charged_by)
            for line in applied:
                running += line.delta_minor
                lines.append((line.code, line.delta_minor))
        outcomes[tuple(r.id for r in order)] = (running, tuple(lines))

    totals = {total for total, _lines in outcomes.values()}
    assert totals == {WEEKLY}, f"the order of two caps changed the total: {outcomes}"

    line_sets = {lines for _total, lines in outcomes.values()}
    assert len(line_sets) == 2, (
        "the two orders produced identical LINES, so this fixture cannot tell "
        "order-independence of the total from the caps not running at all"
    )


@pytest.mark.guarantee("F33")
def test_the_LOWER_ceiling_is_the_one_that_stands_whichever_is_lower():
    """The control on the item above: swapping which cap is lower must swap the
    answer, or the fixture is proving that 2500 is a constant."""
    swapped = copy.deepcopy(PLAN)
    for rule in swapped["rules"]:
        if rule["id"] == "cap-daily":
            rule["max_minor"] = 2000
        if rule["id"] == "cap-weekly":
            rule["max_minor"] = 3500
    _status, body = _quote(swapped)
    assert body["fee_minor"] == 2000


@pytest.mark.guarantee("F33")
def test_a_weekly_cap_counts_WEEKS_and_a_rolling_one_counts_SEVEN_DAY_BLOCKS():
    """`week_boundary` is the field `day_boundary` is, one unit up, and the two
    answers differ for a stay that crosses a week boundary."""
    from datetime import timedelta

    from rate_engine.rules.weekly_max import weeks_covered

    plan = load_plan(copy.deepcopy(PLAN))
    weekly = next(r for r in plan.rules if r.id == "cap-weekly")
    entry_at = parse_instant("2026-03-08T12:00:00-04:00", "entry")  # a Sunday
    crosses = make_stay(entry_at, entry_at + timedelta(days=1), "standard")

    # Monday starts the week, so Sunday-to-Monday touches two calendar weeks and
    # one rolling seven-day block. The two are genuinely different rules.
    assert weeks_covered(weekly, crosses, plan) == 2

    rolling = copy.deepcopy(PLAN)
    for rule in rolling["rules"]:
        if rule["id"] == "cap-weekly":
            rule["week_boundary"] = "rolling_7d"
            rule["week_starts_on"] = None
    rolling_plan = load_plan(rolling)
    rolling_rule = next(r for r in rolling_plan.rules if r.id == "cap-weekly")
    assert weeks_covered(rolling_rule, crosses, rolling_plan) == 1


@pytest.mark.guarantee("F33")
@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"week_boundary": "weekly"}, "week_boundary is 'weekly'"),
        ({"week_starts_on": "monday"}, "needs a day name"),
        ({"week_starts_on": None}, "needs a day name"),
        ({"week_boundary": "rolling_7d"}, "no starting day applies"),
    ],
)
def test_a_week_the_engine_cannot_read_is_REFUSED_by_name(fields, expected):
    """No default: a cap of 100 a week prices a Saturday-to-Tuesday stay at 100
    or at 200 depending on where the week starts, and there is no universal
    answer to that."""
    document = copy.deepcopy(PLAN)
    for rule in document["rules"]:
        if rule["id"] == "cap-weekly":
            rule.update(fields)
    status, body = _quote(document)
    assert status == 400, f"{fields!r} was accepted"
    assert expected in body["error"], body["error"]
