"""F38 -- every identifier the published documents name in backticks exists.

**This is the defect the estate paid for three times in one day: a true-sounding
published sentence sitting over correct code.** A document that names
`early_bird` after `early_bird` is deleted reads perfectly. Nothing compiles it,
nothing imports it, and the reader it misleads is an integrator or an operator
rather than a test runner. `docs/CONTRACT.md`'s generated blocks are derived and
cannot rot -- but the prose AROUND them is ordinary writing, and so is all of
README.md, and prose is where the rot lives.

So the sites are DERIVED rather than listed. Every backticked token in the two
published documents is pulled out and classified against what the code actually
holds -- the rule registry, the stage names, the finding codes, the plan's own
keys, every field each rule type accepts, every enumerated value a plan may
state, the traits, and the guarantee ids. A token that looks like something this
module owns and is not one of them fails this test, naming it.

**Anything else must be in VOCABULARY, below.** That list is not a loophole, it
is the record: it holds the backticked words that are English, JSON or Python
rather than identifiers of ours, and adding to it is a deliberate act somebody
writes down. A check whose escape hatch is silent is not a check.

What this does NOT claim: that every SENTENCE is true. No mechanism can decide
that. It claims that every NAME is real, which is the half that can be decided
and the half that has actually gone wrong here.
"""

from __future__ import annotations

import re

import pytest

from plant import ROOT

#: The PUBLISHED CONTRACT SURFACE, and deliberately only that. `CONTRIBUTING.md`
#: is contributor process: it names CI job names and a git branch, a vocabulary
#: this module does not own, and including it would mean allowlisting four words
#: that are genuinely not ours -- which weakens the allowlist for no gain.
#:
#: Note that README.md uses bold far more than backticks, so what is checked
#: there is a handful of tokens. That is a limit of the mechanism and is stated
#: rather than papered over: this proves every NAME the documents mark as code is
#: real, not that every claim in them is true.
DOCUMENTS = ("README.md", "docs/CONTRACT.md")

#: Names this module USED to hold and may now be mentioned only as history --
#: the contract's version notes say `early_bird` is gone, and that sentence has
#: to survive the check that would otherwise call it stale.
#:
#: Self-policing: a test below requires every entry to be absent from the code,
#: so if one of these ever comes back the entry has to go with it.
REMOVED = frozenset({"early_bird"})

#: Backticked tokens that are not identifiers this module owns. English, JSON,
#: Python, ISO, and the shell. Every entry here is a decision that this word is
#: not ours to check -- which is why it is a list somebody writes rather than a
#: pattern that quietly swallows things.
VOCABULARY = frozenset(
    {
        # Python and JSON vocabulary
        "null", "int", "bool", "float", "str", "Decimal", "zoneinfo", "8e2",
        "1e2", "100.0", "100.5", "True",
        # time and money notation
        "HH:MM", "YYYY-MM-DD", "%H:%M",
        # the CLI and the routes
        "rate-engine", "quote", "validate-plan", "/v1/quote", "/v1/validate-plan",
        "validate-tax-sets", "/v1/validate-tax-sets", "/v1/tax",
        "POST", "pytest", "pip",
        # keys of a JSON response body, which are strings in the code, not names
        # (`invalid` left this list when the 400 shape began to be derived, F60)
        "rule_count", "tax_sets", "probe",
        # things named in prose that are code but not identifiers of ours
        "datetime.time", "time.fromisoformat", "json.dumps", "importlib.reload",
        "max", "min",
        # values a plan may state that are checked as members elsewhere, plus the
        # shapes the contract quotes back at the reader
        "20.5", "2000", "1250",
        # a finding code REMOVED in schema version 4, named only where the
        # contract records the removal so a consumer routing on it can find out why
        "CONFLICT_MULTIPLE_RULES_AT_STAGE",
    }
)

TOKEN = re.compile(r"`([^`\n]+)`")


