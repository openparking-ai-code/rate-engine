"""F22 -- whether a non-qualifying rule speaks depends on its STAGE.

The rule framework's contract said, flatly: *"A rule that did NOT qualify still
returns a line, with delta zero, saying why not."* `space_surcharge` documented
the opposite in its own docstring -- *"A stay in a space class this rule does not
cover produces NO line"* -- so the framework contract and a shipped rule type
contradicted each other and nothing measured either. The engine skips every
non-qualifying rule outside QUALIFY (`engine.py`, `if not QUALIFIERS[...]:
continue`), so the framework sentence was false for every stage except one.

The DISTINCTION is right and is kept. "This special could have applied to you and
did not" is the answer to the question operators actually ask at the counter; "a
VIP tier that was never about your space exists" is noise on a standard receipt.
What was wrong was stating it as a blanket property of every rule.

Both halves are pinned here, because a corrected sentence with no check is a
sentence that drifts back, and this one drifted for a whole round.
"""

from __future__ import annotations

import copy

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote
from rate_engine.stages import QUALIFY


def _codes(document: dict, space_class: str = "standard") -> list[str]:
    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T10:40:00-05:00", "space_class": space_class,
            "currency": "USD",
        }
    )
    assert status == 200, body
    return [line["code"] for line in body["breakdown"]]


@pytest.mark.guarantee("F22")
def test_a_QUALIFY_rule_that_did_not_qualify_STILL_SPEAKS():
    """The half that was always true, and the reason the distinction exists."""
    codes = _codes(copy.deepcopy(DOWNTOWN_V2))
    assert "time_window.not_applied" in codes, (
        "the special that did not apply said nothing, so the breakdown cannot answer "
        "'why didn't I get the early bird rate'"
    )


@pytest.mark.guarantee("F22")
def test_a_rule_at_ANOTHER_stage_that_does_not_cover_the_stay_IS_SILENT():
    """The half the framework contract denied. `space_surcharge` on a vip-only
    class must not appear on a standard receipt."""
    codes = _codes(copy.deepcopy(DOWNTOWN_V2))
    assert not any(c.startswith("space_surcharge") for c in codes), (
        f"a surcharge that was never about this space appeared on the receipt: {codes}"
    )


@pytest.mark.guarantee("F22")
def test_and_it_DOES_speak_when_it_applies():
    """The control on the item above: silence must be about non-coverage, not a
    rule that has stopped working."""
    codes = _codes(copy.deepcopy(DOWNTOWN_V2), space_class="vip")
    assert "space_surcharge.applied" in codes


@pytest.mark.guarantee("F22")
def test_the_silence_rule_holds_at_EVERY_non_qualify_stage_that_ships():
    """Derived from the registry, not from a list of the stages that exist today.

    A rule type registered at a new non-QUALIFY stage is covered the day it is
    added; a written list could not notice it. The specification's enumeration rule.
    """
    from rate_engine.rules import RULE_TYPES

    document = copy.deepcopy(DOWNTOWN_V2)
    # Restrict every non-QUALIFY rule to 'vip', then price a 'standard' stay: no
    # rule outside QUALIFY covers it, so none of them may appear.
    non_qualify_ids = set()
    for rule in document["rules"]:
        # The rule's OWN stage, not the type's. A type may now run at more than
        # one stage -- `time_window` is a base at QUALIFY and an adjustment at
        # ADJUST -- so the registry answers "where may this type run" and the
        # rule answers "where does this one run". The loader makes the document's
        # claim and the code's derivation agree, so reading it here is still a
        # derivation rather than a list somebody types.
        stages, _builder = RULE_TYPES[rule["type"]]
        assert rule["stage"] in stages, f"{rule['id']} states a stage its type cannot run at"
        if rule["stage"] != QUALIFY:
            rule["space_classes"] = ["vip"]
            non_qualify_ids.add(rule["type"])
    assert non_qualify_ids, "no non-QUALIFY rule type ships, so this proves nothing"

    status, body = run_quote(
        {
            "plans": [document], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T10:40:00-05:00", "space_class": "standard",
            "currency": "USD",
        }
    )
    # Nothing prices the time for 'standard' now, so this is a refusal -- and a
    # refusal carries findings, not lines. That is itself the point: the engine
    # says what is missing rather than emitting explanatory zero lines for rules
    # that were never about this stay.
    assert status == 422
    assert body["findings"][0]["code"] == "GAP_NO_ACCUMULATE_RULE"


