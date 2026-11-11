"""F51 -- the fill rule prices on how full the garage was when the car came in.

"When the garage is at least X% full, the time-based charge is Y% more." The
figure is `occupancy_at_entry_bp`, handed in by the caller when the stay opened,
and it is read at entry and only at entry: the cars inside keep the price they
came in on.

**The fixture straddles every edge on purpose.** 80% full is 8000 basis points,
so the stays sit at 7999 (not raised), 8000 (raised: the rule applies AT the
threshold) and 10000. The charge is chosen so the plants each move a different
number: 3 hours at 8.00 + 2 x 4.00 = 16.00 by the hour, +20% = 3.20; a 10.00 daily
most makes a long stay's time charge 10.00, so a rule raising the UNcapped 44.00
is caught; and a 5.00 VIP surcharge on top makes a rule raising the running total
(21.00) rather than the time (16.00) charge 4.20 instead of 3.20.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import stay
from rate_engine.contract import run_quote
from rate_engine.engine import make_stay, quote
from rate_engine.findings import (
    CONFLICT_OVERLAPPING_FILL_RULES,
    CONFLICT_UNORDERED_ADJUSTMENTS,
    GAP_NO_OCCUPANCY_AT_ENTRY,
    Refused,
)
from rate_engine.plan import InvalidPlan, load_plan, parse_instant

#: Tuesday 2026-03-03, New York, 10:00 -- after any early bird.
TEN = "2026-03-03T10:00:00-05:00"
THREE_HOURS = 180
#: 10:00 to 23:00, thirteen hours: 8.00 + 12 x 4.00 = 56.00 by the hour.
THIRTEEN_HOURS = 780

FILL = {
    "id": "busy", "type": "fill_level", "stage": "ADJUST",
    "space_classes": ["standard", "vip"],
    "threshold_bp": 8000, "percent_bp": 2000, "rounding": "up",
    # The first version's behaviour, so every test here means what it meant; the four
    # combinations are F54's.
    "raises_specials": "yes", "raises_vip_extra": "no",
}

PLAN = {
    "plan_version": "fill-2026",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard", "vip"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
        FILL,
    ],
    "decisions": [],
}

CAP = {"id": "day", "type": "daily_max", "stage": "CAP", "space_classes": ["standard", "vip"],
       "max_minor": 1000, "day_boundary": "calendar_day"}
VIP = {"id": "vip", "type": "space_surcharge", "stage": "SURCHARGE", "space_classes": ["vip"],
       "surcharge_minor": 500}
MEMBERS = {
    "id": "members", "type": "time_window", "stage": "ADJUST",
    "space_classes": ["standard", "vip"], "label": "Members",
    "applies_on": {"kind": "days_of_week",
                   "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
    "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59", "day_span": "any_span",
    "effect": {"kind": "adjust", "direction": "discount",
               "amount": {"kind": "percent", "percent_bp": 1000}, "rounding": "down"},
}


def _plan(*extra_rules, **changes) -> dict:
    document = copy.deepcopy(PLAN)
    document["rules"].extend(copy.deepcopy(list(extra_rules)))
    document.update(changes)
    return document


def _without_fill(document: dict) -> dict:
    document = copy.deepcopy(document)
    document["rules"] = [r for r in document["rules"] if r["type"] != "fill_level"]
    return document


def _at(minutes: int, figure, space_class: str = "standard"):
    entry_at = parse_instant(TEN, "entry")
    from datetime import timedelta

    return make_stay(entry_at, entry_at + timedelta(minutes=minutes), space_class, figure)


def _quote(document: dict, at):
    return quote([load_plan(copy.deepcopy(document))], at)


def _lines(result, code: str):
    return [ln for ln in result.breakdown.lines if ln.code == code]


def test_the_fixture_prices_as_worked_by_hand():
    """The control on the fixture: with no fill rule the three stays are 16.00,
    56.00 and, capped, 10.00 -- the numbers every assertion below is worked from."""
    plain = _without_fill(PLAN)
    assert _quote(plain, _at(THREE_HOURS, None)).fee_minor == 1600
    assert _quote(plain, _at(THIRTEEN_HOURS, None)).fee_minor == 5600
    assert _quote(_without_fill(_plan(CAP)), _at(THIRTEEN_HOURS, None)).fee_minor == 1000


@pytest.mark.guarantee("F51")
def test_the_rule_applies_AT_the_threshold_and_not_one_point_below():
    below = _quote(PLAN, _at(THREE_HOURS, 7999))
    at = _quote(PLAN, _at(THREE_HOURS, 8000))
    full = _quote(PLAN, _at(THREE_HOURS, 10000))
    assert below.fee_minor == 1600
    assert at.fee_minor == 1920
    assert full.fee_minor == 1920


@pytest.mark.guarantee("F51")
def test_the_lines_say_how_full_and_by_how_much_in_plain_words():
    applied = _lines(_quote(PLAN, _at(THREE_HOURS, 8400)), "fill_level.applied")
    assert len(applied) == 1
    assert applied[0].delta_minor == 320
    assert applied[0].text == (
        "Garage was 84% full at entry (at or above 80%): time-based charge "
        "+20% on 16.00 USD -- 3.20 USD added"
    ), applied[0].text

    declined = _lines(_quote(PLAN, _at(THREE_HOURS, 6200)), "fill_level.not_applied")
    assert len(declined) == 1 and declined[0].delta_minor == 0
    assert declined[0].text == (
        "Garage was 62% full at entry (below 80%): time-based charge not raised"
    ), declined[0].text


@pytest.mark.guarantee("F51")
def test_a_class_the_rule_does_not_cover_gets_no_line_and_needs_no_figure():
    document = _plan()
    document["rules"][1]["space_classes"] = ["vip"]
    result = _quote(document, _at(THREE_HOURS, None, "standard"))
    assert result.fee_minor == 1600
    assert not [ln for ln in result.breakdown.lines if ln.code.startswith("fill_level")]


@pytest.mark.guarantee("F51")
def test_it_raises_the_CAPPED_time_charge_not_the_uncapped_one():
    """13 hours is 56.00 by the hour and 10.00 under the daily most; +20% of the
    charge actually made is 2.00, not 11.20."""
    result = _quote(_plan(CAP), _at(THIRTEEN_HOURS, 9000))
    assert result.fee_minor == 1200
    assert _lines(result, "fill_level.applied")[0].delta_minor == 200


@pytest.mark.guarantee("F51")
def test_it_raises_the_time_charge_and_NOT_the_vip_surcharge():
    """16.00 for the time, 5.00 VIP on top: +20% is 3.20, never 4.20."""
    result = _quote(_plan(VIP), _at(THREE_HOURS, 9000, "vip"))
    assert result.fee_minor == 1600 + 500 + 320


@pytest.mark.guarantee("F51")
def test_with_a_percent_discount_it_comes_off_first_and_the_fill_rule_raises_what_is_left():
    """Members 10% off and the fill rule both apply, so `adjust_order` is required.
    The rule (2026-10-14), always the cheaper: the discount comes off first and
    the fill rule raises what is left -- 16.00 - 1.60 = 14.40, then +20% of 14.40,
    2.88: 17.28. Before the fix it raised the time charge before the discount,
    16.00 - 1.60 + 3.20 = 17.60 (gate finding F1). The fill rule anywhere but last
    is refused by name."""
    unordered = _plan(MEMBERS)
    with pytest.raises(Refused) as caught:
        _quote(unordered, _at(THREE_HOURS, 9000))
    assert [f.code for f in caught.value.findings] == [CONFLICT_UNORDERED_ADJUSTMENTS]

    members_first = _plan(MEMBERS, adjust_order=["members", "busy"])
    result = _quote(members_first, _at(THREE_HOURS, 9000))
    assert result.fee_minor == 1728
    assert _lines(result, "fill_level.applied")[0].delta_minor == 288
    with pytest.raises(InvalidPlan, match="fill rule"):
        load_plan(_plan(MEMBERS, adjust_order=["busy", "members"]))
    # Below the threshold only the discount applies.
    assert _quote(members_first, _at(THREE_HOURS, 7000)).fee_minor == 1440


#: The gate's F1 case: 10.00 for the hour, a 20% or a 2.00 discount, 90% full, +20%.
GATE_HOURLY = {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
               "space_classes": ["standard", "vip"], "first_period_minutes": 60,
               "first_period_minor": 1000, "repeat_period_minutes": 60,
               "repeat_period_minor": 1000, "rounding": "ceil", "max_duration_minutes": None}
ONE_HOUR = 60
#: 2.00 off a 10.00 hour, as a percent and as a flat amount.
TWO_DISCOUNTS = [{"kind": "percent", "percent_bp": 2000}, {"kind": "fixed", "minor": 200}]


def _discount(amount: dict) -> dict:
    rule = copy.deepcopy(MEMBERS)
    rule["id"], rule["label"] = "off", "Evening discount"
    rule["effect"]["amount"] = amount
    return rule


def _gate_plan(amount: dict, *extra, fill=None) -> dict:
    document = _plan(_discount(amount), *extra, adjust_order=["off", "busy"])
    document["rules"][0] = copy.deepcopy(GATE_HOURLY)
    if fill:
        document["rules"][1].update(fill)
    return document


@pytest.mark.guarantee("F51")
@pytest.mark.parametrize("amount", TWO_DISCOUNTS)
def test_the_gates_case_a_discount_then_the_fill_rule_on_what_is_left_is_960(amount):
    """F1: 10.00, 2.00 off (20% or flat), 90% full, +20%: 8.00 + 1.60 = 9.60, never
    10.00. The line says what was raised: the 8.00 left after the discount."""
    result = _quote(_gate_plan(amount), _at(ONE_HOUR, 9000))
    assert result.fee_minor == 960
    assert result.fee_minor == sum(ln.delta_minor for ln in result.breakdown.lines)
    line = _lines(result, "fill_level.applied")[0]
    assert line.delta_minor == 160
    assert "after discounts +20% on 8.00 USD" in line.text, line.text
    # The control: with no discount the fill rule raises the whole 10.00, and the
    # line does not speak of a discount.
    plain = _quote(_plan(adjust_order=None) | {"rules": [GATE_HOURLY, FILL]}, _at(ONE_HOUR, 9000))
    assert plain.fee_minor == 1200
    assert "after discounts" not in _lines(plain, "fill_level.applied")[0].text


@pytest.mark.guarantee("F51")
@pytest.mark.parametrize("amount", TWO_DISCOUNTS)
def test_the_fill_rule_before_a_discount_is_refused_by_name(amount):
    """Raised first and discounted after, a flat 2.00 would cost 10.00 instead of
    9.60. No plan may state it."""
    document = _gate_plan(amount)
    document["adjust_order"] = ["busy", "off"]
    with pytest.raises(InvalidPlan, match=r"adjust_order must put the fill rule \(busy\)"):
        load_plan(document)


@pytest.mark.guarantee("F51")
def test_a_discount_larger_than_the_time_charge_comes_off_the_extra_and_the_rest_is_raised():
    """VIP 5.00 extra, raised by the fill rule; 12.00 off. 15.00 - 12.00 = 3.00 is
    all extra (the discount takes the 10.00 of time first), so the time is raised
    by nothing and the extra by 20% of 3.00: 3.60. Raised first it would be
    18.00 - 12.00 = 6.00."""
    document = _gate_plan({"kind": "fixed", "minor": 1200}, VIP, fill={"raises_vip_extra": "yes"})
    result = _quote(document, _at(ONE_HOUR, 9000, "vip"))
    assert result.fee_minor == 360
    assert [ln.delta_minor for ln in _lines(result, "fill_level.extra_raised")] == [60]
    assert [ln.delta_minor for ln in _lines(result, "fill_level.applied")] == [0]


@pytest.mark.guarantee("F51")
def test_a_special_that_prices_the_stay_is_the_time_charge_raised():
    """A flat 12.00 all-day special at 90% full: the charge for the time is the
    special, and it is raised to 14.40 -- the stay is priced both ways and the
    cheaper charged, the hour's way being 56.00 + 11.20."""
    special = {
        "id": "all-day", "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": "All day",
        "applies_on": {"kind": "days_of_week", "days": ["tue"]},
        "enter_from": "06:00", "enter_by": "11:00", "exit_by": "23:30",
        "day_span": "same_day", "effect": {"kind": "flat", "price_minor": 1200},
    }
    result = _quote(_plan(special), _at(THIRTEEN_HOURS, 9000))
    assert result.fee_minor == 1440
    assert _lines(result, "fill_level.applied")[0].delta_minor == 240


