#!/usr/bin/env python3
"""Every guarantee, proven able to FAIL.

A test that has never failed is a decoration. For each registered guarantee this
script breaks the thing the guarantee guards, runs that guarantee's tests in a
fresh interpreter, and requires them to go RED. If a test stays green with its
subject broken, it was not measuring its subject and this script says so.

    python scripts/fail_controls.py            # every control
    python scripts/fail_controls.py F3 F8      # a subset
    python scripts/fail_controls.py --anchors  # anchors only, in a second
    python scripts/fail_controls.py --pin      # the control ids against their pin

**The anchor pre-flight.** `--anchors` counts every plant's `from` string in its
file without running a single test. An anchor is a string in a source file, and
editing the line it sits on silently retires the control that depends on it --
five of another repo's ten dead controls were killed exactly that way, by a fix
round that edited the anchor lines. The pre-flight answers that whole failure
mode in a second where the full run takes a minute, and run against an older tree
it is its own positive control.

**Restores are written back, never `git checkout`.** Each plant is a context
manager whose `finally` writes the original bytes and verifies them. `checkout`
has been broken twice on this project and would take a co-resident session's
uncommitted work with it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from _guarantees import GUARANTEES  # noqa: E402
from plant import planted, resolve  # noqa: E402


def guarantee_of(control_id: str) -> str:
    """The guarantee a control id names. `F6b/imported-name-form` -> `F6b`.

    One guarantee can need more than one plant, and F6b's does. The one-encoder
    guard has to be shown catching BOTH the `json.dumps` attribute form and the
    `from json import dumps` form -- a single plant carrying both would go red if
    it caught EITHER, which is the arrangement that hid the second form in the
    first place. So a control id is a guarantee id, optionally with an arm after
    a slash, and every arm has to fire on its own.
    """
    return control_id.split("/", 1)[0]


#: control id -> (test target, source file, anchor, replacement, what breaks)
CONTROLS: dict[str, tuple[str, str, str, str, str]] = {
    "F1": (
        "tests/test_f1_never_guesses.py",
        "rules/increment.py",
        "    return ceiling is None or stay.duration_minutes <= ceiling",
        "    return True  # PLANTED: the rule's stated ceiling is ignored",
        "the stated maximum duration stops being checked, so a stay nothing prices "
        "comes back as a NUMBER instead of a refusal",
    ),
    # NARROWED, and the width was the point. This control plants on the WALL-CLOCK
    # LIMIT alone. Its first form after the exit test was factored out planted
    # `if False:` on the whole `_exit_failure` RESULT, which also disabled the
    # day-span check -- a strictly broader break than the sentence beside it
    # names. F2 is sensitive to the narrow defect on its own (measured: red for
    # the limit relaxed with the span check left live), so the broader plant was
    # buying an old control number with a bigger hammer. Pushing the limit's DATE
    # out of reach relaxes the limit and nothing else: the span check has already
    # run, with the real `span_limit`, before this line.
    "F2": (
        "tests/test_f2_all_conditions.py",
        "rules/time_window.py",
        '    limit_local = _exit_limit(entry_local, rule.params["exit_by"], span_limit)',
        '    limit_local = _exit_limit(  # PLANTED: the exit limit is out of reach\n'
        '        entry_local, rule.params["exit_by"], span_limit + 3650\n'
        "    )",
        "the window's exit condition is relaxed -- the wall-clock limit alone, with "
        "the day-span check left live -- so a stay that left after the limit is "
        "given the cheap rate anyway: partial credit, which the specification forbids",
    ),
    "F3": (
        "tests/test_f3_entry_time_governs.py",
        "engine.py",
        "    in_force = [p for p in plans if p.effective_from <= stay.entry_at]",
        "    in_force = [p for p in plans if p.effective_from <= stay.exit_at]  # PLANTED",
        "the plan version is selected on EXIT time, so a car that parked under one "
        "rate card is billed under a newer one",
    ),
    "F4": (
        "tests/test_f4_integer_minor_units.py",
        "money.py",
        "    if isinstance(node, float):\n        raise NotMinorUnits(",
        "    if False:  # PLANTED: the plan-wide float walk no longer refuses\n"
        "        raise NotMinorUnits(",
        "a float anywhere in a plan is accepted at load, including in a field this "
        "version does not yet read",
    ),
    # The tax fix round. The walk is shared, and a tax set was told it was a plan.
    "F4/tax-set-named": (
        "tests/test_f4_integer_minor_units.py",
        "tax.py",
        '    refuse_non_integer_money(document, where, document_name="tax set")',
        '    refuse_non_integer_money(document, where, document_name="plan")'
        "  # PLANTED: the tax loader calls its document a plan",
        "a float or a bool in a tax set is refused with a message saying it is "
        "in a PLAN, sending the operator to the wrong document",
    ),
    # P3. The plant removes the plan-wide walk entirely -- "remove the check and
    # require red". `as_minor` still guards the fields that ASK for money, so what
    # this exposes is precisely the gap the sentence was false about: the leaves
    # nothing else types. Re-anchored in the tax fix round, when the walk began
    # taking the name of the document it walks. The PLANTED DEFECT IS UNCHANGED.
    "F4b": (
        "tests/test_f4_integer_minor_units.py",
        "plan.py",
        '    refuse_non_integer_money(document, where, document_name="plan")',
        "    pass  # PLANTED: the plan-wide walk no longer runs",
        "a float, a bool or a Decimal in a plan field this version does not read is "
        "accepted at load, so the sentence published at four sites is false again",
    ),
    "F5": (
        "tests/test_f5_determinism.py",
        "rules/time_window.py",
        # Re-anchored when a fix moved the comparison onto wallclock.local_minute,
        # and again when `early_bird` became `time_window`. The PLANTED DEFECT IS
        # UNCHANGED -- the plan's zone is swapped for the server's -- because
        # re-pointing an anchor must not quietly weaken what the control proves.
        "    entry_local = local_minute(stay.entry_at, plan.timezone)\n"
        "    exit_local = local_minute(stay.exit_at, plan.timezone)",
        "    entry_local = local_minute(stay.entry_at, None)  # PLANTED: the SERVER's zone\n"
        "    exit_local = local_minute(stay.exit_at, None)  # PLANTED: the SERVER's zone",
        "the engine reads the SERVER's timezone instead of the plan's, so the same "
        "garage bills two different amounts depending on which machine answered",
    ),
    "F6": (
        "tests/test_f6_one_code_path.py",
        "service.py",
        "        status, body = runner(document)",
        "        status, body = runner(document)\n"
        "        body = dict(body, fee_minor=body.get('fee_minor'))  # PLANTED\n"
        "        body.pop('breakdown', None)  # PLANTED: the route drops the breakdown",
        "the HTTP route answers differently from the pricing path -- the exact shape "
        "of a test function that lies to an operator",
    ),
    # The FIRST plant written for F7 was a dead control and this script said so:
    # it re-sorted each stage's rules by type, which changes nothing when no plan
    # has two rules at one stage -- and none does, because the first version refuses that as a
    # conflict. A control whose fixture cannot reach it reports green from an
    # unmodified measurement. This one plants what F7 actually guards: the
    # REGISTRY leaking into a plan that never named the new type.
    # Re-anchored in F64, when a pass began to read the quote's own answer to
    # which rules qualify. The defect is unchanged: the registry leaks.
    "F7": (
        "tests/test_f7_new_rule_type.py",
        "engine.py",
        "    qualified_at_qualify = qualified.at(QUALIFY)",
        "    for _registered in sorted(RULE_APPLIERS):  # PLANTED: the registry leaks\n"
        "        ledger.add(\n"
        "            Line(code='registry.note', rule_id=None,\n"
        "                 text=f'rule type available: {_registered}', delta_minor=0)\n"
        "        )\n"
        "    qualified_at_qualify = qualified.at(QUALIFY)",
        "the engine mentions every REGISTERED rule type in the breakdown, so "
        "registering a new one rewrites the explanation an existing plan produces",
    ),
    "F10": (
        "tests/test_f10_unambiguous_plan_selection.py",
        "engine.py",
        "    if len(tied) > 1:",
        "    if False:  # PLANTED: an ambiguous selection is resolved by list order again",
        "two plan versions sharing an effective date stop being refused, so the fee "
        "goes back to depending on which one the caller put first in the array",
    ),
    # K3's half of F8, with its own plant: the amendment's "refused at
    # registration" reduced, on execution, to the one shape that was actually
    # broken -- a malformed return reaching Ledger.add and dying there.
    "F8b": (
        "tests/test_f8_breakdown_adds_up.py",
        "engine.py",
        "        if not isinstance(item, Line):",
        "        if False:  # PLANTED: a non-Line return is no longer refused",
        "a rule returning something that is not a Line stops being refused by "
        "name, and dies inside the ledger with a stack trace naming neither the "
        "rule nor its type",
    ),
    # P2's three. F9 and F13 guard files that carried NO mark at all until this
    # round; F14 guards the guard, and its plant is the first one in this project
    # that lands outside src/ -- `tests/conftest.py` IS the mechanism, and no
    # plant in the engine can reach it. See plant.ROOT_RELATIVE_PREFIXES.
    "F9": (
        "tests/test_contract_is_generated.py",
        "contract.py",
        "SCHEMA_VERSION = 6",
        "SCHEMA_VERSION = 7  # PLANTED: the published schema version moves",
        "the code answers with a schema version the committed contract does not "
        "publish, so docs/CONTRACT.md stops being a reading of the code",
    ),
    "F13": (
        "tests/test_fixture_axes.py",
        "rules/daily_max.py",
        "    if running_total_minor <= ceiling:",
        "    if True:  # PLANTED: the cap never applies to anything",
        "no fixture in the corpus can reach the daily max any more, so the capping "
        "branch every cap guarantee is proven against stops being exercised at all",
    ),
    "F14": (
        "tests/test_guarantee_guard.py",
        "tests/conftest.py",
        "    unaccounted = sorted(set(GUARANTEES) - _ran - allowed)",
        "    unaccounted = []  # PLANTED: nothing is ever unaccounted for",
        "the guard stops failing a run in which a registered guarantee never ran, "
        "which is the exact way another repo lost eight wiring guarantees while "
        "its build stayed green",
    ),
    # P4. "make apply() ignore the field and require red" -- the plant restores
    # exactly the shipped behaviour: the counter is chosen without ever looking
    # at what the plan asked for.
    "F15": (
        "tests/test_f15_rounding_is_consulted.py",
        "rules/increment.py",
        "    count_periods = PERIOD_COUNTERS.get(rounding)",
        "    count_periods = _ceil_periods  # PLANTED: the field is ignored again",
        "the applier stops reading `rounding` and always rounds up, so a plan "
        "stating a mode this version does not implement is priced as ceil instead "
        "of refused -- a wrong fee behind a plan that reads correctly",
    ),
    # P1's two arms. F12 is the split an owner reads; F12b is the line that stops
    # the split from turning into "settled means priced" the first time somebody
    # tidies it. The F12b plant is the whole defect in three lines -- a decision
    # suppressing a blocking finding -- and it is the reason the two are separate
    # ids: a single control could only ever plant one of them.
    "F12": (
        "tests/test_f12_a_decision_is_not_a_price.py",
        "contract.py",
        "    outstanding_codes = {f.code for f in undecided(plan)}",
        "    outstanding_codes = {f.code for f in validate_plan(plan)}  # PLANTED",
        "the split collapses -- every finding reports as outstanding whatever the "
        "owner recorded, so decisions[] is write-only again and `undecided()` is "
        "back to being called by nothing",
    ),
    # Re-anchored in F64 (the quote's `qualified` is handed to both); the defect
    # is unchanged.
    "F12b": (
        "tests/test_f12_a_decision_is_not_a_price.py",
        "engine.py",
        "    blocking = find_gaps(plan, stay, qualified) + find_conflicts(plan, stay, qualified)",
        "    _decided = {d['code'] for d in plan.decisions}  # PLANTED\n"
        "    blocking = [\n"
        "        f\n"
        "        for f in find_gaps(plan, stay, qualified)\n"
        "        + find_conflicts(plan, stay, qualified)\n"
        "        if f.code not in _decided\n"
        "    ]  # PLANTED: a free-text note now prices a stay",
        "an entry in decisions[] suppresses the finding it names, so a gap an owner "
        "merely ACKNOWLEDGED starts coming back as a number -- the module inventing "
        "money from prose, which is the failure it exists to prevent",
    ),
    # The plant restores the exact escape the outside review measured: NotMinorUnits is a
    # TypeError, so dropping it from the clause sends a plan float straight past
    # run_quote again and the HTTP route dies without answering.
    "F16": (
        "tests/test_f16_refusals_reach_the_caller.py",
        "contract.py",
        "        plans, stay = parse_quote_request(document)\n"
        "    except (InvalidPlan, NotMinorUnits, ValueError) as exc:",
        "        plans, stay = parse_quote_request(document)\n"
        "    except (InvalidPlan, ValueError) as exc:  # PLANTED: NotMinorUnits escapes again",
        "a plain JSON float in a plan escapes run_quote instead of becoming a named "
        "400, and the HTTP route drops the connection with no response at all",
    ),
    # Two arms, because the item was two defects sharing a cause: the
    # rendering assumed an exponent, and the loader assumed anything shaped like a
    # code was one. Breaking either must go red on its own.
    "F17": (
        "tests/test_f17_currency_is_rendered_by_its_exponent.py",
        "money.py",
        "    digits = minor_unit_digits(currency)",
        "    digits = 2  # PLANTED: every currency is assumed to have two decimals again",
        "a zero-decimal currency renders a hundred times too small -- 800 yen shown "
        "as 8.00 JPY -- while the numeric fee stays correct",
    ),
    "F17b": (
        "tests/test_f17_currency_is_rendered_by_its_exponent.py",
        "plan.py",
        "    if not is_known(currency):",
        "    if False:  # PLANTED: an unrenderable currency code loads again",
        "a code with no known exponent -- ZZZ, or XXX which means 'no currency' -- "
        "is accepted at load and reaches the renderer",
    ),
    # Two arms. The first restores the raw comparison the outside review measured; the
    # second restores the truncation-of-the-limit that the brief's first draft
    # called for and a later amendment reversed -- so the reversal itself has a control.
    # The anchor is the two-line PAIR rather than the entry line alone: `apply`
    # computes the same local minute for the applied line's wording, so the
    # single line now appears twice and a one-line anchor would be refused by
    # plant.py as ambiguous -- correctly. The planted defect is unchanged.
    "F18": (
        "tests/test_f18_wall_clock_is_minute_granular.py",
        "rules/time_window.py",
        "    entry_local = local_minute(stay.entry_at, plan.timezone)\n"
        "    exit_local = local_minute(stay.exit_at, plan.timezone)",
        "    entry_local = stay.entry_at.astimezone(plan.timezone)  # PLANTED: raw precision\n"
        "    exit_local = local_minute(stay.exit_at, plan.timezone)",
        "an entry one microsecond past the limit fails again, and the breakdown "
        "renders 'entry 09:00 is after the 09:00 entry limit'",
    ),
    "F18b": (
        "tests/test_f18_wall_clock_is_minute_granular.py",
        "wallclock.py",
        "    if parsed.second or parsed.microsecond:",
        "    if False:  # PLANTED: a sub-minute limit is silently accepted again",
        "a plan stating enter_by 09:00:30 loads, so a limit the breakdown cannot "
        "render decides the fee -- the engine keeping a decision it cannot explain",
    ),
    # The plant collapses the entry axis back to the single fixed reference,
    # which is exactly the shipped defect: probes vary duration only.
    "F19": (
        "tests/test_f19_validator_probes_declared_boundaries.py",
        "validator.py",
        "    marks = {DEFAULT_PROBE_ENTRY_MINUTE, 0}  # the original reference, and midnight",
        "    return {DEFAULT_PROBE_ENTRY_MINUTE}  # PLANTED: every probe enters at 07:00\n"
        "    marks = {DEFAULT_PROBE_ENTRY_MINUTE, 0}",
        "every probe enters at one fixed time again, so two rules that both qualify "
        "only for an early entry never collide and validate-plan reports the plan "
        "clean while the engine refuses a real stay",
    ),
    # The probe axes read a window's days and times at every stage, because
    # the conflict a plan can still state lives at ADJUST. Put the QUALIFY-only
    # read back and the dawn discounts are never probed before 05:30.
    "F19/every-stage": (
        "tests/test_f19_validator_probes_declared_boundaries.py",
        "validator.py",
        "    return [rule for stage in STAGES for rule in plan.rules_for_stage(stage)]",
        "    return list(plan.rules_for_stage('QUALIFY'))  # PLANTED: QUALIFY only again",
        "the validator reads the days and times of specials only, so two discounts "
        "that collide on an early entry are never probed there and a plan is reported "
        "clean while the engine refuses a real stay",
    ),
    # A later check established the "two comparisons" half of this item did not exist --
    # both already read the rounded value. So the control plants what IS real: the
    # ceiling reading raw seconds instead, which pulls the refusal edge away from
    # the pricing edge.
    "F20": (
        "tests/test_f20_time_rounding_is_declared.py",
        "rules/increment.py",
        "    return ceiling is None or stay.duration_minutes <= ceiling",
        # NOTE: the obvious plant here -- comparing raw elapsed minutes -- is a
        # behavioural NO-OP, because ceil(x) > n is equivalent to x > n for an
        # integer n. fail_controls.py reported it GREEN and it was replaced rather
        # than argued with. FLOOR genuinely separates the two: a stay one
        # millisecond past the ceiling floors back INSIDE it and gets priced.
        "    return ceiling is None or int((stay.exit_at - stay.entry_at).total_seconds() // 60)"
        " <= ceiling  # PLANTED: the ceiling floors raw time, the rules ceil minutes",
        "the stated ceiling is compared against raw elapsed time while the rules "
        "price on rounded minutes, so a stay past the ceiling is priced anyway and "
        "the refusal edge no longer matches the pricing edge",
    ),
    # The plant restores the borrowed code exactly as it shipped.
    "F21": (
        "tests/test_f21_a_refusal_names_its_own_cause.py",
        "engine.py",
        "                    code=CONFLICT_NEGATIVE_TOTAL,",
        "                    code=CONFLICT_MULTIPLE_RULES_AT_STAGE,  # PLANTED: borrowed again",
        "a negative total is refused under the code documented for two rules "
        "qualifying at one stage, so a consumer routing on the code is told to "
        "settle a resolution order that was never the problem",
    ),
    # The three ids guard three DIFFERENT properties -- writing one plant
    # for all of them was how the original F6 ended up unable to see the defect
    # that actually shipped.
    #
    # NOTE, recorded so it is not re-attempted: changing `contract.encode` to
    # indent=4/sort_keys=True is NOT a usable plant any more. Both surfaces read
    # that one function, so they move together and stay equal -- which is the fix
    # working, not a control failing. fail_controls.py reported it GREEN and the
    # plant was replaced rather than argued with.
    "F6b/attribute-form": (
        "tests/test_f6_one_code_path.py",
        "service.py",
        "        payload = encode(body)",
        "        payload = json.dumps(body, indent=2).encode()  # PLANTED: a second encoder",
        "the route encodes its own response again instead of calling the one "
        "encoder, which is the arrangement that let the two doors' bytes diverge "
        "while the contract claimed one serializer",
    ),
    # The second arm, and the reason the guard was widened. It plants the SAME
    # defect written the other common way -- and deliberately BYTE-IDENTICALLY,
    # `indent=2, sort_keys=False` being exactly what `contract.encode` passes, so
    # not one byte diverges and no other test in the file can supply the red.
    # That is why this arm names the single node id rather than the module: the
    # structural guard has to catch it alone or it has caught nothing. Measured
    # against the pre-fix guard it was GREEN, 1 passed.
    "F6b/imported-name-form": (
        "tests/test_f6_one_code_path.py::"
        "test_THERE_IS_ONE_ENCODER_and_no_surface_re_implements_it",
        "service.py",
        "        payload = encode(body)",
        "        from json import dumps  # PLANTED: a second encoder, imported by name\n"
        "        payload = dumps(body, indent=2, sort_keys=False).encode()  # PLANTED",
        "a second encode site is added in the import style that used to walk past "
        "this guard -- byte-identical, so the byte tests cannot see it either, and "
        "the package quietly has two serializers again",
    ),
    "F6c": (
        "tests/test_f6_one_code_path.py",
        "cli.py",
        "    stream.write(payload)",
        "    stream.write(payload + b' ')  # PLANTED: a byte the route does not send",
        "the CLI writes a byte inside the payload that the route does not send -- "
        "the exact shape of the defect that shipped, print() appending a newline, "
        "and the one the old decoded comparison could not see",
    ),
    # Re-anchored when the silence rule stopped being keyed on the stage
    # alone. The PLANTED DEFECT IS THE SAME ONE -- the framework contract's old
    # blanket claim, that every non-qualifying rule everywhere speaks -- expressed
    # against the mechanism that decides it now.
    "F22": (
        "tests/test_f22_the_silence_rule_is_per_stage.py",
        "engine.py",
        "    return SPEAKS_UNQUALIFIED in RULE_TRAITS[rule.type] "
        "and rule.covers(stay.space_class)",
        "    return True  # PLANTED: every rule speaks, whatever it declared",
        "every non-qualifying rule at every stage is asked for lines whatever it "
        "declared and whatever space it covers, so a standard-space receipt carries "
        "VIP tiers that were never about that space -- and carries their money",
    ),
    # The plant is the outside review's own probe: no-op the production invariant. Before
    # this control existed the WHOLE SUITE stayed green under it -- 97 passed.
    "F23": (
        "tests/test_f23_the_production_invariant_is_guarded.py",
        "engine.py",
        "    summed = sum(line.delta_minor for line in ledger.lines)",
        "    return  # PLANTED: the production invariant is a no-op\n"
        "    summed = sum(line.delta_minor for line in ledger.lines)",
        "the invariant that makes the breakdown the product rather than a report "
        "stops reacting at all -- the exact deletion that left all 97 tests green "
        "when the outside pass measured it",
    ),
    # The plant makes a zero-length stay free -- the behaviour an outside review
    # proposed and the owner has not overruled. The control exists so the DECISION cannot be
    # changed by accident; changing it on purpose is a brief.
    "F24": (
        "tests/test_f24_a_zero_length_stay_is_priced.py",
        "rules/increment.py",
        "    if minutes <= first_len:",
        "    if minutes == 0:  # PLANTED: a zero-length stay silently becomes free\n"
        "        return []\n"
        "    if minutes <= first_len:",
        "a stay of zero minutes stops paying the first period, which is a pricing "
        "decision being changed with nothing said -- and it is the exact behaviour "
        "an outside reviewer asked for and the owner has not agreed to",
    ),
    # The plant restores the undeclared condition exactly as it shipped: the
    # engine deciding the day span for every plan, whatever the plan says.
    "F25": (
        "tests/test_f25_day_span_is_declared_by_the_plan.py",
        "rules/time_window.py",
        "    if span_limit is not None and days_after > span_limit:",
        "    if days_after > 0:  # PLANTED: the engine decides the day span again",
        "the engine imposes a same-local-day condition the plan cannot state or "
        "remove, so an overnight stay meeting both declared wall-clock limits is "
        "charged the time-based rate -- 60.00 where the early bird is 12.00",
    ),
    # The second version's six, one per new guarantee. Each one alone must go red: a plant that
    # took several of these files down together would prove that something broke,
    # not that each guarantee measures its own subject.
    "F26": (
        "tests/test_f26_the_days_are_stated_by_the_plan.py",
        "rules/time_window.py",
        '    if not _applies_on_the_entry_date(rule.params["applies_on"], entry_local):',
        "    if False:  # PLANTED: the days the plan states are no longer checked",
        "a window applies on every day whatever the plan says, so a Tuesday is "
        "given the weekend rate and the breakdown says nothing about it",
    ),
    "F27": (
        "tests/test_f27_the_entry_window_has_a_lower_bound.py",
        "rules/time_window.py",
        '    if entry_local.time() < rule.params["enter_from"]:',
        "    if False:  # PLANTED: enter_from is stored and never read",
        "`enter_from` becomes a field the loader validates, the plan states and "
        "the applier ignores -- the `increment.rounding` shape, which shipped in "
        "this module once -- so an evening rate catches the seven-a.m. car",
    ),
    "F39": (
        "tests/test_f39_the_exit_limit_runs_to_the_day_the_span_allows.py",
        "rules/time_window.py",
        "    limit_local = _exit_limit(entry_local, rule.params[\"exit_by\"], span_limit)\n"
        "    if (exit_local.date(), exit_local.time()) > (limit_local.date(), limit_local.time()):",
        "    limit_local = _exit_limit(entry_local, rule.params[\"exit_by\"], span_limit)\n"
        "    if exit_local.time() > rule.params[\"exit_by\"]:  # PLANTED: back to a bare clock",
        "the exit limit goes back to being a clock reading with no day on it, so an "
        "evening window with an after-midnight limit again refuses the car that "
        "leaves the same evening -- 23:45 read as 'after 02:00' -- and prices it on "
        "the plan's ordinary rate instead",
    ),
    # THE COUNTER-MODEL, PROMOTED TO A CONTROL. This is the exact mutation the L
    # review installed to discover that F40's subject was unguarded: a TRUE
    # instant comparison, through `.timestamp()`. It mispriced the repeated hour
    # 40.00 -> 24.00 and the whole 338-test suite stayed GREEN with it in place,
    # over 17,565 bounded exit comparisons. So this plant is not a hypothetical
    # break -- it is the state the module was actually in, and F40 is the test
    # that now refuses to pass under it.
    #
    # It must be `.timestamp()`. `limit_local.replace(tzinfo=...)` compared
    # directly would be a NO-OP: PEP 495 compares same-zone aware datetimes by
    # their naive fields and ignores `fold`. See `_exit_limit`'s docstring, and
    # `test_the_naive_replace_spelling_is_NOT_a_counter_model`.
    "F40": (
        "tests/test_f40_the_exit_limit_is_a_wall_clock_reading.py",
        "rules/time_window.py",
        "    if (exit_local.date(), exit_local.time()) > "
        "(limit_local.date(), limit_local.time()):",
        "    # PLANTED: a TRUE instant comparison, through UTC\n"
        "    if exit_local.timestamp() > "
        "limit_local.replace(tzinfo=exit_local.tzinfo).timestamp():",
        "the exit limit stops being a wall-clock reading and becomes an instant, so "
        "on the night the clocks go back the second stay through the repeated hour "
        "is refused a rate its own wall clock earned -- 40.00 becomes 24.00",
    ),
    "F28": (
        "tests/test_f28_next_day_is_a_bounded_span.py",
        "rules/time_window.py",
        'DAY_SPAN_LIMITS: dict[str, int | None] = {"same_day": 0, "next_day": 1, '
        '"any_span": None}',
        'DAY_SPAN_LIMITS: dict[str, int | None] = {"same_day": 0, "next_day": None, '
        '"any_span": None}  # PLANTED: next_day is unbounded',
        "`next_day` stops being bounded and becomes a spelling of `any_span`, so a "
        "car that left three days later at 05:00 is charged one night's overnight "
        "rate -- the hole day_span itself was created to close",
    ),
    "F29": (
        "tests/test_f29_a_rate_effect_reuses_increment.py",
        "rules/time_window.py",
        "        return [header] + increment.lines_for(\n"
        '            effect["rate"], rule.id, stay.duration_minutes, plan.currency\n'
        "        )",
        '        _p = effect["rate"]  # PLANTED: a second period calculation\n'
        '        _extra = max(0, stay.duration_minutes - _p["first_period_minutes"])\n'
        '        _n = -(-_extra // _p["repeat_period_minutes"])\n'
        "        return [\n"
        "            header,\n"
        '            Line(code="increment.first_period", rule_id=rule.id, text="PLANTED",\n'
        '                 delta_minor=_p["first_period_minor"]\n'
        '                 + _n * _p["repeat_period_minor"]),\n'
        "        ]",
        "a window's `rate` effect prices through its own copy of the period "
        "calculation instead of calling `increment`, which is the arrangement that "
        "lets a weekend rate and a weekday rate drift apart in money",
    ),
    "F30": (
        "tests/test_f30_an_adjust_runs_after_cap_and_surcharge.py",
        "stages.py",
        "STAGES: tuple[str, ...] = (QUALIFY, ACCUMULATE, CAP, SURCHARGE, ADJUST)",
        "STAGES: tuple[str, ...] = (QUALIFY, ACCUMULATE, ADJUST, CAP, SURCHARGE)"
        "  # PLANTED: the adjustment runs first",
        "an adjustment is taken before the cap and the surcharge, so the customer "
        "is given a percentage of a number they are not being charged",
    ),
    # Re-anchored in the tax round, when the division moved into the ONE applier
    # a tax rule shares. The PLANTED DEFECT IS UNCHANGED -- every percentage
    # rounds down whatever the plan says -- because re-pointing an anchor must
    # not quietly weaken what the control proves.
    "F31": (
        "tests/test_f31_the_adjust_rounding_is_consulted.py",
        "percent.py",
        '    if rounding == "down":',
        "    if True:  # PLANTED: the stated rounding is ignored",
        "the direction a fractional minor unit goes stops being the plan's "
        "decision -- every percentage rounds one way whatever the document says, "
        "on a plan that reads correctly to whoever wrote it",
    ),
    # The tax fix round. The corpus stated only `down`, so a comparison over the
    # stated documents never reached `up`. These two arms are one character each,
    # one per side of the branch: F31's counterpart lands on a fraction, F30's on
    # a whole amount, and each is the only corpus fixture that sees its arm.
    "F31/up-fraction": (
        "tests/test_f31_the_adjust_rounding_is_consulted.py",
        "percent.py",
        "        return quotient + (1 if remainder else 0)",
        "        return quotient + (0 if remainder else 0)  # PLANTED: `up` drops the fraction",
        "`up` behaves as `down` on a real fraction, so a garage that stated `up` "
        "keeps a minor unit it said the customer would not keep",
    ),
    "F31/up-whole": (
        "tests/test_f30_an_adjust_runs_after_cap_and_surcharge.py",
        "percent.py",
        "        return quotient + (1 if remainder else 0)",
        "        return quotient + (1 if remainder else 1)  # PLANTED: `up` adds one to a whole",
        "`up` takes an extra minor unit where the percentage is exact, so every "
        "whole-valued `up` adjustment is off by one",
    ),
    # The second tax fix round. The line's rounding clause is conditional, and a
    # boolean is controlled from both sides: `True` is the unconditional form the
    # line had before, `False` drops the clause where a fraction was rounded.
    "F31/exact-says-rounded": (
        "tests/test_f31_the_adjust_rounding_is_consulted.py",
        "rules/time_window.py",
        '        if was_rounded(base, amount["percent_bp"], magnitude):',
        "        if True:  # PLANTED: the line claims a rounding whatever the division did",
        "a percentage that divides exactly is described to the customer as rounded "
        "up or down when nothing was rounded",
    ),
    "F31/fraction-says-nothing": (
        "tests/test_f31_the_adjust_rounding_is_consulted.py",
        "rules/time_window.py",
        '        if was_rounded(base, amount["percent_bp"], magnitude):',
        "        if False:  # PLANTED: the line never says which way a fraction went",
        "a percentage that landed on a fraction is shown without the direction it "
        "was rounded, so a customer disputing a cent is told nothing",
    ),
    # The second version's second build group. One part brings terminality and the
    # trait that finally gives an ADJUST window its line; another brings the second cap type and the
    # three stage categories the first one detonated.
    #
    # The two arms below share an ANCHOR and plant opposite defects, which is the
    # only honest way to control a boolean: `return True` collapses the silence
    # rule into "everything speaks", `return False` into "nothing does", and a
    # single arm would go red for whichever it happened to pick.
    "F22b": (
        "tests/test_f22_the_silence_rule_is_per_stage.py::"
        "test_a_rule_that_COULD_have_applied_and_did_not_SPEAKS_at_any_stage",
        "engine.py",
        "    return SPEAKS_UNQUALIFIED in RULE_TRAITS[rule.type] "
        "and rule.covers(stay.space_class)",
        "    return False  # PLANTED: no type may declare that it speaks",
        "the declaration stops being read, so a weekend discount that declined "
        "because it is a Tuesday says nothing at all and the receipt cannot answer "
        "the question it was asked",
    ),
    # A special for another space class. The engine asks every QUALIFY rule for
    # its lines, and the appliers did not ask the class, so a VIP-only special a
    # standard stay met on every time said "applied" and added its price. Each
    # applier's check is taken out on its own, and the sweep is shown seeing each
    # on its own. And the class is the reason whatever the times: the old order,
    # a time or the minutes said before the class -- a VIP car told it was late
    # for an early bird it could never get -- is red too, for each applier.
    # Re-anchored when the class moved first; the first four defects are unchanged.
    "F22c": (
        "tests/test_f22c_a_special_for_another_class_charges_nothing.py",
        "rules/time_window.py",
        "    if not rule.covers(stay.space_class):\n",
        "    if False:  # PLANTED: a window does not ask the stay's class\n",
        "a window for VIP spaces met on every time by a standard stay says "
        "'applied' and adds its price beside the time-based rate, or stops the "
        "quote where the caps check the base against the receipt",
    ),
    "F22c/grace-applies-for-another-class": (
        "tests/test_f22c_a_special_for_another_class_charges_nothing.py",
        "rules/grace.py",
        "    if not rule.covers(stay.space_class):\n",
        "    if False:  # PLANTED: a grace does not ask the stay's class\n",
        "a grace for VIP spaces tells a five-minute standard stay there is no "
        "charge and nothing further is added, on a receipt that charges it",
    ),
    "F22c/times-said-over-the-class": (
        "tests/test_f22c_a_special_for_another_class_charges_nothing.py",
        "rules/time_window.py",
        "    if not rule.covers(stay.space_class):\n",
        "    if not rule.covers(stay.space_class) and not _failures(rule, stay, plan):"
        "  # PLANTED\n",
        "a window for another class that the stay also missed on a time gives the "
        "time as its reason, so a VIP car reads that it came in too late for an "
        "early bird it could never get",
    ),
    "F22c/minutes-said-over-the-class": (
        "tests/test_f22c_a_special_for_another_class_charges_nothing.py",
        "rules/grace.py",
        "    if not rule.covers(stay.space_class):\n",
        "    if not rule.covers(stay.space_class) and minutes <= allowed:  # PLANTED\n",
        "a grace for another class that the stay ran over gives the minutes as its "
        "reason, so the stay is told by how much it missed a grace it could never have",
    ),
    "F22c/sweep-window": (
        "tests/test_f22c_a_special_for_another_class_charges_nothing.py::"
        "test_a_special_for_another_class_changes_nothing_but_its_own_line_SWEEP",
        "rules/time_window.py",
        "    if not rule.covers(stay.space_class):\n",
        "    if False:  # PLANTED: a window does not ask the stay's class\n",
        "the sweep alone does not see a window for another class adding its "
        "price, which is how every earlier sweep missed it",
    ),
    "F22c/sweep-grace": (
        "tests/test_f22c_a_special_for_another_class_charges_nothing.py::"
        "test_a_special_for_another_class_changes_nothing_but_its_own_line_SWEEP",
        "rules/grace.py",
        "    if not rule.covers(stay.space_class):\n",
        "    if False:  # PLANTED: a grace does not ask the stay's class\n",
        "the sweep alone does not see a grace for another class saying the stay "
        "is free",
    ),
    "F32": (
        "tests/test_f32_grace_is_terminal_and_free.py",
        "engine.py",
        "        if TERMINAL in RULE_TRAITS[rule.type]:",
        "        if False:  # PLANTED: a terminal rule no longer stops the pipeline",
        "a graced stay goes on through CAP, SURCHARGE and ADJUST, so a free stay in "
        "a VIP space is charged the surcharge -- 'if customer decides to laeve "
        "within that period it is free' with a five-dollar line under it",
    ),
    "F33": (
        "tests/test_f33_two_caps_compose.py",
        "rules/weekly_max.py",
        "            delta_minor=ceiling - running_total_minor,",
        "            delta_minor=-rule.params[\"max_minor\"],  # PLANTED: a cap that SUBTRACTS",
        "a cap subtracts its own maximum instead of reducing the total to it, which "
        "is arithmetic that depends on the order the caps ran in -- 500 one way and "
        "1900 the other, from the same two ceilings on the same stay",
    ),
    # Re-anchored: `if stage in RESOLVING:` stopped being unique in
    # engine.py the moment `quote` grew a resolving branch of its own, and
    # plant.py refused the ambiguity -- correctly. This anchors on the COMPOSING
    # branch instead, which is what the guarantee is actually about, and plants
    # the shipped defect there directly rather than inverting the test above it.
    "F34": (
        "tests/test_f34_composing_stages_do_not_conflict.py",
        "engine.py",
        "    # COMPOSING and order-independent: both apply, the total is the same either\n"
        "    # way, and there is nothing for an owner to decide.\n"
        "    return None",
        "    return Finding(  # PLANTED: composing rules reported as a conflict again\n"
        "        code=CONFLICT_UNORDERED_ADJUSTMENTS,\n"
        '        text=f"{len(qualifying)} rules qualify at {stage}",\n'
        "        rule_ids=ids,\n"
        "    )",
        "two rules that COMPOSE are reported as a conflict again, so a plan carrying "
        "a daily AND a weekly cap refuses every stay in the garage -- the defect that "
        "was latent until a second CAP rule type existed",
    ),
    "F35": (
        "tests/test_f35_the_adjust_order_is_stated.py",
        "engine.py",
        "    if stage in COMPOSING_ORDER_DEPENDENT and plan.adjust_order is not None:",
        "    if False:  # PLANTED: the stated order is ignored",
        "the order an owner wrote is discarded and the adjustments run in rule-id "
        "order instead, so a plan that says 'voucher first' quietly charges the "
        "percentage first -- a wrong fee behind a document that reads correctly",
    ),
    # The first two are the field that spent a whole round being
    # required, validated, published -- and read by nothing.
    "F36": (
        "tests/test_f36_the_resolution_modes_decide.py",
        "engine.py",
        "    settings = plan.resolution[stage]",
        '    settings = {"mode": "cheapest_wins"}  # PLANTED: the plan\'s mode is ignored',
        "the plan's stated mode stops being read and every stage resolves by price, "
        "so a garage that wrote 'the weekend rate wins' quietly gets the cheaper "
        "rule instead -- a wrong fee behind a document that reads correctly",
    ),
    "F37": (
        "tests/test_f37_a_stated_order_names_every_rule.py",
        "plan.py",
        "        if missing or extra:",
        "        if False:  # PLANTED: an incomplete order loads again",
        "an order naming two of three rules loads, so the third takes whatever "
        "position the implementation happens to give it -- array position deciding "
        "money, which is the defect `select_plan` exists to refuse",
    ),
    "F38": (
        "tests/test_f38_the_documents_name_only_real_things.py",
        "findings.py",
        'GAP_NO_TAX_SET_IN_FORCE = "GAP_NO_TAX_SET_IN_FORCE"',
        'GAP_NO_TAX_SET_IN_FORCE = "GAP_NO_TAX_SET_STATED"'
        "  # PLANTED: the published code is renamed",
        "a finding code is renamed in the code and not in the prose that names it, "
        "so docs/CONTRACT.md keeps publishing an identifier nothing answers with -- "
        "the true-sounding published sentence over correct code",
    ),
    # The tax round's five, each with the arms its guarantee needs. Every arm
    # alone must go red: a plant that broke two things at once would prove that
    # something broke, not that each check measures its own subject.
    "F41": (
        "tests/test_f41_a_tax_rounds_the_way_its_rule_says.py",
        "percent.py",
        "        return quotient + (1 if 2 * remainder >= BASIS_POINTS_PER_WHOLE else 0)",
        "        return quotient + (1 if 2 * remainder > BASIS_POINTS_PER_WHOLE else 0)"
        "  # PLANTED: exactly half goes down",
        "`nearest` is decided with `>` instead of `>=`, so an exact half rounds "
        "DOWN -- 8.5 becomes 8 -- which agrees with the right answer on every "
        "figure that is not exactly half and is wrong on the one that is",
    ),
    "F41/consulted": (
        "tests/test_f41_a_tax_rounds_the_way_its_rule_says.py",
        "tax.py",
        "    amount = percent_of_minor(subtotal_minor, rule.percent_bp, rule.rounding)",
        '    amount = percent_of_minor(subtotal_minor, rule.percent_bp, "down")'
        "  # PLANTED: the rule's rounding is not read",
        "a tax rule's `rounding` is validated, stored and never read -- the "
        "`increment.rounding` shape -- so a garage that stated `nearest` has "
        "every fraction dropped",
    ),
    # The fifth tax fix round. Whether a line gets a rounding clause is decided
    # ONCE, in `percent.was_rounded`; it used to be written out at the tax line
    # and at the adjustment line, and a gate broke each copy and watched the
    # other's tests stay green. This is ONE plant with TWO arms, and both have to
    # fire: a single target naming both test files goes red if EITHER does, which
    # is the arrangement that would let one call site grow its own copy again
    # without this control noticing.
    "F31/shared-was-rounded": (
        "tests/test_f31_the_adjust_rounding_is_consulted.py",
        "percent.py",
        "    return amount_minor * percent_bp != result_minor * BASIS_POINTS_PER_WHOLE",
        "    return True  # PLANTED: every percentage is said to have been rounded",
        "the one shared rounding test is broken, and the ADJUSTMENT line has to "
        "go red with it -- if it stays green it has stopped asking the shared test "
        "and is deciding for itself",
    ),
    "F41/shared-was-rounded": (
        "tests/test_f41_a_tax_rounds_the_way_its_rule_says.py",
        "percent.py",
        "    return amount_minor * percent_bp != result_minor * BASIS_POINTS_PER_WHOLE",
        "    return True  # PLANTED: every percentage is said to have been rounded",
        "the one shared rounding test is broken, and the TAX line has to go red "
        "with it -- if it stays green it has stopped asking the shared test and "
        "is deciding for itself",
    ),
    "F42": (
        "tests/test_f42_taxes_do_not_compound.py",
        "tax.py",
        "        lines.append(_tax_line(rule, subtotal, currency))",
        "        lines.append(_tax_line(  # PLANTED: the running total, not the subtotal\n"
        "            rule, subtotal + sum(ln.delta_minor for ln in lines), currency))",
        "the applier is fed the running total instead of the subtotal, so the second "
        "tax is taken of the first -- tax of the tax, 55 where 50 is owed, and a "
        "compounding nobody decided on",
    ),
    "F42/base-key": (
        "tests/test_f42_taxes_do_not_compound.py",
        "tax.py",
        'TAX_RULE_KEYS: frozenset[str] = frozenset({"id", "label", "percent_bp", '
        '"rounding", "sequence"})',
        'TAX_RULE_KEYS: frozenset[str] = frozenset({"id", "label", "percent_bp", '
        '"rounding", "sequence", "base"})  # PLANTED: a base is accepted',
        "a rule stating a base LOADS, and the base it states is silently ignored -- "
        "a garage that wrote a compounding rule is told nothing and is not taxed "
        "the way its document reads",
    ),
    "F43": (
        "tests/test_f43_the_tax_set_in_force_is_chosen_by_the_instant.py",
        "tax.py",
        "    in_force = [s for s in sets if s.effective_from <= at]",
        "    in_force = list(sets)  # PLANTED: the instant is not consulted",
        "the latest set is used whatever the instant, so a stay in March is taxed "
        "at a rate that takes effect in July, and an instant before every set is "
        "taxed instead of refused",
    ),
    "F43/same-instant": (
        "tests/test_f43_the_tax_set_in_force_is_chosen_by_the_instant.py",
        "tax.py",
        "            if first.effective_from == second.effective_from:",
        "            if False:  # PLANTED: two sets at one instant load",
        "two sets taking effect at the same instant both load, so which one is in "
        "force is decided by their order in the list",
    ),
    "F44": (
        "tests/test_f44_tax_order_is_the_stated_sequence.py",
        "tax.py",
        "    for rule in sorted(chosen.rules, key=lambda r: r.sequence):",
        "    for rule in chosen.rules:  # PLANTED: list order decides",
        "the lines come out in whatever order the caller's list carried the rules, "
        "and the `sequence` the garage stated is validated and never read",
    ),
    "F44/shared-sequence": (
        "tests/test_f44_tax_order_is_the_stated_sequence.py",
        "tax.py",
        "        if other is not None:",
        "        if False:  # PLANTED: two rules may share a sequence",
        "two rules stating the same `sequence` load, so their relative order is "
        "the sort's tie-break over the caller's list -- array position again",
    ),
    "F44/zero-sequence": (
        "tests/test_f44_tax_order_is_the_stated_sequence.py",
        "tax.py",
        '    sequence = _whole(raw["sequence"], f"{where}.sequence", positive=False)',
        '    sequence = _whole(raw["sequence"] or None, f"{where}.sequence", positive=False)'
        "  # PLANTED: 0 is read as missing",
        "a rule stating `sequence: 0` is refused as though it stated none -- the "
        "truthiness trap, which the whole suite passed when it was planted by hand",
    ),
    "F45": (
        "tests/test_f45_tax_on_nothing_is_nothing.py",
        "tax.py",
        "    if subtotal == 0:\n        return []",
        "    if False:  # PLANTED: a zero subtotal is taxed\n        return []",
        "a stay that paid nothing gets a tax line for every rule, each at zero -- "
        "noise on a receipt under a fee nobody paid",
    ),
    # The tax-set door. Two arms, each required red on its own: the door stops
    # asking the loader, and the loader itself is broken -- the second is the one
    # that proves the door is not a copy, because a copy would stay green.
    "F46": (
        "tests/test_f46_a_tax_set_has_one_door.py",
        "contract.py",
        '    return load_tax_sets(body["tax_sets"], "request.tax_sets")',
        '    return tuple(body["tax_sets"])  # PLANTED: the door no longer asks the loader',
        "the tax-set door answers valid for anything shaped like a list, so a caller "
        "stores sets the engine will refuse when it computes the tax",
    ),
    "F46/loader-is-the-door": (
        "tests/test_f46_a_tax_set_has_one_door.py",
        "tax.py",
        '    if not isinstance(label, str) or not label.strip():',
        '    if not isinstance(label, str) or not label:  # PLANTED: blank is only empty',
        "the LOADER stops treating a whitespace-only label as blank; the door must "
        "go red with it, or it is judging tax sets by some rule other than the loader's",
    ),
    # The tax door. Two arms, each required red on its own: the CLI's path and the
    # route's path each broken while the other is left alone. One plant breaking
    # both would stay a control even if the test compared one surface to itself.
    # F48 replaced F11. Two arms, because the guarantee has two halves
    # that fail differently: the tie refused again (the F11 behaviour put back),
    # and the comparison lost (the dearer rule chosen), which a tie-only test
    # would never see.
    "F48/tie-refused-again": (
        "tests/test_f48_a_tie_at_the_cheapest_charge_is_priced.py",
        "engine.py",
        "        # Never a conflict. A TERMINAL rule wins outright by what its type is; else",
        "        _t = _candidate_totals(qualifying, stay, plan)  # PLANTED: F11 put back\n"
        "        if len(set(_t.values())) == 1 and not any(\n"
        "            TERMINAL in RULE_TRAITS[r.type] for r in qualifying\n"
        "        ):\n"
        "            return Finding(code=CONFLICT_AMBIGUOUS_PLAN_SELECTION,\n"
        "                           text='PLANTED: the tie is refused', rule_ids=ids)\n"
        "        # Never a conflict. A TERMINAL rule wins outright by what its type is; else",
        "two specials charging the same amount are refused again, so a plan whose "
        "every stay has one answer cannot be stored",
    ),
    # Re-anchored in F63, when the ways began to be ranked on the whole fee
    # (`_cheapest`). THE PLANTED DEFECT IS UNCHANGED: the dearer one is chosen.
    "F48/dearer-chosen": (
        "tests/test_f48_a_tie_at_the_cheapest_charge_is_priced.py",
        "engine.py",
        "    return min(rules, key=lambda rule: _rank(plan, rule, compared))",
        "    return max(rules, key=lambda rule: _rank(plan, rule, compared))  # PLANTED",
        "the dearer of two qualifying specials is applied, so the driver pays more "
        "than the plan's own rule says",
    ),
    # Two arms: the comparison skipped (the special replaces the
    # time-based charge whatever it costs, the behaviour before the fix) and the
    # comparison inverted (the dearer way charged). A test that only met stays
    # where the special is cheaper would pass the first; one that only met stays
    # where the hourly rate is cheaper would pass the second.
    "F50/special-always-used": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        "    if time_fee < special_fee:",
        "    if False:  # PLANTED: the special always replaces the time-based charge",
        "a qualifying special is charged even where the time-based rate costs the "
        "driver less",
    ),
    "F50/dearer-chosen": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        "    if time_fee < special_fee:",
        "    if time_fee > special_fee:  # PLANTED: the dearer way charged",
        "the stay is charged whichever of the special and the time-based rate costs "
        "the driver MORE",
    ),
    # F39, F40 and the contract's partly dead window moved to
    # `stated_order` in fix 1, so `cheapest_wins` had no test on any of them. Each
    # now has one where the window is CHEAPER and applies, and each is proven on
    # BOTH ways it can be lost: the window refused (that guarantee's own defect)
    # and the hour charged though it costs more. The target is the one new test,
    # not the module, so the older tests cannot fire the control for it.
    "F39/cheapest-window-refused": (
        "tests/test_f39_the_exit_limit_runs_to_the_day_the_span_allows.py::test_under_cheapest_wins_the_car_out_at_2345_gets_the_cheaper_window",
        "rules/time_window.py",
        "    if (exit_local.date(), exit_local.time()) > (limit_local.date(), limit_local.time()):",
        "    if exit_local.time() > rule.params[\"exit_by\"]:  # PLANTED: back to a bare clock",
        "under `cheapest_wins` the car out at 23:45 is refused a window CHEAPER than "
        "the hour, because its after-midnight limit is read as a bare clock",
    ),
    "F39/cheapest-hour-charged": (
        "tests/test_f39_the_exit_limit_runs_to_the_day_the_span_allows.py::test_under_cheapest_wins_the_car_out_at_2345_gets_the_cheaper_window",
        "engine.py",
        "    if time_fee < special_fee:",
        "    if True:  # PLANTED: the hour charged whatever the special costs",
        "under `cheapest_wins` the event window qualifies and is cheaper, and the "
        "hour is charged instead",
    ),
    "F40/cheapest-window-refused": (
        "tests/test_f40_the_exit_limit_is_a_wall_clock_reading.py::test_under_cheapest_wins_BOTH_passes_get_the_cheaper_window",
        "rules/time_window.py",
        "    if (exit_local.date(), exit_local.time()) > "
        "(limit_local.date(), limit_local.time()):",
        "    # PLANTED: a TRUE instant comparison, through UTC\n"
        "    if exit_local.timestamp() > "
        "limit_local.replace(tzinfo=exit_local.tzinfo).timestamp():",
        "under `cheapest_wins` the second pass through the repeated hour is refused "
        "a window CHEAPER than the hour -- 10.00 becomes 24.00",
    ),
    "F40/cheapest-hour-charged": (
        "tests/test_f40_the_exit_limit_is_a_wall_clock_reading.py::test_under_cheapest_wins_BOTH_passes_get_the_cheaper_window",
        "engine.py",
        "    if time_fee < special_fee:",
        "    if True:  # PLANTED: the hour charged whatever the special costs",
        "under `cheapest_wins` the night window qualifies on both passes and is "
        "cheaper, and the hour is charged instead",
    ),
    "F50/partly-dead-window-refused": (
        "tests/test_f50_the_cheaper_way_is_charged.py::test_the_contract_partly_dead_window_is_charged_where_it_fits_and_is_cheaper",
        "rules/time_window.py",
        "    exit_side = _exit_failure(rule, entry_local, exit_local)\n",
        "    if rule.params[\"exit_by\"] < rule.params[\"enter_by\"]:\n"
        "        failed.append(\"PLANTED: a partly dead window treated as dead\")\n"
        "    exit_side = _exit_failure(rule, entry_local, exit_local)\n",
        "the contract's 06:00-23:00 / out by 20:00 window is treated as dead for "
        "every entry, so the early car is charged the hour's 33.00, not 10.00",
    ),
    "F50/partly-dead-hour-charged": (
        "tests/test_f50_the_cheaper_way_is_charged.py::test_the_contract_partly_dead_window_is_charged_where_it_fits_and_is_cheaper",
        "engine.py",
        "    if time_fee < special_fee:",
        "    if True:  # PLANTED: the hour charged whatever the special costs",
        "the contract's partly dead window qualifies and is cheaper, and the hour "
        "is charged instead",
    ),
    # When the time-based rate wins, every other special still
    # says why it was not used. Three arms: the specials that did not qualify go
    # silent (the re-gate's R10), the ones that qualified and lost go silent, and
    # the loser's line claims the cheaper special was applied when the hour was.
    # Re-anchored in F64 (a special that did not qualify is asked for its line
    # once a quote, `qualified.why_not`); the defect is unchanged.
    "F50/why-not-unqualified-left-out": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        "                        ledger.add(lost)\n"
        "                    continue\n"
        "                for line in qualified.why_not(rule):\n"
        "                    ledger.add(line)\n",
        "                        ledger.add(lost)\n"
        "                    continue\n"
        "                pass  # PLANTED: a special that did not qualify is silent\n",
        "on the time-based way a special that did not qualify has no line, so the "
        "breakdown frozen on the stay cannot say why the weekend rate was not given",
    ),
    "F50/why-not-losers-left-out": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        "                        ledger.add(lost)\n",
        "                        pass  # PLANTED: a special that lost is silent\n",
        "on the time-based way a special that qualified and lost to a cheaper one "
        "has no line, so a rate the driver was entitled to is simply absent",
    ),
    "F50/why-not-says-applied": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        # Re-anchored in F63 (`compared` replaced `totals`); the defect is unchanged.
        "rule, cheapest, QUALIFY, plan, compared, by_time=True",
        "rule, cheapest, QUALIFY, plan, compared, by_time=False  # PLANTED",
        "on the time-based way the losing special's line says the cheaper special "
        "was applied, when the hour was charged",
    ),
    # An earlier plant: the "why not" lines kept only when two or
    # more specials qualify. The three-special tests above never reach the one-
    # qualifier case and stayed green on it (receipt 289bf252).
    "F50/why-not-one-qualifier-left-out": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        # Re-anchored in F63 (the qualifying specials are named once, at the top
        # of the pass) and in F64 (a rule is found by its id); the defect is
        # unchanged.
        "            for rule in qualified.rules(QUALIFY):\n"
        "                if qualified.has(rule):\n"
        "                    if compared is not None and rule is not cheapest:\n",
        "            for rule in (  # PLANTED: the why-not lines only when 2+ qualify\n"
        "                qualified.rules(QUALIFY) if len(qualified_at_qualify) > 1 else []\n"
        "            ):\n"
        "                if qualified.has(rule):\n"
        "                    if compared is not None and rule is not cheapest:\n",
        "on the time-based way, when the early bird alone qualifies and loses to "
        "the hour, every other special's line is gone, so the breakdown frozen on "
        "the stay cannot say why the weekend rate was not given",
    ),
    "F49": (
        "tests/test_f49_a_finding_names_the_stay_that_found_it.py",
        "validator.py",
        "replace(finding, probe=found_by))",
        "finding)  # PLANTED: the stay that found it is dropped",
        "a finding reaches the owner with no stay, so the sentence cannot say "
        "which car it was about",
    ),
    "F47": (
        "tests/test_f47_a_tax_figure_has_one_path.py",
        "cli.py",
        '        "subtotal_minor": args.subtotal,',
        '        "subtotal_minor": args.subtotal + 1,  # PLANTED: the CLI taxes another amount',
        "`rate-engine tax` hands the one function a different request from the one "
        "`/v1/tax` does, so an operator testing a tax at the terminal is shown a "
        "figure the garage will not charge",
    ),
    "F47/route": (
        "tests/test_f47_a_tax_figure_has_one_path.py",
        "service.py",
        '            "/v1/tax": run_tax,',
        '            "/v1/tax": lambda d: run_tax(  # PLANTED: the route taxes by its own path\n'
        '                {**d, "subtotal_minor": 0} if isinstance(d, dict) else d\n'
        "            ),",
        "`/v1/tax` reaches its figure by a path the CLI does not take, so the two "
        "surfaces answer the same request differently",
    ),
    # The body's decode. Two arms: json's own encoding detection put back, and the
    # catch removed. The first leaves the malformed bytes answered and lets UTF-16
    # and UTF-32 through; the second leaves them refused-by-crash. Neither is the
    # other, so each has to fire on its own.
    "F16/body-decoded-strictly": (
        "tests/test_f16_a_body_is_read_as_utf8.py",
        "service.py",
        '            text = raw.decode("utf-8")',
        '            text = raw.decode(json.detect_encoding(raw), "surrogatepass")  # PLANTED',
        "a POST body is decoded by json's own detection again, so a UTF-16 or UTF-32 "
        "body is read and answered, and a caller that decodes those bytes differently "
        "is judged on text it never sent",
    ),
    "F16/undecodable-body-answered": (
        "tests/test_f16_a_body_is_read_as_utf8.py",
        "service.py",
        "        except UnicodeDecodeError as exc:",
        "        except LookupError as exc:  # PLANTED: an undecodable body escapes again",
        "a body that is not UTF-8 raises out of the handler, and the caller gets a "
        "dropped connection with no status and no body",
    ),
    "F8": (
        "tests/test_f8_breakdown_adds_up.py",
        "engine.py",
        "    fee = ledger.total_minor\n    _assert_ledger_is_the_fee(fee, ledger)",
        "    fee = ledger.total_minor - 1  # PLANTED: a second route to the total\n"
        "    _assert_ledger_is_the_fee(fee, ledger)",
        "the fee is reached by a route other than adding a Line, which is the defect "
        "the ledger exists to make impossible",
    ),
    # The fill-rule round. One arm per way the money can go wrong, each required
    # red on its own: a test that only met stays above the threshold would pass
    # the edge plant, and one that never met a VIP space would pass the plant
    # that raises the running total instead of the time.
    "F51/at-threshold-not-applied": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "rules/fill_level.py",
        '        and figure >= rule.params["threshold_bp"]',
        '        and figure > rule.params["threshold_bp"]  # PLANTED: AT the threshold misses',
        "a car that came in exactly at the threshold is not charged the busy rate",
    ),
    "F51/below-threshold-applied": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "rules/fill_level.py",
        '        and figure >= rule.params["threshold_bp"]',
        '        and figure >= rule.params["threshold_bp"] - 1  # PLANTED: one point early',
        "a car that came in one basis point below the threshold is charged the busy rate",
    ),
    "F51/no-figure-guessed": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "engine.py",
        "    if stay.occupancy_at_entry_bp is None:",
        "    if False:  # PLANTED: a stay with no figure is priced as if the garage were empty",
        "a stay with no occupancy figure is priced -- as if the garage were empty -- "
        "instead of refused by name",
    ),
    "F51/uncapped-charge-raised": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "engine.py",
        "        if stage == SURCHARGE:",
        "        if stage == CAP:  # PLANTED: the time charge is read before the caps",
        "the fill rule raises the time charge BEFORE the daily most, so a long stay is "
        "raised by a percent of money the driver is not charged",
    ),
    "F51/running-total-raised": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "rules/fill_level.py",
        "        added, measure = _raised(rule, time_charge_minor, plan.currency)",
        "        added, measure = _raised(rule, running_total_minor, plan.currency)  # PLANTED",
        "the fill rule raises the running total, so a VIP surcharge is raised with the time",
    ),
    "F51/overlap-priced": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "engine.py",
        "        if len(one_per_stay) > 1:",
        "        if False:  # PLANTED: two fill rules on one stay both charge",
        "two fill rules applying to one stay are both charged in `adjust_order` "
        "instead of being refused as two answers to one question",
    ),
    "F51/out-of-range-accepted": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "percent.py",
        "    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:",
        "    if isinstance(value, bool) or not isinstance(value, int) or value < low:  # PLANTED",
        "a threshold or a percent above 100% loads, so a plan can state a garage fuller "
        "than full or an increase nobody can read",
    ),
    "F51/raised-before-discount": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "engine.py",
        "                    priced_by_special=priced_by_special, time_charge_minor=time_left,",
        "                    priced_by_special=priced_by_special, time_charge_minor=time_charge,"
        "  # PLANTED",
        "the fill rule raises the time charge before the discount came off, so a "
        "discounted car at a busy garage pays the increase on money it is not charged",
    ),
    "F51/extra-before-discount": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "engine.py",
        "                    extras_minor=extra_left, discounted_minor=taken,",
        "                    extras_minor=extras, discounted_minor=taken,  # PLANTED",
        "a discount larger than the time charge is not taken off the extra before the "
        "fill rule raises it",
    ),
    "F51/fill-before-discount-loads": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "plan.py",
        "        if fills and sorted(tail) != sorted(fills):",
        "        if False:  # PLANTED: the fill rule may come before a discount",
        "a plan that raises first and discounts after loads, so a flat discount costs "
        "the customer more than the cheaper order",
    ),
    "F55/stated-order-charged": (
        "tests/test_f55_a_discount_and_the_fill_rule_charge_the_cheapest_order.py",
        "engine.py",
        "    total, at, split, seq = min(rows, key=lambda r: r[0])"
        "  # min() keeps the first of a tie",
        "    total, at, split, seq = rows[0]  # PLANTED: the stated order, whatever it costs",
        "the plan's order is charged even where another order is cheaper for the driver",
    ),
    "F55/never-raised-first": (
        "tests/test_f55_a_discount_and_the_fill_rule_charge_the_cheapest_order.py",
        "engine.py",
        "            places += [(0, TIME_FIRST), (k, PER_PART)] + [",
        "            places += [(k, PER_PART)] + [  # PLANTED: never raised first",
        "the fill rule is never priced first, so a cent of rounding lands on the driver",
    ),
    "F55/never-per-part": (
        "tests/test_f55_a_discount_and_the_fill_rule_charge_the_cheapest_order.py",
        "engine.py",
        "            places += [(0, TIME_FIRST), (k, PER_PART)] + [",
        "            places += [(0, TIME_FIRST)] + [  # PLANTED: no per-part split",
        "a discount is never shared between the parts, so the raised extra carries none of it",
    ),
    "F55/tie-not-first": (
        "tests/test_f55_a_discount_and_the_fill_rule_charge_the_cheapest_order.py",
        "engine.py",
        "    total, at, split, seq = min(rows, key=lambda r: r[0])"
        "  # min() keeps the first of a tie",
        "    total, at, split, seq = min(reversed(rows), key=lambda r: r[0])"
        "  # PLANTED: last of a tie",
        "a tie charges the last order rather than the first the contract names",
    ),
    "F55/share-rounds-against-driver": (
        "tests/test_f55_a_discount_and_the_fill_rule_charge_the_cheapest_order.py",
        "engine.py",
        "        extra_off = min(extras, -(-taken * extras // whole))",
        "        extra_off = min(extras, taken * extras // whole)  # PLANTED: rounded down",
        "the raised extra's share of a discount rounds down, a cent on the driver",
    ),
    "F51/figure-unchecked": (
        "tests/test_f51_the_fill_rule_prices_on_the_garage_at_entry.py",
        "engine.py",
        "    if figure is not None and (",
        "    if False and (  # PLANTED: the stay's figure is taken as it arrives",
        "an occupancy figure that is negative, over 100%, a string or a bool reaches "
        "the rule instead of being refused at the door",
    ),
    "F52/running-total-taken": (
        "tests/test_f52_a_vip_surcharge_may_be_a_percent.py",
        "engine.py",
        '                {"time_charge_minor": time_charge}',
        '                {"time_charge_minor": ledger.total_minor}  # PLANTED',
        "a percent surcharge is taken of the running total, so two surcharges total "
        "differently depending on which runs first",
    ),
    "F52/uncapped-charge-taken": (
        "tests/test_f52_a_vip_surcharge_may_be_a_percent.py",
        "engine.py",
        "        if stage == SURCHARGE:",
        "        if stage == CAP:  # PLANTED: the time charge is read before the caps",
        "a percent VIP surcharge is a percent of the UNcapped time, so a long VIP stay "
        "pays a percent of money the driver is not charged",
    ),
    "F52/rounding-ignored": (
        "tests/test_f52_a_vip_surcharge_may_be_a_percent.py",
        "rules/space_surcharge.py",
        '    amount = percent_of_minor(time_charge_minor, percent_bp, rule.params["rounding"])',
        '    amount = percent_of_minor(time_charge_minor, percent_bp, "up")  # PLANTED',
        "a percent surcharge rounds up whatever the rule states",
    ),
    "F53/axis-missing": (
        "tests/test_f53_the_validator_probes_the_occupancy_axis.py",
        "validator.py",
        "    if not thresholds:\n        return [None]",
        "    if True:  # PLANTED: no occupancy axis\n        return [None]",
        "the validator probes no occupancy figure, so two fill rules colliding near full "
        "are reported clean and a real car is then refused",
    ),
    "F53/no-figure-probed": (
        "tests/test_f53_the_validator_probes_the_occupancy_axis.py",
        "validator.py",
        "    return sorted(m for m in marks if 0 <= m <= FULL_BP)",
        "    return [None] + sorted(m for m in marks if 0 <= m <= FULL_BP)  # PLANTED",
        "a missing figure is probed and reported as a gap in the plan, so every plan "
        "with a fill rule carries a finding and a plan store refuses all of them",
    ),
    "F53/probe-figure-dropped": (
        "tests/test_f53_the_validator_probes_the_occupancy_axis.py",
        "validator.py",
        "            if stay.occupancy_at_entry_bp is not None:\n"
        "                found_by += (stay.occupancy_at_entry_bp,)",
        "            if False:  # PLANTED: the probe's figure is dropped\n"
        "                found_by += (stay.occupancy_at_entry_bp,)",
        "a fill-rule finding names the car's entry and exit but not how full the garage "
        "was, which is the only thing that made it collide",
    ),
    # The owner's two answers. "Omitted" is planted as a DEFAULT, which is the
    # defect: a plan that never answered priced as if it had. "Flipped" is planted
    # as the answer ignored both ways, and the engine forgetting who priced the
    # time, and the extra measured as the whole running total.
    "F54/specials-defaulted": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        "    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)",
        '    raw = {"raises_specials": "yes", **raw}  # PLANTED: an unanswered rule defaults\n'
        "    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)",
        "a fill rule that never said whether it raises specials loads and raises them",
    ),
    "F54/vip-extra-defaulted": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        "    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)",
        '    raw = {"raises_vip_extra": "no", **raw}  # PLANTED: an unanswered rule defaults\n'
        "    rule_id, space_classes = common_fields(raw, plan_space_classes, where, EXTRA)",
        "a fill rule that never said whether it raises the VIP extra loads and does not",
    ),
    "F54/answer-not-a-word": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        "        if raw[switch] not in ANSWERS:",
        "        if False:  # PLANTED: any value is taken as an answer",
        "an answer that is neither yes nor no -- 1, \"true\", null -- loads and is read "
        "as no",
    ),
    "F54/specials-always-raised": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        '    if priced_by_special is not None and not rule.params["raises_specials"]:',
        "    if False:  # PLANTED: specials raised whatever the owner said",
        "a charge a special priced is raised although the owner said specials are not",
    ),
    "F54/specials-never-raised": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        '    if priced_by_special is not None and not rule.params["raises_specials"]:',
        "    if priced_by_special is not None:  # PLANTED: specials never raised",
        "a charge a special priced is left unraised although the owner said raise it",
    ),
    # Re-anchored in F63, when the special that prices a pass became the pass's
    # own base. The defect is unchanged.
    "F54/special-not-told": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "engine.py",
        "    priced_by_special = base if by_a_special else None",
        "    priced_by_special = None  # PLANTED: the fill rule is never told a special priced",
        "the engine forgets that a special priced the time, so 'do not raise specials' "
        "raises them anyway",
    ),
    "F54/vip-extra-ignored": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        '    if extras_minor and rule.params["raises_vip_extra"]:',
        "    if False:  # PLANTED: the extra is never raised",
        "the VIP extra stays as set although the owner said raise it",
    ),
    "F54/vip-extra-always-raised": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "rules/fill_level.py",
        '    if extras_minor and rule.params["raises_vip_extra"]:',
        "    if extras_minor:  # PLANTED: the extra raised whatever the owner said",
        "the VIP extra is raised although the owner said leave it",
    ),
    "F54/extra-is-the-whole-total": (
        "tests/test_f54_the_owner_says_what_the_fill_rule_raises.py",
        "engine.py",
        "            extras = ledger.total_minor - time_charge",
        "            extras = ledger.total_minor  # PLANTED: the time counted as extra",
        "'raise the VIP extra' raises the whole running total, so the time is raised twice",
    ),
    # The caps' boundaries. The first two arms put back the shipped defect, a
    # period the car is in for no time counting as a period; the third counts a
    # day past the end of a week; the fourth caps a week by the weekly max
    # alone, which is how two weeks were charged for seven days and an hour.
    #
    # Re-anchored when each day became capped on its own (F59): the days are
    # found by cutting the stay in `daily_max.days_of`, and a week's days by
    # `daily_max.pieces`, rather than by counting dates. THE PLANTED DEFECTS ARE
    # UNCHANGED -- the exit's own date counted, a day starting at the week's end
    # counted in it. By the hour such a day holds no time and charges nothing,
    # so these show on the line (over 2 days) and on a flat price, where the
    # count of days is the ceiling.
    "F56/exit-date-counted": (
        "tests/test_f56_a_cap_counts_only_the_time_the_car_is_in.py",
        "rules/daily_max.py",
        "            if start >= exit_at:",
        "            if start > exit_at:  # PLANTED: the exit's own date",
        "an exit at exactly midnight counts the new date, so fifteen hours on Monday "
        "are two days, and a flat price is allowed two daily caps for no time on Tuesday",
    ),
    "F56/week-start-at-exit-counted": (
        "tests/test_f56_a_cap_counts_only_the_time_the_car_is_in.py",
        "rules/weekly_max.py",
        "            if boundary >= exit_at:",
        "            if boundary > exit_at:  # PLANTED: a week start at the exit counts",
        "an exit at exactly the start of a calendar week counts that week, so a "
        "Monday-to-Monday stay is two weeks and a flat price pays the weekly max twice",
    ),
    "F56/rolling-day-past-the-week": (
        "tests/test_f56_a_cap_counts_only_the_time_the_car_is_in.py",
        "rules/daily_max.py",
        "        if not (day_start < end and day_end > start):",
        "        if not (day_start <= end and day_end > start):  # PLANTED: a day past the week",
        "a week ending where a day starts counts that day too, so a flat price's "
        "two-day first week is allowed three daily caps",
    ),
    "F56/week-by-weekly-max-alone": (
        "tests/test_f56_a_cap_counts_only_the_time_the_car_is_in.py",
        "rules/weekly_max.py",
        '                ceiling = min(ceiling, day_rule.params["max_minor"] * count)',
        "                pass  # PLANTED: a week is capped by the weekly max alone",
        "a week holding one day of a flat price is allowed the whole weekly max, so "
        "seven days and an hour pay 100 twice instead of 100 + 30",
    ),
    # Each day capped on its own (F59, decided 2026-10-16). The first arm is the
    # whole-stay cap that shipped; the rest each break one part of splitting the
    # charge by the day or the week, or what the caps are told about the base.
    # Re-anchored when the days began to be tallied rather than listed (F61):
    # the ceiling is the tally's total. THE PLANTED DEFECT IS UNCHANGED.
    "F59/whole-stay-capped": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "rules/daily_max.py",
        "        ceiling = amounts.total",
        "        ceiling = most * caps  # PLANTED: the max times the days touched",
        "the whole stay is capped at the max times the days it touches, so fifteen "
        "minutes past midnight unlock a second 30.00 for Monday's hours: 60, not 34",
    ),
    "F59/day-charged-from-entry": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "rules/daily_max.py",
        "    before = 0 if start == stay.entry_at else charged_by(_minutes_into(stay, start))",
        "    before = 0  # PLANTED: every day charged from entry",
        "each day is charged everything since entry, so Tuesday's fifteen minutes "
        "carry Monday's hours and are capped at 30.00 too",
    ),
    "F59/day-is-24-hours": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "rules/daily_max.py",
        "        yield datetime.combine(day, time(0), tzinfo=plan.timezone).astimezone(UTC)",
        "        yield datetime.combine(  # PLANTED: a day ends 24 hours after its midnight\n"
        "            day - ONE_DAY, time(0), tzinfo=plan.timezone\n"
        "        ).astimezone(UTC) + ONE_DAY",
        "a calendar day is cut 24 hours after the last midnight, so on a 23- or "
        "25-hour day the next day starts an hour early or late and is charged for it",
    ),
    "F59/week-ignores-the-daily-max": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "rules/weekly_max.py",
        "                charged = min(charged, sum(by_day))",
        "                pass  # PLANTED: the week ignores the daily max",
        "a week pays its time up to the weekly max with its days uncapped, so a "
        "week holding two full days pays 100.00 instead of 60.00",
    ),
    "F59/week-allowed-the-whole-max": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "rules/weekly_max.py",
        '            ceiling = min(rule.params["max_minor"], charged)',
        '            ceiling = rule.params["max_minor"]  # PLANTED: a week may cost the whole max',
        "a week holding one hour is allowed the whole weekly max, so the time in it "
        "is not what it pays",
    ),
    # Re-anchored in F63, when `_charged_by` began to be handed the pass's base.
    # The defect is unchanged: the caps are told the time-based rate, or nothing.
    "F59/base-is-the-time-based-rate": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "engine.py",
        "    accrual = RULE_ACCRUALS[base.type]\n",
        "    # PLANTED: the caps are always told the time-based rate\n"
        "    base = next(iter(_qualifying(plan, stay, ACCUMULATE)), None)\n"
        "    if base is None:\n"
        "        return None\n"
        "    accrual = RULE_ACCRUALS[base.type]\n",
        "the caps are told how the time-based rate would have charged even when a "
        "special priced the stay, so a weekend rate is capped as if it were one price",
    ),
    "F59/accrual-not-checked": (
        "tests/test_f59_a_daily_max_caps_each_day_on_its_own.py",
        "engine.py",
        "    if charged_by is not None and charged_by(stay.duration_minutes) != base_minor:",
        "    if False:  # PLANTED: what a base says it charged is not checked",
        "a base whose accrual disagrees with its own lines is capped on the wrong "
        "figure and the quote goes on",
    ),
    # A long stay in a short one's memory (F61). The first two arms put back the
    # two things that made a quote's memory grow with the stay: every minute the
    # base was asked about remembered, and every day of the stay listed. The
    # third walks each week's days from entry, which prices right and makes the
    # work grow with the square of the stay. The fourth spells out every run.
    "F61/charges-remembered": (
        "tests/test_f61_a_long_stay_is_priced_in_the_memory_of_a_short_one.py",
        "rules/increment.py",
        "    @lru_cache(maxsize=CHARGES_REMEMBERED)",
        "    @lru_cache(maxsize=None)  # PLANTED: every minute asked about is kept",
        "the base remembers every minute a cap asks it about, so a quote's memory "
        "grows with the days in the stay",
    ),
    "F61/days-listed": (
        "tests/test_f61_a_long_stay_is_priced_in_the_memory_of_a_short_one.py",
        "rules/daily_max.py",
        "    caps = days_covered(rule, stay, plan)",
        "    caps = len(list(days_of(rule, stay, plan)))  # PLANTED: every day listed",
        "the cap lists every day of the stay to count them, so a quote's memory "
        "grows with the days in the stay",
    ),
    "F61/week-walks-from-entry": (
        "tests/test_f61_a_long_stay_is_priced_in_the_memory_of_a_short_one.py",
        "rules/daily_max.py",
        "    for day_start, day_end in days_of(rule, stay, plan, after=start):",
        "    for day_start, day_end in days_of(rule, stay, plan):  # PLANTED: from entry\n"
        "        if day_end <= start:\n"
        "            continue",
        "each week's days are found by walking from entry, so the fee is right and "
        "the work grows with the square of the stay",
    ),
    # The day holding a week's start is found from its date and checked against
    # the day starts both ways. Up: a date a zone lived twice (Juneau, 1867).
    # Down: a clock that skips over midnight, which the test builds as a zone.
    "F61/day-guess-not-checked-up": (
        "tests/test_f61_a_long_stay_is_priced_in_the_memory_of_a_short_one.py",
        "rules/daily_max.py",
        "    while _start_of_day(rule, stay, plan, index + 1) <= instant:\n"
        "        index += 1\n",
        "    pass  # PLANTED: a day guessed too early is not moved on\n",
        "where a date happens twice, an instant on its second pass is put in the day "
        "before, so a week is cut from the wrong day",
    ),
    "F61/day-guess-not-checked-down": (
        "tests/test_f61_a_long_stay_is_priced_in_the_memory_of_a_short_one.py",
        "rules/daily_max.py",
        "    while index > 0 and _start_of_day(rule, stay, plan, index) > instant:\n"
        "        index -= 1\n",
        "    pass  # PLANTED: a day guessed too late is not moved back\n",
        "where a clock skips over midnight, the first instants of the new date are put "
        "in a day that has not started",
    ),
    "F61/every-run-spelled-out": (
        "tests/test_f61_a_long_stay_is_priced_in_the_memory_of_a_short_one.py",
        "rules/daily_max.py",
        "RUNS_SPELLED_OUT = 20",
        "RUNS_SPELLED_OUT = 10**9  # PLANTED: every run spelled out",
        "a cap's line spells out every run of equal amounts, so a long stay whose "
        "days alternate has a line as long as the stay",
    ),
    # The longest stay priced (F62, decided 2026-10-16): 90 days. The first arm
    # removes the limit; the second refuses 90 days itself; the third asks it
    # only after the stay is priced, which brings back the cost it bounds (the
    # tests stop the walk at a budget, so the arm is red in a moment); the
    # fourth copies the number instead of reading the constant; the fifth stops
    # publishing it; the sixth refuses with the plan's code instead of its own.
    "F62/no-limit": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "engine.py",
        "    if stay.duration_minutes <= limit:\n        return None\n",
        "    return None  # PLANTED: no stay is too long\n",
        "a stay of any length is priced, so a caller hands the engine ten thousand "
        "years and a thread walks them for as long as the caps take",
    ),
    "F62/90-days-refused": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "engine.py",
        "    if stay.duration_minutes <= limit:\n",
        "    if stay.duration_minutes < limit:  # PLANTED: 90 days itself refused\n",
        "a stay of exactly 90 days, which the decision prices, is refused",
    ),
    # Re-anchored in F64 (`quote` asks once which rules qualify); the defect is
    # unchanged.
    "F62/after-the-work": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "engine.py",
        "    too_long = _longer_than_priced(stay)\n"
        "    if too_long is not None:\n"
        "        # First of all, before a plan is read or a day walked (F62).\n"
        "        raise Refused([too_long])\n"
        "    plan = select_plan(plans, stay)\n"
        "    # Which rules qualify, asked once for the whole quote (`_Qualified`).\n"
        "    qualified = _Qualified(plan, stay)\n"
        "\n"
        "    blocking = find_gaps(plan, stay, qualified) + find_conflicts(plan, stay, qualified)\n"
        "    if blocking:\n"
        "        raise Refused(blocking)\n"
        "\n"
        "    ledger = _the_cheapest_way(plan, stay, qualified)\n",
        "    plan = select_plan(plans, stay)  # PLANTED: the limit asked after the work\n"
        "    qualified = _Qualified(plan, stay)\n"
        "\n"
        "    blocking = find_gaps(plan, stay, qualified) + find_conflicts(plan, stay, qualified)\n"
        "    if blocking:\n"
        "        raise Refused(blocking)\n"
        "\n"
        "    ledger = _the_cheapest_way(plan, stay, qualified)\n"
        "    too_long = _longer_than_priced(stay)\n"
        "    if too_long is not None:\n"
        "        raise Refused([too_long])\n",
        "the stay is refused for its length only after it has been priced, so ten "
        "thousand years are walked a day at a time before the refusal comes",
    ),
    "F62/limit-copied": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "engine.py",
        "    limit = max_stay_minutes()\n",
        "    limit = 129600  # PLANTED: a copy of the number, not the constant\n",
        "the limit is a second copy of the number, so changing the one constant "
        "changes what is published and not what is refused",
    ),
    "F62/not-published": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "contract.py",
        '        "max_stay_minutes": max_stay_minutes(),\n',
        "        # PLANTED: the limit is not published\n",
        "`validate-plan` no longer answers the limit, so a rate setup cannot show the "
        "owner which stays will need an operator",
    ),
    "F62/cli-not-told": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "cli.py",
        "    print(limit)\n",
        "    pass  # PLANTED: the limit is not shown beside the findings\n",
        "`rate-engine validate-plan` lists a plan's findings and not the longest stay "
        "priced, so an owner checking rates with a gap open is not told the limit",
    ),
    "F62/wrong-code": (
        "tests/test_f62_a_stay_longer_than_90_days_is_refused_before_any_work.py",
        "engine.py",
        "        code=GAP_STAY_LONGER_THAN_MAX_STAY,\n",
        "        code=GAP_STAY_EXCEEDS_MAX_DURATION,  # PLANTED: the plan's code\n",
        "the engine's limit is refused under the plan's own ceiling code, so a door "
        "routing on codes tells the owner to change a rule no rule can change",
    ),
    # The cheapest price always wins (F63, decided 2026-10-16), comparing whole-stay
    # alternatives (2026-10-17). The first five arms each break one part of the
    # flat special's rule, against the one test that holds it: the whole special
    # owed and capped on the day of entry (the reading the 10-17 decision
    # corrects, which made the full weekend 30.00); a flat price no cap holds; a
    # special charged over a cheaper hour; a special that covers a stay past its
    # exit limit; and the 90-day limit taken out. The rest compare the ways on
    # what the rules charge rather than on the fee, let the stated order choose
    # between specials, drop the whole stay from the losing line, and name a tie
    # at one fee by rule id alone.
    #
    # Retired: F63/flat-capped-at-the-max-times-the-days. Its plant, a flat
    # special as one price capped at the max times the days the car is in, is
    # now the decided behaviour; F63/flat-owed-at-entry is its inverse.
    "F63/flat-owed-at-entry": (
        "tests/test_f63_the_cheapest_price_always_wins.py::test_all_weekend_pays_50",
        "rules/time_window.py",
        '        return increment.charged_by(effect["rate"], rule.id, plan.currency)\n'
        "    return None\n",
        '        return increment.charged_by(effect["rate"], rule.id, plan.currency)\n'
        '    if effect["kind"] == "flat":  # PLANTED: owed and capped on the day of entry\n'
        '        return lambda minutes, price=effect["price_minor"]: price\n'
        "    return None\n",
        "a 50.00 Friday-to-Sunday flat with a 30.00 daily max is owed in full on the "
        "Friday and capped there, so the whole weekend pays 30.00, not 50.00",
    ),
    "F63/one-price-not-capped": (
        "tests/test_f63_the_cheapest_price_always_wins.py::test_saturday_only_pays_30",
        "rules/daily_max.py",
        "        ceiling = most * caps\n",
        "        ceiling = max(running_total_minor, most * caps)  # PLANTED: never capped\n",
        "a flat special is one price that no daily max holds, so with no time-based "
        "rate in the plan a Saturday alone pays 50.00, not the day's 30.00",
    ),
    "F63/special-over-a-cheaper-hour": (
        "tests/test_f63_the_cheapest_price_always_wins.py::"
        "test_a_stay_inside_the_span_whose_normal_price_is_lower_pays_the_normal_price",
        "engine.py",
        "    if time_fee < special_fee:",
        "    if False:  # PLANTED: the special is charged over a cheaper hour",
        "a two-hour Saturday stay inside the weekend flat's span pays the flat held "
        "to the day's max, 30.00, where by the hour it is 12.00",
    ),
    "F63/covered-past-its-limit": (
        "tests/test_f63_the_cheapest_price_always_wins.py::"
        "test_a_stay_that_starts_inside_the_span_and_runs_past_it_is_priced_by_the_hour",
        "rules/time_window.py",
        "    exit_side = _exit_failure(rule, entry_local, exit_local)\n",
        "    exit_side = None  # PLANTED: a stay past the exit limit is still covered\n",
        "a stay that leaves an hour after the weekend flat's 20:00 limit is still "
        "given the flat, 50.00, where the time-based rate prices it at 60.00",
    ),
    "F63/no-limit": (
        "tests/test_f63_the_cheapest_price_always_wins.py::"
        "test_the_90_day_limit_comes_before_any_special",
        "engine.py",
        "    if stay.duration_minutes <= limit:\n        return None\n",
        "    return None  # PLANTED: no stay is too long\n",
        "a stay a minute past 90 days is priced by the cheapest special instead of "
        "refused for its length",
    ),
    "F63/rules-own-charges-decide": (
        "tests/test_f63_the_cheapest_price_always_wins.py",
        "engine.py",
        "    return (compared.fees[rule.id], compared.own[rule.id], named)\n",
        "    return (compared.own[rule.id], compared.fees[rule.id], named)  # PLANTED\n",
        "two ways are compared on what the rules charge, so where a cap makes the "
        "dearer rule the cheaper stay, the driver pays the dearer stay",
    ),
    "F63/stated-order-decides": (
        "tests/test_f63_the_cheapest_price_always_wins.py",
        "engine.py",
        '        named = settings["order"].index(rule.id)\n',
        '        return (settings["order"].index(rule.id),)  # PLANTED: the order chooses\n',
        "under `stated_order` the first rule named is charged, the dearer included",
    ),
    "F63/whole-stay-not-said": (
        "tests/test_f63_the_cheapest_price_always_wins.py",
        "engine.py",
        "    if own[winner.id] >= own[rule.id]:\n",
        "    if False:  # PLANTED: the losing line does not say what the stay comes to\n",
        "the line says the 123.50 front-loaded rate applied instead of a 96.00 "
        "weekend rate, and not that its stay comes to 42.00 -- a receipt that reads "
        "backwards",
    ),
    "F63/tie-named-by-id-alone": (
        "tests/test_f63_the_cheapest_price_always_wins.py",
        "engine.py",
        "    return (compared.fees[rule.id], compared.own[rule.id], named)\n",
        "    return (compared.fees[rule.id], named)  # PLANTED: a tie named by id alone\n",
        "two ways a cap brings to one fee are named by rule id, so the receipt names "
        "the 50.00 flat where the 40.00 one charged less itself",
    ),
    # The work budget (F64). The first arm puts back what the review measured:
    # every lookup asks the stage's rules again and finds the rule by comparing
    # whole rules. The second finds it by comparing whole rules alone; the third
    # asks a special that did not qualify for its line on every pass. The fourth
    # runs the time budget on its own against the first, so the budget is shown
    # to be a measurement too, not only the counters.
    "F64": (
        "tests/test_f64_a_quote_prices_each_way_once_and_asks_nothing_per_pair.py",
        "engine.py",
        "        return rule.id in ids\n",
        "        return rule in _qualifying(self._plan, self._stay, rule.stage)  # PLANTED\n",
        "every pass asks each rule again whether it qualifies and finds it by "
        "comparing whole rules, so the work of a quote grows with the cube of its "
        "ways: 800 any-day specials take tens of seconds a stay",
    ),
    "F64/compared-whole": (
        "tests/test_f64_a_quote_prices_each_way_once_and_asks_nothing_per_pair.py",
        "engine.py",
        "        return rule.id in ids\n",
        "        return rule in self._at[rule.stage]  # PLANTED: found by comparing whole rules\n",
        "a rule is found among those that qualify by comparing it with each of them "
        "field by field, so every pass does work in the square of the ways",
    ),
    "F64/why-not-every-pass": (
        "tests/test_f64_a_quote_prices_each_way_once_and_asks_nothing_per_pair.py",
        "engine.py",
        "        if rule.id not in self._why_not:\n",
        "        if True:  # PLANTED: a special that did not qualify is asked on every pass\n",
        "a special that did not qualify is asked for its line again on every pass, "
        "so beside 400 ways each is asked 401 times, once a pass",
    ),
    "F64/time-budget": (
        "tests/test_f64_a_quote_prices_each_way_once_and_asks_nothing_per_pair.py::"
        "test_400_qualifying_specials_are_priced_within_a_fixed_time_budget",
        "engine.py",
        "        return rule.id in ids\n",
        "        return rule in _qualifying(self._plan, self._stay, rule.stage)  # PLANTED\n",
        "the time budget alone does not see a quote whose work grows with the cube "
        "of its ways",
    ),
    # And the special against the time-based rate under `stated_order` (F50,
    # F63): the early return the old comparison made for that mode, put back.
    # The planted call passes `qualified` since F64; the defect is unchanged.
    "F50/stated-order-replaces": (
        "tests/test_f50_the_cheaper_way_is_charged.py",
        "engine.py",
        "    if time_fee < special_fee:\n",
        '    if plan.resolution[QUALIFY]["mode"] == "stated_order":  # PLANTED\n'
        "        return _priced(plan, stay, special, qualified, compared)\n"
        "    if time_fee < special_fee:\n",
        "under `stated_order` a qualifying special replaces the time-based charge "
        "whatever it costs, so a 9.00 early bird is charged against 7.00 by the hour",
    ),
    # A percent discount can never exceed 100% (F60, decided 2026-10-16).
    "F60/over-100-loads": (
        "tests/test_f60_a_percent_discount_is_at_most_100_percent.py",
        "rules/time_window.py",
        '    if amount["percent_bp"] > WHOLE_FEE_BP:',
        "    if False:  # PLANTED: a discount over 100% loads",
        "a 150% discount loads and validates clean, and every stay it takes below "
        "zero is refused at the counter after the plan was saved",
    ),
    "F60/100-refused": (
        "tests/test_f60_a_percent_discount_is_at_most_100_percent.py",
        "rules/time_window.py",
        '    if amount["percent_bp"] > WHOLE_FEE_BP:',
        '    if amount["percent_bp"] >= WHOLE_FEE_BP:  # PLANTED: 100% refused too',
        "a 100% discount, a free stay the owner may well mean, is refused",
    ),
    "F60/no-code": (
        "tests/test_f60_a_percent_discount_is_at_most_100_percent.py",
        "rules/time_window.py",
        "            code=INVALID_PERCENT_DISCOUNT_OVER_100,",
        "            code=None,  # PLANTED: refused with no code",
        "the plan is refused with a sentence and no code, so a plan store has "
        "nothing to route on",
    ),
    "F60/code-not-sent": (
        "tests/test_f60_a_percent_discount_is_at_most_100_percent.py",
        "contract.py",
        "    if code is not None:\n        body[\"code\"] = code",
        "    if False:  # PLANTED: the code is not sent\n        body[\"code\"] = code",
        "the refusal carries its code inside the engine and every door drops it",
    ),
    "F60/increase-bounded-too": (
        "tests/test_f60_a_percent_discount_is_at_most_100_percent.py",
        "rules/time_window.py",
        '    if direction != "discount" or amount["kind"] != "percent":',
        '    if amount["kind"] != "percent":  # PLANTED: an increase over 100% refused too',
        "a percent increase over 100% is refused as if it were a discount, which "
        "the decision did not ask for",
    ),
    # Fixed amounts in full, and the floor once at the end of the adjustments.
    # The first arm puts back the per-step limit that made a price depend on
    # the order the specials were listed in; the second takes the floor away;
    # the third floors a total that was already below zero before the
    # adjustments, which hides a fault F21 names.
    "F57/limited-per-step": (
        "tests/test_f57_a_fixed_discount_takes_off_at_most_the_charge.py",
        "rules/time_window.py",
        '    if amount["kind"] == "fixed":\n        return amount["minor"]',
        '    if amount["kind"] == "fixed":\n        if effect["direction"] == "discount":'
        '\n            return max(0, min(amount["minor"], running_total_minor))  # PLANTED'
        '\n        return amount["minor"]',
        "a fixed discount is limited to the charge running when it is taken, so 5 off "
        "listed before 4 added on a stay of 3 charges 4, and the other way round 2",
    ),
    "F57/no-floor": (
        "tests/test_f57_a_fixed_discount_takes_off_at_most_the_charge.py",
        "engine.py",
        "        if running < floor:",
        "        if False:  # PLANTED: the floor is gone",
        "a stay cheaper than its discount goes below zero and is refused instead of "
        "priced at zero",
    ),
    "F57/percent-on-negative": (
        "tests/test_f57_a_fixed_discount_takes_off_at_most_the_charge.py",
        "rules/time_window.py",
        "    return max(0, running_total_minor)",
        "    return running_total_minor  # PLANTED: a percentage of a total below zero",
        "a percent discount worked out on a total below zero adds money, and a "
        "percent increase takes it off",
    ),
    "F35/cheapest-order-not-taken": (
        "tests/test_f35_the_adjust_order_is_stated.py",
        "engine.py",
        "        return [list(seq) for seq in itertools.permutations(applying)]",
        "        return [list(applying)]  # PLANTED: the stated order is the only one priced",
        "the specials are taken in the plan's order only, so the same specials cost "
        "more or less by the order they were listed in",
    ),
    "F35/one-arrangement-beyond-five": (
        "tests/test_f35_the_adjust_order_is_stated.py",
        "engine.py",
        "        for arrangement in itertools.permutations(present)\n",
        "        for arrangement in [tuple(present)]  # PLANTED: one arrangement of the kinds\n",
        "beyond five specials only one arrangement of their kinds is priced, so the "
        "car can pay more than the plan's own order would charge",
    ),
    "F35/idle-rules-priced-per-order": (
        "tests/test_f35_the_adjust_order_is_stated.py",
        "engine.py",
        "            total = run(seq[:at] + [fill] + seq[at:], split)[1]",
        "            total = run(full(seq, at), split)[1]  # PLANTED: every rule, every order",
        "every rule of the plan, applying or not, is run again for each order and "
        "each place of the fill rule tried, so a plan full of specials that do not "
        "apply slows every exit",
    ),
    "F35/no-search-budget": (
        "tests/test_f35_the_adjust_order_is_stated.py",
        "engine.py",
        "        if cost > qualified.search_left:",
        "        if False:  # PLANTED: the search has no budget",
        "every way searches every order again whatever the quote has spent, so a "
        "plan with many flat specials applying, five specials and the fill rule "
        "takes many seconds a quote",
    ),
    "F57/floor-hides-a-fault": (
        "tests/test_f21_a_refusal_names_its_own_cause.py",
        "engine.py",
        "        floor = min(0, total_minor)",
        "        floor = 0  # PLANTED: a total already below zero is floored too",
        "a total a rule had already taken below zero before the adjustments is "
        "floored to zero, so the fault is priced at nothing instead of refused by its "
        "own code",
    ),
    "F58/negative-length-read": (
        "tests/test_f58_a_body_is_read_within_a_bound.py",
        "service.py",
        "        if length < 0:",
        "        if False:  # PLANTED: a negative length is read to the end",
        "a negative Content-Length is read to the end of the connection, so a caller "
        "that keeps it open holds a server thread and gets no answer",
    ),
    "F58/no-socket-timeout": (
        "tests/test_f58_a_body_is_read_within_a_bound.py",
        "service.py",
        "    timeout = SOCKET_TIMEOUT_SECONDS",
        "    timeout = None  # PLANTED: no socket timeout",
        "a connection has no socket timeout, so a caller that stops part-way through "
        "a body holds its thread for as long as it keeps the connection open",
    ),
}


#: The set of control ids, pinned. `main` fails a guarantee left with NO arm, and
#: nothing else looked at the arms: deleting one arm of a guarantee that has
#: several -- the arm that caught the defect the others cannot see -- left every
#: check green. This file is the record, and `--pin` compares the two as SETS by
#: equality, both directions. Adding or removing a control is therefore a change
#: to this file too, made in the same commit, where a reviewer sees it.
PIN = ROOT / "scripts" / "fail_controls.ids"


def pinned_ids() -> set[str]:
    lines = PIN.read_text().splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}


def pin_mismatch(ids: set[str], pinned: set[str]) -> tuple[list[str], list[str]]:
    """(pinned but gone from CONTROLS, in CONTROLS but not pinned)."""
    return sorted(pinned - ids), sorted(ids - pinned)


def check_pin() -> int:
    gone, unpinned = pin_mismatch(set(CONTROLS), pinned_ids())
    if gone:
        print(f"PINNED CONTROLS MISSING from CONTROLS: {', '.join(gone)}")
    if unpinned:
        print(f"controls not in {PIN.relative_to(ROOT)}: {', '.join(unpinned)}")
    if gone or unpinned:
        print(
            "\nThe control set and its pin disagree. A removed arm is a guarantee "
            "measured less than it was; a new one is recorded in the pin in the "
            "same commit."
        )
        return 1
    print(f"all {len(CONTROLS)} control ids match {PIN.relative_to(ROOT)}.")
    return 0


def check_anchors() -> int:
    """Count every anchor. Zero or two is a dead control, and it is silent."""
    bad = 0
    for gid, (_target, path, anchor, _to, _why) in sorted(CONTROLS.items()):
        source = resolve(path).read_text()
        count = source.count(anchor)
        status = "ok" if count == 1 else "DEAD"
        if count != 1:
            bad += 1
        print(f"  {status:4}  {gid}  {path}  anchor appears {count}x")
    if bad:
        print(
            f"\n{bad} control(s) have no live anchor. An anchor that matches zero times "
            "plants nothing, and the control then reports green against unmodified "
            "source. Fix the anchors before trusting any result from this script."
        )
        return 1
    print(f"\nall {len(CONTROLS)} anchors live.")
    return 0


def run_control(gid: str) -> bool:
    target, path, anchor, replacement, why = CONTROLS[gid]
    print(f"\n=== {gid} — {GUARANTEES[guarantee_of(gid)]}")
    print(f"    plant: {path}")
    print(f"    breaks: {why}")

    green = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if green.returncode != 0:
        print(f"    UNMEASURED: {target} is already failing before anything was planted.")
        print(green.stdout[-1500:])
        return False

    with planted(path, anchor, replacement):
        red = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    tail = [ln for ln in red.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    summary = red.stdout.strip().splitlines()[-1] if red.stdout.strip() else ""
    if red.returncode == 0:
        print(f"    NOT A CONTROL: {target} stayed GREEN with its subject broken.")
        return False
    print(f"    RED, as required — {summary}")
    for line in tail[:6]:
        print(f"      {line}")
    return True


def main(argv: list[str]) -> int:
    if "--anchors" in argv:
        return check_anchors()
    if "--pin" in argv:
        return check_pin()

    # An argument selects a control id exactly, or a guarantee id and then every
    # arm of it -- `F6b` has to keep meaning "F6b", not "no such control".
    named = [a for a in argv if not a.startswith("-")]
    wanted = [c for c in sorted(CONTROLS) if c in named or guarantee_of(c) in named]
    unknown = [
        a for a in named
        if a not in CONTROLS and a not in {guarantee_of(c) for c in CONTROLS}
    ]
    if unknown:
        print(f"no such control: {', '.join(unknown)}")
        return 2
    wanted = wanted or sorted(CONTROLS)

    missing = sorted(set(GUARANTEES) - {guarantee_of(c) for c in CONTROLS})
    if missing:
        print(
            f"registered guarantees with no fail-control: {', '.join(missing)}. "
            "Every guarantee is proven able to fail, or it is not a guarantee."
        )
        return 1

    if check_pin() or check_anchors():
        return 1

    results = {gid: run_control(gid) for gid in wanted}
    dead = [gid for gid, ok in results.items() if not ok]
    print(f"\n{len(results) - len(dead)}/{len(results)} controls fired.")
    if dead:
        print(f"DEAD CONTROLS: {', '.join(dead)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
