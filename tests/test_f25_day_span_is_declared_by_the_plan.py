"""F25 -- whether a time window may run past midnight is the PLAN's decision.

The defect the outside pass settled as TRUE -- DEFECT: `_failures` compared the
exit's local date to the entry's and refused any cross-midnight stay. The rule's
own docstring said the conditions were *"entry at or before `enter_by`, exit at or
before `exit_by`"* and nothing else; `EXTRA` held three fields, none of them about
days; and the condition appeared in exactly one place in the whole repository --
the message it printed when it fired.

A stay entering Monday 08:00 and leaving Tuesday 08:00 satisfies both stated
limits and was charged **6000** where the early bird was **1200**. The plan could
not state the condition and could not remove it: every attempt was rejected as an
unknown key. That is the engine inventing a pricing decision, which is the one
thing this module exists not to do.

A multi-day early bird is rare, but garages do set unusual rates. So `day_span`
is a declared field with no default.

**The rule this guarantee was written for is now `time_window`** -- `early_bird`
was that rule with its days hardcoded to every day and its effect hardcoded to a
flat price -- and the guarantee moved with it unchanged. The BOUNDED middle case,
`next_day`, has its own guarantee: F28.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2

MONDAY_0800 = "2026-03-02T08:00:00-05:00"
TUESDAY_0800 = "2026-03-03T08:00:00-05:00"   # 24h later: both wall-clock limits met
WINDOW_PRICE = 1200
TIME_BASED = 6000


def _plan(day_span: str | None) -> dict:
    document = copy.deepcopy(DOWNTOWN_V2)
    for rule in document["rules"]:
        if rule["type"] == "time_window":
            if day_span is None:
                rule.pop("day_span", None)
            else:
                rule["day_span"] = day_span
    return document


def _overnight(document: dict):
    from rate_engine.contract import run_quote

    return run_quote(
        {
            "plans": [document], "entry_at": MONDAY_0800, "exit_at": TUESDAY_0800,
            "space_class": "standard", "currency": "USD",
        }
    )


@pytest.mark.guarantee("F25")
def test_a_plan_OMITTING_day_span_is_REFUSED():
    """No default. A missing field is a pricing decision nobody made, and this
    module refuses those rather than choosing one."""
    status, body = _overnight(_plan(None))
    assert status == 400
    assert "day_span" in body["error"]
    assert "missing required field" in body["error"]


@pytest.mark.guarantee("F25")
def test_a_plan_stating_ANY_SPAN_lets_the_overnight_stay_QUALIFY():
    """The case that was unreachable before: both wall-clock limits are met."""
    status, body = _overnight(_plan("any_span"))
    assert status == 200
    assert body["fee_minor"] == WINDOW_PRICE, (
        f"the overnight stay met both stated limits and was charged "
        f"{body['fee_minor']} instead of {WINDOW_PRICE}"
    )
    line = [x for x in body["breakdown"] if x["code"].startswith("time_window")][0]
    assert "NOT applied" not in line["text"], line["text"]


@pytest.mark.guarantee("F25")
def test_a_plan_stating_SAME_DAY_reproduces_exactly_what_shipped():
    """The old behaviour is still available and still correct -- it just has to be
    asked for now. Its refusal names the field, so an operator can see WHY."""
    status, body = _overnight(_plan("same_day"))
    assert status == 200
    assert body["fee_minor"] == TIME_BASED
    line = [x for x in body["breakdown"] if x["code"].startswith("time_window")][0]
    assert "NOT applied" in line["text"]
    assert "not the same local day" in line["text"]
    assert "day_span 'same_day'" in line["text"], (
        f"the refusal does not name the field that decided it: {line['text']}"
    )


@pytest.mark.guarantee("F25")
@pytest.mark.parametrize("bad", ["overnight", "SAME_DAY", "", "any", True, 1, None])
def test_a_value_the_engine_does_not_implement_is_REFUSED_not_guessed(bad):
    document = _plan("same_day")
    for rule in document["rules"]:
        if rule["type"] == "time_window":
            rule["day_span"] = bad
    status, body = _overnight(document)
    assert status == 400, f"{bad!r} was accepted"
    assert "day_span" in body["error"] or "boolean" in body["error"]


@pytest.mark.guarantee("F25")
def test_day_span_does_not_disturb_a_SAME_DAY_stay_under_any_value():
    """The control. `day_span` decides one thing; a stay that never crosses
    midnight must price identically whichever value the plan states."""
    from rate_engine.contract import run_quote

    fees = set()
    for value in ("same_day", "next_day", "any_span"):
        status, body = run_quote(
            {
                "plans": [_plan(value)], "entry_at": "2026-03-03T08:00:00-05:00",
                "exit_at": "2026-03-03T16:00:00-05:00", "space_class": "standard",
                "currency": "USD",
            }
        )
        assert status == 200
        fees.add(body["fee_minor"])
    assert fees == {WINDOW_PRICE}, (
        f"day_span changed the answer for a stay that never crosses midnight: {fees}"
    )


def test_the_engine_no_longer_holds_an_UNDECLARED_day_condition():
    """The property, as a structural claim rather than one scenario.

    Every condition the rule tests must be one the plan can state. This walks the
    rule's declared fields and requires the day condition to be among them -- the
    defect was precisely a condition that existed in the code and in no field.
    """
    from rate_engine.rules.time_window import DAY_SPAN_LIMITS, DAY_SPANS, EXTRA

    assert "day_span" in EXTRA, "the day condition is not a field a plan may state"
    assert set(DAY_SPANS) == {"same_day", "next_day", "any_span"}
    assert set(DAY_SPAN_LIMITS) == set(DAY_SPANS), (
        "a span a plan may state has no limit behind it, or a limit exists for a "
        "span no plan can ask for"
    )
