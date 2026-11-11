"""F37 -- a stated order names every rule at its stage, exactly once, or is refused.

**A rule left out of the order would take a silent position in it.** That is the
array-order disease this module already refuses at `select_plan`, where two plan
versions sharing an effective date used to be settled by whichever the caller
happened to put first in a JSON list -- 300 or 2700 minor units for the same car,
with nothing said. An order that names two of three rules is the same defect
wearing a field name: the third one still has to go somewhere, and wherever the
implementation puts it is a decision nobody wrote down.

**Refused at LOAD, not at quote time.** It is a property of the plan and not of
any particular stay, so an owner meets it while writing the document -- and
`validate-plan` reports it -- rather than when a particular car happens to
trigger both rules on a Tuesday.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote

EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}


def _window(rule_id: str, price: int) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": f"Window {rule_id}",
        "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
        "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "flat", "price_minor": price},
    }


BASE = {
    "plan_version": "order-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York", "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {
        "QUALIFY": {"mode": "stated_order", "order": ["a", "b"]},
        "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        _window("a", 1200),
        _window("b", 1500),
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _quote(document: dict):
    return run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T13:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def _with_order(order) -> dict:
    document = copy.deepcopy(BASE)
    document["resolution"]["QUALIFY"] = {"mode": "stated_order", "order": order}
    return document


def test_the_complete_order_LOADS_and_prices():
    """The control, and it runs first. If the valid case were refused too, every
    assertion below would pass against a loader that rejected everything."""
    status, body = _quote(copy.deepcopy(BASE))
    assert status == 200, body
    assert body["fee_minor"] == 1200


@pytest.mark.guarantee("F37")
def test_an_order_that_OMITS_a_rule_at_its_stage_is_REFUSED_naming_it():
    status, body = _quote(_with_order(["a"]))
    assert status == 400, body
    assert "resolution.QUALIFY.order" in body["error"], body["error"]
    assert "Missing: b" in body["error"], body["error"]


@pytest.mark.guarantee("F37")
def test_an_order_naming_a_rule_from_ANOTHER_STAGE_is_REFUSED_naming_it():
    """The other direction. An order carrying an ACCUMULATE rule id reads as a
    decision about QUALIFY and is not one."""
    status, body = _quote(_with_order(["a", "b", "hourly"]))
    assert status == 400, body
    assert "Not a QUALIFY rule in this plan: hourly" in body["error"], body["error"]


@pytest.mark.guarantee("F37")
def test_an_order_naming_a_rule_TWICE_is_REFUSED():
    status, body = _quote(_with_order(["a", "b", "a"]))
    assert status == 400, body
    assert "names a rule more than once" in body["error"], body["error"]


@pytest.mark.guarantee("F37")
@pytest.mark.parametrize("order", ["a,b", [1, 2], None, {"a": 1}])
def test_an_order_that_is_not_a_LIST_OF_RULE_IDS_is_REFUSED(order):
    status, body = _quote(_with_order(order))
    assert status == 400, f"{order!r} was accepted"
    assert "must be a list of rule ids" in body["error"], body["error"]


@pytest.mark.guarantee("F37")
def test_stated_order_WITHOUT_an_order_is_REFUSED():
    """No default, and no silent fallback to the plan's array order."""
    document = copy.deepcopy(BASE)
    document["resolution"]["QUALIFY"] = {"mode": "stated_order"}
    status, body = _quote(document)
    assert status == 400, body
    assert "missing required field(s): order" in body["error"], body["error"]


@pytest.mark.guarantee("F37")
def test_an_ORDER_given_to_cheapest_wins_is_REFUSED_rather_than_ignored():
    """`order` means nothing to `cheapest_wins`, and a key this version cannot
    act on is rejected by name -- an ignored key is how a plan an operator
    believes is live prices something else."""
    document = copy.deepcopy(BASE)
    document["resolution"]["QUALIFY"] = {"mode": "cheapest_wins", "order": ["b", "a"]}
    status, body = _quote(document)
    assert status == 400, body
    assert "order" in body["error"] and "does not understand" in body["error"], body["error"]


@pytest.mark.guarantee("F37")
def test_the_refusal_reaches_VALIDATE_PLAN_too():
    """It is a property of the plan, so an owner meets it where plans are
    checked rather than when a particular car leaves."""
    from rate_engine.contract import run_validate

    status, body = run_validate({"plan": _with_order(["a"])})
    assert status == 400, body
    assert "Missing: b" in body["error"], body["error"]
