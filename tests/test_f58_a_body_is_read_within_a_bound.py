"""F58 -- the HTTP door reads a request body only within a bound.

`do_POST` refused a body larger than `MAX_BODY_BYTES`, but a NEGATIVE
`Content-Length` passed that check, and `rfile.read` with a negative size reads
to the end of the connection. A caller that sent `Content-Length: -1` and kept
the connection open held a server thread for as long as it liked, and could
send as much as it liked. It is now a named 400.

The connections had no socket timeout either, so a caller that stopped part-way
through a body held its thread the same way. Every connection now carries
`SOCKET_TIMEOUT_SECONDS`.

`scripts/fail_controls.py` lets a negative length through again, and separately
removes the timeout, and requires this file to go red each time.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from rate_engine.service import SOCKET_TIMEOUT_SECONDS, Handler, make_server

ROUTES = ("/v1/quote", "/v1/validate-plan", "/v1/validate-tax-sets", "/v1/tax")


@pytest.fixture
def port():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _head(route: str, length: str) -> bytes:
    return (
        f"POST {route} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        f"Content-Type: application/json\r\nContent-Length: {length}\r\n\r\n"
    ).encode()


def _read_all(connection: socket.socket) -> bytes:
    received = b""
    while chunk := connection.recv(4096):
        received += chunk
    return received


@pytest.mark.guarantee("F58")
@pytest.mark.parametrize("route", ROUTES)
def test_a_negative_length_is_a_named_400(port, route):
    """The caller keeps the connection open and sends nothing more. Without the
    check the server waits for the end of the connection, and this read times
    out instead of receiving an answer."""
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        connection.sendall(_head(route, "-1"))
        answer = _read_all(connection)
    assert answer.startswith(b"HTTP/1.0 400 "), answer[:200]
    assert b"Content-Length is negative" in answer


@pytest.mark.guarantee("F58")
def test_every_connection_carries_a_socket_timeout():
    """`StreamRequestHandler` leaves `timeout` as None, which is no timeout."""
    assert Handler.timeout == SOCKET_TIMEOUT_SECONDS
    assert 0 < SOCKET_TIMEOUT_SECONDS <= 60


@pytest.mark.guarantee("F58")
def test_a_caller_that_stops_part_way_through_a_body_is_disconnected(port, monkeypatch):
    """Ten bytes promised, two sent, then nothing. The server gives up after its
    timeout -- shortened here so the test is quick -- and closes the connection,
    and the next request is answered as usual."""
    monkeypatch.setattr(Handler, "timeout", 0.3)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(_head("/v1/quote", "10") + b"{}")
        started = time.monotonic()
        answer = _read_all(connection)
        waited = time.monotonic() - started
    assert answer == b"", answer[:200]
    assert waited < 4

    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(_head("/v1/quote", "4") + b"null")
        answer = _read_all(connection)
    assert answer.startswith(b"HTTP/1.0 400 "), answer[:200]
