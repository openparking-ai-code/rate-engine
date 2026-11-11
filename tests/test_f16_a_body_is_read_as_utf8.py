"""F16, at the body -- a POST body is decoded strictly as UTF-8, and anything else
is a named 400 rather than a dropped connection or a guess.

`do_POST` handed the raw BYTES to `json.loads`, which runs its own encoding
detection. Measured at 0ca131f, on every POST route: a malformed byte raised a
`UnicodeDecodeError` that nothing caught, and the client got `RemoteDisconnected`
-- no status, no body. And a UTF-16 or UTF-32 body, a UTF-8 body behind a
byte-order mark, and surrogates encoded as bytes were all DECODED and answered
200 on `/v1/validate-tax-sets`. A caller whose own layer decodes those bytes
differently from this engine -- Express replaces a bad byte with U+FFFD -- is then
judged on text it never sent. JSON over HTTP is UTF-8 (RFC 8259); the body is
decoded as that and nothing else, and only then parsed.

**Two instruments, and they are not mixed.**

  - `PROVES_THE_DECODE`: bodies refused with the ENCODING sentence. Each one
    dropped the connection or answered without the fix, so each is a
    measurement of it.
  - `STAYS_REFUSED`: a UTF-16BE body with no byte-order mark and a UTF-8 body
    with one. Both ARE valid UTF-8 -- ASCII plus NUL bytes; a byte-order mark is
    a character -- so they decode and are refused by the JSON parser, with the
    sentence an invalid-JSON body gets. They are here so they stay refused, not
    as evidence of the decode: the JSON sentence cannot tell the fix from its
    absence. (Both answered 200 before the fix, measured; naming them by an
    encoding-specific sentence would need a new rule, and none was asked for.)

`scripts/fail_controls.py` puts the auto-detecting decode back, and separately
removes the catch, and requires this file to go red each time.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import (
    SCHEMA_VERSION,
    encode,
    run_quote,
    run_tax,
    run_validate,
    run_validate_tax_sets,
)
from rate_engine.service import make_server

TAX_SETS = [{"effective_from": "2026-01-01T00:00:00Z", "rules": []}]

#: One valid request per route, answered in-process by the function the route calls.
VALID: dict[str, tuple[object, dict]] = {
    "/v1/quote": (
        run_quote,
        {
            "plans": [DOWNTOWN_V2], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T18:40:00-05:00", "space_class": "standard",
            "currency": "USD",
        },
    ),
    "/v1/validate-plan": (run_validate, {"plan": DOWNTOWN_V2}),
    "/v1/validate-tax-sets": (run_validate_tax_sets, {"tax_sets": TAX_SETS}),
    "/v1/tax": (
        run_tax,
        {"tax_sets": TAX_SETS, "subtotal_minor": 1999, "currency": "USD",
         "at": "2026-06-01T12:00:00Z"},
    ),
}
ROUTES = tuple(VALID)


def _text(route: str) -> str:
    return json.dumps(VALID[route][1])


#: route -> body. Every one is refused with the encoding sentence, and every one
#: either dropped the connection or was decoded and answered at 0ca131f.
PROVES_THE_DECODE = {
    "FF": lambda route: b"\xff",
    "overlong C0 AF": lambda route: b"\xc0\xaf",
    "truncated E2 82": lambda route: b"\xe2\x82",
    "UTF-16 with a BOM": lambda route: _text(route).encode("utf-16"),
    "UTF-32 with a BOM": lambda route: _text(route).encode("utf-32"),
    # Not one of the brief's five: a consequence of the same decode, recorded.
    # `json.loads` on bytes decodes with `surrogatepass`, so ED A0 80 -- U+D800
    # encoded as bytes, which UTF-8 forbids -- used to arrive as a lone surrogate.
    "a surrogate encoded as bytes": lambda route: b'{"x": "\xed\xa0\x80"}',
}

#: Valid UTF-8, so the decode passes them and the JSON parser refuses them.
STAYS_REFUSED = {
    "UTF-16BE with no BOM": lambda route: _text(route).encode("utf-16-be"),
    "UTF-8 with a BOM": lambda route: b"\xef\xbb\xbf" + _text(route).encode(),
}


@pytest.fixture(scope="module")
def port():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _post(port: int, route: str, body: bytes) -> tuple[int, bytes]:
    """Raw bytes out, raw bytes back. A dropped connection raises here, which is
    the failure being guarded -- it is never converted into a status."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("POST", route, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@pytest.mark.guarantee("F16")
def test_a_body_that_is_not_utf8_is_a_named_400_on_every_route(port):
    for route in ROUTES:
        for name, make in PROVES_THE_DECODE.items():
            status, raw = _post(port, route, make(route))
            assert status == 400, f"{route} {name}: {status} {raw[:120]!r}"
            error = json.loads(raw)["error"]
            assert error.startswith("body is not UTF-8: "), f"{route} {name}: {error}"


@pytest.mark.guarantee("F16")
def test_valid_utf8_that_is_not_json_stays_refused_by_the_json_sentence(port):
    for route in ROUTES:
        for name, make in {**STAYS_REFUSED, "invalid JSON": lambda r: b"{not json"}.items():
            status, raw = _post(port, route, make(route))
            assert status == 400, f"{route} {name}: {status} {raw[:120]!r}"
            error = json.loads(raw)["error"]
            assert error.startswith("body is not JSON: "), f"{route} {name}: {error}"


@pytest.mark.guarantee("F16")
def test_CONTROL_an_empty_body_and_a_valid_request_answer_as_they_did(port):
    """In the same run as the refusals above: the decode must not have moved the
    empty body onto its own sentence, nor changed a single valid answer."""
    for route in ROUTES:
        run, document = VALID[route]
        status, raw = _post(port, route, b"")
        assert (status, json.loads(raw)) == (
            400,
            {"schema_version": SCHEMA_VERSION, "invalid": True,
             "error": "request must be an object, got NoneType."},
        ), route
        expected_status, expected = run(document)
        assert expected_status == 200, (route, expected)
        assert _post(port, route, _text(route).encode()) == (200, encode(expected)), route


@pytest.mark.guarantee("F16")
def test_a_body_over_one_megabyte_is_refused_before_it_is_read(port):
    """A plan is a few kilobytes. A body declaring more than MAX_BODY_BYTES gets a
    named 413 from the length alone: the test sends the headers and a handful of
    bytes, and the answer arrives without the server waiting for the rest -- so
    the body was never read into memory, let alone parsed."""
    from rate_engine.service import MAX_BODY_BYTES

    with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
        raw.sendall(
            b"POST /v1/validate-plan HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {MAX_BODY_BYTES + 1}\r\n\r\n".encode()
            + b'{"plan": '
        )
        answer = b""
        while b"\r\n\r\n" not in answer or not answer.rstrip().endswith(b"}"):
            chunk = raw.recv(4096)
            if not chunk:
                break
            answer += chunk
    head, _, body = answer.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 413") or head.startswith(b"HTTP/1.1 413"), head
    assert json.loads(body) == {"error": f"body larger than {MAX_BODY_BYTES} bytes"}
