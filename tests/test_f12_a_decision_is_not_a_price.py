"""F12 / F12b -- an owner's decision is an ACKNOWLEDGEMENT, and never a price.

`validate-plan` hands an owner a list of gaps and conflicts to work through, and
`decisions[]` is where they record having worked through one. Two separate
promises live on that, and they pull in opposite directions, which is why they
are two guarantees with two controls rather than one:

* **F12 -- the list separates.** An owner clearing a list needs to know what is
  left. A surface that reports the same undifferentiated list before and after a
  decision was recorded makes `decisions[]` write-only, which is what it was:
  `undecided()` existed, was correct, and was called by nothing.

* **F12b -- and separating changes NO answer.** A decision carries a `code` and a
  free-text `note`, and **a note cannot price a stay.** If recording one could
  make the engine start answering, the module would be inventing money from prose
  -- the exact failure it exists to prevent. So a stay hitting a SETTLED gap is
  refused exactly as one hitting an outstanding gap is. The way to make a gap
  price is to add a RULE: a visible plan change, which is how the specification says an owner
  resolves a gap.

F12 without F12b is the dangerous half. A split that an implementer later "made
consistent" by letting settled mean priced would satisfy every reading of F12
alone, so the control for F12b plants precisely that and requires red.
"""

from __future__ import annotations

import copy
import json

import pytest

from fixtures import PLANS_DIR, stay
from rate_engine.contract import run_quote, run_validate
from rate_engine.engine import quote
from rate_engine.findings import GAP_NO_ACCUMULATE_RULE, GAP_STAY_EXCEEDS_MAX_DURATION, Refused
from rate_engine.plan import load_plan
from rate_engine.validator import undecided, validate_plan

#: Two findings, deliberately: one gets decided and one does not, so the split
#: has a case on BOTH sides. A fixture where every finding falls on one side
#: would let a surface that hard-codes either heading pass.
LOT_C = json.loads((PLANS_DIR / "lot_c_with_gaps.json").read_text())

#: A stay in a 'reserved' space. Nothing accumulates time for that class, so it
#: is the stay that meets GAP_NO_ACCUMULATE_RULE -- the finding decided below.
RESERVED_STAY = stay("2026-03-03T09:00:00-05:00", 65, "reserved")


def _with_decision(code: str) -> dict:
    document = copy.deepcopy(LOT_C)
    document["decisions"] = [
        {
            "code": code,
            "decided_by": "owner@example.com",
            "decided_at": "2026-03-01T12:00:00-05:00",
            "note": "we know; the attendant handles these at the booth",
        }
    ]
    return document


def test_the_fixture_really_does_carry_one_of_each():
    """The positive control on the fixture, before anything is asserted about it.

    A plan whose findings were all on one side would make both assertions below
    pass against a surface that never separates anything.
    """
    plan = load_plan(LOT_C)
    codes = {f.code for f in validate_plan(plan)}
    assert codes == {GAP_NO_ACCUMULATE_RULE, GAP_STAY_EXCEEDS_MAX_DURATION}, (
        f"the split fixture no longer carries two findings ({sorted(codes)}); with "
        "fewer than two, one of the headings below is never exercised"
    )
    decided = load_plan(_with_decision(GAP_NO_ACCUMULATE_RULE))
    assert {f.code for f in undecided(decided)} == {GAP_STAY_EXCEEDS_MAX_DURATION}


@pytest.mark.guarantee("F12")
def test_a_decided_finding_reports_as_SETTLED_and_an_undecided_one_as_OUTSTANDING():
    """The split, on the published surface rather than on the helper.

    `undecided()` was already correct in isolation. What was missing is that
    nothing called it, so no owner could see its answer -- which is why this
    asserts on `run_validate`'s body and not on the function.
    """
    status, body = run_validate({"plan": _with_decision(GAP_NO_ACCUMULATE_RULE)})
    assert status == 200

    by_code = {f["code"]: f for f in body["findings"]}
    assert by_code[GAP_NO_ACCUMULATE_RULE]["decided"] is True, (
        "a finding the owner recorded a decision for is still reported as "
        "outstanding, so working through the list changes nothing an owner can see"
    )
    assert by_code[GAP_STAY_EXCEEDS_MAX_DURATION]["decided"] is False, (
        "a finding nobody decided is reported as settled, which would tell an owner "
        "they had cleared something they never looked at"
    )
    assert (body["outstanding"], body["settled"]) == (1, 1)

    # Every finding is still REPORTED. Settled is a heading, not a filter: a
    # surface that dropped decided findings would hide the ones a stay still
    # refuses on.
    assert body["gaps"] + body["conflicts"] == len(body["findings"]) == 2


@pytest.mark.guarantee("F12")
def test_deciding_nothing_leaves_everything_outstanding():
    """The other side of the same axis, so the split is measured and not assumed."""
    status, body = run_validate({"plan": LOT_C})
    assert status == 200
    assert (body["outstanding"], body["settled"]) == (2, 0)
    assert all(f["decided"] is False for f in body["findings"])


@pytest.mark.guarantee("F12b")
def test_a_stay_hitting_a_DECIDED_gap_is_still_refused():
    """THE SAFETY LINE. A note is prose; prose does not price a stay.

    The decision below acknowledges GAP_NO_ACCUMULATE_RULE in as many words. The
    stay still comes back as a refusal naming that same code -- not as a number,
    and not as a smaller number.
    """
    plan = load_plan(_with_decision(GAP_NO_ACCUMULATE_RULE))

    with pytest.raises(Refused) as caught:
        quote([plan], RESERVED_STAY)
    assert [f.code for f in caught.value.findings] == [GAP_NO_ACCUMULATE_RULE], (
        "a stay hitting a gap the owner had DECIDED came back priced. An entry in "
        "decisions[] carries a code and a free-text note; a note cannot price a "
        "stay, and a module that let one is inventing money from prose"
    )

    # The undecided plan refuses identically. Without this the assertion above
    # would pass against an engine that refuses everything for some other reason.
    with pytest.raises(Refused) as undecided_case:
        quote([load_plan(LOT_C)], RESERVED_STAY)
    assert [f.code for f in undecided_case.value.findings] == [
        f.code for f in caught.value.findings
    ], "deciding a finding changed WHICH codes the engine refused on"


@pytest.mark.guarantee("F12b")
def test_the_refusal_reaches_the_published_surface_unchanged_by_a_decision():
    """Byte-for-byte, because F6 says the surfaces cannot differ from the path.

    A decision that altered the refusal BODY -- a softer message, a partial fee,
    a 200 -- would be the same defect arriving through the serializer instead of
    through the engine.
    """
    request = {
        "entry_at": RESERVED_STAY.entry_at.isoformat(),
        "exit_at": RESERVED_STAY.exit_at.isoformat(),
        "space_class": "reserved",
        "currency": "USD",
    }
    undecided_status, undecided_body = run_quote({**request, "plans": [LOT_C]})
    decided_status, decided_body = run_quote(
        {**request, "plans": [_with_decision(GAP_NO_ACCUMULATE_RULE)]}
    )

    assert undecided_status == decided_status == 422
    assert decided_body["refused"] is True
    assert "fee_minor" not in decided_body
    assert json.dumps(decided_body, sort_keys=True) == json.dumps(
        undecided_body, sort_keys=True
    ), "recording a decision changed the refusal an operator is shown"
