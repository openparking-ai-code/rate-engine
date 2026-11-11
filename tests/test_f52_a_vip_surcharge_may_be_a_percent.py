"""F52 -- a VIP surcharge may be a percent of the stay's time-based charge.

"We will need to do %." The flat form stays exactly as it was; the percent form is
taken of the charge for the TIME -- the total after the base and the caps -- and
never of another surcharge, so two surcharges still total the same whichever runs
first, which is what makes SURCHARGE an order-independent stage.

The numbers: 3 hours is 8.00 + 2 x 4.00 = 16.00; 13 hours is 56.00, or 10.00 under
the daily most. 25% VIP is 4.00 and 2.50 of those. A second, flat 3.00 surcharge
on the same class makes a percent taken of the RUNNING total 4.75 or 4.00
depending on which ran first.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import make_stay, quote
from rate_engine.plan import load_plan, parse_instant

TEN = "2026-03-03T10:00:00-05:00"

PLAN = {
    "plan_version": "vip-2026",
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
        {"id": "vip", "type": "space_surcharge", "stage": "SURCHARGE", "space_classes": ["vip"],
         "amount": {"kind": "percent", "percent_bp": 2500}, "rounding": "up"},
    ],
    "decisions": [],
}
CAP = {"id": "day", "type": "daily_max", "stage": "CAP", "space_classes": ["standard", "vip"],
       "max_minor": 1000, "day_boundary": "calendar_day"}


def _plan(*extra_rules) -> dict:
    document = copy.deepcopy(PLAN)
    document["rules"].extend(copy.deepcopy(list(extra_rules)))
    return document


def _at(minutes: int, space_class: str = "vip"):
    entry_at = parse_instant(TEN, "entry")
    return make_stay(entry_at, entry_at + timedelta(minutes=minutes), space_class)


def _quote(document: dict, at):
    return quote([load_plan(copy.deepcopy(document))], at)


def _surcharges(result):
    return [ln for ln in result.breakdown.lines if ln.code == "space_surcharge.applied"]


@pytest.mark.guarantee("F52")
def test_a_percent_vip_is_a_percent_of_the_time_charge_with_its_line():
    result = _quote(PLAN, _at(180))
    assert result.fee_minor == 1600 + 400
    line = _surcharges(result)[0]
    assert line.delta_minor == 400
    assert line.text == (
        "Space class 'vip': 25% of the time-based charge 16.00 USD -- 4.00 USD on top "
        "of the base"
    ), line.text


@pytest.mark.guarantee("F52")
def test_it_is_a_percent_of_the_CAPPED_time_charge():
    result = _quote(_plan(CAP), _at(780))
    assert result.fee_minor == 1000 + 250


@pytest.mark.guarantee("F52")
def test_a_standard_space_is_not_charged_and_gets_no_line():
    result = _quote(PLAN, _at(180, "standard"))
    assert result.fee_minor == 1600 and not _surcharges(result)


@pytest.mark.guarantee("F52")
def test_two_surcharges_total_the_same_in_either_order():
    """A flat 3.00 named so it sorts BEFORE the percent, and again AFTER it.
    Taken of the running total the percent would be 4.75 in one order and 4.00 in
    the other; taken of the time charge it is 4.00 both ways, total 23.00."""
    for flat_id in ("a-flat", "z-flat"):
        flat = {"id": flat_id, "type": "space_surcharge", "stage": "SURCHARGE",
                "space_classes": ["vip"], "surcharge_minor": 300}
        result = _quote(_plan(flat), _at(180))
        assert result.fee_minor == 1600 + 300 + 400, flat_id


@pytest.mark.guarantee("F52")
def test_the_rounding_is_the_rules():
    """10:00 to 10:20 is 8.00; 33.33% of it is 2.6664 -- 2.67 up, 2.66 down."""
    up = _plan()
    up["rules"][1]["amount"]["percent_bp"] = 3333
    down = copy.deepcopy(up)
    down["rules"][1]["rounding"] = "down"
    assert _surcharges(_quote(up, _at(20)))[0].delta_minor == 267
    assert _surcharges(_quote(down, _at(20)))[0].delta_minor == 266
    assert "(rounded up)" in _surcharges(_quote(up, _at(20)))[0].text


@pytest.mark.guarantee("F52")
def test_the_flat_form_prices_exactly_as_it_did():
    flat = copy.deepcopy(PLAN)
    flat["rules"][1] = {"id": "vip", "type": "space_surcharge", "stage": "SURCHARGE",
                        "space_classes": ["vip"], "surcharge_minor": 500}
    result = _quote(flat, _at(180))
    assert result.fee_minor == 2100
    assert _surcharges(result)[0].text == "Space class 'vip': 5.00 USD on top of the base"


@pytest.mark.guarantee("F52")
@pytest.mark.parametrize("change", [
    {"surcharge_minor": 500},                                   # both forms
    {"amount": {"kind": "percent", "percent_bp": 0}},
    {"amount": {"kind": "percent", "percent_bp": 10001}},
    {"amount": {"kind": "percent", "percent_bp": -100}},
    {"amount": {"kind": "percent", "percent_bp": "2500"}},
    {"amount": {"kind": "percent", "percent_bp": 25.0}},
    {"amount": {"kind": "percent", "percent_bp": True}},
    {"amount": {"kind": "percent"}},
    {"amount": {"kind": "fixed", "minor": 500}},
    {"amount": {"kind": "percent", "percent_bp": 2500, "extra": 1}},
    {"rounding": "nearest"},
])
def test_a_malformed_percent_surcharge_is_refused_by_name(change):
    document = copy.deepcopy(PLAN)
    document["rules"][1].update(change)
    status, body = run_quote({
        "plans": [document], "entry_at": TEN, "exit_at": "2026-03-03T13:00:00-05:00",
        "space_class": "vip", "currency": "USD",
    })
    assert status == 400 and body["invalid"] is True, body
    assert "rules[1]" in body["error"], body["error"]
