"""F47 -- a tax figure is reached the same way from both surfaces.

`tax_lines` was a library call and nothing more, and the platform reaches this
engine over HTTP only -- there is no in-process shortcut (service.py). A caller
that needed a garage's tax on a stay therefore had no way to ask for it, and the
way that gets filled is a second copy of the arithmetic on the far side of the
wire. So `POST /v1/tax` and `rate-engine tax` hand the request to ONE function,
`contract.run_tax`, and write what the one encoder returns. What is measured:

  - every input below answers with the same status and the same BYTES from the
    route, the CLI (minus its newline, which F6c places outside the payload) and
    the in-process call -- a 200, a 422 and a 400 alike;
  - the lines are `tax_lines`' lines, as `Ledger.to_json()` writes them, and the
    total is their sum;
  - an instant no set covers is a 422 `GAP_NO_TAX_SET_IN_FORCE`, and the same
    request with a covering set is 200;
  - a zero subtotal produces no lines, and a non-zero one on the same sets does;
  - a bad currency, a naive instant and a negative subtotal are each a named 400
    over HTTP -- `tax_lines` raises for two of them AFTER the request has parsed,
    and a refusal caught only around the parse would drop the connection.

`scripts/fail_controls.py` breaks the CLI's path and the route's path, each on
its own, and requires this file to go red.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from rate_engine.breakdown import Ledger
from rate_engine.contract import encode, run_tax
from rate_engine.plan import parse_instant
from rate_engine.service import make_server
from rate_engine.tax import load_tax_sets, tax_lines

FROM = "2026-01-01T00:00:00Z"
CITY = {
    "id": "city", "label": "City parking tax", "percent_bp": 1850, "rounding": "nearest",
    "sequence": 1,
}
STATE = {
    "id": "state", "label": "State tax", "percent_bp": 625, "rounding": "up", "sequence": 2,
}
#: Two sets, the second a law change: the city rate moves and the state tax is repealed.
SETS = [
    {"effective_from": FROM, "rules": [STATE, CITY]},  # list order is not sequence order
    {"effective_from": "2027-01-01T00:00:00-05:00", "rules": [{**CITY, "percent_bp": 2000}]},
]
NONE = [{"effective_from": FROM, "rules": []}]
IN_FORCE = "2026-06-01T12:00:00-04:00"
BEFORE_EVERY_SET = "2025-12-31T23:59:59Z"


def request(**over) -> dict:
    return {"tax_sets": SETS, "subtotal_minor": 1999, "currency": "USD", "at": IN_FORCE, **over}


#: Inputs the CLI can also express: a JSON list of sets in a file, an integer
#: subtotal and two strings. Keyed by name; value is (request, expected status).
BOTH_SURFACES: dict[str, tuple[dict, int]] = {
    "two rules, first set": (request(), 200),
    "one rule, second set": (request(at="2027-03-01T08:00:00-05:00"), 200),
    "the second set's own instant": (request(at="2027-01-01T05:00:00Z"), 200),
    "stated none": (request(tax_sets=NONE), 200),
    "zero subtotal": (request(subtotal_minor=0), 200),
    "exact division, no rounding clause": (request(subtotal_minor=10000), 200),
    "zero-exponent currency": (request(currency="JPY", subtotal_minor=1999), 200),
    "instant before every set": (request(at=BEFORE_EVERY_SET), 422),
    "instant before every set, zero subtotal": (
        request(at=BEFORE_EVERY_SET, subtotal_minor=0), 422
    ),
    "currency unknown": (request(currency="XXX1"), 400),
    "currency lowercase": (request(currency="usd"), 400),
    "at naive": (request(at="2026-06-01T12:00:00"), 400),
    "at not ISO": (request(at="noon"), 400),
    "subtotal negative": (request(subtotal_minor=-1), 400),
    "tax sets empty": (request(tax_sets=[]), 400),
    "tax set with a base": (
        request(tax_sets=[{"effective_from": FROM, "rules": [{**CITY, "base": "x"}]}]), 400
    ),
}

#: Inputs only a JSON body can carry: the request shape, and values argparse
#: would refuse before the request exists.
HTTP_ONLY: dict[str, tuple[object, int]] = {
    "request not an object": ([], 400),
    "request missing at": ({k: v for k, v in request().items() if k != "at"}, 400),
    "request with an unknown key": ({**request(), "garage": "x"}, 400),
    "subtotal a float": (request(subtotal_minor=1999.0), 400),
    "subtotal a bool": (request(subtotal_minor=True), 400),
    "subtotal a string": (request(subtotal_minor="1999"), 400),
    "currency not a string": (request(currency=840), 400),
    "at not a string": (request(at=1767225600), 400),
}


@pytest.fixture(scope="module")
def base_url():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _over_http(url: str, body: object) -> tuple[int, bytes]:
    """The RAW BYTES the route wrote -- see test_f6 on why never a decode."""
    req = urllib.request.Request(
        url + "/v1/tax",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _over_cli(tmp_path, body: dict) -> subprocess.CompletedProcess:
    path = tmp_path / "tax_sets.json"
    path.write_text(json.dumps(body["tax_sets"]))
    return subprocess.run(
        [
            sys.executable, "-m", "rate_engine.cli", "tax",
            "--tax-sets", str(path), "--subtotal", str(body["subtotal_minor"]),
            "--currency", body["currency"], "--at", body["at"], "--json",
        ],
        capture_output=True,
    )


@pytest.mark.guarantee("F47")
def test_every_input_answers_the_same_bytes_from_the_route_and_the_cli(base_url, tmp_path):
    for name, (body, expected) in BOTH_SURFACES.items():
        status, direct = run_tax(body)
        assert status == expected, f"{name}: {status} {direct}"
        assert _over_http(base_url, body) == (status, encode(direct)), f"{name}: HTTP differs"
        cli = _over_cli(tmp_path, body)
        assert cli.returncode == (0 if status == 200 else 1), f"{name}: {cli.stderr!r}"
        assert cli.stdout == encode(direct) + b"\n", f"{name}: the CLI's bytes differ"


@pytest.mark.guarantee("F47")
def test_a_request_only_json_can_carry_is_refused_by_name_over_http(base_url):
    for name, (body, expected) in HTTP_ONLY.items():
        status, direct = run_tax(body)
        assert (status, direct.get("invalid")) == (expected, True), f"{name}: {direct}"
        assert direct["error"], name
        assert _over_http(base_url, body) == (status, encode(direct)), f"{name}: HTTP differs"


@pytest.mark.guarantee("F47")
def test_the_lines_are_tax_lines_lines_and_the_total_is_their_sum():
    """The door computes nothing of its own: it is `tax_lines`, serialized."""
    for name, (body, expected) in BOTH_SURFACES.items():
        if expected != 200:
            continue
        _, door = run_tax(body)
        lines = tax_lines(
            load_tax_sets(body["tax_sets"]),
            subtotal_minor=body["subtotal_minor"],
            currency=body["currency"],
            at=parse_instant(body["at"], "at"),
        )
        assert door["lines"] == Ledger(lines).to_json(), name
        assert door["total_minor"] == sum(line["delta_minor"] for line in door["lines"]), name
    # What a figure looks like: sequence order, not list order, and each line its own.
    _, door = run_tax(request())
    assert [(ln["rule_id"], ln["delta_minor"]) for ln in door["lines"]] == [
        ("city", 370), ("state", 125)
    ]
    assert door["total_minor"] == 495


@pytest.mark.guarantee("F47")
def test_an_instant_no_set_covers_is_refused_with_the_gap_code():
    status, body = run_tax(request(at=BEFORE_EVERY_SET))
    assert status == 422 and body["refused"] is True
    assert [f["code"] for f in body["findings"]] == ["GAP_NO_TAX_SET_IN_FORCE"]
    # CONTROL: the same request with a set covering the instant is taxed.
    covering = [{"effective_from": "2025-01-01T00:00:00Z", "rules": [CITY]}, *SETS]
    status, body = run_tax(request(at=BEFORE_EVERY_SET, tax_sets=covering))
    assert status == 200 and body["lines"], body


@pytest.mark.guarantee("F47")
def test_a_zero_subtotal_produces_no_lines():
    status, body = run_tax(request(subtotal_minor=0))
    assert (status, body["lines"], body["total_minor"]) == (200, [], 0)
    # CONTROL: a non-zero subtotal on the same sets produces lines.
    status, body = run_tax(request(subtotal_minor=1))
    assert status == 200 and len(body["lines"]) == 2, body


@pytest.mark.guarantee("F47")
def test_a_refusal_tax_lines_makes_after_the_parse_is_a_named_400_not_a_dropped_connection(
    base_url,
):
    """Two of these are raised by `tax_lines` itself, after the request parsed.
    Over HTTP a refusal that escaped `run_tax` is `RemoteDisconnected` -- an
    exception here, never a status -- so reading a status IS the measurement."""
    named = {
        "currency": (request(currency="XXX1"), "currency is 'XXX1'"),
        "naive at": (request(at="2026-06-01T12:00:00"), "request.at has no UTC offset"),
        "negative subtotal": (request(subtotal_minor=-1), "subtotal_minor is negative"),
    }
    for name, (body, says) in named.items():
        status, raw = _over_http(base_url, body)
        assert status == 400, f"{name}: {status}"
        assert says in json.loads(raw)["error"], f"{name}: {raw!r}"
    # CONTROL: the same request with all three good is taxed.
    assert _over_http(base_url, request())[0] == 200


def test_the_corpus_reaches_every_status_and_both_sides_of_each_boundary():
    """The control on the corpus: a byte comparison over inputs that never reach a
    422, or never a 400 from `tax_lines` itself, would leave that path unmeasured."""
    statuses = {expected for _body, expected in BOTH_SURFACES.values()}
    assert statuses == {200, 400, 422}
    raised_by_tax_lines = [
        name for name, (body, _e) in BOTH_SURFACES.items()
        if run_tax(body)[0] == 400 and not run_tax({**body, "currency": "USD",
                                                   "subtotal_minor": 1})[0] == 400
    ]
    # The unknown and lowercase currencies and the negative subtotal: refused by
    # `tax_lines`, and taxed once those two arguments are made good.
    assert sorted(raised_by_tax_lines) == [
        "currency lowercase", "currency unknown", "subtotal negative"
    ]
