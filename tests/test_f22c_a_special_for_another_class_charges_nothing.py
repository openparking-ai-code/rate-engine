"""F22c -- a special for another space class charges nothing.

A QUALIFY rule speaks whether it qualified or not: the engine asks every special
for its lines, so a receipt can say why the early bird was not given. The
qualifier asks the stay's space class; the appliers did not. So a special
scoped to one class, met on every time by a stay of another class, answered
"applied", with its price, and the engine added that price beside the
time-based rate the stay was also charged:

* $8 the first hour and $4 an hour after, with a 30.00 flat for VIP spaces: a
  two-hour standard stay was 42.00 instead of 12.00. Since the caps check what
  the base charged against the receipt (F59), the same stay stops the quote
  instead, and the HTTP door drops the connection with no answer.
* The reference plan's early bird is for standard spaces. A VIP stay in its
  window, Tuesday 07:30 to 16:30, carried "Early bird ... applied +12.00".
* A grace for VIP spaces told a five-minute standard stay "there is no charge,
  and nothing further is added", on a receipt that then charged it 8.00.

Such a special now gets its not-applied line, at zero, saying the stay's class
is not one it covers -- what `apply` says it returns for a rule that did not
qualify. The line stays: a QUALIFY rule always speaks (F22).

**And the class is the reason whatever the times.** A special for another class
that the stay also missed on a time used to give that time: every VIP receipt on
the reference plan read "Early bird NOT applied: entry 09:14 is after the 09:00
entry limit ...", so a VIP car read that it came in too late for an early bird it
could never get. A grace for VIP spaces told a fifteen-minute standard stay it
was five minutes over. Both now name the class, and nothing else. A stay of the
special's own class still gets the time, or the minutes, as before. Only the
words of a line at zero changed; no fee moves.

The sweep at the end holds the whole property: on every stay, a plan's quote is
the quote of the same plan with its specials for other classes taken out, but
for those specials' own lines, each at zero. Every special in the earlier
sweeps covered both classes, which is how this went unseen.

`scripts/fail_controls.py` takes the class check out of each applier, and has
a time or the minutes said before the class, and requires red.
"""

from __future__ import annotations

import copy
import itertools

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote
from rate_engine.rules import RULE_TYPES
from rate_engine.stages import QUALIFY

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
BOTH = ["standard", "vip"]

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE", "space_classes": BOTH,
    "first_period_minutes": 60, "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}
DAILY = {
    "id": "cap", "type": "daily_max", "stage": "CAP", "space_classes": BOTH,
    "max_minor": 3000, "day_boundary": "calendar_day",
}
VIP_EXTRA = {
    "id": "vip-extra", "type": "space_surcharge", "stage": "SURCHARGE",
    "space_classes": ["vip"], "surcharge_minor": 500,
}


def _window(rule_id, classes, label, effect, *, days=ALL_DAYS, enter_from="00:00",
            enter_by="23:59", exit_by="23:59", day_span="any_span"):
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": list(classes), "label": label,
        "applies_on": {"kind": "days_of_week", "days": list(days)},
        "enter_from": enter_from, "enter_by": enter_by, "exit_by": exit_by,
        "day_span": day_span, "effect": effect,
    }


def _flat(minor):
    return {"kind": "flat", "price_minor": minor}


def _rate(minor_an_hour):
    return {
        "kind": "rate", "first_period_minutes": 60, "first_period_minor": minor_an_hour,
        "repeat_period_minutes": 60, "repeat_period_minor": minor_an_hour,
        "rounding": "ceil", "max_duration_minutes": None,
    }


def _grace(rule_id, classes, minutes=10):
    return {
        "id": rule_id, "type": "grace", "stage": "QUALIFY",
        "space_classes": list(classes), "minutes": minutes,
    }


def _early(rule_id, classes, minor):
    return _window(rule_id, classes, "Early bird", _flat(minor), days=ALL_DAYS[:5],
                   enter_from="06:00", enter_by="09:00", exit_by="17:00",
                   day_span="same_day")


def _plan(*rules, mode="cheapest_wins"):
    resolution = {"QUALIFY": {"mode": "cheapest_wins"},
                  "ACCUMULATE": {"mode": "cheapest_wins"}}
    if mode == "stated_order":
        order = [r["id"] for r in rules if r["stage"] == QUALIFY]
        resolution["QUALIFY"] = {"mode": "stated_order", "order": order}
    return {
        "plan_version": "classes-2026-03", "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD", "space_classes": BOTH,
        "resolution": resolution, "adjust_order": None,
        "rules": [copy.deepcopy(r) for r in rules], "decisions": [],
    }


def _quote(plan, entry, exit_, space_class):
    return run_quote({
        "plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
        "space_class": space_class, "currency": "USD",
    })


