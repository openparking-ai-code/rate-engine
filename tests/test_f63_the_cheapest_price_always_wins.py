"""F63 -- the cheapest price always wins.

Decided 2026-10-16: **when more than one price could apply to the same time, the
car pays the cheapest.** And 2026-10-17, on a flat special that spans several
days: **compare whole-stay alternatives.** A special spanning several days is one
price for the stay it covers. It is compared with the normal price for the whole
stay -- each calendar day capped by the daily max, each week by the weekly max --
and the cheaper is charged. The owner's example, a $50 Friday-to-Sunday flat with a $30
daily max and an hourly rate that reaches $30 within a day: **Saturday only pays
$30; all weekend (Friday to Sunday) pays $50.**

Every place the engine chooses between prices for the same time was audited, and
this file pins each:

* **A flat special against a daily or weekly max.** One price for the stay it
  covers, never split by the day. The caps hold it to the max for each day and
  each week the car is in -- 30.00 on a Saturday alone, 90.00 over Friday to
  Sunday -- and the engine charges the cheaper of it and the time-based rate's
  whole stay. On one day that is the day's max, as it was. A first reading of
  the 10-16 rule owed the whole price on the day of entry and capped it there,
  which made the full weekend 30.00: the whole special capped at one day. The
  10-17 decision corrects that, and a control puts it back.
* **Two specials, or two time-based rates, for one stay.** They were compared on
  what the RULES charged, and only the special that won was compared with the
  time-based rate on the fee. A cap can make the rule that charges more the
  cheaper stay. Every way is now priced through the whole pipeline and the
  lowest FEE charged; the losing rule's line says what the stay comes to by
  each, where the rules' own prices do not say why it lost.
* **`stated_order`.** The plan's order chose outright, so a dearer special
  replaced a cheaper one, and the time-based rate, whatever the driver paid.
  The cheapest is charged under either mode; the order names one of two ways
  that charge the same (F36).

The stay a special covers is the stay it qualified for. A window is all of its
conditions or nothing (section 8), so a stay that runs past a special's exit
limit is not covered by it and the time-based rate prices the whole stay, as
before. And the longest stay priced is still 90 days (F62): the limit comes
before any special is asked.

And what is NOT a choice stays as it was: a surcharge and a fixed increase are
added; the caps already leave the lowest ceiling standing; the discounts apply
in the plan's stated order. Both halves are pinned below, and a sweep checks the
rule itself: the fee is the least of the fees each way charges on its own.

`scripts/fail_controls.py` puts back the whole special owed and capped on the
day of entry, a flat price no cap holds, a special charged over a cheaper hour,
a special that covers a stay past its limit, the 90-day limit taken out, the
rules' own charges deciding, the stated order deciding, the losing line without
the whole stay, and a tie named by id alone, and requires this file to go red
each time.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.contract import run_quote
from rate_engine.plan import parse_instant

EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard", "vip"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}


def _daily(max_minor: int = 3000, boundary: str = "calendar_day") -> dict:
    return {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
            "space_classes": ["standard", "vip"], "max_minor": max_minor,
            "day_boundary": boundary}


def _weekly(max_minor: int = 10000) -> dict:
    return {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
            "space_classes": ["standard", "vip"], "max_minor": max_minor,
            "week_boundary": "calendar_week", "week_starts_on": "mon"}


def _window(rule_id: str, label: str, days: list[str], effect: dict, **times) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard", "vip"], "label": label,
        "applies_on": {"kind": "days_of_week", "days": days},
        "enter_from": times.get("enter_from", "00:00"),
        "enter_by": times.get("enter_by", "23:59"),
        "exit_by": times.get("exit_by", "23:59"),
        "day_span": times.get("day_span", "any_span"),
        "effect": effect,
    }


def _flat(price_minor: int) -> dict:
    return {"kind": "flat", "price_minor": price_minor}


def _rate(per_hour_minor: int, first_minor: int | None = None) -> dict:
    return {"kind": "rate", "first_period_minutes": 60,
            "first_period_minor": per_hour_minor if first_minor is None else first_minor,
            "repeat_period_minutes": 60, "repeat_period_minor": per_hour_minor,
            "rounding": "ceil", "max_duration_minutes": None}


#: The decision's special: a flat 50.00 for a car in on a Friday, a Saturday or a
#: Sunday, out by 20:00 on whatever day it leaves.
WEEKEND_FLAT = _window("weekend-flat", "Weekend flat", ["fri", "sat", "sun"], _flat(5000),
                       exit_by="20:00")


def _plan(*rules: dict, resolution: dict | None = None, adjust_order=None) -> dict:
    return {
        "plan_version": "cheapest-2026-10",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard", "vip"],
        "resolution": resolution or {"QUALIFY": {"mode": "cheapest_wins"},
                                     "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": adjust_order,
        "rules": [copy.deepcopy(r) for r in rules],
        "decisions": [],
    }


def _quote(plan: dict, entry: str, exit_: str, space_class: str = "standard") -> dict:
    status, body = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
         "space_class": space_class, "currency": "USD"}
    )
    assert status == 200, body
    return body


def _line(body: dict, rule_id: str, code: str | None = None) -> dict:
    return next(
        ln for ln in body["breakdown"]
        if ln["rule_id"] == rule_id and (code is None or ln["code"] == code)
    )


def _applied(body: dict) -> list[str]:
    return [ln["rule_id"] for ln in body["breakdown"] if ln["code"] == "time_window.applied"]


# Friday 10 April 2026 to Sunday 12 April: three calendar days. Saturday 11 April.
FRIDAY_1800, SUNDAY_2000 = "2026-04-10T18:00:00-04:00", "2026-04-12T20:00:00-04:00"
SUNDAY_1800 = "2026-04-12T18:00:00-04:00"
SATURDAY_0900, SATURDAY_1900 = "2026-04-11T09:00:00-04:00", "2026-04-11T19:00:00-04:00"
SATURDAY_1000 = "2026-04-11T10:00:00-04:00"


# --- a flat special against the caps: whole-stay alternatives ------------------


@pytest.mark.guarantee("F63")
def test_saturday_only_pays_30():
    """The decision's first example. In at 09:00 on the Saturday, out at 19:00: by
    the hour 8.00 + 9 x 4.00 = 44.00, held to the 30.00 max. The flat is one price,
    50.00, held to the max for the one day the car is in: 30.00. The two ways come
    to the same and the special keeps a tie (F50). With no time-based rate in the
    plan the flat alone is 30.00 too: the max is the most that day can cost."""
    body = _quote(_plan(WEEKEND_FLAT, HOURLY, _daily()), SATURDAY_0900, SATURDAY_1900)
    assert body["fee_minor"] == 3000
    assert _line(body, "weekend-flat", "special_used")["compared_minor"] == 3000

    alone = _quote(_plan(WEEKEND_FLAT, _daily()), SATURDAY_0900, SATURDAY_1900)
    assert alone["fee_minor"] == 3000
    cap = _line(alone, "cap-daily")
    assert cap["code"] == "daily_max.applied", cap["text"]
    assert "applied over the day: 50.00 USD reduced to 30.00 USD" in cap["text"], cap["text"]


@pytest.mark.guarantee("F63")
def test_all_weekend_pays_50():
    """The decision's second example, and the inverse of the reading it corrects.
    Friday 18:00 to Sunday 18:00: by the hour 28.00 + 30.00 + 30.00 = 88.00. The
    flat is one price for the whole stay, 50.00; the max for the three days the
    car is in is 90.00, so it stands, and it is the cheaper way. Owed and capped
    on the day of entry it was 30.00 -- the whole special capped at one day."""
    body = _quote(_plan(WEEKEND_FLAT, HOURLY, _daily()), FRIDAY_1800, SUNDAY_1800)
    assert body["fee_minor"] == 5000
    assert _applied(body) == ["weekend-flat"]
    assert _line(body, "weekend-flat", "special_used")["compared_minor"] == 8800
    cap = _line(body, "cap-daily")
    assert cap["code"] == "daily_max.not_reached", cap["text"]
    assert "(calendar_day, 3 days)" in cap["text"], cap["text"]

    # With no time-based rate in the plan: 50.00 as well.
    assert _quote(_plan(WEEKEND_FLAT, _daily()), FRIDAY_1800, SUNDAY_1800)["fee_minor"] == 5000


@pytest.mark.guarantee("F63")
def test_a_stay_inside_the_span_whose_normal_price_is_lower_pays_the_normal_price():
    """Saturday 10:00 to 12:00: by the hour 8.00 + 4.00 = 12.00, below the cap and
    below the flat held to it (30.00), so the hour is charged and the line says
    what the flat would have been. Over two days too: Friday 18:00 to Saturday
    01:00 is 28.00 + 4.00 = 32.00 by the hour, against the flat's 50.00."""
    plan = _plan(WEEKEND_FLAT, HOURLY, _daily())
    body = _quote(plan, SATURDAY_1000, "2026-04-11T12:00:00-04:00")
    assert body["fee_minor"] == 1200
    assert _applied(body) == []
    assert _line(body, "weekend-flat", "time_based_used")["compared_minor"] == 3000

    two_days = _quote(plan, FRIDAY_1800, "2026-04-11T01:00:00-04:00")
    assert two_days["fee_minor"] == 3200
    assert _line(two_days, "weekend-flat", "time_based_used")["compared_minor"] == 5000