@pytest.mark.guarantee("F51")
def test_the_rounding_is_the_rules_and_the_line_says_so():
    """10:00 to 10:20 is one period, 8.00. 3.33% of it is 0.2664: up is 0.27, down
    is 0.26, and each line says which way it went. 20% of 8.00 is exactly 1.60,
    and a line claiming it was rounded would be false."""
    up = _plan()
    up["rules"][1]["percent_bp"] = 333
    down = copy.deepcopy(up)
    down["rules"][1]["rounding"] = "down"
    up_line = _lines(_quote(up, _at(20, 9000)), "fill_level.applied")[0]
    down_line = _lines(_quote(down, _at(20, 9000)), "fill_level.applied")[0]
    assert (up_line.delta_minor, down_line.delta_minor) == (27, 26)
    assert "(rounded up)" in up_line.text and "(rounded down)" in down_line.text
    exact = _lines(_quote(PLAN, _at(20, 9000)), "fill_level.applied")[0]
    assert exact.delta_minor == 160 and "rounded" not in exact.text


@pytest.mark.guarantee("F51")
def test_the_breakdown_is_the_fee_with_the_rule_applied():
    result = _quote(_plan(CAP, VIP, MEMBERS, adjust_order=["members", "busy"]),
                    _at(THIRTEEN_HOURS, 9500, "vip"))
    assert result.fee_minor == sum(ln.delta_minor for ln in result.breakdown.lines)


