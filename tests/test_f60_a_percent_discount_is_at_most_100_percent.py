"""F60 -- a percent discount can never exceed 100%.

Decided 2026-10-16: refuse it at save or validation time, not when a stay is
priced. A `time_window` discount with a `percent_bp` above 10000 used to load,
validate clean, and then refuse at the counter every stay it took below zero as
`CONFLICT_NEGATIVE_TOTAL` -- after the plan had been saved and the car had
parked. The Open Parking admin form already refuses one; the engine did not, so
any other caller could save it.

Now the plan does not LOAD. Every door answers 400, naming the field in the
sentence and carrying INVALID_PERCENT_DISCOUNT_OVER_100 as `code`, which is what
a plan store routes on. 100% itself loads and makes the stay free. Two things
this does not touch, and both are pinned: a percent INCREASE over 100% still
loads, and a FIXED discount larger than the charge loads, and the fee is
floored at zero once (F57).

`scripts/fail_controls.py` lets the discount load, refuses 100% as well, drops
the code, stops sending it, and bounds increases too, and requires this file to
go red each time.
"""

from __future__ import annotations

import copy
import http.client
import json
import subprocess
import sys
import threading

import pytest

from plant import ROOT
from rate_engine.contract import run_quote, run_validate
from rate_engine.findings import (
    ALL_CODES,
    INVALID_CODES,
    INVALID_PERCENT_DISCOUNT_OVER_100,
    Finding,
)
from rate_engine.plan import InvalidPlan, load_plan
from rate_engine.service import make_server


def _adjust(direction: str, amount: dict) -> dict:
    return {"id": "weekend", "type": "time_window", "stage": "ADJUST",
            "space_classes": ["standard"], "label": "Weekend special",
            "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
            "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
            "day_span": "any_span",
            "effect": {"kind": "adjust", "direction": direction, "amount": amount,
                       "rounding": "down"}}


def _plan(direction: str = "discount", percent_bp: int = 10001) -> dict:
    return {
        "plan_version": "percent-2026-10",
        "effective_from": "2026-01-01T00:00:00-05:00",
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [
            {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
             "space_classes": ["standard"], "first_period_minutes": 60,
             "first_period_minor": 300, "repeat_period_minutes": 60,
             "repeat_period_minor": 300, "rounding": "ceil", "max_duration_minutes": None},
            _adjust(direction, {"kind": "percent", "percent_bp": percent_bp}),
        ],
        "decisions": [],
    }


SATURDAY = "2026-03-07T10:00:00-05:00"
AN_HOUR_LATER = "2026-03-07T11:00:00-05:00"
FIELD = "rules[1].effect.amount.percent_bp"


def _quote(plan: dict):
    return run_quote(
        {"plans": [copy.deepcopy(plan)], "entry_at": SATURDAY, "exit_at": AN_HOUR_LATER,
         "space_class": "standard", "currency": "USD"}
    )


@pytest.mark.guarantee("F60")
@pytest.mark.parametrize("percent_bp", [10001, 15000, 20000])
def test_a_discount_over_100_percent_does_not_load(percent_bp):
    with pytest.raises(InvalidPlan) as caught:
        load_plan(_plan(percent_bp=percent_bp))
    assert caught.value.code == INVALID_PERCENT_DISCOUNT_OVER_100
    message = str(caught.value)
    assert FIELD in message and str(percent_bp) in message, message
    assert "at most the whole fee" in message, message


@pytest.mark.guarantee("F60")
def test_validate_plan_refuses_it_with_the_code():
    status, body = run_validate({"plan": _plan()})
    assert status == 400, body
    assert body["invalid"] is True
    assert body["code"] == INVALID_PERCENT_DISCOUNT_OVER_100
    assert FIELD in body["error"], body["error"]
    assert list(body) == ["schema_version", "invalid", "error", "code"]


@pytest.mark.guarantee("F60")
def test_a_quote_on_it_is_refused_before_any_stay_is_priced():
    """Not 422: nothing was priced. The plan itself is refused, the same way."""
    status, body = _quote(_plan())
    assert status == 400, body
    assert body["code"] == INVALID_PERCENT_DISCOUNT_OVER_100
    assert "fee_minor" not in body and "findings" not in body


@pytest.mark.guarantee("F60")
def test_the_http_door_refuses_it_with_the_code():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        connection.request("POST", "/v1/validate-plan", body=json.dumps({"plan": _plan()}),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
    assert response.status == 400, body
    assert body["code"] == INVALID_PERCENT_DISCOUNT_OVER_100


@pytest.mark.guarantee("F60")
def test_the_cli_names_the_code(tmp_path):
    path = tmp_path / "over.json"
    path.write_text(json.dumps(_plan()))
    result = subprocess.run(
        [sys.executable, "-m", "rate_engine.cli", "validate-plan", "--plan", str(path)],
        cwd=ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0, result.stdout
    assert INVALID_PERCENT_DISCOUNT_OVER_100 in result.stdout, result.stdout + result.stderr


@pytest.mark.guarantee("F60")
def test_100_percent_loads_and_the_stay_is_free():
    status, body = _quote(_plan(percent_bp=10000))
    assert status == 200, body
    assert body["fee_minor"] == 0
    line = next(ln for ln in body["breakdown"] if ln["rule_id"] == "weekend")
    assert line["delta_minor"] == -300
    assert "100% discount on 3.00 USD" in line["text"], line["text"]
    assert run_validate({"plan": _plan(percent_bp=10000)})[0] == 200


@pytest.mark.guarantee("F60")
def test_an_increase_over_100_percent_still_loads():
    """The decision is about discounts. 150% added to 3.00 is 4.50 added."""
    status, body = _quote(_plan("increase", 15000))
    assert status == 200, body
    assert body["fee_minor"] == 750


@pytest.mark.guarantee("F60")
def test_a_fixed_discount_larger_than_the_charge_still_loads():
    """F57's rule, kept: 5.00 off a 3.00 stay loads, and the fee is floored at zero."""
    plan = _plan()
    plan["rules"][1] = _adjust("discount", {"kind": "fixed", "minor": 500})
    status, body = _quote(plan)
    assert status == 200, body
    assert body["fee_minor"] == 0


@pytest.mark.guarantee("F60")
def test_the_code_is_registered_and_is_not_a_finding():
    """A plan that does not load is not a finding about a stay: the code is in
    its own tuple, a Finding cannot carry it, and an unregistered code cannot be
    put on a refusal."""
    assert INVALID_PERCENT_DISCOUNT_OVER_100 in INVALID_CODES
    assert not set(INVALID_CODES) & set(ALL_CODES)
    with pytest.raises(ValueError):
        Finding(code=INVALID_PERCENT_DISCOUNT_OVER_100, text="x")
    with pytest.raises(ValueError):
        InvalidPlan("x", code="INVALID_SOMETHING_ELSE")


@pytest.mark.guarantee("F60")
def test_every_other_load_refusal_is_the_bytes_it_was():
    """A refusal with no code carries no `code` key."""
    plan = _plan(percent_bp=2000)
    del plan["rules"][1]["day_span"]
    status, body = run_validate({"plan": plan})
    assert status == 400, body
    assert list(body) == ["schema_version", "invalid", "error"]
