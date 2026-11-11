"""F34 -- "two rules qualified" means three different things, and the stage says which.

**The defect this closes was latent and load-bearing.** `find_conflicts` reported
a conflict whenever more than one rule qualified at ANY stage. That is right at
QUALIFY -- two specials are competing bases and only one can be the price -- and
it is wrong everywhere else. It stayed harmless only because the first version shipped one rule
type per stage, so no plan could reach the wrong branch. `weekly_max` reaches it,
and `time_window` at ADJUST reaches it twice over.

So stages.py carries three categories and this file holds all three arms. Testing
only the widening would leave "the engine no longer refuses anything" passing
every check.

* **RESOLVING** (QUALIFY, ACCUMULATE) -- an either/or, and the plan's mode
  always settles it: the cheaper wins, and since a later fix a tie at the cheapest charge
  is priced at that charge. `tests/test_f48_a_tie_at_the_cheapest_charge_is_priced.py`
  is the other half of this arm.
* **COMPOSING, order-independent** (CAP, SURCHARGE) -- both apply and the total
  is the same either way. Not reported at all: there is nothing to decide.
* **COMPOSING, order-dependent** (ADJUST) -- both apply and the order changes the
  money, so the plan states it. See F35.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote
from rate_engine.findings import CONFLICT_UNORDERED_ADJUSTMENTS
from rate_engine.stages import (
    COMPOSING_ORDER_DEPENDENT,
    COMPOSING_ORDER_INDEPENDENT,
    RESOLVING,
    STAGES,
)

RESOLUTION = {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}}
EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}


def _window(rule_id: str, stage: str, price: int) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": stage,
        "space_classes": ["standard"], "label": f"Window {rule_id}",
        "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
        "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "flat", "price_minor": price},
    }


def _adjust(rule_id: str) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "ADJUST",
        "space_classes": ["standard"], "label": f"Adjust {rule_id}",
        "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
        "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "adjust", "direction": "discount",
                   "amount": {"kind": "fixed", "minor": 100}, "rounding": "down"},
    }


BASE_RULES = [
    {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
     "space_classes": ["standard"], "first_period_minutes": 60,
     "first_period_minor": 800, "repeat_period_minutes": 60,
     "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
]


def _plan(extra: list[dict], adjust_order=None) -> dict:
    return {
        "plan_version": "categories-2026-03",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD",
        "space_classes": ["standard"],
        "resolution": RESOLUTION,
        "adjust_order": adjust_order,
        "rules": copy.deepcopy(BASE_RULES) + copy.deepcopy(extra),
        "decisions": [],
    }


def _quote(plan: dict):
    return run_quote(
        {
            "plans": [plan], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T12:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def test_every_stage_falls_in_EXACTLY_ONE_category():
    """The control on the categories themselves, and it runs first.

    A stage in none of them would fall through `find_conflicts` silently, which
    is how a stage stops being checked at all. Derived from STAGES rather than
    from a list here, so a stage added later is covered the day it exists.
    """
    categorised = RESOLVING | COMPOSING_ORDER_INDEPENDENT | COMPOSING_ORDER_DEPENDENT
    assert categorised == set(STAGES)
    for stage in STAGES:
        membership = [
            stage in RESOLVING,
            stage in COMPOSING_ORDER_INDEPENDENT,
            stage in COMPOSING_ORDER_DEPENDENT,
        ]
        assert sum(membership) == 1, f"{stage} is in {sum(membership)} categories"


@pytest.mark.guarantee("F34")
def test_two_rules_at_a_RESOLVING_stage_are_settled_by_the_mode_TIE_INCLUDED():
    """Two specials cannot both be the price, and the plan's mode says which. The
    cheaper wins; at the same price the driver pays that price either way, so the
    stay is priced (F48) rather than refused, and only ONE of them is applied."""
    status, body = _quote(_plan([_window("win-a", "QUALIFY", 1200),
                                 _window("win-b", "QUALIFY", 1200)]))
    assert status == 200, body
    assert body["fee_minor"] == 1200
    applied = [ln["rule_id"] for ln in body["breakdown"] if ln["code"] == "time_window.applied"]
    assert applied == ["win-a"], f"not exactly one base applied: {applied}"

    # And at different prices the cheaper one, whichever id it carries.
    status, priced = _quote(_plan([_window("win-a", "QUALIFY", 1500),
                                   _window("win-b", "QUALIFY", 1200)]))
    assert status == 200, priced
    assert priced["fee_minor"] == 1200


@pytest.mark.guarantee("F34")
def test_two_rules_at_an_ORDER_INDEPENDENT_composing_stage_are_NOT_a_conflict():
    """Two caps are two ceilings, not a contradiction. This is the plan that
    would have refused every stay in the garage."""
    both_caps = _plan([
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000,
         "day_boundary": "calendar_day"},
        {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 2500,
         "week_boundary": "calendar_week", "week_starts_on": "mon"},
    ])
    status, body = _quote(both_caps)
    assert status == 200, f"two caps were reported as a conflict: {body}"


@pytest.mark.guarantee("F34")
def test_two_SURCHARGES_are_not_a_conflict_either_and_BOTH_apply():
    """The other order-independent stage, and the arm that says "not a conflict"
    means "both applied" rather than "one was dropped"."""
    two = _plan([
        {"id": "surcharge-a", "type": "space_surcharge", "stage": "SURCHARGE",
         "space_classes": ["standard"], "surcharge_minor": 300},
        {"id": "surcharge-b", "type": "space_surcharge", "stage": "SURCHARGE",
         "space_classes": ["standard"], "surcharge_minor": 700},
    ])
    status, body = _quote(two)
    assert status == 200, body
    assert body["fee_minor"] == 1600 + 300 + 700, (
        "one of the two surcharges was silently dropped"
    )
    ids = [ln["rule_id"] for ln in body["breakdown"]]
    assert "surcharge-a" in ids and "surcharge-b" in ids


@pytest.mark.guarantee("F34")
def test_two_rules_at_the_ORDER_DEPENDENT_stage_are_refused_under_their_OWN_code():
    """A third answer, and a third code. "Which of these is the price" and "in
    what order do these both apply" are different questions, and a consumer
    routing on the code has to be able to tell them apart."""
    status, body = _quote(_plan([_adjust("adj-a"), _adjust("adj-b")]))
    assert status == 422, body
    finding = body["findings"][0]
    assert finding["code"] == CONFLICT_UNORDERED_ADJUSTMENTS


@pytest.mark.guarantee("F34")
def test_COMPOSING_rules_are_applied_in_ASCENDING_RULE_ID_never_array_position():
    """Deciding money by the order of a JSON list, silently, is a defect this
    module has already shipped once. The breakdown must be identical whichever
    order the caller wrote the rules in."""
    forwards = _plan([
        {"id": "surcharge-a", "type": "space_surcharge", "stage": "SURCHARGE",
         "space_classes": ["standard"], "surcharge_minor": 300},
        {"id": "surcharge-b", "type": "space_surcharge", "stage": "SURCHARGE",
         "space_classes": ["standard"], "surcharge_minor": 700},
    ])
    backwards = copy.deepcopy(forwards)
    backwards["rules"] = [backwards["rules"][0]] + backwards["rules"][:0:-1]

    _s, first = _quote(forwards)
    _s, second = _quote(backwards)
    assert first["breakdown"] == second["breakdown"], (
        "the caller's array order changed the receipt"
    )
    assert [ln["rule_id"] for ln in first["breakdown"] if ln["rule_id"]
            and ln["rule_id"].startswith("surcharge")] == ["surcharge-a", "surcharge-b"]