# --- never a guess -------------------------------------------------------------


@pytest.mark.guarantee("F51")
def test_a_covered_stay_with_NO_figure_is_refused_naming_the_cause():
    with pytest.raises(Refused) as caught:
        _quote(PLAN, _at(THREE_HOURS, None))
    findings = caught.value.findings
    assert [f.code for f in findings] == [GAP_NO_OCCUPANCY_AT_ENTRY]
    assert findings[0].rule_ids == ("busy",)
    assert "occupancy_at_entry_bp" in findings[0].text


@pytest.mark.guarantee("F51")
def test_a_decision_on_the_gap_does_not_price_it():
    decided = _plan(decisions=[{"code": GAP_NO_OCCUPANCY_AT_ENTRY, "note": "fine",
                                "decided_by": "owner", "decided_at": "2026-01-01T00:00:00Z"}])
    with pytest.raises(Refused):
        _quote(decided, _at(THREE_HOURS, None))


@pytest.mark.guarantee("F51")
def test_a_plan_WITHOUT_a_fill_rule_prices_the_same_with_or_without_the_figure():
    plain = _without_fill(_plan(CAP, VIP))
    for minutes, space_class in ((THREE_HOURS, "standard"), (THIRTEEN_HOURS, "vip")):
        bare = _quote(plain, _at(minutes, None, space_class))
        for figure in (0, 7999, 8000, 10000):
            given = _quote(plain, _at(minutes, figure, space_class))
            assert given.to_json() == bare.to_json()