def _lines(body, rule_id):
    return [line for line in body["breakdown"] if line["rule_id"] == rule_id]


def _the_class_line(body, rule_id, code="time_window.not_applied"):
    lines = _lines(body, rule_id)
    assert len(lines) == 1, body["breakdown"]
    (line,) = lines
    assert line["code"] == code, line
    assert line["delta_minor"] == 0, f"a special for another class moved the fee: {line}"
    return line


VIP_FLAT = _window("vip-flat", ["vip"], "VIP flat", _flat(3000))
TUE = "2026-03-03T{}:00-05:00"


@pytest.mark.guarantee("F22c")
def test_a_flat_for_VIP_spaces_met_on_every_time_charges_a_standard_stay_NOTHING():
    status, body = _quote(_plan(HOURLY, VIP_FLAT), TUE.format("10:00"), TUE.format("12:00"),
                          "standard")
    assert status == 200, body
    assert body["fee_minor"] == 1200, body["breakdown"]  # 8.00 + 4.00; it was 42.00
    line = _the_class_line(body, "vip-flat")
    assert "the stay is in a 'standard' space and this rule covers 'vip' only" in line["text"]


@pytest.mark.guarantee("F22c")
def test_and_a_VIP_stay_still_gets_it():
    """The control on the item above: the line is about the class, not a window
    that stopped applying."""
    plan = _plan(HOURLY, _window("vip-flat", ["vip"], "VIP flat", _flat(900)))
    status, body = _quote(plan, TUE.format("10:00"), TUE.format("12:00"), "vip")
    assert status == 200, body
    assert body["fee_minor"] == 900
    assert _lines(body, "vip-flat")[0]["code"] == "time_window.applied"


@pytest.mark.guarantee("F22c")
def test_the_reference_plans_early_bird_on_a_VIP_stay_inside_its_window():
    status, body = _quote(copy.deepcopy(DOWNTOWN_V2), TUE.format("07:30"), TUE.format("16:30"),
                          "vip")
    assert status == 200, body
    # 8.00 + 8 x 4.00 = 40.00, capped at 30.00, and the VIP extra 5.00.
    assert body["fee_minor"] == 3500, body["breakdown"]
    line = _the_class_line(body, "eb-weekday")
    assert "this rule covers 'standard' only" in line["text"]


@pytest.mark.guarantee("F22c")
def test_on_the_time_based_way_too():
    """A special for the stay's own class qualifies and the hour is cheaper, so
    the stay is priced again by the time-based rate alone and every other special
    is asked again why it was not used. That is a second place the engine asks."""
    plan = _plan(HOURLY, _early("early", ["standard"], 1200), VIP_FLAT)
    status, body = _quote(plan, TUE.format("07:30"), TUE.format("08:30"), "standard")
    assert status == 200, body
    assert body["fee_minor"] == 800, body["breakdown"]
    assert [line["code"] for line in _lines(body, "early")] == ["time_based_used"]
    _the_class_line(body, "vip-flat")


@pytest.mark.guarantee("F22c")
@pytest.mark.parametrize("mode", ["cheapest_wins", "stated_order"])
def test_on_the_specials_way_under_either_mode(mode):
    """The early bird prices the stay. Under `stated_order` there is no second
    way to price it, so nothing stopped the quote: the VIP flat was added and
    the cap took the stay to 30.00."""
    plan = _plan(HOURLY, DAILY, _early("early", ["standard"], 1200), VIP_FLAT, mode=mode)
    status, body = _quote(plan, TUE.format("07:30"), TUE.format("16:30"), "standard")
    assert status == 200, body
    assert body["fee_minor"] == 1200, body["breakdown"]
    assert _lines(body, "early")[0]["code"] == "time_window.applied"
    _the_class_line(body, "vip-flat")


@pytest.mark.guarantee("F22c")
def test_a_time_based_rate_for_VIP_spaces_charges_a_standard_stay_nothing():
    plan = _plan(HOURLY, _window("vip-rate", ["vip"], "VIP rate", _rate(100)))
    status, body = _quote(plan, TUE.format("10:00"), TUE.format("12:00"), "standard")
    assert status == 200, body
    assert body["fee_minor"] == 1200, body["breakdown"]
    _the_class_line(body, "vip-rate")

    status, body = _quote(plan, TUE.format("10:00"), TUE.format("12:00"), "vip")
    assert status == 200, body
    assert body["fee_minor"] == 200, body["breakdown"]


