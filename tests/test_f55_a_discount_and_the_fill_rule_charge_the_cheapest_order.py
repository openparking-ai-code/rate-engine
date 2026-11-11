"""F55 -- a discount and the fill rule: the driver pays the cheapest order.

10-14 20:25, asked whether a busy garage's +20% is on the full price or the
discounted one: "always the cheaper". Never a cent more than the cheapest order,
rounding included. So the engine prices every order and charges the cheapest;
the plan's stated order no longer decides the price.

**Priced by hand**, below, from the product words and not from the engine's
code: three orders per pass -- (A) discount first, fill rule on what is left,
the discount set against the time charge first; (B) the fill rule first, the
discount on the raised total; (C) discount first, each part carrying its share
in proportion to what it charged (the raised part's share rounded up), the fill
rule on what is left of the parts it raises. The cheapest of A, B, C; under
`cheapest_wins` the cheaper of the special's way and the hour's way.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from rate_engine.engine import make_stay, quote
from rate_engine.plan import load_plan, parse_instant

CLASSES = ["standard", "vip"]


def _plan(*, first, repeat, special=None, vip=500, discount, fill):
    rules = [{"id": "hourly", "type": "increment", "stage": "ACCUMULATE", "space_classes": CLASSES,
              "first_period_minutes": 60, "first_period_minor": first,
              "repeat_period_minutes": 60, "repeat_period_minor": repeat, "rounding": "ceil",
              "max_duration_minutes": None}]
    if special:
        rules.append({"id": "early", "type": "time_window", "stage": "QUALIFY",
                      "space_classes": CLASSES, "label": "Early bird",
                      "applies_on": {"kind": "days_of_week", "days": ["tue"]},
                      "enter_from": "06:00", "enter_by": "09:00", "exit_by": "18:00",
                      "day_span": "same_day", "effect": {"kind": "flat", "price_minor": special}})
    rules.append({"id": "vip", "type": "space_surcharge", "stage": "SURCHARGE",
                  "space_classes": ["vip"], "surcharge_minor": vip})
    rules.append({"id": "off", "type": "time_window", "stage": "ADJUST", "space_classes": CLASSES,
                  "label": "Tuesday off", "applies_on": {"kind": "days_of_week", "days": ["tue"]},
                  "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
                  "day_span": "any_span",
                  "effect": {"kind": "adjust", "direction": "discount", "amount": discount,
                             "rounding": "down"}})
    rules.append({"id": "busy", "type": "fill_level", "stage": "ADJUST", "space_classes": CLASSES,
                  "threshold_bp": 8000, **fill})
    return {"plan_version": "f55", "effective_from": "2026-01-01T00:00:00-05:00",
            "timezone": "America/New_York", "currency": "USD", "space_classes": CLASSES,
            "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                           "ACCUMULATE": {"mode": "cheapest_wins"}},
            "adjust_order": ["off", "busy"], "rules": rules, "decisions": []}


def _quote(document, entry, minutes, space_class, figure):
    entry_at = parse_instant(f"2026-03-03T{entry}:00-05:00", "entry")
    stay = make_stay(entry_at, entry_at + timedelta(minutes=minutes), space_class, figure)
    return quote([load_plan(copy.deepcopy(document))], stay)


def _order_line(result):
    return [ln for ln in result.breakdown.lines if ln.code == "fill_level.order"]


# --- the two cases the re-check found ----------------------------------------


@pytest.mark.guarantee("F55")
def test_R1_a_special_not_raised_and_the_extra_raised_pays_the_cheaper_15_88():
    """Early bird 12.35, VIP 5.00, 20% off, 95% full, +50%; specials no, extra yes.
    Discount first against the time charge: 17.35 - 3.47 = 13.88, the whole 5.00
    extra raised +2.50: 16.38. Raised first: 12.35 + 7.50 = 19.85, 20% off 3.97:
    15.88. Each part its share: 9.88 + (4.00 + 2.00) = 15.88. Charged: 15.88."""
    document = _plan(first=525, repeat=315, special=1235,
                     discount={"kind": "percent", "percent_bp": 2000},
                     fill={"percent_bp": 5000, "rounding": "up", "raises_specials": "no",
                           "raises_vip_extra": "yes"})
    result = _quote(document, "07:00", 300, "vip", 9500)
    assert result.fee_minor == 1588
    assert result.fee_minor == sum(ln.delta_minor for ln in result.breakdown.lines)
    [line] = _order_line(result)
    assert line.delta_minor == 0
    assert "the fill rule first, then the discounts" in line.text
    assert "16.38 USD" in line.text


@pytest.mark.guarantee("F55")
def test_N1_a_cent_of_rounding_is_the_drivers_5_13_not_5_14():
    """5.25 for 45 minutes, 15% off rounded down, +15% rounded down, 90% full.
    Discount first: 5.25 - 0.78 = 4.47, +0.67 = 5.14. Raised first: 5.25 + 0.78 =
    6.03, 15% off 0.90 = 5.13. A cent is a difference: 5.13."""
    document = _plan(first=525, repeat=315, discount={"kind": "percent", "percent_bp": 1500},
                     fill={"percent_bp": 1500, "rounding": "down", "raises_specials": "yes",
                           "raises_vip_extra": "no"})
    result = _quote(document, "10:00", 45, "standard", 9000)
    assert result.fee_minor == 513
    assert "5.14 USD" in _order_line(result)[0].text


@pytest.mark.guarantee("F55")
def test_a_tie_charges_the_first_order_and_says_every_order_charges_the_same():
    """F1's case: 10.00, 20% off, 90% full, +20%. Discount first 8.00 + 1.60 and
    raised first 12.00 - 2.40 are both 9.60: the first order is charged."""
    document = _plan(first=1000, repeat=1000, discount={"kind": "percent", "percent_bp": 2000},
                     fill={"percent_bp": 2000, "rounding": "up", "raises_specials": "yes",
                           "raises_vip_extra": "no"})
    result = _quote(document, "10:00", 60, "standard", 9000)
    assert result.fee_minor == 960
    text = _order_line(result)[0].text
    assert "the discounts first, then the fill rule on what is left" in text
    assert "every order charges the same" in text


@pytest.mark.guarantee("F55")
def test_below_the_threshold_there_is_one_order_and_no_order_line():
    document = _plan(first=1000, repeat=1000, discount={"kind": "fixed", "minor": 200},
                     fill={"percent_bp": 2000, "rounding": "up", "raises_specials": "yes",
                           "raises_vip_extra": "no"})
    result = _quote(document, "10:00", 60, "standard", 7999)
    assert result.fee_minor == 800
    assert _order_line(result) == []


@pytest.mark.guarantee("F55")
def test_the_raised_parts_share_of_the_discount_rounds_the_drivers_way():
    """Early bird 10.00 (not raised), VIP 1.01 (raised +100%), 10% off, 95% full.
    11.01, 10% off 1.10 = 9.91. The extra's share is 1.10 x 1.01 / 11.01 = 0.1009:
    rounded up, 0.11, leaving 0.90, raised +0.90 = 10.81. Rounded down, 0.10,
    leaving 0.91: 10.82. Raised first 12.02 - 1.20 = 10.82; discount first, all
    of it off the time, 9.91 + 1.01 = 10.92. Charged: 10.81."""
    document = _plan(first=525, repeat=315, special=1000, vip=101,
                     discount={"kind": "percent", "percent_bp": 1000},
                     fill={"percent_bp": 10000, "rounding": "up", "raises_specials": "no",
                           "raises_vip_extra": "yes"})
    assert _quote(document, "07:00", 300, "vip", 9500).fee_minor == 1081


# --- every pair x percent and flat x each side, by hand ------------------------

HOURLY = (800, 400)
SPECIAL = 1200
VIP = 500
FILL_PCT = 2000


def _pct(amount, bp, rounding):
    q, r = divmod(amount * bp, 10000)
    return q + (1 if rounding == "up" and r else 0)


def _hand(*, time, extra, by_special, raises_specials, raises_extra, discount, figure):
    """The fee on one way of pricing (time charge `time`, extra `extra`)."""
    def off(total):
        if discount["kind"] == "percent":
            return _pct(total, discount["percent_bp"], "down")
        return discount["minor"]

    if figure < 8000:
        return time + extra - off(time + extra)
    raises_time = not (by_special and not raises_specials)

    def up(amount):
        return _pct(amount, FILL_PCT, "up")

    whole = time + extra
    # A: discount first, set against the time first.
    d = off(whole)
    t_left = time - min(time, d)
    e_left = extra - (d - min(time, d))
    a = whole - d + (up(t_left) if raises_time else 0)
    a += up(e_left) if raises_extra and extra else 0
    # B: the fill rule first.
    raised = (up(time) if raises_time else 0) + (up(extra) if raises_extra and extra else 0)
    b = whole + raised - off(whole + raised)
    # C: each part its share; the raised part's share rounded up.
    if extra and raises_extra and not raises_time:
        e_off = min(extra, -(-d * extra // whole))
        t_off = d - e_off
    elif extra:
        t_off = min(time, -(-d * time // whole) if raises_time else d * time // whole)
        e_off = d - t_off
    else:
        t_off, e_off = d, 0
    c = whole - d + (up(time - t_off) if raises_time else 0) + (
        up(extra - e_off) if raises_extra and extra else 0)
    return min(a, b, c)


#: name -> (entry, minutes, class): A standard by the special, B vip by the hour,
#: C vip by the special.
STAYS = {"A": ("07:00", 600, "standard"), "B": ("10:00", 60, "vip"), "C": ("07:00", 600, "vip")}
PAIRS = [("yes", "yes"), ("yes", "no"), ("no", "yes"), ("no", "no")]
DISCOUNTS = [{"kind": "percent", "percent_bp": 2000}, {"kind": "fixed", "minor": 300}]


def _by_hand(name, pair, discount, figure):
    entry, minutes, space_class = STAYS[name]
    extra = VIP if space_class == "vip" else 0
    hours = -(-minutes // 60)
    by_hour = HOURLY[0] + HOURLY[1] * (hours - 1)
    common = dict(extra=extra, raises_specials=pair[0] == "yes", raises_extra=pair[1] == "yes",
                  discount=discount, figure=figure)
    fees = [_hand(time=by_hour, by_special=False, **common)]
    if entry == "07:00":
        fees.append(_hand(time=SPECIAL, by_special=True, **common))
    return min(fees)


@pytest.mark.guarantee("F55")
@pytest.mark.parametrize("figure", [7999, 8000])
@pytest.mark.parametrize("discount", DISCOUNTS, ids=["percent", "flat"])
@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: "-".join(p))
@pytest.mark.parametrize("name", sorted(STAYS))
def test_every_pair_and_both_discounts_on_each_side_price_as_by_hand(name, pair, discount, figure):
    document = _plan(first=HOURLY[0], repeat=HOURLY[1], special=SPECIAL, vip=VIP, discount=discount,
                     fill={"percent_bp": FILL_PCT, "rounding": "up", "raises_specials": pair[0],
                           "raises_vip_extra": pair[1]})
    entry, minutes, space_class = STAYS[name]
    result = _quote(document, entry, minutes, space_class, figure)
    expected = _by_hand(name, pair, discount, figure)
    assert result.fee_minor == expected, (name, pair, discount, figure)
    assert result.fee_minor == sum(ln.delta_minor for ln in result.breakdown.lines)


@pytest.mark.guarantee("F55")
def test_with_two_discounts_every_place_of_the_fill_rule_is_priced_and_the_cheapest_charged():
    """Early bird 12.35 (not raised), VIP 5.00 (raised +50%), 10% off then 3.00
    off, 95% full. By hand, each place of the fill rule:
      after both, time first:  17.35 - 1.73 - 3.00 = 12.62; extra 5.00 +2.50 = 15.12
      first:                   19.85 - 1.98 - 3.00 = 14.87
      after both, per part:    4.73 off, extra share 1.37 -> 3.63 +1.82: 14.44
      between, time first:     15.62 + 2.50 - 3.00 = 15.12
      between, per part:       extra share 0.50 -> 4.50 +2.25: 17.87 - 3.00 = 14.87
    Charged: 14.44. The plan's order with the fill rule stated last does not stop
    the fill rule being priced first or between."""
    document = _plan(first=525, repeat=315, special=1235,
                     discount={"kind": "percent", "percent_bp": 1000},
                     fill={"percent_bp": 5000, "rounding": "up", "raises_specials": "no",
                           "raises_vip_extra": "yes"})
    second = copy.deepcopy(document["rules"][3])
    second["id"], second["label"] = "off2", "Tuesday 3.00 off"
    second["effect"]["amount"] = {"kind": "fixed", "minor": 300}
    document["rules"].insert(4, second)
    document["adjust_order"] = ["off", "off2", "busy"]
    result = _quote(document, "07:00", 300, "vip", 9500)
    assert result.fee_minor == 1444
    text = _order_line(result)[0].text
    assert "each part its share" in text
    assert "14.87 USD" in text and "15.12 USD" in text
