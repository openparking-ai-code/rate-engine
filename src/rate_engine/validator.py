"""`validate-plan`: every gap and every conflict, before a stay ever arrives.

Same mechanism as the engine's refusal -- literally the same two functions,
``engine.find_gaps`` and ``engine.find_conflicts`` -- run over a matrix of probe
stays instead of one real one. That is what makes the promise in R5 structural: a
gap the validator reports and a gap the engine refuses on are the same object
with the same identifier, because there is one implementation and the validator
is the thing calling it repeatedly.

**The probe matrix is DERIVED from the plan, not written down.** A fixed list of
scenarios can only find the gaps whoever wrote the list already thought of. So
the probes are built from the plan's own thresholds -- every rule's period
lengths, every stated ceiling, every window limit -- with a stay either side of
each. A plan whose ceiling is 24 hours gets probed at 24h and at 24h+1m whatever
those numbers are, because they are read out of the rules.

**THREE axes, and the third arrived with `time_window`.** The README says, in as
many words, that a rule type qualifying on something it does not declare as a
time or a duration "would need its own probe axis, and adding one is part of
adding the rule type". `time_window` qualifies on the DAY, so the day is an axis
now: every probe used to enter on one fixed Tuesday, and two weekend rules that
conflict with each other would have gone unreported exactly the way the two dawn
rules did before entry became an axis. That is the same defect in a new place,
and it is closed here rather than left for the next outside pass to find.

**FOUR axes, and the fourth arrived with `fill_level`.** A fill rule qualifies on
how full the garage was at entry, which is neither a day, a time nor a duration,
so -- as the README requires of a rule type that qualifies on something new -- it
brought its own axis in the same round: every declared threshold is probed one
basis point below, ON it, and at 100% full, across every other axis. A plan with
no fill rule is probed exactly as before, with no figure at all.

**"No figure" is not a probe, and that is a decision.** A stay with no occupancy
figure in a class a fill rule covers is refused (GAP_NO_OCCUPANCY_AT_ENTRY) --
but that is a fact about the CALLER, a garage that has not stated its number of
spaces, not about the plan. Probing it would report that gap for every plan that
carries a fill rule, and a plan store that refuses any plan with a finding would
then refuse every one of them. The refusal is held at quote time instead, by
`tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

from .engine import Stay, find_conflicts, find_gaps
from .findings import Finding
from .plan import Plan
from .rules import NEEDS_OCCUPANCY, RULE_TRAITS
from .rules.time_window import DAY_SPAN_LIMITS
from .stages import ACCUMULATE, STAGES
from .wallclock import DAYS_OF_WEEK

#: The reference entry the validator has always used: early enough that an
#: early-bird rule CAN qualify, so the QUALIFY branch is exercised even by a plan
#: that declares no entry limit at all. Kept as one mark among many rather than
#: as THE entry -- being the only one was the defect.
DEFAULT_PROBE_ENTRY_MINUTE = 7 * 60

#: The reference local DATE every probe used to enter on, and still the one a
#: plan that names no days is probed on. A Tuesday, so an ordinary weekday rule
#: qualifies against it.
REFERENCE_DATE = date(2026, 3, 3)


def _windowed_rules(plan: Plan) -> list:
    """Every rule that states a day or a time, at EVERY stage.

    **This read QUALIFY only until a later fix, and that hid the conflict that is left.**
    Two specials at QUALIFY are settled by the plan's mode now, tie included
    (F48), so the conflict a plan can still state is two DISCOUNTS at ADJUST with
    no order given -- and a discount window states its days and times exactly as
    a special does. Probing only QUALIFY's times meant two discounts colliding
    only before 05:30 were never probed there, and the validator reported the
    plan clean while the engine refused a real stay: the defect F19 exists for,
    one stage over. A rule that names no time contributes nothing below, so
    reading every stage costs nothing for the ones that do not.
    """
    return [rule for stage in STAGES for rule in plan.rules_for_stage(stage)]


def _entry_minutes_of_day(plan: Plan) -> set[int]:
    """Every ENTRY time this plan makes interesting, as minutes past local midnight.

    **This is the half that was missing, and it is what let a conflict through.**
    Every probe used to enter at 07:00 and vary only the duration, so two rules
    that both qualify only for an EARLY entry never overlapped in any probe: the
    validator reported a plan clean and the engine then refused a real stay for a
    conflict. A rule that names a time makes that time interesting, and the plan
    is where those times live.
    """
    marks = {DEFAULT_PROBE_ENTRY_MINUTE, 0}  # the original reference, and midnight
    for rule in _windowed_rules(plan):
        enter_by = rule.params.get("enter_by")
        if enter_by is not None:
            at = enter_by.hour * 60 + enter_by.minute
            # ON the limit and one minute INSIDE it: a rule qualifies at or before
            # `enter_by`, so both of those qualify and the pair is what makes two
            # rules overlap. One minute after is covered by the next rule's marks
            # and by the base entry.
            marks.update({at, at - 1})
        enter_from = rule.params.get("enter_from")
        if enter_from is not None:
            # The window's OTHER end, and it is a boundary the plan declares as
            # plainly as the first. ON the opening minute and one minute after:
            # both qualify, which is what lets two evening rules overlap. The
            # minute BEFORE is a non-qualifying probe and is covered by midnight.
            at = enter_from.hour * 60 + enter_from.minute
            marks.update({at, at + 1})
    return {m for m in marks if 0 <= m < 24 * 60}


def _entry_dates(plan: Plan) -> set[date]:
    """Every local DATE this plan makes interesting.

    A `time_window` qualifies on the day the car arrived, so a day a rule names
    is a day worth probing -- and a plan whose only rules apply at the weekend
    would otherwise be probed exclusively on a Tuesday, where none of them can
    qualify and none of them can therefore conflict with each other.

    Derived, like every other axis here: stated weekday names become the dates in
    the reference date's own week, and stated dates are used as they are written.
    """
    dates = {REFERENCE_DATE}
    week_starts = REFERENCE_DATE - timedelta(days=REFERENCE_DATE.weekday())
    for rule in _windowed_rules(plan):
        applies_on = rule.params.get("applies_on")
        if applies_on is None:
            continue
        if applies_on["kind"] == "days_of_week":
            dates.update(
                week_starts + timedelta(days=DAYS_OF_WEEK.index(name))
                for name in applies_on["days"]
            )
        else:
            dates.update(applies_on["dates"])
    return dates


def _duration_marks(plan: Plan, entry_minute: int) -> set[int]:
    """Every stay LENGTH that is interesting from this particular entry time.

    Computed per entry rather than once, because an exit limit is a wall-clock
    time: how long a stay has to be to land on 17:00 depends on when it started.
    The old code derived these against a single fixed entry, which is the same
    defect as the fixed entry itself, one level down.
    """
    marks: set[int] = {0, 1}
    for rule in plan.rules_for_stage(ACCUMULATE):
        for key in ("first_period_minutes", "repeat_period_minutes"):
            length = rule.params.get(key)
            if length:
                marks.update({length - 1, length, length + 1})
        ceiling = rule.params.get("max_duration_minutes")
        if ceiling:
            marks.update({ceiling - 1, ceiling, ceiling + 1})
        else:
            # Unbounded rules still need a long probe, or a cap's multi-day
            # branch is never entered by any stay the validator tries.
            marks.add(3 * 24 * 60)

    for rule in _windowed_rules(plan):
        exit_by = rule.params.get("exit_by")
        if exit_by is None:
            continue
        # Derived from the SAME corrected limit the rule now applies: `exit_by`
        # on the entry date plus the span. The old line read the limit as a bare
        # wall-clock time, so for an after-midnight `exit_by` -- 02:00 against a
        # 20:00 entry -- it computed a NEGATIVE length, `limit > 0` dropped it,
        # and the exit boundary of exactly those windows was never probed. That
        # is why a plan carrying the defect this round fixes validated clean.
        exit_minute = exit_by.hour * 60 + exit_by.minute
        day_span = rule.params.get("day_span")
        span_limit = DAY_SPAN_LIMITS[day_span] if day_span is not None else None
        if span_limit is None:
            limit = exit_minute - entry_minute
        else:
            limit = span_limit * 24 * 60 + exit_minute - entry_minute
        if limit > 0:
            marks.update({limit - 1, limit, limit + 1})

    # Always probe across a local midnight and across more than one day, because
    # a day-boundary branch that no probe reaches is a branch the validator
    # cannot report on.
    marks.update({17 * 60, 25 * 60, 49 * 60})
    return {m for m in marks if m >= 0}


def _occupancy_marks(plan: Plan) -> list[int | None]:
    """Every occupancy figure this plan makes interesting, in basis points.

    One basis point below each declared threshold, ON it, and 100% full: the
    first does not qualify, the other two do, and the last is where every fill
    rule on a class qualifies at once -- which is what lets two of them collide.
    A plan with no rule that reads the figure gets the one mark it always had:
    no figure. Sorted with `None` first so probe order is deterministic.
    """
    from .engine import FULL_BP

    thresholds = [
        rule.params["threshold_bp"]
        for stage in STAGES
        for rule in plan.rules_for_stage(stage)
        if NEEDS_OCCUPANCY in RULE_TRAITS[rule.type]
    ]
    if not thresholds:
        return [None]
    marks = {FULL_BP}
    for threshold in thresholds:
        marks.update({threshold - 1, threshold})
    return sorted(m for m in marks if 0 <= m <= FULL_BP)


def probe_stays(plan: Plan) -> list[Stay]:
    """Stays either side of every boundary this plan DECLARES.

    Two axes, both read out of the rules: when the stay ENTERS and how long it
    lasts. Neither is a written list of scenarios -- a fixed list can only find
    the gaps whoever wrote it already thought of -- and neither is a search: the
    probes are the plan's own stated times, each side of each.

    THREE axes, all read out of the rules: which DAY the stay enters on, when it
    ENTERS on that day, and how long it LASTS. None is a written list of
    scenarios -- a fixed list can only find the gaps whoever wrote it already
    thought of -- and none is a search: the probes are the plan's own stated
    days and times, each side of each.

    **What this does NOT claim.** It is not exhaustive over all possible stays,
    and no bounded probe set could be. It is exhaustive over the boundaries the
    plan STATES, which is the class of conflict a rule can express: every
    qualification a rule makes turns on a day, a time or a duration it declares.
    `validate_plan`'s docstring and the README say exactly that and no more --
    see the limit recorded there.
    """
    stays: list[Stay] = []
    occupancy = _occupancy_marks(plan)
    for space_class in plan.space_classes:
        for day in sorted(_entry_dates(plan)):
            midnight = datetime(day.year, day.month, day.day, 0, 0, tzinfo=plan.timezone)
            for entry_minute in sorted(_entry_minutes_of_day(plan)):
                entry_at = midnight + timedelta(minutes=entry_minute)
                for minutes in sorted(_duration_marks(plan, entry_minute)):
                    for figure in occupancy:
                        stays.append(
                            Stay(
                                entry_at=entry_at,
                                exit_at=entry_at + timedelta(minutes=minutes),
                                space_class=space_class,
                                occupancy_at_entry_bp=figure,
                            )
                        )
    return stays


def validate_plan(plan: Plan) -> list[Finding]:
    """Every distinct gap and conflict, deduplicated by (code, rule_ids).

    Deduplicated by identifier rather than by sentence: the same gap found at
    three probe durations says a slightly different number each time, and an
    owner should be asked about it once. Each carries the stay that found it
    (`probe`): the first probe, in probe order, that produced it.
    """
    seen: dict[tuple[str, tuple[str, ...]], Finding] = {}
    for stay in probe_stays(plan):
        for finding in find_gaps(plan, stay) + find_conflicts(plan, stay):
            # The FIRST probe that found it, in probe order: deterministic, and
            # the stay an owner can be told about -- when it came in and left.
            found_by = (stay.entry_at.isoformat(), stay.exit_at.isoformat())
            if stay.occupancy_at_entry_bp is not None:
                found_by += (stay.occupancy_at_entry_bp,)
            seen.setdefault((finding.code, finding.rule_ids), replace(finding, probe=found_by))
    return [seen[key] for key in sorted(seen)]


def undecided(plan: Plan) -> list[Finding]:
    """The findings the owner has not recorded a decision for.

    A decision is matched on the finding's CODE, which is why the codes live in
    one registry. Substring-matching a decision against a sentence would let a
    reworded message quietly un-decide a gap an owner had already settled.
    """
    decided = {d["code"] for d in plan.decisions}
    return [f for f in validate_plan(plan) if f.code not in decided]
