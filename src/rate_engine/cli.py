"""The CLI. The same four operations, because an operator testing a rate should
not need an HTTP client.

**This is not a simulation mode.** `rate-engine quote` builds the same request
object `/v1/quote` builds and hands it to the same function, `contract.run_quote`,
and writes what `contract.encode` returns -- **the one encoder**, which both
surfaces call and neither re-implements. Exactly what is byte-identical is stated
once, in docs/CONTRACT.md's F6, F6b and F6c, which are generated from the tests
that measure it; a second hand-written copy of that claim is the one that drifts.

The one thing to know before piping it anywhere: the terminal newline is written
after the payload and OUTSIDE it, so stdout is the route's bytes plus exactly one
byte. `--json | cmp - <the route's body>` therefore exits 1 on EOF -- `cmp`
compares STREAMS, and one of them carries a newline the route does not send. Drop
that last byte and the two are identical, which is what
`test_the_cli_writes_exactly_the_bytes_the_route_returns` asserts over every
fixture. No byte count is written here on purpose: it would be a figure in prose
that nothing regenerates, which is the defect this paragraph replaced.

That is F6, and F6 is the control that matters most here: a test function that
answers differently from the production path is a tool that tells an operator
their garage will charge something it will not.

**It was false, by one byte, for the whole of the first version.** `print(json.dumps(body,
indent=2))` appended a newline the route does not send -- 1152 against 1151 --
and there were three `json.dumps` call sites with two different argument lists
while the contract claimed "one code path and one serializer". F6 asserted
byte-equality and could not see any of it, because it decoded both sides with
`json.loads` before comparing: re-serializing with `indent=4, sort_keys=True`
left the test green. The guarantee is now measured on BYTES.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contract import (
    SCHEMA_VERSION,
    breakdown_text,
    encode,
    run_quote,
    run_tax,
    run_validate,
    run_validate_tax_sets,
)
from .money import format_minor


def _write_exact(payload: bytes) -> None:
    """Write the route's bytes to stdout, unchanged, and nothing else into them.

    `print(json.dumps(...))` used to do this, and it appended a newline the route
    does not send -- 1152 bytes against 1151, measured. The newline is written
    AFTER the payload and outside it, so `rate-engine quote --json | cmp` against
    the route's body succeeds while a terminal still gets its line break.
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:  # pytest's capsys replaces stdout with a text stream
        sys.stdout.write(payload.decode())
        sys.stdout.write("\n")
        return
    stream.write(payload)
    stream.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()


def _load(path: str) -> object:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def _cmd_quote(args) -> int:
    plans = _load(args.plan)
    request = {
        "plans": plans if isinstance(plans, list) else [plans],
        "entry_at": args.entry,
        "exit_at": args.exit,
        "space_class": args.space_class,
        "currency": args.currency,
    }
    if args.occupancy_at_entry_bp is not None:
        # Only when given, so a request without it is byte-for-byte the request
        # this command has always built -- F6's bytes do not move for anyone
        # who does not price on how full the garage is.
        request["occupancy_at_entry_bp"] = args.occupancy_at_entry_bp
    status, body = run_quote(request)
    if args.json:
        _write_exact(encode(body))
        return 0 if status == 200 else 1

    if status == 200:
        print(f"\n  plan {body['plan_version']}")
        from .breakdown import Ledger, Line

        ledger = Ledger([Line(**line) for line in body["breakdown"]])
        print(breakdown_text(ledger, body["currency"]))
        print(f"\n  FEE  {format_minor(body['fee_minor'], body['currency'])}\n")
        return 0
    if body.get("refused"):
        print("\n  REFUSED -- nothing was guessed.\n")
        for finding in body["findings"]:
            print(f"    [{finding['kind']}] {finding['code']}")
            print(f"      {finding['text']}\n")
        return 1
    print(f"\n  the request could not be read: {body['error']}\n")
    if "code" in body:
        print(f"    [invalid] {body['code']}\n")
    return 2


def _cmd_validate(args) -> int:
    status, body = run_validate({"plan": _load(args.plan)})
    if args.json:
        _write_exact(encode(body))
        return 0 if status == 200 else 1
    if status != 200:
        print(f"\n  the plan could not be read: {body['error']}\n")
        if "code" in body:
            print(f"    [invalid] {body['code']}\n")
        return 2
    # The engine's own limit, the same for every plan (F62): shown where the
    # owner checks the rates, so a stay that will need an operator is no surprise.
    longest = body["max_stay_minutes"]
    limit = f"  The longest stay priced is {longest // (24 * 60)} days ({longest} minutes)."
    if not body["findings"]:
        print(f"\n  plan {body['plan_version']}: no gaps, no conflicts.")
        print(f"{limit}\n")
        return 0
    print(
        f"\n  plan {body['plan_version']}: {body['gaps']} gap(s), "
        f"{body['conflicts']} conflict(s) -- "
        f"{body['outstanding']} outstanding, {body['settled']} settled"
    )
    print(limit)
    # THE CORRECTED SENTENCE. What stood here said the engine "will refuse a stay
    # that hits an UNDECIDED gap", which is false in the direction that matters:
    # it refuses a stay that hits ANY of these, decided or not. That is the
    # correct behaviour -- `decisions[]` carries a code and a free-text note, and
    # a note cannot price a stay -- but it is not what the sentence promised, and
    # an owner who read it would think working down the list made stays priceable.
    print("  Each one is a decision for the owner. Recording a decision ACKNOWLEDGES")
    print("  a finding; it does not price it. The engine refuses a stay that hits any")
    print("  of these -- settled ones included -- rather than invent a fee for it. To")
    print("  make one priceable, add a RULE that covers it: that is a plan change,")
    print("  and it is visible.\n")

    for heading, decided in (("OUTSTANDING", False), ("SETTLED", True)):
        listed = [f for f in body["findings"] if f["decided"] is decided]
        if not listed:
            continue
        print(f"  {heading} ({len(listed)})")
        for finding in listed:
            print(f"    [{finding['kind']}] {finding['code']}")
            print(f"      {finding['text']}\n")

    # Non-zero while ANY finding stands, settled ones included. Exiting 0 once an
    # owner had acknowledged everything would say the plan was clear when stays
    # hitting those gaps are still refused -- the same false promise the sentence
    # above used to make, moved into the exit code where a script would read it.
    return 1


