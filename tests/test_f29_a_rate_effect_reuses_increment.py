"""F29 -- a `rate` effect is priced by `increment`, not by a copy of it.

Decided 2026-09-07: an effect is not only a percent increase or discount; it can
be a completely different rate. So a window's effect can be a whole time-based rate --
the weekend priced in twenty-minute periods where the weekday is hourly.

**The obvious way to build that is a second period calculation, and it is the
wrong way.** Two implementations of "how many periods is this stay" agree on the
day they are written and drift the first time one of them is edited, and when a
period calculation drifts the difference is money on somebody's receipt. There is
no test that catches drift between two copies, because both copies pass their own
tests.

So `increment` was refactored into two callable cores -- `build_params` and
`lines_for` -- and `time_window` calls them. This file proves the call is real,
in two ways that fail differently:

* the same parameters produce IDENTICAL lines through both routes, and
* changing `increment`'s period counting MOVES the window's fee. The second is
  the one a copy would survive: a copy would keep answering the old way while
  `increment` answered the new one, and the first check alone cannot see that
  because it compares the window against nothing but itself.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from plant import ROOT, planted
from rate_engine.contract import run_quote

#: The rate, stated once and used through both routes.
RATE = {
    "first_period_minutes": 30,
    "first_period_minor": 250,
    "repeat_period_minutes": 30,
    "repeat_period_minor": 150,
    "rounding": "ceil",
    "max_duration_minutes": None,
}

RESOLUTION = {"QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"}}
EVERY_DAY = {"kind": "days_of_week",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}

#: Priced by an ordinary ACCUMULATE rule. The reference.
PLAIN = {
    "plan_version": "plain-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York", "currency": "USD", "space_classes": ["standard"],
    "resolution": RESOLUTION,
    "adjust_order": None,
    "rules": [
        {"id": "x", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], **RATE},
    ],
    "decisions": [],
}

#: The same rate, carried INSIDE a window. The rule id matches on purpose: a line
#: carries the id of the rule that produced it, so identical ids are what let the
#: two breakdowns be compared as whole objects rather than field by field.
VIA_WINDOW = {
    "plan_version": "window-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York", "currency": "USD", "space_classes": ["standard"],
    "resolution": RESOLUTION,
    "adjust_order": None,
    "rules": [
        {"id": "x", "type": "time_window", "stage": "QUALIFY",
         "space_classes": ["standard"], "label": "Weekend rate",
         "applies_on": EVERY_DAY, "enter_from": "00:00", "enter_by": "23:59",
         "exit_by": "23:59", "day_span": "same_day",
         "effect": {"kind": "rate", **RATE}},
        # A DIFFERENT standard rate, so a window that silently failed to apply
        # would produce a different fee rather than the same one by luck.
        {"id": "standard", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard"], "first_period_minutes": 60,
         "first_period_minor": 900, "repeat_period_minutes": 60,
         "repeat_period_minor": 900, "rounding": "ceil", "max_duration_minutes": None},
    ],
    "decisions": [],
}

ENTRY = "2026-03-03T09:00:00-05:00"
EXIT = "2026-03-03T10:40:00-05:00"  # 100 minutes: one first period and three repeats


def _request(plan: dict) -> dict:
    return {
        "plans": [copy.deepcopy(plan)], "entry_at": ENTRY, "exit_at": EXIT,
        "space_class": "standard", "currency": "USD",
    }


def _increment_lines(plan: dict) -> list[dict]:
    status, body = run_quote(_request(plan))
    assert status == 200, body
    return [ln for ln in body["breakdown"] if ln["code"].startswith("increment.")]


def test_the_fixture_would_notice_the_window_not_applying():
    """The control on the fixture, and it runs first.

    The window's rate and the plan's standard rate must price this stay
    differently, or every comparison below would hold whether or not the window
    did anything.
    """
    status, body = run_quote(_request(VIA_WINDOW))
    assert status == 200, body
    assert body["fee_minor"] == 250 + 3 * 150
    standard_only = copy.deepcopy(VIA_WINDOW)
    standard_only["rules"] = [r for r in standard_only["rules"] if r["id"] != "x"]
    _s, fallback = run_quote(_request(standard_only))
    assert fallback["fee_minor"] != body["fee_minor"]


@pytest.mark.guarantee("F29")
def test_the_lines_are_IDENTICAL_through_both_routes():
    """Not "the totals agree" -- the LINES, with their codes and their English.

    A copy that produced the right number under a different sentence would still
    be a second implementation, and the receipt is the product here.
    """
    assert _increment_lines(PLAIN) == _increment_lines(VIA_WINDOW), (
        "a rate carried inside a window prices differently from the same rate "
        "stated as an ordinary rule, so there are two period calculations"
    )


@pytest.mark.guarantee("F29")
def test_the_window_ALSO_says_which_window_it_was():
    """The reuse must not have cost the breakdown its explanation: the lines are
    `increment`'s, and the line above them is the window's."""
    _status, body = run_quote(_request(VIA_WINDOW))
    header = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"]
    assert len(header) == 1, body["breakdown"]
    assert header[0]["delta_minor"] == 0, "the header must carry no money; the rate does"
    assert "Weekend rate" in header[0]["text"]
    assert "replaces the standard one" in header[0]["text"]


#: The plant, and the half a byte-comparison structurally cannot see. It changes
#: how `increment` counts repeat periods; the window's fee must follow.
BREAK_THE_PERIOD_COUNT = (
    "rules/increment.py",
    "    return -(-remainder // period_minutes)",
    "    return -(-remainder // period_minutes) + 1  # PLANTED: one period too many",
)

_FEE_SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from rate_engine.contract import run_quote
status, body = run_quote(json.loads(sys.argv[2]))
print(status, body.get("fee_minor"))
"""


