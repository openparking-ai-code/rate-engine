"""F30 -- an `adjust` effect applies to the fee AFTER the caps and the surcharges.

The rule: an effect is not only a percent increase or discount -- so a window's
effect can be an adjustment up or down, and it applies on the whole fee. That places it,
and the placement is not a detail of this implementation.

**A percentage taken before the cap is a percentage of a number the customer is
not being charged.** The pipeline's own docstring already made this argument for
the cap and the surcharge: a cap that ran before the surcharge would cap a number
the customer is not paying, and a surcharge after the cap would survive it. An
adjustment is the same argument one step further along, so it runs LAST.

The stay below is chosen so the two orders disagree. A stay where they happened
to agree would let this file pass against an engine that ran the adjustment
first, which is the arrangement it exists to rule out.
"""

from __future__ import annotations

import copy

import pytest

from rate_engine.contract import run_quote

RESOLUTION = {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}}

PLAN = {
    "plan_version": "adjust-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard", "vip"],
    "resolution": RESOLUTION,
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": 1440},
        {"id": "cap", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard", "vip"], "max_minor": 3000,
         "day_boundary": "calendar_day"},
        {"id": "vip-surcharge", "type": "space_surcharge", "stage": "SURCHARGE",
         "space_classes": ["vip"], "surcharge_minor": 500},
        {"id": "midweek", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard", "vip"], "label": "Midweek discount",
         "applies_on": {"kind": "days_of_week",
                        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
         "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
         "day_span": "any_span",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "percent", "percent_bp": 2000},
                    "rounding": "down"}},
    ],
    "decisions": [],
}

#: The same document stating `up`. A counterpart in the corpus, not a rewrite
#: inside one test: every percentage adjustment here used to state `down`, so a
#: comparison run over the stated documents never reached the applier's `up`
#: branch at all.
PLAN_UP = copy.deepcopy(PLAN)
PLAN_UP["rules"][3]["effect"]["rounding"] = "up"

ENTRY = "2026-03-03T09:00:00-05:00"
EXIT = "2026-03-03T19:00:00-05:00"  # 10 hours

#: 800 + 9 x 400 = 4400, capped to 3000, + 500 vip = 3500, then 20% off = 2800.
CORRECT = 2800
#: The same rules with the adjustment first: 20% off 4400 = 3520, capped to 3000,
#: + 500 = 3500. The number this file exists to distinguish 2800 from.
IF_ADJUSTED_FIRST = 3500


def _quote(plan: dict | None = None, space_class: str = "vip"):
    return run_quote(
        {
            "plans": [copy.deepcopy(plan if plan is not None else PLAN)],
            "entry_at": ENTRY, "exit_at": EXIT,
            "space_class": space_class, "currency": "USD",
        }
    )


def test_the_two_ORDERS_disagree_on_this_stay():
    """The control on the fixture, and it runs first. If these were equal, every
    assertion below would pass against an engine with the stages in any order."""
    assert CORRECT != IF_ADJUSTED_FIRST


@pytest.mark.guarantee("F30")
def test_the_fee_is_the_one_the_LAST_stage_produces():
    status, body = _quote()
    assert status == 200, body
    assert body["fee_minor"] == CORRECT, (
        f"expected the adjustment to run last ({CORRECT}); got {body['fee_minor']}"
        + (" -- which is what running it first produces"
           if body["fee_minor"] == IF_ADJUSTED_FIRST else "")
    )


@pytest.mark.guarantee("F30")
def test_the_adjust_line_names_the_TOTAL_IT_SAW_and_it_is_the_post_surcharge_one():
    """Stronger than the total, and it is what makes the ordering readable rather
    than inferred: the line states the base it took a percentage OF."""
    _status, body = _quote()
    line = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"][0]
    assert "20% discount on 35.00 USD" in line["text"], line["text"]
    assert line["delta_minor"] == -700


@pytest.mark.guarantee("F30")
def test_the_adjustment_is_the_LAST_line_in_the_breakdown():
    """The receipt reads in the order the money moved. An adjustment printed
    before the cap it was taken after would be true and unreadable."""
    _status, body = _quote()
    codes = [ln["code"] for ln in body["breakdown"]]
    assert codes[-1] == "time_window.applied", codes
    assert (
        codes.index("daily_max.applied")
        < codes.index("space_surcharge.applied")
        < len(codes) - 1
    )


@pytest.mark.guarantee("F30")
def test_an_INCREASE_moves_the_other_way_on_the_same_base():
    """The control on the direction: `discount` and `increase` must be a sign and
    not two spellings of one behaviour."""
    increased = copy.deepcopy(PLAN)
    increased["rules"][3]["effect"]["direction"] = "increase"
    increased["rules"][3]["label"] = "Event surcharge"
    status, body = _quote(increased)
    assert status == 200, body
    assert body["fee_minor"] == 3500 + 700
    line = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"][0]
    assert line["delta_minor"] == 700
    assert "700 added" not in line["text"]
    assert "7.00 USD added" in line["text"], line["text"]


@pytest.mark.guarantee("F30")
def test_the_windows_CONDITION_still_governs_an_adjust_effect():
    """It is one rule type: the days and the hours decide whether the adjustment
    happens at all, exactly as they decide whether a flat price does."""
    weekend_only = copy.deepcopy(PLAN)
    weekend_only["rules"][3]["applies_on"] = {"kind": "days_of_week", "days": ["sat", "sun"]}
    status, body = _quote(weekend_only)
    assert status == 200, body
    assert body["fee_minor"] == 3500, "a Tuesday was given the weekend adjustment"


@pytest.mark.guarantee("F30")
def test_the_STAGE_is_DERIVED_from_the_effect_and_a_plan_claiming_otherwise_is_REFUSED():
    """The document states each rule's stage so it reads on its own; the engine
    derives it from what the rule actually does. A disagreement is refused rather
    than resolved in favour of one of them."""
    mislabelled = copy.deepcopy(PLAN)
    mislabelled["rules"][3]["stage"] = "QUALIFY"
    status, body = _quote(mislabelled)
    assert status == 400
    assert "stage is 'QUALIFY'" in body["error"] and "ADJUST" in body["error"], body["error"]


@pytest.mark.guarantee("F30")
def test_a_FLAT_window_claiming_ADJUST_is_refused_by_the_same_check():
    """Both arms. A check that only caught one direction would let half the
    disagreements through."""
    mislabelled = copy.deepcopy(PLAN)
    mislabelled["rules"][3]["stage"] = "ADJUST"
    mislabelled["rules"][3]["effect"] = {"kind": "flat", "price_minor": 1000}
    status, body = _quote(mislabelled)
    assert status == 400
    assert "stage is 'ADJUST'" in body["error"] and "QUALIFY" in body["error"], body["error"]


@pytest.mark.guarantee("F31")
def test_the_UP_counterpart_adds_NOTHING_where_there_is_no_fraction():
    """`up` with no remainder: 20% of 35.00 is exactly 7.00, so `up` and `down`
    agree to the unit. The other side of the `up` branch from F31's fixture,
    which always lands on a fraction."""
    status, body = _quote(PLAN_UP)
    assert status == 200, body
    assert body["fee_minor"] == CORRECT, body["fee_minor"]
    line = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"][0]
    assert line["delta_minor"] == -700, line
