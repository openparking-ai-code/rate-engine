"""F32 -- grace is FREE, and free means free.

The rule: some garages use a grace period, usually 10 minutes but it differs
from garage to garage, and a customer who leaves within that period pays nothing.

**"Free" is the whole guarantee, and it is not "grace returns a zero line".**
A rule that priced the stay at zero and then let a VIP surcharge, a daily cap and
a weekend adjustment run after it would return a zero line and charge the
customer five dollars. So the property measured here is the TOTAL, on a plan
carrying one of each -- and the control plants terminality off and requires red,
because a plan with no surcharge could not tell the two behaviours apart.

**Terminality is DECLARED by the rule type, not known by the engine.** An
`if rule.type == "grace"` in the pipeline would be the engine holding a pricing
decision no plan can see or change, which is the defect `day_span` was created to
undo. The type registers `TERMINAL`; the engine reads the declaration.

**And a special it beat is not dropped silently.** "Why is the early bird not on
here?" is the question the specification exists to make answerable, so the window that also
qualified gets a line saying it was superseded and by what.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

RESOLUTION = {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}}
EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}

#: One of everything that could possibly add to a free stay: a base, a cap, a
#: surcharge on the class being priced, and an adjustment. If any of them runs,
#: the fee is not zero and this file says so.
PLAN = {
    "plan_version": "grace-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard", "vip"],
    "resolution": RESOLUTION,
    "adjust_order": None,
    "rules": [
        {"id": "grace-10", "type": "grace", "stage": "QUALIFY",
         "space_classes": ["standard", "vip"], "minutes": 10},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard", "vip"], "max_minor": 3000,
         "day_boundary": "calendar_day"},
        {"id": "vip-surcharge", "type": "space_surcharge", "stage": "SURCHARGE",
         "space_classes": ["vip"], "surcharge_minor": 500},
        {"id": "always-up", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard", "vip"], "label": "Event surcharge",
         "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
         "exit_by": "23:59", "day_span": "any_span",
         "effect": {"kind": "adjust", "direction": "increase",
                    "amount": {"kind": "fixed", "minor": 250}, "rounding": "up"}},
    ],
    "decisions": [],
}

ENTRY = "2026-03-03T09:00:00-05:00"


def _quote(minutes: int, space_class: str = "vip", plan: dict | None = None):
    entry_at = parse_instant(ENTRY, "entry")
    return run_quote(
        {
            "plans": [copy.deepcopy(plan if plan is not None else PLAN)],
            "entry_at": ENTRY,
            "exit_at": (entry_at + timedelta(minutes=minutes)).isoformat(),
            "space_class": space_class, "currency": "USD",
        }
    )


def test_the_fixture_has_something_for_grace_to_SUPPRESS():
    """The control on the fixture, and it runs first.

    A stay one minute over the grace must be charged by a base AND a surcharge
    AND an adjustment. On a plan carrying none of those, "the graced stay is
    free" would hold against a grace rule that was not terminal at all.
    """
    status, body = _quote(11)
    assert status == 200, body
    codes = [ln["code"] for ln in body["breakdown"]]
    assert "increment.first_period" in codes
    assert "space_surcharge.applied" in codes
    assert "time_window.applied" in codes
    assert body["fee_minor"] == 800 + 500 + 250


@pytest.mark.guarantee("F32")
def test_a_graced_stay_is_FREE_even_with_a_surcharge_a_cap_and_an_adjust():
    status, body = _quote(8)
    assert status == 200, body
    assert body["fee_minor"] == 0, (
        f"a graced stay was charged {body['fee_minor']}: "
        f"{[ln['code'] for ln in body['breakdown']]}"
    )


@pytest.mark.guarantee("F32")
def test_and_NOTHING_after_QUALIFY_appears_on_the_receipt_at_all():
    """Stronger than the total, and it is what makes the reason readable: a
    graced receipt shows the grace and nothing else, rather than a list of
    charges that happen to cancel."""
    _status, body = _quote(8)
    codes = [ln["code"] for ln in body["breakdown"]]
    assert codes == ["stay", "grace.applied"], codes


@pytest.mark.guarantee("F32")
def test_grace_is_ALL_OR_NOTHING_one_minute_over_prices_from_ENTRY():
    """Not from minute ten. The specification's all-conditions rule, and the ordinary garage
    convention."""
    _s, graced = _quote(10)
    _s, over = _quote(11)
    assert graced["fee_minor"] == 0
    assert over["fee_minor"] == 800 + 500 + 250, (
        "the stay was priced from the end of the grace rather than from entry"
    )
    line = [ln for ln in over["breakdown"] if ln["code"] == "grace.not_applied"][0]
    assert "the stay was 11 min, which is 1 over" in line["text"], line["text"]


@pytest.mark.guarantee("F32")
def test_grace_BEATS_a_window_that_also_qualified_and_the_window_SAYS_SO():
    """Terminality is an outright win, so it is not a conflict for the plan to
    settle -- and the special that lost is named rather than dropped."""
    with_window = copy.deepcopy(PLAN)
    with_window["rules"].append(
        {"id": "eb-weekday", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard", "vip"], "label": "Early bird",
         "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
         "exit_by": "23:59", "day_span": "any_span",
         "effect": {"kind": "flat", "price_minor": 1200}}
    )
    status, body = _quote(8, plan=with_window)
    assert status == 200, body
    assert body["fee_minor"] == 0, "the window's price was charged over the grace"

    line = [ln for ln in body["breakdown"] if ln["code"] == "superseded"][0]
    assert line["rule_id"] == "eb-weekday"
    assert line["delta_minor"] == 0
    assert line["text"].startswith("Early bird also qualified and was NOT applied"), (
        f"the receipt names a rule by its database key rather than by what the "
        f"operator called it: {line['text']}"
    )
    assert "grace-10 prices this stay by itself" in line["text"], line["text"]


@pytest.mark.guarantee("F32")
def test_terminality_is_DECLARED_BY_THE_TYPE_and_not_known_by_the_engine():
    """The structural half. An engine that knew the string "grace" would price
    this identically today and would be the defect anyway, so the claim is
    checked where it lives.

    Read from the AST rather than by searching the text, and over EVERY
    registered type rather than this one: a comment naming a rule type is fine
    -- `quote` has one, pointing a reader at rules/grace.py -- and a string
    LITERAL compared against `rule.type` is not. Grepping the source would
    confuse the two, which is measuring the wrong thing.
    """
    import ast
    import inspect
    import textwrap

    from rate_engine import engine
    from rate_engine.rules import RULE_TRAITS, RULE_TYPES, TERMINAL

    assert TERMINAL in RULE_TRAITS["grace"], "the type does not declare terminality"

    tree = ast.parse(textwrap.dedent(inspect.getsource(engine.quote)))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    named = sorted(literals & set(RULE_TYPES))
    assert not named, (
        f"the pipeline carries the rule type name(s) {', '.join(named)} as a string "
        "literal -- that is the engine holding a pricing decision no plan can see"
    )


@pytest.mark.guarantee("F32")
def test_a_ZERO_LENGTH_stay_is_FREE_under_a_plan_that_declares_grace():
    """The consequence the specification records, and the one that qualifies a decision already
    published: "a stay of zero length pays the first period" describes a garage
    that declares NO grace, and the contract now says so."""
    _s, with_grace = _quote(0)
    assert with_grace["fee_minor"] == 0

    without = copy.deepcopy(PLAN)
    without["rules"] = [r for r in without["rules"] if r["id"] != "grace-10"]
    _s, no_grace = _quote(0, plan=without)
    assert no_grace["fee_minor"] == 800 + 500 + 250, (
        "the published decision changed for a plan that declares no grace"
    )


@pytest.mark.guarantee("F32")
@pytest.mark.parametrize("bad", [0, -5, 10.5, True, "10", None])
def test_a_grace_the_engine_cannot_read_is_REFUSED(bad):
    """No default, and no grace unless the plan states one. A grace of zero is
    not a grace period, it is the absence of one."""
    document = copy.deepcopy(PLAN)
    for rule in document["rules"]:
        if rule["id"] == "grace-10":
            rule["minutes"] = bad
    status, body = _quote(8, plan=document)
    assert status == 400, f"{bad!r} was accepted"
    assert "minutes" in body["error"] or "float" in body["error"], body["error"]