def _fee_in_a_fresh_interpreter(plan: dict) -> int:
    """Price the stay in a subprocess, so a planted module is actually loaded.

    In-process would import the module once and never see the plant -- the same
    trap tests/plant.py's header records about `importlib.reload`.
    """
    result = subprocess.run(
        [sys.executable, "-c", _FEE_SCRIPT, str(ROOT / "src"), json.dumps(_request(plan))],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    status, fee = result.stdout.split()
    assert status == "200", result.stdout
    return int(fee)


@pytest.mark.guarantee("F29")
def test_a_change_to_INCREMENTS_counting_MOVES_the_windows_fee():
    """The half that proves the call is live rather than the shapes agreeing.

    A copied period calculation would keep answering the old way while
    `increment` answered the new one -- and every byte comparison in this file
    would still pass, because both sides of it would be the copy.
    """
    before = _fee_in_a_fresh_interpreter(VIA_WINDOW)
    with planted(*BREAK_THE_PERIOD_COUNT):
        after = _fee_in_a_fresh_interpreter(VIA_WINDOW)

    assert before == 250 + 3 * 150
    assert after == before + RATE["repeat_period_minor"], (
        f"the window's fee did not follow increment's period counting "
        f"({before} -> {after}), so the rate effect is a copy rather than a call"
    )


@pytest.mark.guarantee("F29")
def test_the_rates_OWN_CEILING_is_a_condition_like_any_other():
    """A window whose rate stops at four hours does not price a five-hour stay at
    the ceiling and does not pro-rate it: the window does not apply at all, which
    is the specification's all-conditions-or-nothing, and the stay falls to the plan's ordinary
    rate."""
    bounded = copy.deepcopy(VIA_WINDOW)
    bounded["rules"][0]["effect"]["max_duration_minutes"] = 240
    status, body = run_quote(
        {
            "plans": [bounded], "entry_at": ENTRY, "exit_at": "2026-03-03T15:00:00-05:00",
            "space_class": "standard", "currency": "USD",
        }
    )
    assert status == 200, body
    line = [ln for ln in body["breakdown"] if ln["code"] == "time_window.not_applied"][0]
    assert "this rate stops at 240" in line["text"], line["text"]
    assert body["fee_minor"] == 900 * 6, "the stay did not fall to the standard rate"