@pytest.mark.guarantee("F63")
def test_a_stay_that_starts_inside_the_span_and_runs_past_it_is_priced_by_the_hour():
    """In on the Saturday at 10:00. Out on the Sunday at 20:00 is inside the flat's
    limit: 50.00, against 30.00 + 30.00 by the hour. Out at 21:00 is past it, and
    a window is all of its conditions or nothing (section 8), as before: the flat
    does not cover the stay, its line says why, and the time-based rate prices
    the whole stay, 60.00."""
    plan = _plan(WEEKEND_FLAT, HOURLY, _daily())
    assert _quote(plan, SATURDAY_1000, SUNDAY_2000)["fee_minor"] == 5000

    past = _quote(plan, SATURDAY_1000, "2026-04-12T21:00:00-04:00")
    assert past["fee_minor"] == 6000
    assert _applied(past) == []
    why = _line(past, "weekend-flat", "time_window.not_applied")
    assert "exit 21:00 is after the 20:00 limit" in why["text"], why["text"]


@pytest.mark.guarantee("F63")
def test_the_90_day_limit_comes_before_any_special():
    """A flat for any entry day, over 90 days exactly: one price for the stay,
    50.00, against 1300.00 by the hour at 30.00 a day and 100.00 a week. A minute
    more is refused for its length (F62), however cheap the special."""
    any_day = _window("any-day", "Any day", EVERY_DAY, _flat(5000))
    plan = _plan(any_day, HOURLY, _daily(), _weekly())
    entry = "2026-04-06T09:00:00-04:00"
    body = _quote(plan, entry, "2026-07-05T09:00:00-04:00")
    assert body["fee_minor"] == 5000
    assert _line(body, "any-day", "special_used")["compared_minor"] == 130000

    status, refused = run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": entry,
         "exit_at": "2026-07-05T09:01:00-04:00", "space_class": "standard", "currency": "USD"}
    )
    assert status == 422, refused
    assert [f["code"] for f in refused["findings"]] == ["GAP_STAY_LONGER_THAN_MAX_STAY"]


