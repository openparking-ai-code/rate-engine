"""F23 -- the invariant in the production path has a test that dies with it.

**Measured in the outside review: deleting `engine._assert_ledger_is_the_fee`
outright left all 97 tests green.** The invariant sits in the production path on
purpose -- engine.py says so in as many words, "an invariant that only tests check
is an invariant that holds only where tests look" -- and nothing whatsoever
guarded it. It could have been deleted, no-op'd, or lost in a refactor, in
silence.

F8's own control on that property was
`assert ledger.total_minor != 501` against a hand-built `Ledger`: it never invokes
the invariant, so it passes with the invariant gone. The F8 GUARANTEE was still
covered -- `test_every_priced_fixture_equals_the_sum_of_its_lines` catches a
second route to the total on its own -- but the guard was checking a COPY of the
property rather than the property.

**This is the second time this project has shipped exactly that shape.** The first
was the specification's own entry: a document-versus-renderer check where both sides carried the
same claim and agreed happily. Same lesson, second occurrence: derive the
expectation from the MEASUREMENT, never from a second statement of the assertion.

So these tests call the function. Delete it, no-op it, or make it stop raising,
and this file goes red.
"""

from __future__ import annotations

import pytest

from fixtures import CORPUS, loaded
from rate_engine.breakdown import Ledger, Line
from rate_engine.engine import _assert_ledger_is_the_fee, quote


def _ledger(*deltas: int) -> Ledger:
    ledger = Ledger()
    for n, delta in enumerate(deltas):
        ledger.add(Line(code=f"l{n}", rule_id=None, text="t", delta_minor=delta))
    return ledger


@pytest.mark.guarantee("F23")
def test_the_invariant_RAISES_when_the_fee_is_not_the_sum():
    """The property itself, exercised through the function that enforces it.

    Not a restatement of the arithmetic -- the arithmetic is checked elsewhere.
    This asserts that the GUARD reacts, which is what nothing did before.
    """
    ledger = _ledger(800, -300)
    with pytest.raises(AssertionError) as caught:
        _assert_ledger_is_the_fee(501, ledger)
    assert "not the sum of the breakdown" in str(caught.value)


@pytest.mark.guarantee("F23")
@pytest.mark.parametrize("wrong", [499, 501, 0, -500, 1_000_000])
def test_it_raises_for_every_wrong_total_not_merely_one(wrong):
    with pytest.raises(AssertionError):
        _assert_ledger_is_the_fee(wrong, _ledger(800, -300))


@pytest.mark.guarantee("F23")
def test_and_it_ACCEPTS_the_right_total():
    """The control. A guard that raises on everything is not a guard either --
    it would make the whole engine refuse and this file would still be green."""
    _assert_ledger_is_the_fee(500, _ledger(800, -300))
    _assert_ledger_is_the_fee(0, _ledger())


@pytest.mark.guarantee("F23")
def test_it_also_refuses_a_line_carrying_non_integer_money():
    """The invariant's second clause, which had no test at all.

    `Line` refuses non-integer money at construction, so this reaches the clause
    by bypassing that -- the clause exists precisely for the case where something
    got past the front door.
    """
    ledger = Ledger()
    ledger.add(Line(code="a", rule_id=None, text="t", delta_minor=500))
    object.__setattr__(ledger.lines[0], "delta_minor", True)
    # The fee must MATCH the sum, or the first clause fires and this would pass
    # for the wrong reason: `sum([True])` is 1, so 1 is the total that gets past
    # the sum check and reaches the type check this test is about.
    with pytest.raises(AssertionError) as caught:
        _assert_ledger_is_the_fee(1, ledger)
    assert "non-integer money" in str(caught.value), (
        f"it raised, but for the sum rather than the type: {caught.value}"
    )


@pytest.mark.guarantee("F23")
def test_the_invariant_IS_ON_THE_PRODUCTION_PATH_not_only_in_tests():
    """Calling the function proves it works; this proves `quote()` runs it.

    A version that was correct but no longer wired would pass every test above.
    Established by counting calls through the real pricing path rather than by
    reading the source.
    """
    import rate_engine.engine as engine

    calls: list[tuple[int, int]] = []
    original = engine._assert_ledger_is_the_fee

    def counting(fee, ledger):
        calls.append((fee, len(ledger.lines)))
        return original(fee, ledger)

    engine._assert_ledger_is_the_fee = counting
    try:
        result = quote([loaded()], CORPUS["worked_example"])
    finally:
        engine._assert_ledger_is_the_fee = original

    assert len(calls) == 1, f"quote() called the invariant {len(calls)} times, not once"
    assert calls[0][0] == result.fee_minor
    assert calls[0][1] == len(result.breakdown.lines)