def _owned_names() -> dict[str, set[str]]:
    """Everything this module actually holds, by category. Read from the code."""
    import rate_engine  # noqa: F401  (registers the rule types)
    from _guarantees import GUARANTEES
    from rate_engine import engine
    from rate_engine.engine import RESOLVED, SPECIAL_USED, TIME_BASED_USED
    from rate_engine.findings import ALL_CODES, INVALID_CODES
    from rate_engine.plan import PLAN_KEYS, RESOLUTION_MODES
    from rate_engine.rules import (
        RULE_TYPES,
        TRAITS,
        daily_max,
        fill_level,
        grace,
        increment,
        space_surcharge,
        time_window,
        weekly_max,
    )
    from rate_engine.stages import STAGES
    from rate_engine.tax import TAX_ROUNDINGS, TAX_RULE_KEYS, TAX_SET_KEYS
    from rate_engine.wallclock import DAYS_OF_WEEK

    modules = (daily_max, fill_level, grace, increment, space_surcharge, time_window, weekly_max)
    fields = {"id", "type", "stage", "space_classes", "label", "order", "mode", "kind"}
    for module in modules:
        fields |= set(module.EXTRA)
    fields |= set(space_surcharge.PERCENT_EXTRA)
    # Nested field names the rule types define inside their own objects.
    fields |= {"days", "dates", "price_minor", "percent_bp", "minor", "amount",
               "direction", "rounding"}

    values = set(RESOLUTION_MODES) | set(DAYS_OF_WEEK)
    values |= set(time_window.DAY_SPANS) | set(time_window.APPLIES_ON_KINDS)
    values |= set(time_window.EFFECT_STAGES) | set(time_window.DIRECTIONS)
    values |= set(time_window.AMOUNT_KINDS) | set(time_window.ADJUST_ROUNDINGS)
    values |= set(increment.ROUNDING_MODES)
    values |= set(daily_max.DAY_BOUNDARIES) | set(weekly_max.WEEK_BOUNDARIES)
    values |= set(TAX_ROUNDINGS)
    values |= set(fill_level.ROUNDINGS) | set(space_surcharge.ROUNDINGS)
    values |= set(fill_level.ANSWERS)

    # The tax functions, their keyword arguments, and the fields a tax set and a
    # tax rule carry -- read from the module, so a renamed one turns this red.
    import inspect

    from rate_engine import tax

    tax_names = set(tax.__all__) | set(TAX_SET_KEYS) | set(TAX_RULE_KEYS)
    tax_names |= {
        name for name, parameter in inspect.signature(tax.tax_lines).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }

    return {
        "response field": _response_fields(),
        "rule type": set(RULE_TYPES),
        "stage": set(STAGES),
        "trait": set(TRAITS),
        "finding code": set(ALL_CODES),
        "invalid code": set(INVALID_CODES),
        "plan key": set(PLAN_KEYS),
        "rule field": fields,
        "stated value": values,
        "guarantee": set(GUARANTEES),
        "tax": tax_names,
        "engine line code": {SPECIAL_USED, TIME_BASED_USED, RESOLVED},
        # The engine's one stated limit (F62), read off the module that holds it.
        "engine constant": {name for name in ("MAX_STAY_DAYS",) if hasattr(engine, name)},
    }


