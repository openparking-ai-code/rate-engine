"""The breakdown, and the reason the fee cannot disagree with it.

The first requirement of this module is clarity: an operator gets the number AND
the plain-English reason for every part of it, including the specials that did
NOT apply and why. So the breakdown is not a report written alongside the
calculation -- it IS the calculation.

**A LEDGER, NOT A SUM.** The brief said "the fee is the sum of the lines" and its
own worked example did not sum:

    ... total 4400 · Daily max 3000 applied · Fee 3000

4400 + 3000 is not 3000. A CAP is not additive: it replaces. Stating the rule as
a plain sum forces every capping rule to either lie in its line or live outside
the ledger, and the second of those is the two-code-paths defect the rule existed
to prevent. So each line carries a SIGNED DELTA and the fee is the running total.
The same example, priced honestly:

    Time-based: first hour 800                              +800
    Time-based: 9 additional hours at 400                  +3600
    Daily max 3000 applied                                 -1400
                                                    fee =  3000

Every line's text describes its own delta, the deltas add to the fee by
construction, and a cap that reduces a total says by how much -- which is the
number an operator actually wants to see and the plain sum would have hidden.

**There is exactly one way for a rule to change the fee: return a Line.** No rule
receives the running total to mutate, and the engine has no adjustment channel of
its own. That is what makes F8 a structural property rather than a comparison
between two copies of the same claim -- see ``engine.quote``, which asserts the
invariant on every quote, and ``tests/test_f8_breakdown_adds_up.py``, which
plants a second path and requires red.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .money import as_minor


@dataclass(frozen=True)
class Line:
    """One line of the breakdown, and the only way a fee ever changes.

    ``delta_minor`` may be negative (a cap giving money back) or zero (a special
    that did not apply, which is a line precisely BECAUSE it did not -- an
    operator asking "why didn't early bird apply?" is the question this module
    exists to answer).
    """

    #: Stable, machine-readable. The text is for a human and may be reworded; a
    #: consumer keying off a line keys off this.
    code: str
    #: The id of the rule that produced it, or None for an engine line.
    rule_id: str | None
    #: Plain English, and it must describe THIS line's own delta.
    text: str
    delta_minor: int
    #: Only on the line that says which way a stay was priced (the special or
    #: the time-based rate): what the OTHER way would have charged. Never part
    #: of the fee, and written to JSON only on the lines that carry it.
    compared_minor: int | None = None

    def __post_init__(self) -> None:
        as_minor(self.delta_minor, f"line[{self.code}].delta_minor")
        if self.compared_minor is not None:
            as_minor(self.compared_minor, f"line[{self.code}].compared_minor")


@dataclass
class Ledger:
    """An ordered list of lines whose running total is the fee.

    Deliberately has no ``set_total``, no ``adjust`` and no way to reach the
    total except by adding a line. A rule holding this object can do exactly one
    thing to the answer.
    """

    lines: list[Line] = field(default_factory=list)

    def add(self, line: Line) -> None:
        self.lines.append(line)

    @property
    def total_minor(self) -> int:
        return sum(line.delta_minor for line in self.lines)

    def to_json(self) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for line in self.lines:
            entry: dict[str, object] = {
                "code": line.code,
                "rule_id": line.rule_id,
                "text": line.text,
                "delta_minor": line.delta_minor,
            }
            if line.compared_minor is not None:
                entry["compared_minor"] = line.compared_minor
            out.append(entry)
        return out
