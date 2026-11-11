"""F36 -- the resolution modes decide which rule is NAMED, and never the money.

**They were a decision the owner made and the software ignored.** `resolution`
was required on every plan, validated against two named modes, published in the
contract's own table -- and read in exactly one place: the text of a conflict
finding, quoting the mode back while declining to apply it. `find_conflicts` said
so in its own docstring. A required field that changes no answer is the shape of
defect this project has a name for, and it shipped here for a whole round.

Two modes, and the same stay under both, because that is the only arrangement
that shows the FIELD deciding rather than one plan pricing one way:

* `cheapest_wins` -- the lowest fee for the customer. The owner's choice,
  confirmed.
* `stated_order` -- the plan names the rule ids and the first that qualifies
  wins.

**And then the owner made the cheapest win everywhere** (decided 2026-10-16,
F63): when more than one price could apply to the same time, the car pays the
cheapest. `stated_order` charged the dearer of two windows when the plan named
it first; it no longer can. Both modes charge the cheaper window. What the mode
still decides is the NAME where two windows charge the same: the lowest rule id
under `cheapest_wins`, the first in the order under `stated_order` -- on the
same stay, and reversing the order reverses it. So the field still changes an
answer the owner can read, and this file still shows it doing so.

**And the rules that LOST still appear on the receipt.** The specification's first requirement
is that a customer can read why they were charged what they were charged, and a
breakdown that silently omits a rate the customer nearly got cannot answer the
question an attendant is actually asked. The line names the loser, its price, the
winner, the winner's price, and the mode that chose between them.

The fixture prices the two windows differently, so the cheaper can be seen
winning under both modes, and the SAME (`TIE`), so the mode can be seen naming.
"""

from __future__ import annotations

import pytest

from rate_engine.contract import run_quote

EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}

EARLY_BIRD = 1200
WEEKEND = 1500
#: Both windows at one price: the case where the mode names the rule.
TIE = 1300


def _window(rule_id: str, label: str, price: int) -> dict:
    return {
        "id": rule_id, "type": "time_window", "stage": "QUALIFY",
        "space_classes": ["standard"], "label": label,
        "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
        "exit_by": "23:59", "day_span": "any_span",
        "effect": {"kind": "flat", "price_minor": price},
    }


def _plan(resolution: dict, early_bird: int = EARLY_BIRD, weekend: int = WEEKEND) -> dict:
    return {
        "plan_version": "resolve-2026-03",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York", "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": resolution, "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [
            _window("eb", "Early bird", early_bird),
            _window("weekend", "Weekend rate", weekend),
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 800, "repeat_period_minutes": 60,
             "repeat_period_minor": 400, "rounding": "ceil",
             "max_duration_minutes": None},
        ],
        "decisions": [],
    }


