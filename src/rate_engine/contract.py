"""The wire contract: version, request parsing, and ONE serializer.

Every surface -- `/v1/quote`, `/v1/validate-plan`, `/v1/validate-tax-sets`,
`/v1/tax` and their four CLI commands -- turns
its answer into JSON through the functions here and nowhere else. That is F6's
other half: proving the CLI and the HTTP route both MOVE when the engine changes
is weaker than proving they cannot differ, and a single serializer is what makes
the second statement true.

**Versioning, per the specification.** A commercial contract is versioned on the assumption it
will GAIN fields, so consumers must tolerate fields appearing. The consequence
that keeps that safe runs the other way: this engine REJECTS a key it does not
understand and names it, rather than ignoring it. An ignored key is how a plan an
operator believes is live ends up pricing something else.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from .breakdown import Ledger
from .engine import Quote, Stay, make_stay, max_stay_minutes, quote
from .findings import Refused
from .money import NotMinorUnits
from .plan import InvalidPlan, load_plan, parse_instant
from .tax import load_tax_sets, tax_lines
from .validator import undecided, validate_plan

#: **2 in the second version, and the bump is not decoration.** A plan written for version 1 does
#: not load on this version: the `early_bird` rule type is gone, and an unknown
#: rule type is REJECTED rather than skipped. The specification versions this contract on the
#: assumption it will gain fields, and that assumption is only safe while removals
#: are announced -- so a removal moves the number.
#:
#: **3 in the tax round, and the reason is the specification's: a commercial change moves the
#: number.** Nothing was removed and no plan changed -- a plan that loaded on 2
#: loads and prices identically on 3 -- but the module now computes tax lines and
#: has a finding code a consumer routing on codes has not seen before.
#:
#: **4: a finding code was REMOVED.** A tie at the cheapest charge is
#: priced now (F48), so `CONFLICT_MULTIPLE_RULES_AT_STAGE` had nothing left to
#: name and went. Every plan that loaded on 3 loads on 4 and every stay it priced
#: is priced the same; a stay 3 refused for a tie is priced.
#:
#: **5 in the fill-rule round: a rule type, a stay field and two finding codes
#: were ADDED.** `fill_level` prices on `occupancy_at_entry_bp`, which a quote
#: request may now carry, and `space_surcharge` gained a percent form. Every plan
#: that loaded on 4 loads on 5 and every stay it priced is priced the same, with
#: or without the new field; a consumer routing on codes meets two it has not seen.
#:
#: **6 in the fill rule's follow-up: a plan that loaded on 5 may not load.** A
#: `fill_level` rule now REQUIRES the owner's two answers, `raises_specials` and
#: `raises_vip_extra`, and a rule written without them is refused by name. Plans
#: with no fill rule load and price exactly as on 5.
SCHEMA_VERSION = 6

QUOTE_REQUEST_KEYS = frozenset({"plans", "entry_at", "exit_at", "space_class", "currency"})

#: Keys a quote request MAY carry. Absent and `null` mean the same thing: the
#: caller has no figure. Optional rather than required so that every request a
#: version-4 consumer sends is still a whole request -- a plan with no fill rule
#: never reads it.
QUOTE_OPTIONAL_KEYS = frozenset({"occupancy_at_entry_bp"})
VALIDATE_REQUEST_KEYS = frozenset({"plan"})
VALIDATE_TAX_SETS_REQUEST_KEYS = frozenset({"tax_sets"})
TAX_REQUEST_KEYS = frozenset({"tax_sets", "subtotal_minor", "currency", "at"})


def _require(
    document: object, keys: frozenset[str], where: str,
    optional: frozenset[str] = frozenset(),
) -> dict:
    if not isinstance(document, dict):
        raise InvalidPlan(f"{where} must be an object, got {type(document).__name__}.")
    missing = sorted(keys - set(document))
    unknown = sorted(set(document) - keys - optional)
    if missing:
        raise InvalidPlan(f"{where} is missing required field(s): {', '.join(missing)}.")
    if unknown:
        raise InvalidPlan(
            f"{where} carries key(s) this version does not understand: "
            f"{', '.join(unknown)}. Rejected, not ignored."
        )
    return document


def parse_quote_request(document: object) -> tuple[list, Stay]:
    """Parse a quote request into plans and a stay.

    `plans` is a LIST because the entry-time rule needs something to choose
    between: the plan in force at entry prices the whole stay, and an engine
    handed exactly one plan can never demonstrate that it chose by entry rather
    than by exit. One element is the ordinary case and is fine. Nothing is stored
    -- the versions arrive on the call, and a plan STORE is round B.
    """
    body = _require(document, QUOTE_REQUEST_KEYS, "request", QUOTE_OPTIONAL_KEYS)

    raw_plans = body["plans"]
    if not isinstance(raw_plans, list) or not raw_plans:
        raise InvalidPlan("request.plans must be a non-empty list of plan documents.")
    plans = [load_plan(p, f"request.plans[{i}]") for i, p in enumerate(raw_plans)]

    currency = body["currency"]
    wrong = sorted({p.currency for p in plans if p.currency != currency})
    if wrong:
        raise InvalidPlan(
            f"request.currency is {currency!r} but a plan prices in {', '.join(wrong)}. "
            "The engine will not convert; a rate quoted in the wrong currency is a "
            "wrong number that looks right."
        )
    versions = [p.plan_version for p in plans]
    if len(set(versions)) != len(versions):
        raise InvalidPlan("request.plans contains two versions with the same plan_version.")

    stay = make_stay(
        parse_instant(body["entry_at"], "request.entry_at"),
        parse_instant(body["exit_at"], "request.exit_at"),
        body["space_class"],
        body.get("occupancy_at_entry_bp"),
    )
    return plans, stay


def parse_validate_request(document: object):
    body = _require(document, VALIDATE_REQUEST_KEYS, "request")
    return load_plan(body["plan"], "request.plan")


def parse_validate_tax_sets_request(document: object):
    """A garage's tax sets, loaded by `tax.load_tax_sets` -- THE loader, not a copy.

    This door adds no rule. Whatever `load_tax_sets` refuses is refused here, in
    its words, and whatever it loads is valid: a caller that stores only what this
    door accepted stores only what the engine will load when it computes the tax.
    A second validator -- in this module or in a caller -- is the defect the door
    exists to remove: two of them agreed on most inputs and disagreed on ten, and
    a set one accepted and the other refused was stored where it could never be
    loaded again.
    """
    body = _require(document, VALIDATE_TAX_SETS_REQUEST_KEYS, "request")
    return load_tax_sets(body["tax_sets"], "request.tax_sets")


def parse_tax_request(document: object):
    """The loader's own document, and the three arguments `tax_lines` takes.

    Only the request shape, the sets and the instant are judged here. The
    subtotal and the currency go to `tax_lines` exactly as they arrived, because
    it judges them itself -- a second check here would be a second rule, the
    defect `parse_validate_tax_sets_request` records.
    """
    body = _require(document, TAX_REQUEST_KEYS, "request")
    sets = load_tax_sets(body["tax_sets"], "request.tax_sets")
    at = parse_instant(body["at"], "request.at")
    return sets, body["subtotal_minor"], body["currency"], at


# --- the one serializer ----------------------------------------------------
#
# It builds the BODY and it encodes the BYTES. Building it here while each
# surface called `json.dumps` for itself is what made "the CLI returns the same
# bytes as /v1/quote" false: there were three encode sites with two different
# argument lists, and `print()` added a newline the route does not. F6 asserted
# byte-equality and could not see any of it, because the test decoded both sides
# before comparing.


def encode(body: dict[str, Any]) -> bytes:
    """THE response bytes. Every surface writes exactly what this returns.

    No trailing newline: the route writes these bytes with a Content-Length, so a
    newline here would be part of the payload. The CLI writes them to stdout
    unchanged and adds the newline separately, outside the payload, so a terminal
    still behaves -- see cli.py.
    """
    return json.dumps(body, indent=2, sort_keys=False).encode()


def quote_response(result: Quote) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **result.to_json()}


def refusal_response(refused: Refused) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **refused.to_json()}


def invalid_response(error: Exception) -> dict[str, Any]:
    """400: the request or the plan could not be read, and the sentence says why.

    A refusal that carries a code (`findings.INVALID_CODES`) carries it as
    `code`, after `error`. Every other refusal is the bytes it always was.
    """
    body: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "invalid": True, "error": str(error)}
    code = error.code if isinstance(error, InvalidPlan) else None
    if code is not None:
        body["code"] = code
    return body


def validate_response(plan) -> dict[str, Any]:
    """Every finding, split into the ones the owner still has to look at and the
    ones they have already acknowledged.

    **A DECISION IS AN ACKNOWLEDGEMENT, NOT A PRICE.** `decisions[]` carries a
    `code` and a free-text `note`, and a note cannot price a stay. So `settled`
    does NOT mean "the engine will now answer this" -- a stay hitting a SETTLED
    gap is refused exactly as one hitting an outstanding gap is, and
    `tests/test_f1_never_guesses.py::test_a_stay_hitting_a_DECIDED_gap_is_still_refused`
    is the line that holds it there. The split exists because an owner working
    through a list needs to know what is left, not because deciding changes an
    answer. The way to make a gap price is to add a RULE, which is a visible plan
    change -- that is how the specification says an owner resolves a gap.

    `decided` is stamped here rather than on the Finding, because decidedness is
    a property of (finding, plan) and a Finding does not know which plan it came
    from. The membership test itself is NOT re-implemented here: `undecided()`
    owns the rule that a decision matches on CODE, and a second copy of that rule
    at a second site is exactly the drift findings.py exists to prevent.

    **`max_stay_minutes` is the longest stay the engine prices** -- the same for
    every plan, so it is not a finding about this one -- read from
    `engine.MAX_STAY_DAYS` at every call (F62). It rides on the answer a rate
    setup already asks for, so the setup can show the owner that a longer stay
    is refused, GAP_STAY_LONGER_THAN_MAX_STAY, and needs an operator.
    """
    findings = validate_plan(plan)
    outstanding_codes = {f.code for f in undecided(plan)}
    serialized = [
        {**f.to_json(), "decided": f.code not in outstanding_codes} for f in findings
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_version": plan.plan_version,
        "max_stay_minutes": max_stay_minutes(),
        "findings": serialized,
        "gaps": sum(1 for f in findings if f.is_gap),
        "conflicts": sum(1 for f in findings if not f.is_gap),
        "outstanding": sum(1 for f in serialized if not f["decided"]),
        "settled": sum(1 for f in serialized if f["decided"]),
    }


def validate_tax_sets_response(sets) -> dict[str, Any]:
    """What was loaded, set by set in the order it arrived: the instant each takes
    effect, as the loader read it, and how many rules it holds. No finding list:
    a tax set has no gaps to acknowledge -- the loader either loads it or refuses
    it by name, and the refusal is `invalid_response`, exactly as a plan's is.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "tax_sets": [
            {"effective_from": s.effective_from.isoformat(), "rule_count": len(s.rules)}
            for s in sets
        ],
    }


