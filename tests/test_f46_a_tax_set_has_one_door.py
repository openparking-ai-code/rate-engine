"""F46 -- a tax set is judged by the engine's loader, through a door, and nowhere else.

`load_tax_sets` was a library call and nothing more, so the platform that stores
a garage's taxes wrote its own validator to the same rules. The two agreed on
most inputs and disagreed on ten: an id or a label made only of U+001C-U+001F or
U+0085 is blank to Python's `str.strip()` and not to JavaScript's `trim()`. The
platform stored those sets; this module refuses them at load; and because a
garage's sets are append-only and loaded as a whole list, one of them meant that
garage's taxes never loaded again.

The fix is not a better copy. `POST /v1/validate-tax-sets` and
`rate-engine validate-tax-sets` hand the document to `load_tax_sets` and answer
what it answers, in `validate-plan`'s shape. What is measured here:

  - every refusal the loader makes reaches BOTH surfaces as the same named
    refusal, byte for byte, and a valid set is valid from both;
  - the ten blank-text inputs are refused, naming the field;
  - the door's verdict IS the loader's, input for input -- the same refusal
    text, or a load -- so a break in the loader is a break in the door
    (`scripts/fail_controls.py` plants one and requires this file to go red).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from rate_engine.contract import encode, run_validate_tax_sets
from rate_engine.service import make_server
from rate_engine.tax import load_tax_sets

AT = "2026-01-01T00:00:00Z"
RULE = {
    "id": "city", "label": "City parking tax", "percent_bp": 1850, "rounding": "nearest",
    "sequence": 1,
}
VALID = [{"effective_from": AT, "rules": [RULE]}]
NONE = [{"effective_from": AT, "rules": []}]


def at(effective_from, *rules):
    """A request body holding one set taking effect at `effective_from`."""
    return {"tax_sets": [{"effective_from": effective_from, "rules": list(rules)}]}


def one(**over):
    """One set holding one rule, with `over` replacing (or, as None, removing) rule keys."""
    rule = {k: v for k, v in {**RULE, **over}.items() if v is not None}
    return [{"effective_from": AT, "rules": [rule]}]


#: The ten inputs the platform's copy accepted and this loader refuses.
BLANK_CODE_POINTS = (0x1C, 0x1D, 0x1E, 0x1F, 0x85)
BLANK_TEXT = {
    f"{field}=U+{cp:04X}": (one(**{field: chr(cp)}), field)
    for field in ("id", "label")
    for cp in BLANK_CODE_POINTS
}

#: One input per refusal the loader makes, each through the door's request shape.
#: Keys are the request BODY, so a malformed request is in here too.
REFUSED: dict[str, object] = {
    "request not an object": [],
    "request missing tax_sets": {},
    "request with an unknown key": {"tax_sets": VALID, "garage": "x"},
    "tax_sets not a list": {"tax_sets": {}},
    "tax_sets empty": {"tax_sets": []},
    "set not an object": {"tax_sets": ["x"]},
    "set missing rules": {"tax_sets": [{"effective_from": AT}]},
    "set missing effective_from": {"tax_sets": [{"rules": []}]},
    "set with an unknown key": {"tax_sets": [{"effective_from": AT, "rules": [], "x": 1}]},
    "effective_from naive": {"tax_sets": [{"effective_from": "2026-01-01T00:00:00", "rules": []}]},
    "effective_from not ISO": {"tax_sets": [{"effective_from": "soon", "rules": []}]},
    "effective_from Feb 30": at("2026-02-30T00:00:00Z"),
    "effective_from not a string": {"tax_sets": [{"effective_from": 1767225600, "rules": []}]},
    "rules not a list": {"tax_sets": [{"effective_from": AT, "rules": {}}]},
    "rule not an object": {"tax_sets": [{"effective_from": AT, "rules": [None]}]},
    "rule missing id": {"tax_sets": one(id=None)},
    "rule missing sequence": {"tax_sets": one(sequence=None)},
    "rule with a base": at(AT, {**RULE, "base": "subtotal"}),
    "id blank": {"tax_sets": one(id=" ")},
    "id not a string": {"tax_sets": one(id=5)},
    "label empty": {"tax_sets": one(label="")},
    "percent_bp zero": {"tax_sets": one(percent_bp=0)},
    "percent_bp float": {"tax_sets": one(percent_bp=18.5)},
    "percent_bp whole float": {"tax_sets": one(percent_bp=100.0)},
    "percent_bp bool": {"tax_sets": one(percent_bp=True)},
    "percent_bp string": {"tax_sets": one(percent_bp="1850")},
    "rounding unknown": {"tax_sets": one(rounding="half_even")},
    "rounding null": at(AT, {**RULE, "rounding": None}),
    "sequence negative": {"tax_sets": one(sequence=-1)},
    "two rules one id": at(AT, RULE, {**RULE, "sequence": 2}),
    "two rules one sequence": at(AT, RULE, {**RULE, "id": "state"}),
    "two sets one instant": {
        "tax_sets": [NONE[0], {"effective_from": "2026-01-01T02:00:00+02:00", "rules": []}]
    },
    "a float anywhere": {"tax_sets": [{"effective_from": AT, "rules": [], "x": 1.0}]},
    **{f"blank {name}": {"tax_sets": doc} for name, (doc, _field) in BLANK_TEXT.items()},
}

#: Inputs the loader accepts -- each one the other side of a boundary above.
LOADED: dict[str, object] = {
    "one rule": {"tax_sets": VALID},
    "stated none": {"tax_sets": NONE},
    "percent_bp one": {"tax_sets": one(percent_bp=1)},
    "sequence zero": {"tax_sets": one(sequence=0)},
    "id one character": {"tax_sets": one(id="x")},
    "label with U+001C inside text": {"tax_sets": one(label="\x1cCity\x1c")},
    "two sets, two instants, out of order": {
        "tax_sets": [{"effective_from": "2027-01-01T00:00:00Z", "rules": []}, VALID[0]]
    },
    **{f"rounding {r}": {"tax_sets": one(rounding=r)} for r in ("up", "down", "nearest")},
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
    request = urllib.request.Request(
        url + "/v1/validate-tax-sets",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _over_cli(tmp_path, tax_sets: object) -> subprocess.CompletedProcess:
    path = tmp_path / "tax_sets.json"
    path.write_text(json.dumps(tax_sets))
    return subprocess.run(
        [
            sys.executable, "-m", "rate_engine.cli", "validate-tax-sets",
            "--tax-sets", str(path), "--json",
        ],
        capture_output=True,
    )


@pytest.mark.guarantee("F46")
def test_every_refusal_reaches_both_surfaces_as_the_same_named_refusal(base_url, tmp_path):
    """HTTP, CLI and the in-process path: one status, one set of bytes, per input.

    The CLI takes the `tax_sets` VALUE (it builds the request itself, as
    `validate-plan --plan` does), so the request-shape refusals are HTTP-only.
    """
    for name, body in REFUSED.items():
        status, direct = run_validate_tax_sets(body)
        assert status == 400, f"{name}: the door did not refuse ({status})"
        assert direct["invalid"] is True and direct["error"], name
        http_status, http_bytes = _over_http(base_url, body)
        assert (http_status, http_bytes) == (400, encode(direct)), f"{name}: HTTP differs"
        if isinstance(body, dict) and set(body) == {"tax_sets"}:
            cli = _over_cli(tmp_path, body["tax_sets"])
            assert cli.returncode == 1, f"{name}: the CLI did not refuse"
            assert cli.stdout == encode(direct) + b"\n", f"{name}: the CLI's bytes differ"


@pytest.mark.guarantee("F46")
def test_CONTROL_a_valid_set_is_valid_from_both_surfaces(base_url, tmp_path):
    for name, body in LOADED.items():
        status, direct = run_validate_tax_sets(body)
        assert status == 200 and "invalid" not in direct, f"{name}: {direct}"
        assert _over_http(base_url, body) == (200, encode(direct)), f"{name}: HTTP differs"
        cli = _over_cli(tmp_path, body["tax_sets"])
        assert (cli.returncode, cli.stdout) == (0, encode(direct) + b"\n"), (
            f"{name}: the CLI differs"
        )
    # What a valid answer says: each set's instant as read, and its rule count.
    _, body = run_validate_tax_sets(LOADED["two sets, two instants, out of order"])
    assert body["tax_sets"] == [
        {"effective_from": "2027-01-01T00:00:00+00:00", "rule_count": 0},
        {"effective_from": "2026-01-01T00:00:00+00:00", "rule_count": 1},
    ]


@pytest.mark.guarantee("F46")
def test_the_ten_blank_text_inputs_are_refused_naming_the_field():
    """The inputs a second validator let through. Each is refused, and says where."""
    assert len(BLANK_TEXT) == 10
    for name, (doc, field) in BLANK_TEXT.items():
        status, body = run_validate_tax_sets({"tax_sets": doc})
        assert status == 400, f"{name}: stored-and-unloadable, again"
        where = f"request.tax_sets[0].rules[0].{field} must be a non-empty string"
        assert where in body["error"], name
    # CONTROL: an ordinary id and label pass.
    assert run_validate_tax_sets({"tax_sets": one(id="city", label="City parking tax")})[0] == 200


@pytest.mark.guarantee("F46")
def test_the_door_is_the_loader_input_for_input():
    """Not a copy that agrees today: for every input above, the door refuses exactly
    when `load_tax_sets` raises, with the loader's own sentence, and loads exactly
    when it loads. A rule changed in the loader is a rule changed in the door."""
    for name, body in {**REFUSED, **LOADED}.items():
        if not (isinstance(body, dict) and set(body) == {"tax_sets"}):
            continue  # request-shape refusals are the door's own, and the loader never sees them
        status, door = run_validate_tax_sets(body)
        try:
            sets = load_tax_sets(body["tax_sets"], "request.tax_sets")
        except Exception as exc:  # noqa: BLE001 - whatever the loader raises, the door must match
            assert (status, door["error"]) == (400, str(exc)), f"{name}: the door is not the loader"
        else:
            assert status == 200, f"{name}: the loader loads it and the door refuses it"
            assert [s["rule_count"] for s in door["tax_sets"]] == [len(s.rules) for s in sets], name


def test_the_corpus_reaches_every_refusal_the_loader_names():
    """The control on the corpus itself: an input list that never reached a refusal
    would leave that refusal unmeasured by the byte comparison above."""
    errors = {run_validate_tax_sets(body)[1]["error"] for body in REFUSED.values()}
    # 43 inputs, 31 sentences. The loader says one sentence for a list that is
    # not a list and one that is empty, one for every blank or non-string id, and
    # one for every blank label -- so the ten blank-text inputs, `id` blank, `id`
    # not a string and `label` empty add no sentence of their own. Every other
    # input is refused for a reason nothing else in the corpus reaches.
    assert (len(REFUSED), len(errors)) == (43, 31), (len(REFUSED), len(errors))