def _cmd_validate_tax_sets(args) -> int:
    """`validate-plan`'s exits, for the same reasons: `--json` is the route's bytes
    and exits 0 or 1 on the route's status; without it an unreadable document is 2.
    """
    status, body = run_validate_tax_sets({"tax_sets": _load(args.tax_sets)})
    if args.json:
        _write_exact(encode(body))
        return 0 if status == 200 else 1
    if status != 200:
        print(f"\n  the tax sets could not be read: {body['error']}\n")
        return 2
    print(f"\n  {len(body['tax_sets'])} tax set(s) load:")
    for s in body["tax_sets"]:
        stated = "no tax" if s["rule_count"] == 0 else f"{s['rule_count']} rule(s)"
        print(f"    from {s['effective_from']}: {stated}")
    print()
    return 0


def _cmd_tax(args) -> int:
    """`quote`'s exits: `--json` is the route's bytes and exits 0 or 1 on the
    route's status; without it a refusal is 1 and an unreadable request is 2.
    The request is built here and handed to `run_tax`, the function `/v1/tax`
    calls -- the CLI decides nothing about a tax figure (F47).
    """
    request = {
        "tax_sets": _load(args.tax_sets),
        "subtotal_minor": args.subtotal,
        "currency": args.currency,
        "at": args.at,
    }
    status, body = run_tax(request)
    if args.json:
        _write_exact(encode(body))
        return 0 if status == 200 else 1

    if status == 200:
        from .breakdown import Ledger, Line

        ledger = Ledger([Line(**line) for line in body["lines"]])
        if ledger.lines:
            print()
            print(breakdown_text(ledger, args.currency))
        else:
            print("\n  no tax lines")
        print(f"\n  TAX  {format_minor(body['total_minor'], args.currency)}\n")
        return 0
    if body.get("refused"):
        print("\n  REFUSED -- nothing was guessed.\n")
        for finding in body["findings"]:
            print(f"    [{finding['kind']}] {finding['code']}")
            print(f"      {finding['text']}\n")
        return 1
    print(f"\n  the request could not be read: {body['error']}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rate-engine",
        description=(
            "Price a parking stay and explain every line of the answer. "
            f"Contract schema v{SCHEMA_VERSION}. Calculation only -- this takes no payment."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("quote", help="price a stay (the same path /v1/quote uses)")
    q.add_argument("--plan", required=True, help="a plan document, or a list of versions, or '-'")
    q.add_argument(
        "--entry", required=True,
        help="ISO 8601 with an offset, e.g. 2026-03-03T09:14:00-05:00",
    )
    q.add_argument("--exit", required=True, dest="exit", help="ISO 8601 with an offset")
    q.add_argument("--space-class", required=True)
    q.add_argument("--currency", required=True)
    q.add_argument(
        "--occupancy-at-entry-bp", type=int, default=None, dest="occupancy_at_entry_bp",
        help="how full the garage was when the car came in, in basis points (8400 = 84%%)",
    )
    q.add_argument("--json", action="store_true", help="the exact bytes /v1/quote returns")
    q.set_defaults(func=_cmd_quote)

    v = sub.add_parser("validate-plan", help="list a plan's gaps and conflicts")
    v.add_argument("--plan", required=True)
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=_cmd_validate)

    t = sub.add_parser(
        "validate-tax-sets",
        help=(
            "load a garage's tax sets, or refuse them by name "
            "(the same path /v1/validate-tax-sets uses)"
        ),
    )
    t.add_argument("--tax-sets", required=True, dest="tax_sets", help="a list of tax sets, or '-'")
    t.add_argument(
        "--json", action="store_true", help="the exact bytes /v1/validate-tax-sets returns"
    )
    t.set_defaults(func=_cmd_validate_tax_sets)

    x = sub.add_parser(
        "tax", help="the tax lines on a subtotal (the same path /v1/tax uses)"
    )
    x.add_argument("--tax-sets", required=True, dest="tax_sets", help="a list of tax sets, or '-'")
    x.add_argument(
        "--subtotal", required=True, type=int,
        help="the money actually paid, in minor units, after every discount and validation",
    )
    x.add_argument("--currency", required=True)
    x.add_argument(
        "--at", required=True,
        help="the instant that chooses the set in force, ISO 8601 with an offset",
    )
    x.add_argument("--json", action="store_true", help="the exact bytes /v1/tax returns")
    x.set_defaults(func=_cmd_tax)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