def tax_response(lines) -> dict[str, Any]:
    """The lines exactly as `Ledger.to_json()` writes a breakdown's, and their total.

    `total_minor` is the ledger's own total, the one route to a sum this module
    has (F8): the caller adds these lines after its validation line, and its fee
    is still the running total of its ledger.
    """
    ledger = Ledger(list(lines))
    return {
        "schema_version": SCHEMA_VERSION,
        "lines": ledger.to_json(),
        "total_minor": ledger.total_minor,
    }


def run_quote(document: object) -> tuple[int, dict[str, Any]]:
    """Parse, price, serialize -- the whole of `/v1/quote` and of `rate-engine quote`.

    Returns an HTTP-ish status alongside the body so both surfaces agree on what
    a refusal is, rather than each deciding for itself.

    **`NotMinorUnits` is named explicitly, and `TypeError` is NOT.** It subclasses
    `TypeError` rather than `ValueError`, so `except (InvalidPlan, ValueError)`
    did not catch it: a plain JSON float in a plan -- `8.0`, ordinary operator
    data -- escaped this function entirely, and `/v1/quote` dropped the connection
    without answering. Widening the clause to `TypeError` would have fixed that
    and broken something worse: every genuine programming error in this module is
    a `TypeError` too, and each one would come back to an operator as "your plan
    is invalid", which is a confident wrong answer in a module whose standing
    acceptance is that it is never wrong silently. The refusal is named; the bug
    is still allowed to crash.
    """
    try:
        plans, stay = parse_quote_request(document)
    except (InvalidPlan, NotMinorUnits, ValueError) as exc:
        return 400, invalid_response(exc)
    try:
        return 200, quote_response(quote(plans, stay))
    except Refused as refused:
        # 422: the request was well-formed and the plan cannot price it. That is
        # not a server error and not a bad request -- it is the module working.
        return 422, refusal_response(refused)