@pytest.mark.guarantee("F63")
def test_a_flat_under_the_max_is_charged_as_it_is():
    """The cap is a ceiling, never a price: a 20.00 flat over the same three
    days is 20.00, and the cap was not reached."""
    flat = copy.deepcopy(WEEKEND_FLAT)
    flat["effect"]["price_minor"] = 2000
    body = _quote(_plan(flat, _daily()), FRIDAY_1800, SUNDAY_2000)
    assert body["fee_minor"] == 2000
    assert _line(body, "cap-daily")["code"] == "daily_max.not_reached"


@pytest.mark.guarantee("F63")
def test_a_rolling_day_holds_the_flat_the_same_way():
    """24 hours from entry instead of the calendar: Friday 18:00 to Sunday 20:00 is
    three rolling days, 90.00, and the 50.00 stands; the Saturday stay is one,
    and pays 30.00."""
    plan = _plan(WEEKEND_FLAT, _daily(boundary="rolling_24h"))
    assert _quote(plan, FRIDAY_1800, SUNDAY_2000)["fee_minor"] == 5000
    assert _quote(plan, SATURDAY_0900, SATURDAY_1900)["fee_minor"] == 3000


@pytest.mark.guarantee("F63")
def test_a_weekly_max_holds_a_flat_to_the_weeks_the_car_is_in():
    """Friday to the Sunday nine days later touches two Monday weeks. A 250.00 flat
    with a 100.00 weekly max: 200.00, the max for each of the two weeks. With the
    30.00 daily max too, the first week holds three days and costs no more than
    90.00: 190.00. A 150.00 flat is under both, and stands."""
    exit_ = "2026-04-19T20:00:00-04:00"
    flat = copy.deepcopy(WEEKEND_FLAT)
    flat["effect"]["price_minor"] = 25000
    assert _quote(_plan(flat, _weekly()), FRIDAY_1800, exit_)["fee_minor"] == 20000
    body = _quote(_plan(flat, _daily(), _weekly()), FRIDAY_1800, exit_)
    assert body["fee_minor"] == 19000
    assert "(90.00 USD + 100.00 USD:" in _line(body, "cap-weekly")["text"]
    flat["effect"]["price_minor"] = 15000
    assert _quote(_plan(flat, _daily(), _weekly()), FRIDAY_1800, exit_)["fee_minor"] == 15000


