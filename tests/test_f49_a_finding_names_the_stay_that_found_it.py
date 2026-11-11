"""F49 -- every `validate-plan` finding names the stay that found it.

An owner whose new rates are refused reads one sentence per finding. "Nothing
prices a stay of 1441 minutes" is true and is not enough: which car? The
validator found it by pricing a probe stay -- a car that came in at a moment
the plan's own boundaries make interesting -- and that stay is the answer. So
each finding carries `probe`, the entry and exit of the FIRST probe that
produced it, and the admin says the day and the time in the garage's words.

Set by the validator only. A refusal at quote time is about the stay the caller
sent, and its bytes are unchanged: no `probe` key at all.
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from fixtures import DOWNTOWN_V2
from rate_engine.contract import run_quote, run_validate
from rate_engine.engine import find_gaps
from rate_engine.plan import load_plan


@pytest.mark.guarantee("F49")
def test_every_finding_carries_the_stay_that_found_it_and_that_stay_finds_it():
    status, body = run_validate({"plan": copy.deepcopy(DOWNTOWN_V2)})
    assert status == 200
    assert body["findings"], "the premise: the reference plan has a finding"
    plan = load_plan(copy.deepcopy(DOWNTOWN_V2))
    for finding in body["findings"]:
        probe = finding["probe"]
        entry = datetime.fromisoformat(probe["entry_at"])
        exit_ = datetime.fromisoformat(probe["exit_at"])
        assert entry.tzinfo is not None and exit_ >= entry
        # The stay named is one that really produces this finding.
        from rate_engine.engine import make_stay

        stay = make_stay(entry, exit_, "standard")
        codes = {f.code for f in find_gaps(plan, stay)}
        assert finding["code"] in codes, (finding, codes)


@pytest.mark.guarantee("F49")
def test_the_probe_is_the_FIRST_stay_in_probe_order_so_it_does_not_move():
    _s, first = run_validate({"plan": copy.deepcopy(DOWNTOWN_V2)})
    _s, again = run_validate({"plan": copy.deepcopy(DOWNTOWN_V2)})
    assert [f["probe"] for f in first["findings"]] == [f["probe"] for f in again["findings"]]
    # The 24-hour ceiling: the shortest stay past it, 1441 minutes.
    gap = next(f for f in first["findings"] if f["code"] == "GAP_STAY_EXCEEDS_MAX_DURATION")
    probe = gap["probe"]
    span = datetime.fromisoformat(probe["exit_at"]) - datetime.fromisoformat(probe["entry_at"])
    assert span.total_seconds() == 1441 * 60, span


@pytest.mark.guarantee("F49")
def test_a_refusal_at_quote_time_carries_no_probe_key_its_bytes_are_unchanged():
    status, body = run_quote(
        {
            "plans": [copy.deepcopy(DOWNTOWN_V2)],
            "entry_at": "2026-03-03T09:14:00-05:00",
            "exit_at": "2026-03-04T09:15:00-05:00",
            "space_class": "standard",
            "currency": "USD",
        }
    )
    assert status == 422
    assert all("probe" not in f for f in body["findings"]), body["findings"]
    assert set(body["findings"][0]) == {"code", "kind", "text", "rule_ids"}