@pytest.mark.guarantee("F22c")
def test_a_grace_for_VIP_spaces_does_not_tell_a_standard_stay_it_is_free():
    plan = _plan(HOURLY, _grace("vip-grace", ["vip"]))
    status, body = _quote(plan, TUE.format("10:00"), TUE.format("10:05"), "standard")
    assert status == 200, body
    assert body["fee_minor"] == 800, body["breakdown"]
    line = _the_class_line(body, "vip-grace", code="grace.not_applied")
    assert "the stay is in a 'standard' space and this grace covers 'vip' only" in line["text"]
    assert "no charge" not in line["text"]

    status, body = _quote(plan, TUE.format("10:00"), TUE.format("10:05"), "vip")
    assert status == 200, body
    assert body["fee_minor"] == 0
    assert _lines(body, "vip-grace")[0]["code"] == "grace.applied"


@pytest.mark.guarantee("F22c")
def test_a_special_for_another_class_the_stay_also_missed_on_a_time_names_the_class():
    """Never a time reason for a special the stay could never get. The reference
    plan's early bird is for standard spaces; a VIP car in at 09:14 and out at
    18:40 missed both its times as well, and its line names the class alone."""
    status, body = _quote(copy.deepcopy(DOWNTOWN_V2), TUE.format("09:14"), TUE.format("18:40"),
                          "vip")
    assert status == 200, body
    assert _the_class_line(body, "eb-weekday")["text"] == (
        "Early bird NOT applied: the stay is in a 'vip' space and this rule covers "
        "'standard' only. All of its conditions must hold, so the stay prices on the "
        "time-based rate"
    )

    status, body = _quote(_plan(HOURLY, _grace("vip-grace", ["vip"])), TUE.format("10:00"),
                          TUE.format("10:15"), "standard")
    assert status == 200, body
    assert _the_class_line(body, "vip-grace", code="grace.not_applied")["text"] == (
        "Grace period 10 min NOT applied: the stay is in a 'standard' space and this grace "
        "covers 'vip' only, so the stay prices from entry on the ordinary rate"
    )


@pytest.mark.guarantee("F22c")
def test_and_a_stay_of_the_specials_own_class_still_gets_the_time_it_missed():
    """The control on the item above: the same stays in a class the special
    covers keep the lines they always had, byte for byte."""
    status, body = _quote(copy.deepcopy(DOWNTOWN_V2), TUE.format("09:14"), TUE.format("18:40"),
                          "standard")
    assert status == 200, body
    assert _the_class_line(body, "eb-weekday")["text"] == (
        "Early bird NOT applied: entry 09:14 is after the 09:00 entry limit; exit 18:40 on "
        "Tue 03 Mar is after the 17:00 limit on Tue 03 Mar. All of its conditions must "
        "hold, so the stay prices on the time-based rate"
    )

    status, body = _quote(_plan(HOURLY, _grace("vip-grace", ["vip"])), TUE.format("10:00"),
                          TUE.format("10:15"), "vip")
    assert status == 200, body
    assert _the_class_line(body, "vip-grace", code="grace.not_applied")["text"] == (
        "Grace period 10 min NOT applied: the stay was 15 min, which is 5 over. Grace is "
        "all-or-nothing, so the stay prices from entry on the ordinary rate"
    )


@pytest.mark.guarantee("F22c")
def test_every_rule_type_that_runs_at_QUALIFY_is_measured_here():
    """Derived from the registry. The engine asks every QUALIFY rule for lines
    whether it qualified or not, so a type added there answers for the class in
    its applier too, and gets a case in this file before this passes."""
    at_qualify = {name for name, (stages, _builder) in RULE_TYPES.items() if QUALIFY in stages}
    assert at_qualify == {"time_window", "grace"}, (
        f"rule types that run at QUALIFY: {sorted(at_qualify)}. A new one needs a case "
        "here showing that, for a space class it does not cover, it charges nothing"
    )


# --- the sweep -------------------------------------------------------------

#: Specials for one class or both, at prices either side of the hour.
SPECIALS = {
    "early-std": _early("early-std", ["standard"], 1200),
    "early-vip": _early("early-vip", ["vip"], 1000),
    "flat-vip": _window("flat-vip", ["vip"], "VIP flat", _flat(3000)),
    "flat-both": _window("flat-both", BOTH, "Any flat", _flat(2500)),
    "rate-vip": _window("rate-vip", ["vip"], "VIP weekend rate", _rate(100), days=["sat", "sun"]),
    "rate-std": _window("rate-std", ["standard"], "Standard rate", _rate(300)),
    "grace-vip": _grace("grace-vip", ["vip"]),
    "grace-std": _grace("grace-std", ["standard"], minutes=15),
}
SPECIAL_SETS = [
    ("early-std", "flat-vip"),
    ("early-std", "early-vip", "rate-vip"),
    ("flat-both", "flat-vip", "grace-vip"),
    ("rate-std", "rate-vip", "early-vip"),
    ("grace-std", "flat-vip", "early-std"),
    ("early-vip", "flat-vip", "rate-vip", "grace-vip"),
]
BASES = [(HOURLY, DAILY), (HOURLY, DAILY, VIP_EXTRA)]
MODES = ["cheapest_wins", "stated_order"]
#: Tuesday in the early window and mid-morning, Friday night into the weekend,
#: Saturday morning, and Sunday 7 March into the clock change of 8 March.
ENTRIES = ["2026-03-03T07:30:00-05:00", "2026-03-03T10:00:00-05:00",
           "2026-03-06T22:00:00-05:00", "2026-03-07T08:00:00-05:00",
           "2026-03-07T23:30:00-05:00"]