#: A plan whose ONLY adjustment applies at the weekend, priced on a Tuesday. The
#: window covers the space and declines for a reason that has nothing to do with
#: the space -- which is the case the stage-keyed silence rule got wrong.
WEEKEND_DISCOUNT = {
    "plan_version": "speaks-2026-03",
    "effective_from": "2026-01-01T00:00:00-05:00",
    "timezone": "America/New_York", "currency": "USD",
    "space_classes": ["standard", "vip"],
    "resolution": {
        "QUALIFY": {"mode": "cheapest_wins"}, "ACCUMULATE": {"mode": "cheapest_wins"},
    },
    "adjust_order": None,
    "rules": [
        {"id": "hourly", "type": "increment", "stage": "ACCUMULATE",
         "space_classes": ["standard", "vip"], "first_period_minutes": 60,
         "first_period_minor": 800, "repeat_period_minutes": 60,
         "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None},
        {"id": "weekend-off", "type": "time_window", "stage": "ADJUST",
         "space_classes": ["standard"], "label": "Weekend discount",
         "applies_on": {"kind": "days_of_week", "days": ["sat", "sun"]},
         "enter_from": "00:00", "enter_by": "23:59", "exit_by": "23:59",
         "day_span": "any_span",
         "effect": {"kind": "adjust", "direction": "discount",
                    "amount": {"kind": "percent", "percent_bp": 2000},
                    "rounding": "down"}},
    ],
    "decisions": [],
}

#: The same document stating `up`. A counterpart in the corpus, not a rewrite
#: inside one test: every percentage adjustment here used to state `down`, so a
#: comparison run over the stated documents never reached the applier's `up`
#: branch at all.
WEEKEND_DISCOUNT_UP = copy.deepcopy(WEEKEND_DISCOUNT)
WEEKEND_DISCOUNT_UP["rules"][1]["effect"]["rounding"] = "up"


def _lines(document: dict, space_class: str = "standard") -> list[dict]:
    status, body = run_quote(
        {
            "plans": [copy.deepcopy(document)], "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-03T10:40:00-05:00", "space_class": space_class,
            "currency": "USD",
        }
    )
    assert status == 200, body
    return body["breakdown"]


@pytest.mark.guarantee("F22b")
def test_a_rule_that_COULD_have_applied_and_did_not_SPEAKS_at_any_stage():
    """The hole the stage-keyed rule left, and the question it could not answer.

    A weekend discount on a Tuesday is not "a tier that was never about your
    space" -- it is a rate the customer nearly got, declining for a reason they
    can act on next time. It runs at ADJUST, which the old rule called silent.
    """
    lines = _lines(WEEKEND_DISCOUNT)
    declined = [ln for ln in lines if ln["code"] == "time_window.not_applied"]
    assert declined, (
        "the weekend discount declined and said nothing, so the breakdown cannot "
        "answer 'why didn't I get the weekend discount?'"
    )
    assert declined[0]["delta_minor"] == 0, "a rule that did not apply moved the fee"
    assert "Tuesday is not one of sat, sun" in declined[0]["text"]


@pytest.mark.guarantee("F22b")
def test_and_it_says_the_RIGHT_CONSEQUENCE_for_an_adjustment():
    """An adjustment that did not apply does not change the basis of the stay.
    Saying "the stay prices on the time-based rate" -- true of a base -- would
    tell a customer their whole rate had changed, which is not what happened."""
    declined = [ln for ln in _lines(WEEKEND_DISCOUNT)
                if ln["code"] == "time_window.not_applied"][0]
    assert "so the fee is not adjusted" in declined["text"], declined["text"]


@pytest.mark.guarantee("F22b")
def test_but_COVERAGE_still_governs_and_a_rule_about_another_space_is_SILENT():
    """The half that was always right, and the control on the widening: a type
    that declares it speaks must not start speaking about stays it was never
    about."""
    lines = _lines(WEEKEND_DISCOUNT, space_class="vip")
    assert not [ln for ln in lines if ln["code"].startswith("time_window.")], (
        "a discount scoped to standard spaces appeared on a VIP receipt"
    )


@pytest.mark.guarantee("F22b")
def test_the_declaration_is_the_TYPES_and_a_type_that_declares_nothing_is_SILENT():
    """The structural half: this is a property of the registry, not of a stage.

    `space_surcharge` declares nothing and must stay silent -- which is what the
    stage-keyed rule got right and this widening must not undo.
    """
    from rate_engine.rules import RULE_TRAITS, SPEAKS_UNQUALIFIED

    assert SPEAKS_UNQUALIFIED in RULE_TRAITS["time_window"]
    assert SPEAKS_UNQUALIFIED not in RULE_TRAITS["space_surcharge"]


def test_the_framework_contract_no_longer_states_the_blanket_claim():
    """The control on the DOCUMENTATION half.

    Keyed on the claim rather than on a phrase somebody might reword: the module
    must not say a non-qualifying rule always returns a line without also saying
    the rule is per stage.
    """
    import rate_engine.rules as framework

    text = " ".join((framework.__doc__ or "").split())
    assert "depends on its stage" in text.lower(), (
        "the rule framework no longer says the silence rule is per stage"
    )
    assert "A rule that did NOT qualify still returns a line, with delta zero, saying" \
        not in text, "the blanket claim has come back"
    assert "speaks_unqualified" in text.lower(), (
        "the framework no longer documents that a TYPE can declare it speaks -- the "
        "stage stopped being the whole answer and the contract has to say so"
    )


@pytest.mark.guarantee("F31")
def test_the_UP_counterpart_on_a_SATURDAY_takes_the_same_whole_amount():
    """The weekend window APPLYING, under both roundings: 86 minutes is 8.00 +
    4.00, and 20% of 12.00 is exactly 2.40 -- no fraction, so `up` adds nothing.
    On the Tuesday every test above uses, the window declines under either."""
    fees = {}
    for name, document in (("down", WEEKEND_DISCOUNT), ("up", WEEKEND_DISCOUNT_UP)):
        status, body = run_quote(
            {
                "plans": [copy.deepcopy(document)],
                "entry_at": "2026-03-07T09:14:00-05:00",
                "exit_at": "2026-03-07T10:40:00-05:00",
                "space_class": "standard", "currency": "USD",
            }
        )
        assert status == 200, body
        applied = [ln for ln in body["breakdown"] if ln["code"] == "time_window.applied"]
        assert applied and applied[0]["delta_minor"] == -240, body["breakdown"]
        fees[name] = body["fee_minor"]
    assert fees == {"down": 960, "up": 960}, fees
