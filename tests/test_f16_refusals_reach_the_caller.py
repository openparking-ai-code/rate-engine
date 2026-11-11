"""F16 -- a refusal that does not reach the caller is not a refusal.

Found by the outside review, by neither outside reviewer, and it is the item
that reached ordinary operator data. `money.NotMinorUnits` subclasses `TypeError`,
not `ValueError`, so `run_quote`'s `except (InvalidPlan, ValueError)` did not
catch it. A plain JSON float in a plan -- `8.0`, the shape `json.loads` produces
from any decimal an operator types -- escaped the function entirely. Over HTTP
the handler died mid-request and the client got `RemoteDisconnected`: no status,
no body, nothing to act on.

The float was ALWAYS correctly refused; F4 and F4b were never wrong. What was
wrong is that the refusal never became a RESPONSE. So this file tests the
boundary rather than the check: not "is a float rejected" but "what does the
caller receive".

**What is deliberately NOT done here: widening the clause to `TypeError`.** Every
genuine programming error in this module is a `TypeError` too, and catching them
all would answer an operator "your plan is invalid" for a bug in our own code --
a confident wrong answer, in the module whose standing acceptance is that it is
never wrong silently. The named class is caught; a real bug still crashes.
"""

from __future__ import annotations

import copy
import json
import threading
import urllib.error
import urllib.request

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote, run_validate
from rate_engine.money import NotMinorUnits
from rate_engine.service import make_server

#: Every leaf shape the plan-wide walk refuses, at a field the engine READS and at
#: one it does not. `decisions[]` is the position no other check types, which is
#: why F4b exists; both positions must come back as a response, not as a crash.
MALFORMED = (
    ("a float in a field the engine reads", ["rules", 1, "first_period_minor"], 8.0),
    ("a float in a field it ignores", ["decisions"], [{"code": "X", "decided_by": "a",
                                                       "decided_at": "b", "note": 1.5}]),
    ("a bool", ["rules", 1, "first_period_minor"], True),
)


def _plan_with(path, value) -> dict:
    document = copy.deepcopy(DOWNTOWN_V2)
    if path == ["decisions"]:
        document["decisions"] = value
        return document
    node = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return document


def _request(document: dict) -> dict:
    return {
        "plans": [document],
        "entry_at": "2026-03-03T09:14:00-05:00",
        "exit_at": "2026-03-03T18:40:00-05:00",
        "space_class": "standard",
        "currency": "USD",
    }


@pytest.mark.guarantee("F16")
@pytest.mark.parametrize("label,path,value", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_a_malformed_number_is_a_named_400_not_an_escaping_exception(label, path, value):
    status, body = run_quote(_request(_plan_with(path, value)))
    assert status == 400, f"{label}: it escaped run_quote instead of becoming a response"
    assert body["invalid"] is True
    assert "error" in body and body["error"], "a refusal that does not say what is wrong"


@pytest.mark.guarantee("F16")
def test_the_400_NAMES_THE_FIELD_so_an_operator_can_act_on_it():
    """A refusal that does not say where to look is one an operator cannot use."""
    status, body = run_quote(_request(_plan_with(["rules", 1, "first_period_minor"], 8.0)))
    assert status == 400
    assert "rules[1].first_period_minor" in body["error"], body["error"]
    assert "float" in body["error"]


@pytest.mark.guarantee("F16")
def test_validate_plan_has_the_same_boundary():
    """The other door onto the same loader. It had the identical clause and the
    identical hole."""
    status, body = run_validate({"plan": _plan_with(["rules", 1, "first_period_minor"], 8.0)})
    assert status == 400
    assert "rules[1].first_period_minor" in body["error"]


@pytest.mark.guarantee("F16")
def test_the_http_route_ANSWERS_rather_than_dropping_the_connection():
    """The failure as an integrator met it: no status, no body, nothing to act on."""
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/quote"
        payload = json.dumps(_request(_plan_with(["rules", 1, "first_period_minor"], 8.0)))
        request = urllib.request.Request(
            url, data=payload.encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                status, body = response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            status, body = error.code, json.loads(error.read())
        assert status == 400
        assert body["invalid"] is True
        assert "rules[1].first_period_minor" in body["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_the_exception_class_is_still_the_one_that_escaped():
    """The control on this whole file.

    F16 is only meaningful while `NotMinorUnits` is NOT a `ValueError` -- if it
    ever becomes one, the generic clause catches it, every test above passes for
    a reason unrelated to the fix, and the named catch could be deleted without
    anything going red. This asserts the condition that makes the rest evidence.
    """
    assert issubclass(NotMinorUnits, TypeError)
    assert not issubclass(NotMinorUnits, ValueError), (
        "NotMinorUnits became a ValueError, so the generic clause now catches it and "
        "every assertion in this file passes without the named catch doing anything. "
        "Either drop this file or re-point it at whatever still escapes."
    )
