"""F24 -- a zero-length stay pays the first period, and that is published.

An outside review called this a defect: a fee is returned for a stay of zero
duration, and the breakdown line names a first period that never occurred. The
outside review settled it as TRUE -- DECISION: it was decided on 2026-09-07 and
disclosed with the first version, naming the divergence from the platform's older fee
code, which returns zero for the same stay.

But the outside review also found the decision had reached **no receipt and no published
surface** -- nothing in the contract, the README or any docstring told an
integrator that entry == exit is billed a full first period. A decision an
integrator cannot discover is indistinguishable from an accident, and the next
person to notice it files it as a bug, exactly as an outside reviewer just did.

**This file changes no behaviour.** It pins the decision so it cannot drift
silently, and its last test holds the published sentence to the code.
"""

from __future__ import annotations

import copy
import pathlib

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote


def _quote(entry: str, exit_: str):
    return run_quote(
        {
            "plans": [copy.deepcopy(DOWNTOWN_V2)], "entry_at": entry, "exit_at": exit_,
            "space_class": "standard", "currency": "USD",
        }
    )


@pytest.mark.guarantee("F24")
def test_entry_equals_exit_is_PRICED_at_the_first_period():
    status, body = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:00-05:00")
    assert status == 200
    assert body["fee_minor"] == 800, "the decision is the first period, not zero"
    assert body["breakdown"][0]["text"].startswith("Entered 09:14 Tue 03 Mar, 0 minutes")


@pytest.mark.guarantee("F24")
def test_it_is_the_SAME_fee_as_a_one_minute_stay():
    """Which is the whole argument: the first period covers [0, first_len], so
    zero is not a special case in the rule -- it is the bottom of the range."""
    zero = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:14:00-05:00")[1]
    one = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:15:00-05:00")[1]
    fifty_nine = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T10:13:00-05:00")[1]
    assert zero["fee_minor"] == one["fee_minor"] == fifty_nine["fee_minor"] == 800


@pytest.mark.guarantee("F24")
def test_a_NEGATIVE_stay_is_a_different_case_and_is_REFUSED():
    """Pricing it at zero would hide a caller bug. This is not the zero-length
    decision and must not be folded into it.

    It comes back as a named 400, not an exception -- that is the boundary fix,
    and asserting `pytest.raises` here would re-assert the escape that fix removed.
    """
    status, body = _quote("2026-03-03T09:14:00-05:00", "2026-03-03T09:13:00-05:00")
    assert status == 400
    assert body["invalid"] is True
    assert "is before entry_at" in body["error"]


def test_the_DECISION_IS_PUBLISHED_where_an_integrator_reads():
    """The control on the documentation half, and the reason this round exists.

    The behaviour was decided and disclosed in a brief nobody outside this
    project can read. If the published paragraph is deleted or reworded away,
    this goes red -- keyed on the CLAIM, not on one phrasing.
    """
    contract = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "CONTRACT.md")
    text = " ".join(contract.read_text().split())
    assert "zero length pays the first period" in text.lower(), (
        "docs/CONTRACT.md no longer publishes the zero-length decision"
    )
    assert "diverges" in text.lower() and "returns zero" in text.lower(), (
        "the published decision no longer records the divergence it was disclosed with"
    )
