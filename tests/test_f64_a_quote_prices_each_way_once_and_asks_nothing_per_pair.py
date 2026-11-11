"""F64 -- a quote prices each way once, and asks nothing again per way or per pair.

The cheapest price always wins (F63), so every way of pricing a stay -- each
special and each time-based rate that qualifies -- is priced through the whole
pipeline, caps and all, and the lowest fee is charged. With N ways that is
N + 1 passes, and it is the rule itself: no way's fee is known until it has
been through every stage.

**What a review measured on top of that.** Each pass asked every rule again
whether it qualified, and then looked each rule up in the answer with
`rule in [...]`, which compares two rules field by field. Every pass also asked
every special that had NOT qualified for its line again. The work of a quote
grew with the cube of the ways: 800 any-day specials on a 90-day stay with a
daily and a weekly max took 26.9 s a stay, and 400 took about 3 s.

Now `quote` asks each rule once whether it qualifies (`engine._Qualified`) and
hands the answer to the gaps, the conflicts and every pass; a rule is found by
its id, which `load_plan` holds unique; a special that did not qualify is asked
for its line once. No limit was added: not on the rules a plan may hold, not on
the ways. What is left grows with the ways times the plan's rules.

What this file pins, counted rather than timed:

* every rule is asked once a quote whether it qualifies;
* no two rules are compared field by field;
* a special or time-based rate that qualifies is asked for its lines at most
  three times (its own pass, what it charges itself, and the receipt's pass if
  it wins), and one that did not qualify once;
* every cap runs once a pass, N + 1 times;

under both resolution modes, on 400 ways (300 specials and 100 time-based rates)
beside 100 specials that do not qualify. The counters stop the quote the moment
one goes over, so a quote doing the old work fails at once.

And timed: 400 qualifying specials and 400 that do not, on a 90-day stay with a
daily and a weekly max, are priced within `TIME_BUDGET_SECONDS`. On the machine
that measured this file it took about 0.3 s; the same stay took about 3 s with
the work repeated per pass, on 400 specials and none that did not qualify. The
budget stops the quote when it runs out, where the platform allows it.

`scripts/fail_controls.py` has each pass ask again and find the rule by
comparing whole rules, has a rule found by comparing whole rules alone, has a
special that did not qualify asked on every pass, and runs the time budget on
its own against the first of those, and requires red.
"""

from __future__ import annotations

import copy
import signal
import time
from collections import Counter
from contextlib import contextmanager

import pytest

from rate_engine import engine
from rate_engine.engine import make_stay, quote
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import RULE_APPLIERS, Rule

EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}
DAILY = {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000, "day_boundary": "calendar_day"}
WEEKLY = {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
          "space_classes": ["standard"], "max_minor": 10000,
          "week_boundary": "calendar_week", "week_starts_on": "mon"}

#: A Monday, and 90 days later to the minute: the longest stay priced (F62).
ENTRY = "2026-04-06T09:00:00-04:00"
EXIT = "2026-07-05T09:00:00-04:00"

#: The fixed budget for `test_400_qualifying_specials_are_priced_within_a_fixed_time_budget`.
TIME_BUDGET_SECONDS = 5.0


def _flat(i: int, days=EVERY_DAY) -> dict:
    """An any-day flat special: it qualifies for any stay that enters on `days`."""
    return {
        "id": f"flat-{i:04d}", "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": f"Flat {i}",
        "applies_on": {"kind": "days_of_week", "days": list(days)},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
        "day_span": "any_span", "effect": {"kind": "flat", "price_minor": 100_000 + i},
    }


def _weekend_flat(i: int) -> dict:
    """A flat for a weekend entry, so a Monday stay does not qualify for it."""
    rule = _flat(i, days=["sat", "sun"])
    rule["id"], rule["label"] = f"weekend-{i:04d}", f"Weekend {i}"
    return rule


def _rate(i: int) -> dict:
    """A time-based rate that qualifies for every stay: a way of its own."""
    return {
        "id": f"rate-{i:04d}", "type": "increment", "stage": "ACCUMULATE",
        "space_classes": ["standard"], "first_period_minutes": 60,
        "first_period_minor": 900 + i, "repeat_period_minutes": 60,
        "repeat_period_minor": 450 + i, "rounding": "ceil", "max_duration_minutes": None,
    }


def _plan(rules: list[dict], mode: str = "cheapest_wins") -> dict:
    resolution = {stage: {"mode": "cheapest_wins"} for stage in ("QUALIFY", "ACCUMULATE")}
    if mode == "stated_order":
        resolution = {
            stage: {"mode": "stated_order",
                    "order": [r["id"] for r in reversed(rules) if r["stage"] == stage]}
            for stage in ("QUALIFY", "ACCUMULATE")
        }
    return {
        "plan_version": "work-budget-2026-10", "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD", "space_classes": ["standard"],
        "resolution": resolution, "adjust_order": None,
        "rules": [copy.deepcopy(r) for r in rules], "decisions": [],
    }


def _stay():
    return make_stay(parse_instant(ENTRY, "entry"), parse_instant(EXIT, "exit"), "standard")


class _OverBudget(AssertionError):
    pass