# --- two ways of pricing the time, compared on the whole fee ------------------

#: A Saturday event at a flat 100.00, and a weekend rate of 1.00 an hour.
EVENT = _window("event", "Event rate", ["sat"], _flat(10000))
WEEKEND_RATE = _window("weekend", "Weekend rate", ["sat"], _rate(100))
#: Two Saturday rates: 100.00 for the first hour and 0.50 an hour after, and
#: 2.00 an hour throughout. Over Saturday and Sunday the first charges 123.50
#: and the second 96.00.
FRONT_SPECIAL = _window("front", "Front-loaded rate", ["sat"], _rate(50, first_minor=10000))
EVEN_SPECIAL = _window("weekend", "Weekend rate", ["sat"], _rate(200))
SATURDAY, MONDAY_AFTER = "2026-04-11T00:00:00-04:00", "2026-04-13T00:00:00-04:00"


@pytest.mark.guarantee("F63")
def test_two_specials_are_compared_on_the_WHOLE_FEE_not_on_what_they_charge():
    """Saturday and Sunday, 48 hours. The weekend rate charges 96.00 and the
    front-loaded rate 123.50 -- and with 30.00 a day the front-loaded rate's
    Saturday is 111.50 and pays 30.00, and its Sunday 12.00: 42.00. The weekend
    rate pays 30.00 both days: 60.00. The front-loaded rate is charged. Compared
    on what the rules charge, it was 60.00."""
    body = _quote(_plan(FRONT_SPECIAL, EVEN_SPECIAL, _daily()), SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 4200
    assert _applied(body) == ["front"]
    lost = _line(body, "weekend", "resolved")
    assert lost["text"] == (
        "Weekend rate qualified at 96.00 USD -- Front-loaded rate 123.50 USD applied "
        "instead: with the rest of the plan this stay comes to 42.00 USD by Front-loaded "
        "rate and 60.00 USD by Weekend rate (plan resolves QUALIFY by cheapest_wins)"
    ), lost["text"]


@pytest.mark.guarantee("F63")
def test_without_the_cap_the_rule_that_charges_less_is_the_cheaper_stay():
    """The control on the item above: nothing between the rules and the fee, so
    the weekend rate's 96.00 is the cheaper stay, and its line needs no more
    than the two prices."""
    body = _quote(_plan(FRONT_SPECIAL, EVEN_SPECIAL), SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 9600
    lost = _line(body, "front", "resolved")
    assert lost["text"] == (
        "Front-loaded rate qualified at 123.50 USD -- Weekend rate 96.00 USD applied "
        "instead (plan resolves QUALIFY by cheapest_wins)"
    ), lost["text"]


#: Two time-based rates: 100.00 for the first hour and 0.50 an hour after, and
#: 2.00 an hour throughout. Over two days the first charges 123.50 and the
#: second 96.00.
FRONT_LOADED = {**HOURLY, "id": "front-loaded", "first_period_minor": 10000,
                "repeat_period_minor": 50}
EVEN = {**HOURLY, "id": "even", "first_period_minor": 200, "repeat_period_minor": 200}
MONDAY, WEDNESDAY = "2026-04-06T00:00:00-04:00", "2026-04-08T00:00:00-04:00"


@pytest.mark.guarantee("F63")
def test_two_time_based_rates_are_compared_on_the_whole_fee_too():
    """At 30.00 a day the front-loaded rate's Monday is 111.50 and pays 30.00,
    and its Tuesday 12.00: 42.00. The even rate pays 30.00 both days: 60.00.
    Compared on what the rules charge, 96.00 against 123.50, it was 60.00."""
    body = _quote(_plan(FRONT_LOADED, EVEN, _daily()), MONDAY, WEDNESDAY)
    assert body["fee_minor"] == 4200
    lost = _line(body, "even", "resolved")
    assert lost["text"] == (
        "even qualified at 96.00 USD -- front-loaded 123.50 USD applied instead: with "
        "the rest of the plan this stay comes to 42.00 USD by front-loaded and 60.00 USD "
        "by even (plan resolves ACCUMULATE by cheapest_wins)"
    ), lost["text"]
    # The control: with no cap, the rate that charges less is the cheaper stay.
    assert _quote(_plan(FRONT_LOADED, EVEN), MONDAY, WEDNESDAY)["fee_minor"] == 9600


@pytest.mark.guarantee("F63")
def test_a_stated_order_does_not_charge_the_dearer_way():
    """The plan names the event first. It used to be charged: its 100.00, held to
    30.00 for each of the two days, 60.00. The weekend rate's stay is 24.00 +
    24.00 = 48.00, and that is charged."""
    stated = {"QUALIFY": {"mode": "stated_order", "order": ["event", "weekend"]},
              "ACCUMULATE": {"mode": "cheapest_wins"}}
    body = _quote(_plan(EVENT, WEEKEND_RATE, _daily(), resolution=stated),
                  SATURDAY, MONDAY_AFTER)
    assert body["fee_minor"] == 4800
    assert _applied(body) == ["weekend"]


@pytest.mark.guarantee("F63")
def test_two_ways_at_one_fee_name_the_one_that_charges_less_itself():
    """A 40.00 and a 50.00 flat over the same Saturday, at 30.00 a day: both
    stays come to 30.00. The 40.00 is named -- its own price is lower -- though
    the 50.00 has the lower rule id, and the 50.00's line says the 40.00 applied
    instead."""
    forty = _window("zz-forty", "Forty", ["sat"], _flat(4000))
    fifty = _window("aa-fifty", "Fifty", ["sat"], _flat(5000))
    body = _quote(_plan(forty, fifty, _daily()), SATURDAY, SATURDAY_1900)
    assert body["fee_minor"] == 3000
    assert _applied(body) == ["zz-forty"]
    lost = _line(body, "aa-fifty", "resolved")
    assert "Forty 40.00 USD applied instead" in lost["text"], lost["text"]


# --- what is not a choice stays as it was -------------------------------------


@pytest.mark.guarantee("F63")
def test_a_surcharge_and_a_fixed_increase_are_still_added_in_full():
    """Additive rules are not made a choice. In a VIP space the decision's stay
    is the flat 50.00 and the 5.00 VIP extra; with a 4.00 event fee, 4.00 more."""
    vip = {"id": "vip-extra", "type": "space_surcharge", "stage": "SURCHARGE",
           "space_classes": ["vip"], "surcharge_minor": 500}
    fee = {**_window("event-fee", "Event fee", EVERY_DAY,
                     {"kind": "adjust", "direction": "increase",
                      "amount": {"kind": "fixed", "minor": 400}, "rounding": "up"}),
           "stage": "ADJUST"}
    assert _quote(_plan(WEEKEND_FLAT, _daily(), vip), FRIDAY_1800, SUNDAY_2000,
                  "vip")["fee_minor"] == 5500
    assert _quote(_plan(WEEKEND_FLAT, _daily(), vip, fee), FRIDAY_1800, SUNDAY_2000,
                  "vip")["fee_minor"] == 5900


# --- the rule itself, swept ---------------------------------------------------

#: A plan with every kind of competing way: four specials (flat and rate, same
#: day, next day, any span), two time-based rates, both caps, a VIP extra and a
#: discount on every stay.
SWEPT = _plan(
    _window("early-bird", "Early bird", ["mon", "tue", "wed", "thu", "fri"], _flat(1100),
            enter_from="06:00", enter_by="09:00", exit_by="18:00", day_span="same_day"),
    _window("overnight", "Overnight", EVERY_DAY, _flat(1800), enter_from="17:00",
            exit_by="10:00", day_span="next_day"),
    _window("weekend-rate", "Weekend rate", ["sat", "sun"], _rate(150)),
    _window("event", "Event", ["sat"], _flat(9000)),
    {**HOURLY, "id": "hourly", "first_period_minor": 300, "repeat_period_minor": 250},
    {**HOURLY, "id": "short-stay", "first_period_minutes": 180, "first_period_minor": 1200,
     "repeat_period_minor": 100},
    _daily(2500),
    _weekly(12000),
    {"id": "vip-extra", "type": "space_surcharge", "stage": "SURCHARGE",
     "space_classes": ["vip"], "surcharge_minor": 500},
    {**_window("members", "Members", EVERY_DAY,
               {"kind": "adjust", "direction": "discount",
                "amount": {"kind": "percent", "percent_bp": 1000}, "rounding": "down"}),
     "stage": "ADJUST"},
)

#: The rules that can price the time: each is a way.
WAYS = ("early-bird", "overnight", "weekend-rate", "event", "hourly", "short-stay")


def _only(way: str) -> dict:
    """SWEPT with every other way taken out: the stay priced by `way` alone."""
    document = copy.deepcopy(SWEPT)
    document["rules"] = [r for r in document["rules"] if r["id"] == way or r["id"] not in WAYS]
    return document


@pytest.mark.guarantee("F63")
def test_the_fee_is_the_least_of_the_fees_each_way_charges_on_its_own():
    """Over entries on a weekday, a Friday and a Saturday at four times of day,
    stays from an hour to nine days, both space classes: the fee is the lowest of
    the fees the plan charges with each way alone -- a way that does not price
    the stay alone takes no part. Some stays here are ones a cap reverses, and
    the sweep requires that it saw them."""
    days = ("2026-04-07", "2026-04-10", "2026-04-11")
    times = ("05:30", "07:30", "17:30", "22:00")
    minutes = (60, 150, 600, 900, 1500, 2880, 4400, 12960)
    checked = reversed_by_a_cap = 0
    for day in days:
        for at in times:
            entry = f"{day}T{at}:00-04:00"
            for length in minutes:
                exit_ = (parse_instant(entry, "e") + timedelta(minutes=length)).isoformat()
                for space_class in ("standard", "vip"):
                    request = {"entry_at": entry, "exit_at": exit_,
                               "space_class": space_class, "currency": "USD"}
                    status, whole = run_quote({"plans": [copy.deepcopy(SWEPT)], **request})
                    assert status == 200, whole
                    alone = {}
                    for way in WAYS:
                        status, body = run_quote({"plans": [_only(way)], **request})
                        if status == 200:
                            alone[way] = body["fee_minor"]
                    assert whole["fee_minor"] == min(alone.values()), (entry, length, alone)
                    checked += 1
                    special = [w for w in alone if w in WAYS[:4]]
                    if len(special) > 1:
                        reversed_by_a_cap += _a_cap_reverses(special, request, alone)
    assert checked == len(days) * len(times) * len(minutes) * 2
    assert reversed_by_a_cap > 0, "the sweep never met a stay a cap reverses"


def _a_cap_reverses(ways: list[str], request: dict, alone: dict) -> int:
    """1 when the special that charges least ITSELF is not the cheapest stay --
    the case the old comparison of the rules' own charges got wrong."""
    own = {}
    for way in ways:
        _s, body = run_quote({"plans": [_only(way)], **request})
        # A flat's price is on its applied line; a rate's on its period lines.
        own[way] = sum(
            ln["delta_minor"] for ln in body["breakdown"]
            if ln["rule_id"] == way
            and (ln["code"] == "time_window.applied" or ln["code"].startswith("increment."))
        )
    by_own = min(ways, key=lambda w: (own[w], w))
    return int(alone[by_own] > min(alone[w] for w in ways))
