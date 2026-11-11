"""F41 -- a tax rounds the way its rule says, all three ways, and there is no default.

A tax is a percentage of money, and a percentage lands on a fraction of a minor
unit. Which way that fraction goes is stated per rule -- `up`, `down` or
`nearest` -- and a rule that does not say is refused rather than defaulted.

**The fixtures are chosen so every mode is DISTINGUISHABLE.** A base where two
modes agree cannot tell them apart: at 1005 and 850 bp the exact value is 85.425,
where `down` and `nearest` are both 85, so a `nearest` that was secretly `down`
would pass there. The second base separates them, and the third sits on EXACTLY
half, which is the only case that tells `>=` from `>` in the integer test
`nearest` is decided by.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rate_engine.plan import InvalidPlan
from rate_engine.tax import TAX_ROUNDINGS, load_tax_sets, tax_lines

AT = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)

#: base, basis points, exact value, then down / up / nearest -- hand-computed.
CASES = [
    (1005, 850, "85.425", 85, 86, 85),
    (1011, 850, "85.935", 85, 86, 86),
    (100, 850, "8.5", 8, 9, 9),
]


def _rule(**overrides) -> dict:
    rule = {"id": "city", "label": "City parking tax", "percent_bp": 850,
            "rounding": "down", "sequence": 1}
    rule.update(overrides)
    return rule


def _sets(*rules: dict) -> list:
    return [{"effective_from": "2026-01-01T00:00:00-05:00", "rules": list(rules)}]


def _one(base: int, bp: int, rounding: str):
    sets = load_tax_sets(_sets(_rule(percent_bp=bp, rounding=rounding)))
    (line,) = tax_lines(sets, subtotal_minor=base, currency="USD", at=AT)
    return line


def test_the_fixtures_SEPARATE_the_modes():
    """The control on the fixtures, and it runs first.

    Across the three cases every pair of modes disagrees at least once, and the
    third case is an exact half. Without this, a table of agreeing numbers would
    pass against an applier that ignored the field.
    """
    for mode_a, mode_b in (("down", "up"), ("down", "nearest"), ("up", "nearest")):
        column = {"down": 3, "up": 4, "nearest": 5}
        assert any(case[column[mode_a]] != case[column[mode_b]] for case in CASES), (
            f"no case separates {mode_a} from {mode_b}"
        )
    assert any(base * bp % 10_000 == 5_000 for base, bp, *_ in CASES), "no exact half"
    assert set(TAX_ROUNDINGS) == {"up", "down", "nearest"}


@pytest.mark.guarantee("F41")
@pytest.mark.parametrize("base,bp,exact,down,up,nearest", CASES)
def test_every_mode_lands_on_its_own_hand_computed_figure(base, bp, exact, down, up, nearest):
    assert _one(base, bp, "down").delta_minor == down
    assert _one(base, bp, "up").delta_minor == up
    assert _one(base, bp, "nearest").delta_minor == nearest


@pytest.mark.guarantee("F41")
def test_EXACTLY_HALF_goes_up_under_nearest():
    """8.5 is 9. An applier deciding `nearest` with `>` instead of `>=` gives 8."""
    assert _one(100, 850, "nearest").delta_minor == 9


@pytest.mark.guarantee("F41")
def test_the_LINE_shows_the_exact_figure_and_which_way_it_went():
    """A driver disputing a cent is shown the answer rather than told it."""
    assert "is 0.85425 USD, rounded nearest (down)" in _one(1005, 850, "nearest").text
    assert "is 0.85935 USD, rounded nearest (up)" in _one(1011, 850, "nearest").text
    assert "is 0.85425 USD, rounded up" in _one(1005, 850, "up").text
    line = _one(1000, 850, "down")
    assert "rounded" not in line.text, "a whole result has nothing to round"
    assert "8.5% of 10.00 USD paid -- 0.85 USD added" in line.text


@pytest.mark.guarantee("F41")
def test_an_omitted_rounding_is_REFUSED_naming_the_field_not_defaulted():
    rule = _rule()
    del rule["rounding"]
    with pytest.raises(InvalidPlan) as caught:
        load_tax_sets(_sets(rule))
    assert caught.value.missing_keys == ("rounding",)


@pytest.mark.guarantee("F41")
def test_a_mode_that_does_not_exist_is_REFUSED_naming_the_three_that_do():
    with pytest.raises(InvalidPlan) as caught:
        load_tax_sets(_sets(_rule(rounding="ceil")))
    message = str(caught.value)
    assert "'ceil'" in message
    assert all(mode in message for mode in TAX_ROUNDINGS), message


@pytest.mark.guarantee("F41")
@pytest.mark.parametrize("value", [8.5, True])
def test_percent_bp_refuses_a_float_and_a_bool_by_name(value):
    with pytest.raises(Exception) as caught:
        load_tax_sets(_sets(_rule(percent_bp=value)))
    assert "tax_sets[0].rules[0].percent_bp" in str(caught.value), str(caught.value)


@pytest.mark.guarantee("F41")
@pytest.mark.parametrize("value", [0, -850])
def test_percent_bp_refuses_nothing_and_a_negative(value):
    with pytest.raises(InvalidPlan):
        load_tax_sets(_sets(_rule(percent_bp=value)))


def test_the_control_850_loads():
    """The control on the three refusals above: the field itself is fine."""
    (tax_set,) = load_tax_sets(_sets(_rule(percent_bp=850)))
    assert tax_set.rules[0].percent_bp == 850


def test_the_PLAN_adjustment_still_offers_exactly_two_modes():
    """`nearest` is the tax's, and only the tax's. Widening the adjustment's set
    would change what a plan may state, which nobody asked for."""
    from rate_engine.rules.time_window import ADJUST_ROUNDINGS

    assert ADJUST_ROUNDINGS == ("up", "down")