def _quote(resolution: dict, **prices):
    return run_quote(
        {
            "plans": [_plan(resolution, **prices)], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T13:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )


def _applied(body: dict) -> list[str]:
    return [ln["rule_id"] for ln in body["breakdown"] if ln["code"] == "time_window.applied"]


def _resolved(body: dict) -> list[dict]:
    return [ln for ln in body["breakdown"] if ln["code"] == "resolved"]


def test_the_fixture_can_tell_the_two_winners_apart():
    """The control on the fixture, and it runs first. If both windows charged the
    same, no mode could be shown charging the cheaper; and the tie must be dearer
    than neither and cheaper than the hour, or it is not the tie it claims."""
    assert EARLY_BIRD != WEEKEND
    status, body = _quote({"mode": "cheapest_wins"}, early_bird=TIE, weekend=TIE)
    assert status == 200 and body["fee_minor"] == TIE, body


@pytest.mark.guarantee("F36")
def test_cheapest_wins_picks_the_LOWER_FEE_FOR_THE_CUSTOMER():
    status, body = _quote({"mode": "cheapest_wins"})
    assert status == 200, body
    assert body["fee_minor"] == EARLY_BIRD
    assert _applied(body) == ["eb"]


@pytest.mark.guarantee("F36")
def test_stated_order_charges_the_CHEAPER_window_too_on_the_same_stay():
    """The plan names the dearer window first, and the cheaper is charged: the
    order no longer decides the money (F63). It used to charge 15.00 here."""
    status, body = _quote({"mode": "stated_order", "order": ["weekend", "eb"]})
    assert status == 200, body
    assert body["fee_minor"] == EARLY_BIRD, "the stated order charged the dearer window"
    assert _applied(body) == ["eb"]


@pytest.mark.guarantee("F36")
def test_and_REVERSING_the_stated_order_does_not_move_the_money():
    """The control on the item above: either order charges the cheaper window."""
    status, body = _quote({"mode": "stated_order", "order": ["eb", "weekend"]})
    assert status == 200, body
    assert body["fee_minor"] == EARLY_BIRD
    assert _applied(body) == ["eb"]


@pytest.mark.guarantee("F36")
def test_where_both_charge_the_same_each_mode_NAMES_its_own_rule():
    """The same stay, the same two rules at one price, a different field -- and a
    different rule named. That is what makes this the FIELD deciding: the money
    is the same and the receipt is not. `cheapest_wins` names the lowest rule id
    ("eb" < "weekend"); `stated_order` names the first in its order, and
    reversing the order reverses the name."""
    tie = {"early_bird": TIE, "weekend": TIE}
    _s, cheapest = _quote({"mode": "cheapest_wins"}, **tie)
    _s, weekend_first = _quote({"mode": "stated_order", "order": ["weekend", "eb"]}, **tie)
    _s, eb_first = _quote({"mode": "stated_order", "order": ["eb", "weekend"]}, **tie)

    assert {cheapest["fee_minor"], weekend_first["fee_minor"], eb_first["fee_minor"]} == {TIE}
    assert _applied(cheapest) == ["eb"]
    assert _applied(weekend_first) == ["weekend"], (
        "the stated order was ignored where it is the one thing left to decide"
    )
    assert _applied(eb_first) == ["eb"]

    lost = _resolved(weekend_first)
    assert [ln["rule_id"] for ln in lost] == ["eb"]
    assert "charged the same as Weekend rate" in lost[0]["text"], lost[0]["text"]
    assert "the plan's stated order puts it first" in lost[0]["text"], lost[0]["text"]
    assert "its rule id comes first" in _resolved(cheapest)[0]["text"]


@pytest.mark.guarantee("F36")
def test_the_rule_that_LOST_still_appears_and_names_the_winner():
    """The line an attendant is read at the counter."""
    _status, body = _quote({"mode": "cheapest_wins"})
    lost = _resolved(body)
    assert len(lost) == 1, [ln["code"] for ln in body["breakdown"]]
    line = lost[0]
    assert line["rule_id"] == "weekend"
    assert line["delta_minor"] == 0, "a rule that did not apply moved the fee"
    assert line["text"] == (
        "Weekend rate qualified at 15.00 USD -- Early bird 12.00 USD applied "
        "instead (plan resolves QUALIFY by cheapest_wins)"
    ), line["text"]


@pytest.mark.guarantee("F36")
def test_the_loser_line_names_the_MODE_and_it_follows_the_plan():
    """Not a fixed sentence: change the mode and the sentence has to change with
    it, or it is prose borrowing the mechanism's credibility. Under
    `stated_order` it says what the order does now."""
    _s, cheapest = _quote({"mode": "cheapest_wins"})
    _s, stated = _quote({"mode": "stated_order", "order": ["weekend", "eb"]})

    assert "(plan resolves QUALIFY by cheapest_wins)" in _resolved(cheapest)[0]["text"]
    assert (
        "(plan resolves QUALIFY by stated_order: the cheapest is charged, and the order "
        "names one of two that charge the same)"
    ) in _resolved(stated)[0]["text"], _resolved(stated)[0]["text"]
    assert _resolved(stated)[0]["rule_id"] == "weekend", (
        "the loser is the dearer window, whatever the order names first"
    )


@pytest.mark.guarantee("F36")
def test_the_LEDGER_still_sums_when_a_rule_is_resolved_away():
    """A rule removed from the pricing must be removed from the MONEY too. The
    engine asserts this on every quote; this is the fixture that reaches it with
    a loser in the breakdown."""
    _status, body = _quote({"mode": "cheapest_wins"})
    assert sum(ln["delta_minor"] for ln in body["breakdown"]) == body["fee_minor"]
    assert body["fee_minor"] == EARLY_BIRD, "the loser's price leaked into the fee"


@pytest.mark.guarantee("F36")
def test_resolution_is_keyed_ONLY_by_the_stages_that_can_resolve():
    """A mode stated for a stage that cannot resolve is a decision that does
    nothing, and this module has shipped one of those. CAP composes -- both caps
    apply -- so a mode there could never choose anything, and the key is refused
    by name like every other key this version does not understand."""
    document = _plan({"mode": "cheapest_wins"})
    document["resolution"]["CAP"] = {"mode": "cheapest_wins"}
    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T13:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )
    assert status == 400
    assert "CAP" in body["error"] and "does not understand" in body["error"], body["error"]