def run_validate(document: object) -> tuple[int, dict[str, Any]]:
    try:
        plan = parse_validate_request(document)
    except (InvalidPlan, NotMinorUnits, ValueError) as exc:
        return 400, invalid_response(exc)
    return 200, validate_response(plan)


def run_validate_tax_sets(document: object) -> tuple[int, dict[str, Any]]:
    """The whole of `/v1/validate-tax-sets` and of `rate-engine validate-tax-sets`.

    `run_validate`'s shape exactly -- the same three refusals caught and nothing
    wider (see `run_quote` on why `TypeError` is not one of them), the same 400
    and the same body -- so a caller that speaks to one door needs no new habit
    for the other.
    """
    try:
        sets = parse_validate_tax_sets_request(document)
    except (InvalidPlan, NotMinorUnits, ValueError) as exc:
        return 400, invalid_response(exc)
    return 200, validate_tax_sets_response(sets)


def run_tax(document: object) -> tuple[int, dict[str, Any]]:
    """The whole of `/v1/tax` and of `rate-engine tax`.

    The shapes are the ones that already exist: 400 `invalid` with the sentence
    the loader or `tax_lines` wrote, 422 with the findings `Refused` carries, 200
    with the lines. **The 400 covers the `tax_lines` CALL, not only the parse.**
    `tax_lines` judges its own three arguments -- a currency it does not render, a
    negative or non-integer subtotal -- and it does so after the request has
    parsed; a refusal caught only around parsing escapes this function exactly as
    a plain float once escaped `run_quote`. `ValueError` is caught around the
    parse and NOT around the arithmetic, for `run_quote`'s reason: past the parse
    nothing refuses by raising one, so one arriving there is a bug, and it is
    allowed to crash rather than come back as "your request is invalid".
    """
    try:
        sets, subtotal_minor, currency, at = parse_tax_request(document)
    except (InvalidPlan, NotMinorUnits, ValueError) as exc:
        return 400, invalid_response(exc)
    try:
        lines = tax_lines(sets, subtotal_minor=subtotal_minor, currency=currency, at=at)
    except (InvalidPlan, NotMinorUnits) as exc:
        return 400, invalid_response(exc)
    except Refused as refused:
        # 422, as `run_quote`: well-formed, and the garage's own statement cannot
        # tax this instant -- the module working, not a bad request.
        return 422, refusal_response(refused)
    return 200, tax_response(lines)


def breakdown_text(ledger: Ledger, currency: str, width: int = 78) -> str:
    """The human rendering, for the CLI and for a receipt.

    Derived from the same lines the JSON carries -- the text and the amount are
    never composed twice. A line too long to sit beside its amount wraps under
    it rather than being truncated: the sentence explaining why a special did
    not apply is the one an operator reads, and a `...` in the middle of it is
    the module failing at the thing it exists to do.
    """
    from .money import format_minor

    out = []
    for line in ledger.lines:
        amount = format_minor(line.delta_minor, currency) if line.delta_minor else "--"
        if len(line.text) <= width:
            out.append(f"  {line.text.ljust(width)} {amount:>14}")
        else:
            wrapped = textwrap.wrap(line.text, width=width, subsequent_indent="    ")
            out.extend(f"  {part}" for part in wrapped[:-1])
            out.append(f"  {wrapped[-1].ljust(width)} {amount:>14}")
    return "\n".join(out)
