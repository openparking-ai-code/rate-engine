"""The pipeline's stages, in order, and what each one is for.

Settled in the specification. Several rates can be live on one stay at
once, so this is not "pick one" -- a stay runs through every stage and each may
add lines to the ledger.

    QUALIFY    which base applies: increments, or a special that beats them
    ACCUMULATE the time-based charge itself
    CAP        daily and weekly maxima
    SURCHARGE  a space class costing more than the base (VIP, reserved)
    ADJUST     occupancy-driven multipliers

The order is load-bearing and is not a detail of this implementation: a cap that
ran before the surcharge would cap a number the customer is not being charged,
and a surcharge applied before the cap would be silently capped away.

Every stage now carries at least one rule type. ADJUST was empty in the first version and went
live in the second version with `time_window`'s `adjust` effect -- a percentage or an amount, up
or down, on the whole fee. It runs LAST, which is the same argument the order
above rests on: an adjustment applied before the cap and the surcharge would take
a percentage of a number the customer is not being charged.
"""

from __future__ import annotations

QUALIFY = "QUALIFY"
ACCUMULATE = "ACCUMULATE"
CAP = "CAP"
SURCHARGE = "SURCHARGE"
ADJUST = "ADJUST"

#: Iteration order IS the pipeline order. Nothing sorts this at runtime.
STAGES: tuple[str, ...] = (QUALIFY, ACCUMULATE, CAP, SURCHARGE, ADJUST)

# --- what happens when TWO rules qualify at one stage ----------------------
#
# **Not one answer, three, and treating it as one was a live defect.**
# `find_conflicts` refused whenever more than one rule qualified at ANY stage.
# That is right at QUALIFY, where two specials are competing bases and only one
# can be the price. It is wrong everywhere else -- and the moment `weekly_max`
# exists it is catastrophically wrong, because every plan carrying a daily AND a
# weekly cap would refuse every stay in the garage. Two caps are not a
# contradiction; they are two ceilings, and the lower one wins.

#: Two qualifying rules are a genuine either/or: only one of them can be the
#: base, and the PLAN says which. This is the stage set the resolution modes act
#: on, and the only one they can act on -- a mode stated for a stage that cannot
#: resolve is a decision that does nothing.
RESOLVING: frozenset[str] = frozenset({QUALIFY, ACCUMULATE})

#: All of them apply, and the order they are applied in cannot change the total.
#: Two caps in sequence leave the lower ceiling standing whichever runs first,
#: which falls out of what a cap IS rather than being arranged. The LINES differ
#: by order, so they are emitted in ascending rule id -- deterministic, and never
#: the caller's array position, which decided money in this module once already.
COMPOSING_ORDER_INDEPENDENT: frozenset[str] = frozenset({CAP, SURCHARGE})

#: All of them apply, and the order DOES change the total: 20% off then $5 off is
#: not $5 off then 20% off. So when more than one qualifies the plan must state
#: their order, and a plan that does not is refused naming them. The engine will
#: not pick, for the same reason it will not pick between two specials.
COMPOSING_ORDER_DEPENDENT: frozenset[str] = frozenset({ADJUST})

#: Every stage is in exactly one category. Asserted at import rather than left as
#: a comment: a stage added to STAGES and to none of the sets below would fall
#: through `find_conflicts` silently, which is how a stage stops being checked.
assert RESOLVING | COMPOSING_ORDER_INDEPENDENT | COMPOSING_ORDER_DEPENDENT == set(STAGES)
assert not (RESOLVING & COMPOSING_ORDER_INDEPENDENT)
assert not (RESOLVING & COMPOSING_ORDER_DEPENDENT)
assert not (COMPOSING_ORDER_INDEPENDENT & COMPOSING_ORDER_DEPENDENT)