def _response_fields() -> set[str]:
    """The names that appear in a RESPONSE, taken by producing two.

    `schema_version`, `fee_minor`, `delta_minor` and the rest are contract
    vocabulary the documents use constantly, and they are not plan keys. Derived
    by pricing a stay and refusing one rather than listed here, so a field added
    to the wire format is covered the day it exists.
    """
    import json

    from rate_engine.contract import run_quote

    plan = json.loads((ROOT / "tests" / "plans" / "downtown_v2.json").read_text())
    request = {
        "plans": [plan], "entry_at": "2026-03-03T09:14:00-05:00",
        "exit_at": "2026-03-03T18:40:00-05:00", "space_class": "standard",
        "currency": "USD",
    }
    status, priced = run_quote(request)
    assert status == 200, priced
    from rate_engine.contract import QUOTE_OPTIONAL_KEYS

    fields = set(request) | set(QUOTE_OPTIONAL_KEYS) | set(priced)
    for line in priced["breakdown"]:
        fields |= set(line)

    # A stay the early bird qualifies for, so the line that compares the special
    # with the time-based rate -- and the key only it carries -- is derived too.
    status, compared = run_quote(
        {**request, "entry_at": "2026-03-03T08:30:00-05:00", "exit_at": "2026-03-03T09:30:00-05:00"}
    )
    assert status == 200, compared
    for line in compared["breakdown"]:
        fields |= set(line)

    # A stay past the plan's stated ceiling, so the refusal shape is derived too.
    status, refused = run_quote({**request, "exit_at": "2026-03-04T18:40:00-05:00"})
    assert status == 422, refused
    fields |= set(refused)
    for finding in refused["findings"]:
        fields |= set(finding)

    # A plan that does not load, so the 400 shape is derived too -- one whose
    # refusal carries a code (F60), so `code` beside `error` is read off the wire.
    from rate_engine.contract import run_validate

    over = json.loads(json.dumps(plan))
    over["adjust_order"] = None
    over["rules"].append({
        "id": "over", "type": "time_window", "stage": "ADJUST", "space_classes": ["standard"],
        "label": "Over 100%", "applies_on": {"kind": "days_of_week", "days": ["sat"]},
        "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
        "day_span": "any_span",
        "effect": {"kind": "adjust", "direction": "discount", "rounding": "down",
                   "amount": {"kind": "percent", "percent_bp": 15000}},
    })
    status, invalid = run_validate({"plan": over})
    assert status == 400 and "code" in invalid, invalid
    fields |= set(invalid)

    # And a plan that DOES load: the validate-plan answer, `max_stay_minutes` in it
    # (F62), taken off the wire like the rest.
    status, validated = run_validate({"plan": plan})
    assert status == 200, validated
    fields |= set(validated)

    # And the tax door's answer, taken the same way: a figure with a line in it.
    from rate_engine.contract import run_tax

    status, taxed = run_tax(
        {
            "tax_sets": [{"effective_from": "2026-01-01T00:00:00Z", "rules": [{
                "id": "city", "label": "City tax", "percent_bp": 1000,
                "rounding": "up", "sequence": 1,
            }]}],
            "subtotal_minor": 1000, "currency": "USD", "at": "2026-06-01T00:00:00Z",
        }
    )
    assert status == 200 and taxed["lines"], taxed
    fields |= set(taxed)
    for line in taxed["lines"]:
        fields |= set(line)
    return fields


def _tokens() -> dict[str, list[tuple[str, int]]]:
    """Every backticked token in the published documents, with where it came from."""
    found: dict[str, list[tuple[str, int]]] = {}
    for name in DOCUMENTS:
        for number, line in enumerate((ROOT / name).read_text().splitlines(), start=1):
            for token in TOKEN.findall(line):
                found.setdefault(token.strip(), []).append((name, number))
    return found


SOURCE_SUFFIXES = (".py", ".md", ".json", ".toml", ".yml")


def _is_a_path(token: str) -> bool:
    """A file this repository contains, or claims to.

    Whitespace disqualifies it: `POST /v1/quote` is a route and
    `python scripts/fail_controls.py` is a command line, and treating either as a
    path would have this test reporting a missing file for a document that is
    perfectly correct. That is not hypothetical -- both were reported on the
    first run of this check.
    """
    if any(character.isspace() for character in token):
        return False
    if token in VOCABULARY:
        # `/v1/quote` is a ROUTE. It contains a slash and is not a file, and the
        # place that says so is VOCABULARY -- written down rather than special-cased
        # by a pattern that would also swallow a genuinely broken pointer.
        return False
    return "/" in token or token.endswith(SOURCE_SUFFIXES)


def _resolves_on_disk(token: str) -> bool:
    """Root-relative, or a bare filename that exists somewhere in the tree.

    The documents say `money.py`, which lives at `src/rate_engine/money.py`. A
    root-relative check alone would call that a broken pointer, and the pointer
    is fine.
    """
    if (ROOT / token).exists():
        return True
    return any(
        path.name == token
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and ".venv" not in path.parts
    )


