"""F8 -- the fee is the sum of the breakdown's deltas, by construction.

The brief asked for a rule "whose reported line disagrees with its own effect".
Under the ledger that defect is not writable: a rule's only way to change the fee
IS to return a Line, so its line and its effect are the same object. That is the
point -- the guarantee is structural rather than a comparison between two copies
of one claim, and the specification is explicit that comparing two copies verifies nothing.

So the defect this file plants is the one that IS writable and that would
reintroduce the problem: a second route to the total. An engine that adjusts the
fee outside the ledger, or a rule that mutates something the ledger does not see.
The invariant in `engine._assert_ledger_is_the_fee` catches it, it lives in the
production path rather than only in tests, and `scripts/fail_controls.py` plants
exactly that second route and requires red.

The other half is registration-time: a rule that returns something which is not a
Line, or a Line carrying non-integer money, cannot enter the ledger at all.
"""

from __future__ import annotations

import pytest

from fixtures import CORPUS, DOWNTOWN_V2, loaded
from rate_engine.breakdown import Ledger, Line
from rate_engine.engine import quote
from rate_engine.findings import FAULT_RULE_RETURNED_NOT_LINES, Refused
from rate_engine.money import NotMinorUnits


@pytest.mark.guarantee("F8")
def test_every_priced_fixture_equals_the_sum_of_its_lines():
    priced = 0
    for name, s in CORPUS.items():
        try:
            result = quote([loaded()], s)
        except Refused:
            continue
        priced += 1
        assert result.fee_minor == sum(line.delta_minor for line in result.breakdown.lines), name
    assert priced >= 10, f"only {priced} fixtures were priced; this proves too little"


@pytest.mark.guarantee("F8")
def test_a_cap_gives_back_exactly_what_it_took():
    """The line that made a plain sum impossible, and the arithmetic it now shows."""
    result = quote([loaded()], CORPUS["worked_example"])
    lines = {line.code: line for line in result.breakdown.lines}

    charged = (
        lines["increment.first_period"].delta_minor
        + lines["increment.repeat_periods"].delta_minor
    )
    assert charged == 4400
    assert lines["daily_max.applied"].delta_minor == -1400
    assert result.fee_minor == 3000 == charged + lines["daily_max.applied"].delta_minor
    assert "44.00 USD reduced to 30.00 USD" in lines["daily_max.applied"].text, (
        "the line must describe its own delta, not merely announce that a cap applied"
    )


@pytest.mark.guarantee("F8")
def test_a_rule_that_did_not_apply_contributes_exactly_zero():
    result = quote([loaded()], CORPUS["worked_example"])
    for line in result.breakdown.lines:
        if line.code.endswith(("not_applied", "not_reached")) or line.code == "stay":
            assert line.delta_minor == 0, f"{line.code} moved the fee while reporting it did not"


@pytest.mark.guarantee("F8")
def test_a_line_cannot_carry_non_integer_money():
    """Registration-time half: a Line is refused before it can reach a ledger."""
    for bad in (8.5, 800.0, True, "800"):
        with pytest.raises(NotMinorUnits):
            Line(code="x", rule_id=None, text="t", delta_minor=bad)


@pytest.mark.guarantee("F8")
def test_the_ledger_offers_no_route_to_the_total_except_adding_a_line():
    """A structural assertion about the type, not about one run of it.

    If a `set_total`, an `adjust` or a writable `total_minor` ever appears, the
    invariant becomes bypassable and this goes red the moment it is added rather
    than the round somebody uses it.
    """
    ledger = Ledger()
    writable = [
        name
        for name in dir(ledger)
        if not name.startswith("_") and name not in {"lines", "add", "total_minor", "to_json"}
    ]
    assert writable == [], f"Ledger grew {writable}; a second route to the total is a defect"

    with pytest.raises(AttributeError):
        ledger.total_minor = 999


def test_the_sum_check_can_tell_a_wrong_total_from_a_right_one():
    """The control on this file's own assertion.

    Without it, "the fee equals the sum" is a sentence that has never been shown
    to be false for anything.
    """
    ledger = Ledger()
    ledger.add(Line(code="a", rule_id=None, text="a", delta_minor=800))
    ledger.add(Line(code="b", rule_id=None, text="b", delta_minor=-300))
    assert ledger.total_minor == 500
    assert ledger.total_minor != 501


# --- K3: the amended property, established by probing rather than assumed -----
#
# The amendment asked that "a rule producing an effect with no ledger entry, or a
# ledger entry with no effect, is REFUSED AT REGISTRATION". Probing the branch
# split that into three, and only one of them was a real hole:
#
#   effect with no entry  -- IMPOSSIBLE by construction. The applier is handed
#                            (rule, stay, plan); there is no ledger to reach and
#                            no return channel but Lines. Proven below.
#   entry with no effect  -- NOT A DEFECT. Zero-delta lines are required by the
#                            design; every "NOT applied" line is one.
#   a malformed return    -- THE REAL HOLE. It used to reach Ledger.add and die
#                            with an AttributeError naming neither rule nor type.


def _stay_and_plan(applier, name: str):
    """Register a test-only rule type and build a plan whose only rule is it."""
    from rate_engine.engine import QUALIFIERS
    from rate_engine.plan import load_plan
    from rate_engine.rules import Rule, common_fields, register
    from rate_engine.stages import ACCUMULATE

    def build(raw, plan_space_classes, where):
        rule_id, classes = common_fields(raw, plan_space_classes, where, {"amount"})
        return Rule(
            id=rule_id, type=name, stage=ACCUMULATE, space_classes=classes,
            params={"amount": raw["amount"]},
        )

    register(name, ACCUMULATE, build, applier)
    QUALIFIERS[name] = lambda rule, stay, plan: rule.covers(stay.space_class)

    return load_plan(_plan_document(name))


