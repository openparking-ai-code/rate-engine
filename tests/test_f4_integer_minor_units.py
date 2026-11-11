"""F4 -- money is an integer of minor units, and a plan that says otherwise is
refused at load.

Refused AT LOAD, not at the point the arithmetic goes wrong: a float that reaches
the pipeline has already been written into a plan an operator believes is live.

Three shapes are tested separately because they are three different ways in and a
guard that stops one lets the others past:

* a plain float (``8.5``)
* a float that looks whole (``800.0``, and JSON's ``8e2`` which parses to one)
* a ``bool``, which is an ``int`` subclass in Python -- ``isinstance(True, int)``
  is ``True``, so a naive integer check accepts it and prices the stay at one cent

And a fourth that is not about a field the engine reads: a float sitting in a
part of the plan this version ignores. It is refused too, because the round that
adds the rule type which reads it is the round it starts pricing something.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from fixtures import DOWNTOWN_V2, plan_with, with_rule_field
from rate_engine.money import NotMinorUnits, as_minor
from rate_engine.plan import InvalidPlan, load_plan


def _refused(document) -> str:
    with pytest.raises((InvalidPlan, NotMinorUnits)) as caught:
        load_plan(document)
    return str(caught.value)


@pytest.mark.guarantee("F4")
def test_a_fractional_price_is_refused_at_load():
    message = _refused(with_rule_field("hourly", first_period_minor=8.5))
    assert "float" in message
    assert "first_period_minor" in message, "the refusal must name the field"


@pytest.mark.guarantee("F4")
def test_a_float_that_looks_whole_is_refused_too():
    """800.0 is not 800. There is no "but it is a whole number" branch, because
    that branch is how every other float gets in."""
    assert "float" in _refused(with_rule_field("hourly", first_period_minor=800.0))


@pytest.mark.guarantee("F4")
def test_json_exponent_form_parses_to_a_float_and_is_refused():
    """A plan author writing 8e2 for eight dollars produces a float, silently."""
    raw = json.dumps(DOWNTOWN_V2).replace('"first_period_minor": 800', '"first_period_minor": 8e2')
    document = json.loads(raw)
    assert isinstance(
        next(r for r in document["rules"] if r["id"] == "hourly")["first_period_minor"], float
    ), "this test's own premise: JSON exponent form is a float"
    assert "float" in _refused(document)


@pytest.mark.guarantee("F4")
def test_a_bool_is_refused_even_though_python_calls_it_an_int():
    assert isinstance(True, int), "this test's own premise: bool subclasses int in Python"
    message = _refused(with_rule_field("hourly", first_period_minor=True))
    assert "boolean" in message


@pytest.mark.guarantee("F4")
def test_a_decimal_is_refused():
    """Accurate, and still refused: one money type all the way down."""
    with pytest.raises(NotMinorUnits) as caught:
        as_minor(Decimal("8.00"), "rules[0].first_period_minor")
    assert "Decimal" in str(caught.value)


@pytest.mark.guarantee("F4")
def test_a_float_in_a_field_this_version_ignores_is_refused_as_well():
    """It is not read today. It is in a live plan, and it will be read one day."""
    assert "float" in _refused(_with_note(1.5))


# --- F4b: the SENTENCE, not three examples of it -----------------------------
#
# "A float, a bool or a Decimal anywhere in a plan is refused at load" is
# published at four sites. Every individual test above was true and the sentence
# over them was not: a bool hit an early `return` in the plan-wide walk and a
# Decimal fell off the end of it, so both were ACCEPTED at all four `decisions[]`
# fields -- the only leaves in a plan that nothing else types.
#
# The fix was to make the sentence true rather than to narrow it. What holds it
# true is the derived test below, not the two examples: an example passes for one
# field, and the sentence is a claim about every field there is or will be.


def _with_note(value) -> dict:
    """The reference plan carrying one decision whose note is `value`."""
    document = plan_with(decisions=[])
    document["rules"][0]["space_classes"] = ["standard"]
    document["decisions"] = [
        {
            "code": "GAP_NO_ACCUMULATE_RULE",
            "decided_by": "owner",
            "decided_at": "2026-03-01",
            "note": value,
        }
    ]
    return document


@pytest.mark.guarantee("F4b")
def test_a_bool_in_a_decisions_note_is_refused():
    """Measured as ACCEPTED before this fix. A note is prose an owner wrote;
    a bool in it is a malformed document, not a pricing subtlety."""
    assert "boolean" in _refused(_with_note(True))


@pytest.mark.guarantee("F4b")
def test_a_decimal_in_a_decisions_note_is_refused():
    """Also measured as ACCEPTED. `as_minor` never sees it -- nothing asks a note
    for money -- so only the plan-wide walk can refuse it."""
    assert "Decimal" in _refused(_with_note(Decimal("8.00")))


@pytest.mark.guarantee("F4b")
def test_the_published_sentence_is_true_at_EVERY_LEAF_of_a_plan():
    """DERIVED, and this is the test that makes the sentence a guarantee.

    It enumerates every leaf position in a loadable plan by walking the document
    itself, puts each of the three named types at each position in turn, and
    requires a refusal every time. A leaf added to the plan format in a later
    round is probed the day it exists -- which is the difference between a
    guarantee and a list of examples somebody remembered to extend.

    A positive control comes with it: the unmodified plan must LOAD. Without
    that, an engine refusing every document whatsoever would satisfy this.
    """
    document = _with_note("we know; the attendant handles these at the booth")
    assert load_plan(document), "the unprobed plan must load, or nothing below means anything"

    def leaves(node, path="plan"):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from leaves(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from leaves(value, f"{path}[{index}]")
        else:
            yield path

    def replace_at(node, path, value, prefix="plan"):
        """Rebuild `node` with the leaf at `path` replaced."""
        if prefix == path:
            return value
        if isinstance(node, dict):
            return {k: replace_at(v, path, value, f"{prefix}.{k}") for k, v in node.items()}
        if isinstance(node, list):
            return [replace_at(v, path, value, f"{prefix}[{i}]") for i, v in enumerate(node)]
        return node

    positions = sorted(set(leaves(document)))
    assert len(positions) > 30, (
        f"only {len(positions)} leaves were probed; the plan fixture has shrunk and "
        "this test is no longer covering the format"
    )

    accepted: list[str] = []
    for probe in (True, Decimal("8.00"), 8.0):
        for position in positions:
            probed = replace_at(document, position, probe)
            try:
                load_plan(probed)
            except (InvalidPlan, NotMinorUnits):
                continue
            accepted.append(f"{position} = {probe!r}")

    assert not accepted, (
        "the published sentence says a float, a bool or a Decimal ANYWHERE in a plan "
        "is refused at load. These were accepted:\n  " + "\n  ".join(accepted)
    )




@pytest.mark.guarantee("F4")
@pytest.mark.parametrize("probe,kind", [(8.5, "float"), (True, "bool")])
def test_the_refusal_names_the_DOCUMENT_it_was_found_in(probe, kind):
    """A tax set is walked by the same check as a plan, and was told it was one.

    "No float appears anywhere in a plan" on a tax set sends an operator to the
    wrong document. Both halves in ONE test, so neither can be fixed by breaking
    the other: the tax set is named as a tax set, and a plan is still a plan.
    """
    from rate_engine.tax import load_tax_sets

    tax_set = [{"effective_from": "2026-01-01T00:00:00-05:00", "rules": [
        {"id": "city", "label": "City parking tax", "percent_bp": probe,
         "rounding": "down", "sequence": 1},
    ]}]
    with pytest.raises(NotMinorUnits) as caught:
        load_tax_sets(tax_set)
    in_tax_set = str(caught.value)
    assert "tax_sets[0].rules[0].percent_bp" in in_tax_set, in_tax_set
    assert f"No {kind} appears anywhere in a tax set" in in_tax_set, in_tax_set
    assert "anywhere in a plan" not in in_tax_set, in_tax_set

    in_plan = _refused(_with_note(probe))
    assert f"No {kind} appears anywhere in a plan" in in_plan, in_plan
    assert "tax set" not in in_plan, in_plan
