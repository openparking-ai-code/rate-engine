"""The pinned set of fail-control ids -- the check that sees a DELETED ARM.

`scripts/fail_controls.py` refuses to run while a registered guarantee has no
control at all. It could not see one arm of several being deleted: F31 has five,
and removing the one that catches a defect the other four cannot left every check
green. `scripts/fail_controls.ids` pins the whole set; `--pin` compares the two
by equality, and CI runs it in the controls job beside the anchor pre-flight.

This file measures the compare rather than trusting it: the real set matches the
pin, and one arm taken out -- or one added -- is named. It is F14's: the same
failure F14 guards -- the machinery that proves guarantees quietly measuring less
than it did -- one level down, at the arms rather than the guarantees.
"""

from __future__ import annotations

import sys

import pytest

from plant import ROOT

sys.path.insert(0, str(ROOT / "scripts"))

import fail_controls  # noqa: E402


@pytest.mark.guarantee("F14")
def test_the_control_set_is_the_pinned_set():
    assert fail_controls.pin_mismatch(
        set(fail_controls.CONTROLS), fail_controls.pinned_ids()
    ) == ([], [])


@pytest.mark.guarantee("F14")
def test_CONTROL_one_arm_of_a_multi_arm_guarantee_deleted_is_named():
    ids = set(fail_controls.CONTROLS)
    arms = {c for c in ids if fail_controls.guarantee_of(c) == "F31"}
    assert len(arms) > 1 and "F31/shared-was-rounded" in arms
    # The coverage check `main` already had is blind to this: F31 keeps an arm.
    fewer = ids - {"F31/shared-was-rounded"}
    assert "F31" in {fail_controls.guarantee_of(c) for c in fewer}
    assert fail_controls.pin_mismatch(fewer, fail_controls.pinned_ids()) == (
        ["F31/shared-was-rounded"], []
    )


@pytest.mark.guarantee("F14")
def test_CONTROL_an_unpinned_arm_is_named():
    ids = set(fail_controls.CONTROLS) | {"F31/not-pinned"}
    assert fail_controls.pin_mismatch(ids, fail_controls.pinned_ids()) == ([], ["F31/not-pinned"])