@contextmanager
def _counted(plan):
    """Count the questions a quote asks, and stop it the moment one goes over.

    Per rule: how often it is asked whether it qualifies (once), how often its
    applier is asked for lines (a way: three; a special that did not qualify:
    one; a cap: once a pass). And how often two rules are compared as whole
    rules (never). Counted through the engine's own tables, so a rule asked by
    any route is counted.
    """
    qualified = {r.id for stage in engine.STAGES for r in engine._qualifying(plan, _stay(), stage)}
    ways = {r.id for r in plan.rules if r.stage in ("QUALIFY", "ACCUMULATE") and r.id in qualified}
    caps = {r.id for r in plan.rules if r.stage == "CAP"}
    passes = len(ways) + 1
    allowed = {
        r.id: (3 if r.id in ways else passes if r.id in caps else 1) for r in plan.rules
    }
    asked: Counter = Counter()
    applied: Counter = Counter()
    compared = Counter()

    def tick(counter, key, limit, what):
        counter[key] += 1
        if counter[key] > limit:
            raise _OverBudget(f"{what} {key!r} more than {limit} time(s) in one quote")

    def counting_qualifier(name):
        original = engine.QUALIFIERS[name]

        def qualifier(rule, stay, plan):
            tick(asked, rule.id, 1, "asked whether it qualifies:")
            return original(rule, stay, plan)

        return qualifier

    def counting_applier(name):
        original = RULE_APPLIERS[name]

        def applier(rule, *args, **kwargs):
            tick(applied, rule.id, allowed[rule.id], "asked for its lines:")
            return original(rule, *args, **kwargs)

        return applier

    original_eq = Rule.__eq__

    def counting_eq(self, other):
        tick(compared, "rules", 0, "two rules compared field by field:")
        return original_eq(self, other)

    with pytest.MonkeyPatch.context() as patch:
        for name in list(engine.QUALIFIERS):
            patch.setitem(engine.QUALIFIERS, name, counting_qualifier(name))
        for name in ("time_window", "increment", "daily_max", "weekly_max"):
            patch.setitem(RULE_APPLIERS, name, counting_applier(name))
        patch.setattr(Rule, "__eq__", counting_eq)
        yield {"asked": asked, "applied": applied, "compared": compared,
               "ways": ways, "caps": caps, "passes": passes}


@pytest.mark.guarantee("F64")
@pytest.mark.parametrize("mode", ["cheapest_wins", "stated_order"])
def test_400_ways_are_each_priced_once_and_nothing_is_asked_per_pair(mode):
    rules = ([HOURLY, DAILY, WEEKLY] + [_flat(i) for i in range(300)]
             + [_rate(i) for i in range(99)] + [_weekend_flat(i) for i in range(100)])
    plan = load_plan(_plan(rules, mode))
    with _counted(plan) as counts:
        result = quote([plan], _stay())

    assert len(counts["ways"]) == 400  # 300 specials, the hourly rate and 99 more
    # Every rule was asked, and once: the gaps, the conflicts and all 401 passes
    # share one answer.
    assert set(counts["asked"]) == {r.id for r in plan.rules}
    assert max(counts["asked"].values()) == 1
    assert counts["compared"]["rules"] == 0
    # A special that did not qualify was asked for its line once, not 401 times.
    weekend = [r.id for r in plan.rules if r.id.startswith("weekend-")]
    assert {counts["applied"][i] for i in weekend} == {1}
    # Each cap ran once a pass: the stay was priced 401 times, and no more.
    for cap in counts["caps"]:
        assert counts["applied"][cap] == counts["passes"] == 401

    # And the answer is the cheapest way's (F63): the lowest flat, one price for
    # the stay, 1000.00, against the hour's 1300.00 over 13 weeks.
    assert result.fee_minor == 100_000
    codes = Counter(line.code for line in result.breakdown.lines)
    # The other 299 specials say they lost; the one line comparing the time-based
    # way says what it would have charged; the 100 weekend specials say why not.
    assert codes["resolved"] == 299
    assert codes["special_used"] == 1
    assert codes["time_window.not_applied"] == 100


@pytest.mark.guarantee("F64")
def test_the_counters_see_a_quote_that_asks_again():
    """The counters' own control: a quote asked twice in one count is over every
    budget at once, so a pass that asked again could not hide under them."""
    plan = load_plan(_plan([HOURLY, DAILY, _flat(1), _flat(2)]))
    with _counted(plan), pytest.raises(_OverBudget, match="qualifies"):
        quote([plan], _stay())
        quote([plan], _stay())


@contextmanager
def _time_budget(seconds: float):
    """Stop the code inside after `seconds` of wall time, where the platform has
    a real-time interval timer; elsewhere it runs to the end and is timed."""
    if not hasattr(signal, "setitimer"):
        yield
        return

    def expired(signum, frame):
        raise _OverBudget(f"the quote ran past its budget of {seconds} s")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.guarantee("F64")
def test_400_qualifying_specials_are_priced_within_a_fixed_time_budget():
    rules = ([HOURLY, DAILY, WEEKLY] + [_flat(i) for i in range(400)]
             + [_weekend_flat(i) for i in range(400)])
    document = _plan(rules)
    plan = load_plan(document)
    stay = _stay()

    started = time.perf_counter()
    with _time_budget(TIME_BUDGET_SECONDS):
        result = quote([plan], stay)
    took = time.perf_counter() - started

    assert took < TIME_BUDGET_SECONDS, f"{took:.2f} s for 400 qualifying specials"
    assert result.fee_minor == 100_000
    assert sum(1 for line in result.breakdown.lines if line.code == "resolved") == 399