@pytest.mark.guarantee("F51")
def test_cars_inside_keep_their_price_it_is_the_figure_at_ENTRY():
    """Two cars leaving at the same minute after the same stay: the one that came
    in at 70% pays the plain price, the one that came in at 85% pays the raised
    one. Nothing about the exit -- or how full the garage is then -- reaches it."""
    early = _quote(PLAN, _at(THREE_HOURS, 7000))
    late = _quote(PLAN, _at(THREE_HOURS, 8500))
    assert (early.fee_minor, late.fee_minor) == (1600, 1920)


@pytest.mark.guarantee("F51")
def test_two_fill_rules_on_one_class_are_a_conflict_even_with_an_order():
    second = {**FILL, "id": "very-busy", "threshold_bp": 9500, "percent_bp": 3000}
    document = _plan(second, adjust_order=["busy", "very-busy"])
    assert _quote(document, _at(THREE_HOURS, 9000)).fee_minor == 1920  # only one applies
    with pytest.raises(Refused) as caught:
        _quote(document, _at(THREE_HOURS, 9600))
    codes = [f.code for f in caught.value.findings]
    assert codes == [CONFLICT_OVERLAPPING_FILL_RULES], codes
    assert caught.value.findings[0].rule_ids == ("busy", "very-busy")


# --- refused at the door, by name ---------------------------------------------