MINUTES = [0, 5, 60, 540, 1500, 4400]


def _exit(entry, minutes):
    from datetime import datetime, timedelta

    return (datetime.fromisoformat(entry) + timedelta(minutes=minutes)).isoformat()


def _class_sentence(rule, space_class):
    """The whole line a special for another class gives: the class, and nothing else."""
    covered = ", ".join(repr(c) for c in rule["space_classes"])
    if rule["type"] == "grace":
        return (
            f"Grace period {rule['minutes']} min NOT applied: the stay is in a "
            f"{space_class!r} space and this grace covers {covered} only, so the stay "
            "prices from entry on the ordinary rate"
        )
    return (
        f"{rule['label']} NOT applied: the stay is in a {space_class!r} space and this rule "
        f"covers {covered} only. All of its conditions must hold, so the stay prices on the "
        "time-based rate"
    )


def _missed_a_time(rule, entry, exit_, space_class):
    """Whether the stay also missed one of the special's times: asked of the
    registered qualifier with the special widened to the stay's class."""
    from rate_engine.engine import QUALIFIERS, make_stay
    from rate_engine.plan import load_plan, parse_instant

    widened = copy.deepcopy(rule)
    widened["space_classes"] = BOTH
    plan = load_plan(_plan(HOURLY, widened))
    (loaded,) = [r for r in plan.rules if r.id == rule["id"]]
    stay = make_stay(parse_instant(entry, "entry"), parse_instant(exit_, "exit"), space_class)
    return not QUALIFIERS[loaded.type](loaded, stay, plan)


def _without_other_classes(plan, space_class):
    """The same plan with every special that does not cover `space_class` taken out."""
    reduced = copy.deepcopy(plan)
    gone = {r["id"] for r in reduced["rules"]
            if r["stage"] == QUALIFY and space_class not in r["space_classes"]}
    reduced["rules"] = [r for r in reduced["rules"] if r["id"] not in gone]
    settings = reduced["resolution"]["QUALIFY"]
    if settings["mode"] == "stated_order":
        settings["order"] = [i for i in settings["order"] if i not in gone]
    return reduced, gone


@pytest.mark.guarantee("F22c")
def test_a_special_for_another_class_changes_nothing_but_its_own_line_SWEEP():
    met_every_time = missed_a_time = priced = 0
    for names, base, mode, entry, minutes, space_class in itertools.product(
        SPECIAL_SETS, BASES, MODES, ENTRIES, MINUTES, BOTH
    ):
        plan = _plan(*base, *(SPECIALS[n] for n in names), mode=mode)
        reduced, gone = _without_other_classes(plan, space_class)
        if not gone:
            continue  # every special in this set covers the stay's class
        exit_ = _exit(entry, minutes)
        case = f"{names} {mode} {[r['id'] for r in base]} {entry} +{minutes} {space_class}"

        status, body = _quote(plan, entry, exit_, space_class)
        want_status, want = _quote(reduced, entry, exit_, space_class)
        assert status == want_status, f"{case}: {status} {body} / {want_status} {want}"
        if status != 200:
            assert body == want, case
            continue
        priced += 1
        assert body["fee_minor"] == want["fee_minor"], f"{case}: {body['breakdown']}"
        theirs = [line for line in body["breakdown"] if line["rule_id"] in gone]
        rest = [line for line in body["breakdown"] if line["rule_id"] not in gone]
        assert rest == want["breakdown"], case
        assert len(theirs) == len(gone), f"{case}: {theirs}"
        rules = {r["id"]: r for r in plan["rules"]}
        for line in theirs:
            assert line["delta_minor"] == 0 and line["code"].endswith(".not_applied"), (
                f"{case}: {line}"
            )
            # The class, and nothing else, whatever the stay did on the times.
            rule = rules[line["rule_id"]]
            assert line["text"] == _class_sentence(rule, space_class), f"{case}: {line}"
            if _missed_a_time(rule, entry, exit_, space_class):
                missed_a_time += 1
            else:
                met_every_time += 1
    # Both kinds of stay were met -- ones that met every time of a special for
    # another class, and ones that also missed a time -- and enough stays priced
    # for the comparison to mean something.
    assert met_every_time >= 900 and missed_a_time >= 1000 and priced >= 1100, (
        met_every_time, missed_a_time, priced,
    )