#: A token this module would own if it existed: a bare snake_case or SCREAMING
#: identifier, or a dotted pair of them. Anything with a space, a bracket, a
#: quote or a slash is prose or a code fragment and is not classified here.
LOOKS_LIKE_OURS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def test_the_documents_are_actually_being_read():
    """The control on this file's own input, and it runs first.

    A regex that matched nothing, a path that moved, a document renamed -- any of
    those would make every assertion below pass while measuring an empty set,
    which is this project's named failure mode.
    """
    tokens = _tokens()
    assert len(tokens) >= 40, (
        f"only {len(tokens)} backticked tokens were found across {DOCUMENTS}; a regex "
        "that stopped matching, or a document that moved, would make every check "
        "below pass against an empty set"
    )
    assert "time_window" in tokens, "the rule type this round is about is not mentioned"
    assert any(_is_a_path(token) for token in tokens), "no path is being checked at all"

    owned = _owned_names()
    assert owned["rule type"], "the registry came back empty"
    assert len(owned["finding code"]) >= 5
    assert "schema_version" in owned["response field"]


@pytest.mark.guarantee("F38")
def test_every_PATH_the_documents_name_exists_on_disk():
    """A pointer to a file that moved is worse than no pointer: it sends a reader
    somewhere confidently."""
    missing = []
    for token, places in sorted(_tokens().items()):
        if not _is_a_path(token):
            continue
        if not _resolves_on_disk(token):
            missing.append(f"{token} (named at {places[0][0]}:{places[0][1]})")
    assert not missing, "the documents point at files that do not exist:\n  " + "\n  ".join(
        missing
    )


@pytest.mark.guarantee("F38")
def test_every_IDENTIFIER_the_documents_name_is_one_the_code_holds():
    """The derivation the round's contract sweep rests on.

    Not "the sentences this brief happened to name" -- every token in both
    documents, classified against the code. A rule type that is deleted, a field
    that is renamed, a finding code that is retired: each of them turns this red
    naming the document and the line.
    """
    owned = _owned_names()
    known = set().union(*owned.values()) | VOCABULARY | REMOVED

    orphans = []
    for token, places in sorted(_tokens().items()):
        if _is_a_path(token) or token in known:
            continue
        if not LOOKS_LIKE_OURS.match(token):
            continue  # prose, a fragment, or a shape rather than a name
        head = token.split(".")[0]
        if head in known:
            continue  # `increment.rounding`, `money.py`-style qualified references
        where = ", ".join(f"{doc}:{line}" for doc, line in places[:3])
        orphans.append(f"{token}  ({where})")

    assert not orphans, (
        "the published documents name things the code does not hold. Either the "
        "name is stale, or it belongs in VOCABULARY as a deliberate decision:\n  "
        + "\n  ".join(orphans)
    )


@pytest.mark.guarantee("F38")
def test_every_REMOVED_name_is_genuinely_gone_from_the_code():
    """The self-policing half of the history allowance.

    `early_bird` may be named in the version notes BECAUSE it no longer exists.
    If it ever came back, that sentence would be wrong and this entry would be
    hiding it -- so the entry is only legal while the name is really absent.
    """
    owned = _owned_names()
    still_here = sorted(REMOVED & set().union(*owned.values()))
    assert not still_here, (
        f"{', '.join(still_here)} is allowed as a REMOVED name and the code holds it "
        "again -- either the removal notice is wrong, or the allowance is stale"
    )


@pytest.mark.guarantee("F38")
def test_the_VOCABULARY_does_not_hide_a_real_identifier():
    """The control on the escape hatch.

    An allowlist that quietly grew to contain the module's own names would let
    the check above pass on a document naming a deleted rule type -- so a word in
    VOCABULARY that the code DOES hold is itself a failure, and the word belongs
    in the derived set instead.
    """
    owned = _owned_names()
    shadowed = sorted(VOCABULARY & set().union(*owned.values()))
    assert not shadowed, (
        f"VOCABULARY allows {', '.join(shadowed)}, which the code actually holds -- "
        "so the allowlist is masking the very names this check exists to verify"
    )
