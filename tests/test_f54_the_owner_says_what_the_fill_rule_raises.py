"""F54 -- the owner says what the fill rule raises; the engine assumes nothing.

2026-10-14: whether the fill rule also raises specials, and whether it also raises
the VIP extra, is the owner's choice at rate setup. So a `fill_level` rule carries
`raises_specials` and `raises_vip_extra`, both required, each "yes" or "no" --
words, because no bool appears anywhere in a plan (F4).

**Priced by hand.** Tuesday 2026-03-03, 10:00. By the hour: 8.00 the first hour,
4.00 each after. An all-day special at 12.00 (in by 11:00, out by 23:30) on both
classes; a 5.00 VIP extra; the fill rule 80% full, +20%, rounding up;
`cheapest_wins`, so every stay is priced both ways and the cheaper charged.

    stay                       below (7999)  at 8000: TT     TF     FT     FF
    A standard, 10:00-23:00       12.00              14.40  14.40  12.00  12.00
    B vip,      10:00-11:00       13.00              15.60  14.60  15.60  14.60
    C vip,      10:00-23:00       17.00              20.40  19.40  18.00  17.00

    (T/F = raises_specials, raises_vip_extra)

A: the special 12.00 against 56.00 by the hour; raised, +2.40. B: the hour 8.00
against the special 12.00; raised either way, 8.00 + 1.60 + 5.00, and +1.00 on the
extra when it is raised (the special's way, 17.00 or more, is dearer). C: the
special 12.00 + 5.00; +2.40 on the special when specials are raised, +1.00 on the
extra when it is.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.engine import make_stay, quote
from rate_engine.plan import load_plan, parse_instant

TEN = "2026-03-03T10:00:00-05:00"

FILL = {
    "id": "busy", "type": "fill_level", "stage": "ADJUST",
    "space_classes": ["standard", "vip"],
    "threshold_bp": 8000, "percent_bp": 2000, "rounding": "up",
    "raises_specials": "yes", "raises_vip_extra": "yes",
}

PLAN = {
    "plan_version": "fill-switches-2026",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard", "vip"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "all-day", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard", "vip"], "label": "Early bird",
         "applies_on": {"kind": "days_of_week", "days": ["tue"]},
         "enter_from": "06:00", "enter_by": "11:00", "exit_by": "23:30",
         "day_span": "same_day", "effect": {"kind": "flat", "price_minor": 1200}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "vip", "type": "space_surcharge", "stage": "SURCHARGE", "space_classes": ["vip"],
         "surcharge_minor": 500},
        FILL,
    ],
    "decisions": [],
}

STAYS = {"A": (780, "standard"), "B": (60, "vip"), "C": (780, "vip")}

BELOW = {"A": 1200, "B": 1300, "C": 1700}
AT = {
    (True, True): {"A": 1440, "B": 1560, "C": 2040},
    (True, False): {"A": 1440, "B": 1460, "C": 1940},
    (False, True): {"A": 1200, "B": 1560, "C": 1800},
    (False, False): {"A": 1200, "B": 1460, "C": 1700},
}
COMBINATIONS = sorted(AT)


def _plan(raises_specials: bool, raises_vip_extra: bool) -> dict:
    document = copy.deepcopy(PLAN)
    word = {True: "yes", False: "no"}
    document["rules"][3].update(
        raises_specials=word[raises_specials], raises_vip_extra=word[raises_vip_extra]
    )
    return document


def _quote(document: dict, name: str, figure: int):
    minutes, space_class = STAYS[name]
    entry_at = parse_instant(TEN, "entry")
    stay = make_stay(entry_at, entry_at + timedelta(minutes=minutes), space_class, figure)
    return quote([load_plan(copy.deepcopy(document))], stay)


def _codes(result) -> list[str]:
    return [line.code for line in result.breakdown.lines]


@pytest.mark.guarantee("F54")
@pytest.mark.parametrize("switches", COMBINATIONS)
@pytest.mark.parametrize("name", sorted(STAYS))
def test_every_combination_on_each_side_of_the_threshold_prices_as_worked_by_hand(switches, name):
    document = _plan(*switches)
    below = _quote(document, name, 7999)
    at = _quote(document, name, 8000)
    assert below.fee_minor == BELOW[name], (switches, name, below.fee_minor)
    assert at.fee_minor == AT[switches][name], (switches, name, at.fee_minor)
    for result in (below, at):
        assert result.fee_minor == sum(line.delta_minor for line in result.breakdown.lines)
    assert "fill_level.extra_raised" not in _codes(below)


@pytest.mark.guarantee("F54")
def test_a_special_not_raised_says_so_in_plain_words():
    result = _quote(_plan(False, False), "A", 8400)
    lines = [ln for ln in result.breakdown.lines if ln.code == "fill_level.special_not_raised"]
    assert len(lines) == 1 and lines[0].delta_minor == 0
    assert lines[0].text == (
        "Early bird special: fill rule not applied (garage was 84% full at entry, at or "
        "above 80%; this plan does not raise specials)"
    ), lines[0].text
    assert "fill_level.applied" not in _codes(result)


@pytest.mark.guarantee("F54")
def test_a_raised_extra_has_its_own_line():
    result = _quote(_plan(False, True), "C", 8400)
    lines = [ln for ln in result.breakdown.lines if ln.code == "fill_level.extra_raised"]
    assert len(lines) == 1 and lines[0].delta_minor == 100
    assert lines[0].text == (
        "Space class 'vip' extra +20% on 5.00 USD (garage was 84% full at entry) -- "
        "1.00 USD added"
    ), lines[0].text


@pytest.mark.guarantee("F54")
def test_a_percent_extra_is_raised_too_rounded_the_rules_way():
    """A 25% VIP extra, 10:00-13:00 at 90% full, specials not raised. By the
    special: 12.00 + 25% = 3.00 extra, raised 20% = 0.60: 15.60. By the hour:
    16.00 + 3.20 + 4.00 + 0.80 = 24.00. The special's way is charged."""
    document = _plan(False, True)
    document["rules"][2] = {"id": "vip", "type": "space_surcharge", "stage": "SURCHARGE",
                            "space_classes": ["vip"],
                            "amount": {"kind": "percent", "percent_bp": 2500}, "rounding": "up"}
    entry_at = parse_instant(TEN, "entry")
    stay = make_stay(entry_at, entry_at + timedelta(minutes=180), "vip", 9000)
    result = quote([load_plan(document)], stay)
    assert result.fee_minor == 1560
    extra = [ln for ln in result.breakdown.lines if ln.code == "fill_level.extra_raised"]
    assert extra[0].delta_minor == 60