@pytest.mark.guarantee("F51")
@pytest.mark.parametrize("field, value", [
    ("threshold_bp", -1), ("threshold_bp", 10001), ("threshold_bp", 80.0),
    ("threshold_bp", "8000"), ("threshold_bp", True), ("threshold_bp", None),
    ("percent_bp", 0), ("percent_bp", -500), ("percent_bp", 10001),
    ("percent_bp", "2000"), ("percent_bp", False), ("percent_bp", 20.5),
    ("rounding", "nearest"), ("rounding", None),
])
def test_a_rule_field_out_of_range_or_not_a_whole_number_is_refused_by_name(field, value):
    document = _plan()
    document["rules"][1][field] = value
    status, body = run_quote({
        "plans": [document], "entry_at": TEN, "exit_at": "2026-03-03T13:00:00-05:00",
        "space_class": "standard", "currency": "USD", "occupancy_at_entry_bp": 9000,
    })
    assert status == 400 and body["invalid"] is True, body
    assert field in body["error"], body["error"]


@pytest.mark.guarantee("F51")
def test_a_fill_rule_on_a_class_the_plan_does_not_declare_does_not_load():
    document = _plan()
    document["rules"][1]["space_classes"] = ["reserved"]
    with pytest.raises(InvalidPlan) as caught:
        load_plan(document)
    assert "reserved" in str(caught.value)


@pytest.mark.guarantee("F51")
@pytest.mark.parametrize("figure", [-1, 10001, 84.0, "8400", True, [8400]])
def test_a_figure_out_of_range_or_not_a_whole_number_is_refused_by_name(figure):
    status, body = run_quote({
        "plans": [PLAN], "entry_at": TEN, "exit_at": "2026-03-03T13:00:00-05:00",
        "space_class": "standard", "currency": "USD", "occupancy_at_entry_bp": figure,
    })
    assert status == 400 and "occupancy_at_entry_bp" in body["error"], body


@pytest.mark.guarantee("F51")
def test_the_figure_reaches_the_engine_through_the_door_and_null_means_none():
    request = {
        "plans": [PLAN], "entry_at": TEN, "exit_at": "2026-03-03T13:00:00-05:00",
        "space_class": "standard", "currency": "USD",
    }
    assert run_quote({**request, "occupancy_at_entry_bp": 8000})[1]["fee_minor"] == 1920
    assert run_quote({**request, "occupancy_at_entry_bp": 7999})[1]["fee_minor"] == 1600
    for absent in ({}, {"occupancy_at_entry_bp": None}):
        status, body = run_quote({**request, **absent})
        assert status == 422
        assert [f["code"] for f in body["findings"]] == [GAP_NO_OCCUPANCY_AT_ENTRY]


def test_the_reference_stay_helper_still_builds_a_stay_with_no_figure():
    """The control on every older test: `stay()` carries no figure, so nothing
    written before this round met one."""
    assert stay(TEN, 60).occupancy_at_entry_bp is None
