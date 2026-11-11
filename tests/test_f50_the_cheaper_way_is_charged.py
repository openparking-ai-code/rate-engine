"""F50 -- the driver pays the cheaper of the special and the time-based rate.

**Before this fix a special that qualified REPLACED the time-based charge, even
when it cost more.** For example: a weekday car in at 08:00 and out
at 10:30 qualifies for an early bird at 9.00, and was charged 9.00, while the same
stay by the hour is 7.00. The rule (2026-10-11): the cheaper way goes
first; confirmed on 2026-10-12 for exactly this stay: the driver always pays the
cheapest way the stay can be priced.

So under `cheapest_wins` the stay is priced through the WHOLE pipeline both ways
-- with the special, and by the time-based rate alone, caps and adjustments
included -- and charged the lower. A tie keeps the special. The breakdown says
which way was used and what the other would have charged. Since F63 (decided
2026-10-16: the cheapest price always wins) the same holds under
`stated_order`, which used to let the special replace the hour whatever it cost.

**The fixture straddles the comparison on purpose.** One stay where the hourly
rate is cheaper (08:00 -> 10:30: 3.00 + 2 x 2.00 = 7.00 against 9.00) and one
where the special is (05:00 -> 18:00: 3.00 + 12 x 2.00 = 27.00 against 9.00). A
test holding only one of them passes one of the two plants.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import stay
from rate_engine.contract import run_quote
from rate_engine.engine import SPECIAL_USED, TIME_BASED_USED, quote
from rate_engine.plan import load_plan

EARLY_BIRD = 900
#: Tuesday 2026-03-03, New York.
IN_0800_OUT_1030 = stay("2026-03-03T08:00:00-05:00", 150)
IN_0500_OUT_1800 = stay("2026-03-03T05:00:00-05:00", 780)

PLAN = {
    "plan_version": "early-bird-2026",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York",
    "currency": "USD",
    "space_classes": ["standard"],
    "resolution": {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}},
    "adjust_order": None,
    "rules": [
        {"id": "early-bird", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Early bird",
         "applies_on": {"kind": "days_of_week", "days": ["mon", "tue", "wed", "thu", "fri"]},
         "enter_from": "05:00", "enter_by": "09:00", "exit_by": "18:00",
         "day_span": "same_day", "effect": {"kind": "flat", "price_minor": EARLY_BIRD}},
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 300, "repeat_period_minutes": 60,
         "repeat_period_minor": 200, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}


def _plan(**changes) -> dict:
    document = copy.deepcopy(PLAN)
    document.update(changes)
    return document


def _with_rule(document: dict, rule: dict) -> dict:
    document = copy.deepcopy(document)
    document["rules"].append(rule)
    return document


def _quote(document: dict, at):
    return quote([load_plan(copy.deepcopy(document))], at)


def _codes(result) -> list[str]:
    return [line.code for line in result.breakdown.lines]


def _compared(result):
    lines = [ln for ln in result.breakdown.lines if ln.code in (SPECIAL_USED, TIME_BASED_USED)]
    assert len(lines) == 1, _codes(result)
    return lines[0]


def test_the_fixture_puts_a_stay_on_each_side_of_the_comparison():
    """The control on the fixture. With the special the plan's only way to price
    either stay, these are the special's prices; the hourly ones are worked by
    hand: 3.00 + 2 x 2.00 and 3.00 + 12 x 2.00."""
    special_only = _plan(rules=[r for r in PLAN["rules"] if r["id"] == "early-bird"])
    assert _quote(special_only, IN_0800_OUT_1030).fee_minor == EARLY_BIRD
    assert _quote(special_only, IN_0500_OUT_1800).fee_minor == EARLY_BIRD
    by_the_hour = _plan(rules=[r for r in PLAN["rules"] if r["id"] == "hourly"])
    assert _quote(by_the_hour, IN_0800_OUT_1030).fee_minor == 700
    assert _quote(by_the_hour, IN_0500_OUT_1800).fee_minor == 2700


@pytest.mark.guarantee("F50")
def test_the_hourly_rate_is_charged_where_it_is_LESS_and_the_breakdown_names_both():
    result = _quote(PLAN, IN_0800_OUT_1030)
    assert result.fee_minor == 700
    assert "time_window.applied" not in _codes(result), "the dearer special was applied"
    assert "increment.first_period" in _codes(result)
    line = _compared(result)
    assert line.code == TIME_BASED_USED
    assert line.rule_id == "early-bird"
    assert line.compared_minor == EARLY_BIRD
    assert line.delta_minor == 0
    assert "Early bird 9.00 USD not used" in line.text, line.text
    assert "7.00 USD is less" in line.text, line.text


@pytest.mark.guarantee("F50")
def test_the_special_is_charged_where_IT_is_less_and_says_what_the_hour_would_be():
    result = _quote(PLAN, IN_0500_OUT_1800)
    assert result.fee_minor == EARLY_BIRD
    assert "time_window.applied" in _codes(result)
    assert "increment.first_period" not in _codes(result)
    line = _compared(result)
    assert line.code == SPECIAL_USED
    assert line.compared_minor == 2700
    assert "Early bird 9.00 USD used" in line.text and "27.00 USD" in line.text, line.text


@pytest.mark.guarantee("F50")
def test_a_daily_most_cheaper_than_both_is_what_the_driver_pays():
    """Caps are inside the comparison: both ways reach the 6.00 most a day."""
    document = _with_rule(PLAN, {
        "id": "day", "type": "daily_max", "stage": "CAP", "space_classes": ["standard"],
        "max_minor": 600, "day_boundary": "calendar_day",
    })
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 600
    assert "daily_max.applied" in _codes(result)
    assert _compared(result).compared_minor == 600


@pytest.mark.guarantee("F50")
def test_the_whole_pipeline_is_compared_not_the_bases_alone():
    """The other way is priced to the end, cap included. With a 5.00 most a day
    the hourly way is 7.00 capped to 5.00, and that 5.00 -- not the raw 7.00 a
    comparison of bases would report -- is what the line says it would charge."""
    document = _with_rule(PLAN, {
        "id": "day", "type": "daily_max", "stage": "CAP", "space_classes": ["standard"],
        "max_minor": 500, "day_boundary": "calendar_day",
    })
    document["rules"][0]["effect"]["price_minor"] = 450
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 450
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor == 500


@pytest.mark.guarantee("F50")
def test_adjustments_run_on_both_ways():
    """A 10 % discount applies to whichever way is charged, and the comparison is
    made after it: 7.00 - 0.70 = 6.30 against 9.00 - 0.90 = 8.10."""
    document = _with_rule(PLAN, {
        "id": "members", "type": "time_window", "stage": "ADJUST",
        "space_classes": ["standard"], "label": "Members",
        "applies_on": {"kind": "days_of_week",
                       "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "adjust", "direction": "discount",
                   "amount": {"kind": "percent", "percent_bp": 1000}, "rounding": "down"},
    })
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 630
    line = _compared(result)
    assert line.code == TIME_BASED_USED and line.compared_minor == 810


@pytest.mark.guarantee("F50")
def test_a_tie_keeps_the_special():
    document = copy.deepcopy(PLAN)
    document["rules"][0]["effect"]["price_minor"] = 700
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 700
    assert "time_window.applied" in _codes(result)
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor == 700
    assert "would be 7.00 USD too" in line.text, line.text


@pytest.mark.guarantee("F50")
def test_stated_order_charges_the_cheaper_way_too():
    """It used to let the special replace the hour, so this stay was 9.00. The
    cheapest price always wins (F63): the hour's 7.00, with the comparison line,
    which says how the plan resolves QUALIFY and what the order still does."""
    document = _plan(resolution={
        "QUALIFY": {"mode": "stated_order", "order": ["early-bird"]},
        "ACCUMULATE": {"mode": "cheapest_wins"},
    })
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 700, "the stated order let a dearer special replace the hour"
    line = _compared(result)
    assert line.code == TIME_BASED_USED and line.compared_minor == EARLY_BIRD
    assert "by stated_order: the cheapest is charged" in line.text, line.text
    # And where the special is the cheaper way, it is still the one charged.
    assert _quote(document, IN_0500_OUT_1800).fee_minor == EARLY_BIRD


@pytest.mark.guarantee("F50")
def test_grace_still_beats_everything():
    document = _with_rule(PLAN, {
        "id": "grace", "type": "grace", "stage": "QUALIFY", "space_classes": ["standard"],
        "minutes": 15,
    })
    result = _quote(document, stay("2026-03-03T08:00:00-05:00", 10))
    assert result.fee_minor == 0
    assert SPECIAL_USED not in _codes(result) and TIME_BASED_USED not in _codes(result)


@pytest.mark.guarantee("F50")
def test_a_stay_the_hourly_rate_cannot_price_is_priced_by_the_special():
    """The time-based rate stops at 2 hours; the 13-hour early bird stay has no
    other way to be priced, and the line says so rather than naming a number."""
    document = copy.deepcopy(PLAN)
    document["rules"][1]["max_duration_minutes"] = 120
    result = _quote(document, IN_0500_OUT_1800)
    assert result.fee_minor == EARLY_BIRD
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor is None
    assert "cannot price this stay" in line.text


@pytest.mark.guarantee("F50")
def test_the_compared_amount_reaches_the_caller_and_only_on_its_line():
    status, body = run_quote({
        "plans": [copy.deepcopy(PLAN)],
        "entry_at": "2026-03-03T08:00:00-05:00",
        "exit_at": "2026-03-03T10:30:00-05:00",
        "space_class": "standard",
        "currency": "USD",
    })
    assert status == 200, body
    assert body["fee_minor"] == 700
    carrying = [ln for ln in body["breakdown"] if "compared_minor" in ln]
    pairs = [(ln["code"], ln["compared_minor"]) for ln in carrying]
    assert pairs == [(TIME_BASED_USED, EARLY_BIRD)]
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == 700


# --- the "why not" lines when the time-based rate wins ---------
#
# The README promises the specials that did not apply, and why. On the special's
# way every other special has its line: its own reason, or `resolved` when it
# qualified and lost to a cheaper special. The time-based way must carry the
# same lines -- they are frozen on every closed stay and are what an attendant
# reads in a dispute. The fixture has one special of each kind beside the early
# bird: one that qualifies and costs more (Morning, 10.00), and one that does
# not qualify (Weekend, not on a Tuesday).

MORNING = {"id": "morning", "type": "time_window", "stage": "QUALIFY",
           "space_classes": ["standard"], "label": "Morning",
           "applies_on": {"kind": "days_of_week", "days": ["mon", "tue", "wed", "thu", "fri"]},
           "enter_from": "06:00", "enter_by": "10:00", "exit_by": "20:00",
           "day_span": "same_day", "effect": {"kind": "flat", "price_minor": 1000}}
WEEKEND = {"id": "weekend", "type": "time_window", "stage": "QUALIFY",
           "space_classes": ["standard"], "label": "Weekend",
           "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
           "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
           "day_span": "next_day", "effect": {"kind": "flat", "price_minor": 1200}}
THREE_SPECIALS = _with_rule(_with_rule(PLAN, MORNING), WEEKEND)


def _lines_of_rule(result, rule_id: str) -> list:
    return [ln for ln in result.breakdown.lines if ln.rule_id == rule_id]


def test_the_why_not_fixture_has_one_special_of_each_kind():
    """The control on the fixture: on the special's way (05:00 -> 18:00, early
    bird 9.00 against the hour's 27.00) Morning qualified and lost, and Weekend
    did not qualify -- so each kind of line is there to be looked for."""
    result = _quote(THREE_SPECIALS, IN_0500_OUT_1800)
    assert result.fee_minor == EARLY_BIRD
    # Morning's enter_from is 06:00: in at 05:00 it does not qualify here.
    in_0700 = stay("2026-03-03T07:00:00-05:00", 600)
    result = _quote(THREE_SPECIALS, in_0700)
    assert result.fee_minor == EARLY_BIRD
    assert [ln.code for ln in _lines_of_rule(result, "morning")] == ["resolved"]
    assert [ln.code for ln in _lines_of_rule(result, "weekend")] == ["time_window.not_applied"]


@pytest.mark.guarantee("F50")
def test_where_the_hour_wins_every_other_special_still_says_why_not():
    """08:00 -> 10:30 on a Tuesday: the hour's 7.00 beats the early bird's 9.00,
    which beat Morning's 10.00. Morning says it qualified and the early bird was
    the cheaper special; Weekend says it is not for a Tuesday; the early bird's
    own line is the comparison."""
    result = _quote(THREE_SPECIALS, IN_0800_OUT_1030)
    assert result.fee_minor == 700
    assert "time_window.applied" not in _codes(result)
    morning = _lines_of_rule(result, "morning")
    assert [ln.code for ln in morning] == ["resolved"], _codes(result)
    assert "Morning qualified at 10.00 USD" in morning[0].text, morning[0].text
    assert "Early bird 9.00 USD was the cheaper special" in morning[0].text, morning[0].text
    assert "applied instead" not in morning[0].text, (
        f"the line says the early bird applied, and the hour was charged: {morning[0].text}"
    )
    weekend = _lines_of_rule(result, "weekend")
    assert [ln.code for ln in weekend] == ["time_window.not_applied"], _codes(result)
    assert [ln.code for ln in _lines_of_rule(result, "early-bird")] == [TIME_BASED_USED]
    assert all(ln.delta_minor == 0 for ln in morning + weekend)


@pytest.mark.guarantee("F50")
def test_the_why_not_lines_are_the_same_on_both_ways():
    """Every special other than the one compared has exactly one line on either
    way, in the plan's order: 08:00 -> 10:30 is charged by the hour, 07:00 ->
    17:00 by the early bird (9.00 against the hour's 3.00 + 9 x 2.00 = 21.00)."""
    for at in (IN_0800_OUT_1030, stay("2026-03-03T07:00:00-05:00", 600)):
        result = _quote(THREE_SPECIALS, at)
        for rule_id in ("morning", "weekend"):
            assert len(_lines_of_rule(result, rule_id)) == 1, (at, _codes(result))
        others = ("morning", "weekend")
        order = [ln.rule_id for ln in result.breakdown.lines if ln.rule_id in others]
        assert order == ["morning", "weekend"], order


@pytest.mark.guarantee("F50")
def test_a_tie_between_the_losing_specials_says_so_on_the_time_based_way():
    """Morning at 9.00 ties the early bird; the hour's 7.00 is less than both.
    Morning says it charged the same, which is why the early bird is the one named."""
    document = copy.deepcopy(THREE_SPECIALS)
    document["rules"][2]["effect"]["price_minor"] = EARLY_BIRD
    result = _quote(document, IN_0800_OUT_1030)
    assert result.fee_minor == 700
    morning = _lines_of_rule(result, "morning")
    assert [ln.code for ln in morning] == ["resolved"]
    assert "charged the same as Early bird" in morning[0].text, morning[0].text


# --- exactly ONE special qualifies and the hour wins -----------
#
# The common case, and the one the three-special tests above never reach: an
# early bird fits, loses to the hour, and every other special of the plan is for
# other days or other dates. An earlier version left out the "why not" lines only when one
# special qualifies, and every test stayed green. Here the plan has the early
# bird, Weekend (other days) and Game night (other dates), and on a Tuesday
# 08:00 -> 10:30 only the early bird qualifies.

GAME_NIGHT = {"id": "game-night", "type": "time_window", "stage": "QUALIFY",
              "space_classes": ["standard"], "label": "Game night",
              "applies_on": {"kind": "dates", "dates": ["2026-03-06", "2026-03-13"]},
              "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
              "day_span": "next_day", "effect": {"kind": "flat", "price_minor": 500}}
ONE_QUALIFIES = _with_rule(_with_rule(PLAN, WEEKEND), GAME_NIGHT)


def test_the_one_qualifier_fixture_has_exactly_one_special_that_fits():
    """The control on the fixture: on 06 Mar, a Game night date and a Friday,
    Game night fits and is the 5.00 charged; on Tuesday 03 Mar only the early
    bird does, so the case below is the one-qualifier case and no other."""
    friday = stay("2026-03-06T08:00:00-05:00", 150)
    result = _quote(ONE_QUALIFIES, friday)
    assert result.fee_minor == 500, _codes(result)
    tuesday = _quote(ONE_QUALIFIES, IN_0800_OUT_1030)
    assert "resolved" not in _codes(tuesday), _codes(tuesday)


@pytest.mark.guarantee("F50")
def test_where_ONE_special_fits_and_the_hour_wins_the_others_still_say_why_not():
    """Tuesday 08:00 -> 10:30: the early bird alone qualifies, and the hour's
    7.00 beats its 9.00. Weekend (not on a Tuesday) and Game night (not on 03
    Mar) each keep their `not_applied` line, by name and in the plan's order,
    and the early bird's only line is the comparison."""
    result = _quote(ONE_QUALIFIES, IN_0800_OUT_1030)
    assert result.fee_minor == 700, _codes(result)
    assert "time_window.applied" not in _codes(result)
    specials = ("early-bird", "weekend", "game-night")
    lines = [(ln.rule_id, ln.code) for ln in result.breakdown.lines if ln.rule_id in specials]
    assert lines == [
        ("weekend", "time_window.not_applied"),
        ("game-night", "time_window.not_applied"),
        ("early-bird", TIME_BASED_USED),
    ], _codes(result)
    weekend = _lines_of_rule(result, "weekend")[0]
    game_night = _lines_of_rule(result, "game-night")[0]
    assert "Weekend NOT applied" in weekend.text, weekend.text
    assert "Game night NOT applied" in game_night.text, game_night.text
    assert weekend.delta_minor == 0 and game_night.delta_minor == 0


# --- the contract's partly dead window, under cheapest_wins ----
#
# docs/CONTRACT.md publishes a window 06:00-23:00 in, out by 20:00, same day, as
# alive for an early entry and dead for a late one -- measured on a 40.00 window,
# dearer than the hour, by whether its lines say it qualified. Here it is CHEAPER
# than the hour and the plan resolves by `cheapest_wins`: the window must apply
# and be charged where it fits, and not where it is dead.

DAY_RATE = 1000


def _day_rate_plan() -> dict:
    return {
        "plan_version": "partial-dead-cheapest",
        "effective_from": "2026-01-01T00:00:00-04:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [
            {"id": "day-rate", "type": "time_window", "stage": "QUALIFY",
             "space_classes": ["standard"], "label": "Day rate",
             "applies_on": {"kind": "days_of_week",
                            "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
             "enter_from": "06:00", "enter_by": "23:00", "exit_by": "20:00",
             "day_span": "same_day", "effect": {"kind": "flat", "price_minor": DAY_RATE}},
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 300, "repeat_period_minutes": 60,
             "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
        ],
        "decisions": [],
    }


@pytest.mark.guarantee("F50")
def test_the_contract_partly_dead_window_is_charged_where_it_fits_and_is_cheaper():
    """In 08:00, out 19:00 on Wednesday 10 June 2026: by the hour 3.00 + 10 x 3.00
    = 33.00, the window 10.00 -- the window applies and is charged, and the line
    says what the hour would have been."""
    result = _quote(_day_rate_plan(), stay("2026-06-10T08:00:00-04:00", 660))
    assert result.fee_minor == DAY_RATE
    assert "time_window.applied" in _codes(result)
    line = _compared(result)
    assert line.code == SPECIAL_USED and line.compared_minor == 3300


@pytest.mark.guarantee("F50")
def test_the_contract_partly_dead_window_stays_dead_for_a_late_entry():
    """In 20:30, out 20:45: past the 20:00 limit on the entry date, so the window
    does not qualify and the hour's 3.00 is charged with no comparison."""
    result = _quote(_day_rate_plan(), stay("2026-06-10T20:30:00-04:00", 15))
    assert result.fee_minor == 300
    assert "time_window.not_applied" in _codes(result)
    assert SPECIAL_USED not in _codes(result) and TIME_BASED_USED not in _codes(result)