def _plan_document(name: str) -> dict:
    """The raw document, so a test can hand it to `run_quote` rather than to `quote`.

    Split out because the surface test needs the DOCUMENT: `quote()` takes loaded
    plans, and the boundary this guarantee is about is the one `run_quote` owns.
    """
    import copy

    document = copy.deepcopy(DOWNTOWN_V2)
    document["rules"] = [
        r for r in document["rules"] if r["id"] not in ("hourly", "eb-weekday")
    ] + [
        {
            "id": f"{name}-1", "type": name, "stage": "ACCUMULATE",
            "space_classes": ["standard", "vip"], "amount": 500,
        }
    ]
    return document


def _unregister(name: str) -> None:
    from rate_engine.engine import QUALIFIERS
    from rate_engine.rules import RULE_APPLIERS, RULE_TYPES

    RULE_TYPES.pop(name, None)
    RULE_APPLIERS.pop(name, None)
    QUALIFIERS.pop(name, None)


@pytest.mark.guarantee("F8")
def test_a_rule_cannot_produce_an_effect_without_a_ledger_entry():
    """Not asserted -- demonstrated. The rule tries, and has nothing to try with."""
    plan = _stay_and_plan(lambda rule, stay, plan: [], "k3_effect_no_entry")
    try:
        result = quote([plan], CORPUS["worked_example"])
        assert result.fee_minor == 0, (
            "a rule returning no lines moved the fee, so a channel exists that the "
            "ledger cannot see -- which is the whole defect F8 guards"
        )
        assert result.fee_minor == sum(x.delta_minor for x in result.breakdown.lines)
    finally:
        _unregister("k3_effect_no_entry")


@pytest.mark.guarantee("F8b")
def test_a_rule_returning_something_that_is_not_a_line_is_refused_by_name():
    """It used to be an AttributeError from inside Ledger.add, two files away.

    Then it was a `TypeError`, which was still not a refusal: `run_quote` catches
    `Refused`, so the guarantee's own sentence -- "REFUSED by name, not left to
    crash inside the ledger" -- was false at the boundary. **This test asserted
    the `TypeError`**, which made it a test blessing the opposite of the thing it
    protects. It now asserts the refusal, and the surface assertion below is the
    half that was missing: what an operator actually receives.
    """
    plan = _stay_and_plan(
        lambda rule, stay, plan: [{"code": "x", "delta_minor": 500}], "k3_not_a_line"
    )
    try:
        with pytest.raises(Refused) as caught:
            quote([plan], CORPUS["worked_example"])
        finding = caught.value.findings[0]
        assert finding.code == FAULT_RULE_RETURNED_NOT_LINES
        assert finding.kind == "fault", "not a gap and not a conflict -- no owner can decide it"
        assert "k3_not_a_line" in finding.text, "the refusal must name the rule TYPE"
        assert "k3_not_a_line-1" in finding.text, "and the offending rule"
        assert "dict" in finding.text
    finally:
        _unregister("k3_not_a_line")


@pytest.mark.guarantee("F8b")
def test_a_rule_returning_a_bare_value_instead_of_a_list_is_refused_by_name():
    plan = _stay_and_plan(lambda rule, stay, plan: 500, "k3_bare_value")
    try:
        with pytest.raises(Refused) as caught:
            quote([plan], CORPUS["worked_example"])
        finding = caught.value.findings[0]
        assert finding.code == FAULT_RULE_RETURNED_NOT_LINES
        assert "k3_bare_value" in finding.text
        assert "int" in finding.text
    finally:
        _unregister("k3_bare_value")


@pytest.mark.guarantee("F8b")
def test_a_malformed_rule_return_reaches_A_CALLER_as_a_refusal_not_an_exception():
    """The half the old test could not see, because it stopped at `quote()`.

    `run_quote` is what both surfaces call. A `TypeError` went straight past its
    except clause and out of the contract; over HTTP that was a dropped
    connection with no response at all. This asserts the STATUS and the BODY an
    integrator actually receives.
    """
    from rate_engine.contract import run_quote

    # Called for the REGISTRATION side effect only -- run_quote loads the plan
    # itself from the document, which is the boundary this test is about.
    _stay_and_plan(lambda rule, stay, plan: 500, "k3_surface")
    try:
        status, body = run_quote(
            {
                "plans": [_plan_document("k3_surface")],
                "entry_at": "2026-03-03T09:14:00-05:00",
                "exit_at": "2026-03-03T18:40:00-05:00",
                "space_class": "standard",
                "currency": "USD",
            }
        )
        assert status == 422, "a malformed rule return must not escape as an exception"
        assert body["refused"] is True
        assert body["findings"][0]["code"] == FAULT_RULE_RETURNED_NOT_LINES
        assert body["findings"][0]["kind"] == "fault"
    finally:
        _unregister("k3_surface")


def test_a_zero_delta_line_is_correct_and_stays_accepted():
    """The control on the item above: the fix must not have banned a legitimate shape.

    A rule reporting that it did NOT apply returns a line with delta zero. If the
    return-channel check had rejected those, every "Early bird NOT applied" line
    would have died with it.
    """
    plan = _stay_and_plan(
        lambda rule, stay, plan: [
            Line(code="k3.zero", rule_id=rule.id, text="considered, no charge", delta_minor=0)
        ],
        "k3_zero_delta",
    )
    try:
        result = quote([plan], CORPUS["worked_example"])
        assert result.fee_minor == 0
        assert any(x.code == "k3.zero" for x in result.breakdown.lines)
    finally:
        _unregister("k3_zero_delta")