@pytest.mark.guarantee("F54")
@pytest.mark.parametrize("name", sorted(STAYS))
@pytest.mark.parametrize("other", [True, False])
def test_flipping_raises_specials_moves_the_fee_by_exactly_its_own_cents(name, other):
    on = _quote(_plan(True, other), name, 8000)
    off = _quote(_plan(False, other), name, 8000)
    expected = AT[(True, other)][name] - AT[(False, other)][name]
    assert on.fee_minor - off.fee_minor == expected
    _only_fill_lines_differ(on, off)


@pytest.mark.guarantee("F54")
@pytest.mark.parametrize("name", sorted(STAYS))
@pytest.mark.parametrize("other", [True, False])
def test_flipping_raises_vip_extra_moves_the_fee_by_exactly_its_own_cents(name, other):
    on = _quote(_plan(other, True), name, 8000)
    off = _quote(_plan(other, False), name, 8000)
    expected = AT[(other, True)][name] - AT[(other, False)][name]
    assert on.fee_minor - off.fee_minor == expected
    _only_fill_lines_differ(on, off)


def _only_fill_lines_differ(one, other) -> None:
    """Everything a flipped answer does not govern is the same, line for line.

    Two kinds of line are its to change: the fill rule's own, and the one line
    comparing the special with the time-based rate, which quotes both final fees
    -- and the special's moves when the answer about raising it does."""
    from rate_engine.engine import SPECIAL_USED, TIME_BASED_USED

    def rest(result):
        return [
            ln for ln in result.breakdown.lines
            if not ln.code.startswith("fill_level")
            and ln.code not in (SPECIAL_USED, TIME_BASED_USED)
        ]

    assert rest(one) == rest(other)


@pytest.mark.guarantee("F54")
@pytest.mark.parametrize("switch", ["raises_specials", "raises_vip_extra"])
def test_a_rule_that_omits_an_answer_is_refused_by_name(switch):
    document = _plan(True, True)
    del document["rules"][3][switch]
    status, body = run_quote({
        "plans": [document], "entry_at": TEN, "exit_at": "2026-03-03T11:00:00-05:00",
        "space_class": "vip", "currency": "USD", "occupancy_at_entry_bp": 9000,
    })
    assert status == 400 and switch in body["error"], body


@pytest.mark.guarantee("F54")
@pytest.mark.parametrize("switch", ["raises_specials", "raises_vip_extra"])
@pytest.mark.parametrize("value", [True, False, 1, 0, "true", "YES", "", None, ["yes"]])
def test_an_answer_that_is_not_yes_or_no_is_refused_by_name(switch, value):
    document = _plan(True, True)
    document["rules"][3][switch] = value
    status, body = run_quote({
        "plans": [document], "entry_at": TEN, "exit_at": "2026-03-03T11:00:00-05:00",
        "space_class": "vip", "currency": "USD", "occupancy_at_entry_bp": 9000,
    })
    assert status == 400 and switch in body["error"], body
