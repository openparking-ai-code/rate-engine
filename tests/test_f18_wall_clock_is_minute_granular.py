"""F18 -- a wall-clock limit decides on the minute it renders, and nothing finer.

The defect, measured at 75c385b on the shipped plan with no edit: an entry at
`09:00:00.000001` failed an `enter_by` of `09:00`, and the breakdown said

    Early bird NOT applied: entry 09:00 is after the 09:00 entry limit.

fee_minor 1200 -> 3000. Eighteen dollars, decided by a microsecond, explained by a
sentence that is false on its face. The specification's first requirement is that this module is
EXTREMELY CLEAR, and a self-contradicting line is the worst failure of it.

Two halves, and the second is why the first is safe:

* the STAY is truncated to the minute before comparison, so the rendered sentence
  is true;
* a LIMIT finer than a minute is REFUSED at load, not truncated. `time.fromisoformat`
  accepts `09:00:30` and a plan can state it today, where it decides the fee.
  Truncating it would silently discard a pricing decision an operator wrote --
  the engine overriding the plan, which is the defect this module exists to
  prevent, and which the first draft of this fix was about to reintroduce.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote

EARLY_BIRD_PRICE = 1200
TIME_BASED_CAPPED = 3000


def _quote(entry: str, exit_: str, plan: dict | None = None):
    document = plan if plan is not None else copy.deepcopy(DOWNTOWN_V2)
    return run_quote(
        {
            "plans": [document],
            "entry_at": entry,
            "exit_at": exit_,
            "space_class": "standard",
            "currency": "USD",
        }
    )


def _window_line(body: dict) -> str:
    return [ln["text"] for ln in body["breakdown"] if ln["code"].startswith("time_window")][0]


#: Every instant inside the 09:00 minute is an arrival at nine.
WITHIN_THE_LIMIT_MINUTE = (
    "2026-03-03T09:00:00-05:00",
    "2026-03-03T09:00:00.000001-05:00",
    "2026-03-03T09:00:30-05:00",
    "2026-03-03T09:00:59.999999-05:00",
)


@pytest.mark.guarantee("F18")
@pytest.mark.parametrize("entry", WITHIN_THE_LIMIT_MINUTE)
def test_an_entry_inside_the_limits_own_minute_QUALIFIES(entry):
    status, body = _quote(entry, "2026-03-03T16:00:00-05:00")
    assert status == 200
    assert body["fee_minor"] == EARLY_BIRD_PRICE, _window_line(body)
    assert "NOT applied" not in _window_line(body)


@pytest.mark.guarantee("F18")
def test_the_NEXT_minute_still_fails_so_the_limit_was_not_merely_relaxed():
    """The control on the item above. Truncation must not become 'anything goes'."""
    status, body = _quote("2026-03-03T09:01:00-05:00", "2026-03-03T16:00:00-05:00")
    assert status == 200
    assert body["fee_minor"] == TIME_BASED_CAPPED
    assert "NOT applied" in _window_line(body)


@pytest.mark.guarantee("F18")
def test_the_exit_limit_has_the_same_granularity():
    within = _quote("2026-03-03T08:00:00-05:00", "2026-03-03T17:00:59.999999-05:00")[1]
    assert within["fee_minor"] == EARLY_BIRD_PRICE, _window_line(within)
    beyond = _quote("2026-03-03T08:00:00-05:00", "2026-03-03T17:01:00-05:00")[1]
    assert "NOT applied" in _window_line(beyond)


@pytest.mark.guarantee("F18")
def test_NO_RENDERED_LINE_CAN_CONTRADICT_ITSELF():
    """The property, stated as the thing an operator sees rather than as a rule.

    Derived by sweeping the minute around the limit rather than by asserting one
    string: if any instant produces a line saying a time is after itself, this
    fails and names it.
    """
    offsets = ("00", "00.000001", "15", "30", "59", "59.999999")
    for second in offsets:
        _status, body = _quote(f"2026-03-03T09:00:{second}-05:00", "2026-03-03T16:00:00-05:00")
        line = _window_line(body)
        assert "entry 09:00 is after the 09:00" not in line, (
            f"the breakdown contradicts itself at 09:00:{second} -> {line}"
        )


@pytest.mark.guarantee("F18b")
@pytest.mark.parametrize("limit", ["09:00:30", "09:00:00.500000", "08:59:59"])
def test_a_limit_finer_than_a_minute_is_REFUSED_not_truncated(limit):
    """Truncating it would discard a decision the operator wrote, silently."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"][0]["enter_by"] = limit
    status, body = _quote("2026-03-03T09:00:00-05:00", "2026-03-03T16:00:00-05:00", document)
    assert status == 400, f"{limit} was accepted"
    assert "enter_by" in body["error"] and "seconds" in body["error"]


@pytest.mark.guarantee("F18b")
def test_a_plain_HH_MM_limit_is_still_accepted():
    """The control: the refusal must not have banned the ordinary case."""
    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"][0]["enter_by"] = "09:00"
    status, _body = _quote("2026-03-03T09:00:00-05:00", "2026-03-03T16:00:00-05:00", document)
    assert status == 200


def test_PLAN_SELECTION_IS_NOT_TRUNCATED():
    """The site that must NOT adopt minute granularity, asserted so nobody adds it.

    `select_plan` compares two absolute INSTANTS, not times of day. Truncating
    there would change which rate card is in force at a boundary. A version
    taking effect one second after entry must still not govern that stay.
    """
    older = copy.deepcopy(DOWNTOWN_V2)
    older["plan_version"] = "older"
    older["effective_from"] = "2026-01-01T00:00:00-05:00"
    newer = copy.deepcopy(DOWNTOWN_V2)
    newer["plan_version"] = "newer"
    newer["effective_from"] = "2026-03-03T09:00:30-05:00"

    status, body = run_quote(
        {
            "plans": [older, newer],
            "entry_at": "2026-03-03T09:00:00-05:00",
            "exit_at": "2026-03-03T16:00:00-05:00",
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 200
    assert body["plan_version"] == "older", (
        "a plan taking effect 30 seconds AFTER entry governed the stay -- plan "
        "selection has been truncated to the minute, which it must never be"
    )
