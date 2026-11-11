"""The canonical registry of this module's guarantees. ONE source, three consumers.

    conftest.py       requires every id below to have RUN in the session
    docs/CONTRACT.md  is generated from this table
    test_f*.py        each declares its id with @pytest.mark.guarantee

Why a registry rather than a list of module names: a guard can name the test
MODULES that may not vanish, in a tuple somebody has to remember to update, and
match skip allowances by SUBSTRING. Both shapes are
ones this project's own rules forbid elsewhere -- a hard-coded list cannot notice
something added to what it is supposed to cover, and a substring match is not a
structural guarantee. So neither shape is used here:
ids are declared on the marks, collected from the run, and compared as a
SET against this table by equality. A guarantee test that stops being collected
-- because its module failed to import, because a file was renamed, because
somebody deleted it -- leaves an id unaccounted for and the run fails naming it.

An allowance is an explicit id in RATE_ENGINE_ALLOW_UNRUN, matched exactly. This
module has no optional dependency and no weights, so there is nothing it can
legitimately skip, and CI names no allowance at all: the variable exists so that
the escape hatch is a decision somebody writes down rather than a green build.
"""

from __future__ import annotations

#: id -> the promise the test proves, in the words the contract publishes.
GUARANTEES: dict[str, str] = {
    "F1": (
        "The engine never guesses. A stay the plan cannot price is REFUSED, naming "
        "the gap, and no number is returned."
    ),
    "F2": (
        "A special rate is all-conditions-or-nothing: miss one condition by a minute "
        "and it does not apply at all -- no pro-rating and no partial credit. "
        "Enforced per rule type; `time_window` is the only special this module "
        "ships, so the property is proven of it rather than of a populated stage."
    ),
    "F3": (
        "The plan version in force at ENTRY prices the whole stay. A rate change "
        "mid-stay never splits it."
    ),
    "F4": (
        "Money is an integer of minor units. A float, a bool or a Decimal anywhere in "
        "a plan is refused at load."
    ),
    "F4b": (
        "That sentence is true at EVERY leaf of a plan, not at the fields the engine "
        "happens to read -- proven by probing every position in the document, so a "
        "field added in a later round is covered the day it exists."
    ),
    "F5": (
        "Determinism. The same plan version and the same stay produce the same fee "
        "AND the same breakdown, always, on any machine and at any wall-clock time."
    ),
    "F6": (
        "The test function IS the production path. `/v1/quote` and the CLI emit the "
        "same response bytes for the same request, from one code path and one "
        "encoder; the CLI's terminal newline is written outside the payload."
    ),
    "F7": (
        "Registering a new rule type changes no existing plan's answer -- fee and "
        "breakdown byte-identical."
    ),
    "F8": (
        "The fee is the sum of the breakdown's deltas, by construction. There is no "
        "second route to the total."
    ),
    "F8b": (
        "A rule's only channel to the fee is a list of Lines. A malformed return is "
        "REFUSED by name, not left to crash inside the ledger."
    ),
    "F10": (
        "Plan selection is never ambiguous. Two versions in force at the same instant "
        "are REFUSED and both named, never resolved by the order of the caller's list."
    ),
    "F15": (
        "`increment.rounding` is CONSULTED by the applier, which refuses a mode it "
        "does not implement rather than pricing the stay under a different one. The "
        "applier checks what it implements, never what the loader accepts."
    ),
    "F12": (
        "`validate-plan` separates the findings an owner has still to look at from the "
        "ones they have recorded a decision for. Every finding is reported either way."
    ),
    "F9": (
        "The published contract is DERIVED, never transcribed. Every generated block "
        "matches the code, and every block that ASSERTS something about its values is "
        "proven to move when those values contradict it."
    ),
    "F13": (
        "The fixture corpus holds a case either side of every threshold the rules "
        "branch on, read out of the plans rather than from a list -- so no guarantee "
        "is proven against a corpus that could only ever exercise one branch."
    ),
    "F14": (
        "A registered guarantee whose test stops running turns the build RED, "
        "including when its module fails to import; and a test module that plants a "
        "defect but registers no guarantee is refused."
    ),
    "F16": (
        "Every refusal reaches the caller AS a refusal. A malformed number anywhere "
        "in a plan comes back as a named 400 naming the field, and a malformed rule "
        "return as a named 422 -- never as an exception escaping the quote contract, "
        "and never as a dropped connection."
    ),
    "F17": (
        "A rendered amount uses its own currency's ISO 4217 minor-unit exponent, "
        "never an assumed two decimal places -- and a code whose exponent this "
        "module does not know is REFUSED at load rather than rendered on a guess."
    ),
    "F17b": (
        "That refusal is at LOAD, so an unrenderable currency never reaches the "
        "renderer at all -- the membership check and the exponent read one table."
    ),
    "F18": (
        "A wall-clock limit is compared at the granularity it is written and "
        "rendered in: the stay is truncated to the minute, so no breakdown line can "
        "say a time is after itself."
    ),
    "F18b": (
        "And the LIMIT is refused rather than truncated. A plan may state 'HH:MM'; "
        "anything finer is rejected at load, because rounding it would silently "
        "discard a pricing decision the operator wrote."
    ),
    "F19": (
        "`validate-plan` probes every boundary the plan DECLARES -- entry limits and "
        "exit limits as well as durations, each side of each -- so a conflict the "
        "engine would refuse is one the owner was shown before the plan went live."
    ),
    "F20": (
        "There are TWO time roundings and both are declared: a part-minute is a whole "
        "minute (assumed, module-wide) and minutes into periods is stated per rule. "
        "Every comparison against a duration reads the same rounded value."
    ),
    "F21": (
        "A refusal's CODE names the cause that actually occurred. A negative total "
        "is CONFLICT_NEGATIVE_TOTAL, not the multi-rule conflict code it borrowed."
    ),
    "F6b": (
        "And there is exactly ONE encoder. No surface re-implements the response "
        "bytes, so the two doors cannot drift the way they silently did."
    ),
    "F6c": (
        "The CLI's payload is the route's payload BYTE FOR BYTE, with any terminal "
        "newline written outside it -- compared as bytes, never as decoded objects."
    ),
    "F22": (
        "Whether a non-qualifying rule appears in the breakdown depends on its STAGE: "
        "a QUALIFY rule always speaks, at delta zero; a rule at another stage that "
        "does not cover the stay is silent."
    ),
    "F22b": (
        "And the stage is not the whole answer. A rule TYPE may declare that it "
        "speaks when it did not qualify, so a weekend discount declining because it "
        "is a Tuesday says so on the receipt -- while a rule that was never about "
        "this space stays silent whatever it declared."
    ),
    "F22c": (
        "A special for another space class charges nothing. A QUALIFY rule that does "
        "not cover the stay's class did not qualify, whatever its times, so it adds "
        "no money and gets its not-applied line at zero, naming the class as the "
        "reason -- never a time for a special the stay could never get; the fee is "
        "what the plan without it charges."
    ),
    "F23": (
        "The production invariant that the fee IS the ledger's sum is itself "
        "guarded: deleting it, no-opping it or unwiring it from the pricing path "
        "turns the suite red."
    ),
    "F24": (
        "A zero-length stay pays the first period -- a decision, published in the "
        "contract with the divergence it was disclosed with, not left for an "
        "integrator to discover as an anomaly."
    ),
    "F25": (
        "Whether a time window may run past midnight is stated by the PLAN, in "
        "`day_span`, with no default -- the engine holds no day condition of its own. "
        "`day_span` also says WHERE the exit limit falls: under a bounded span it is "
        "`exit_by` on the entry date plus the span, so a limit past midnight is a "
        "moment rather than a clock reading. `any_span` names no last day and keeps "
        "the clock reading."
    ),
    "F26": (
        "A window applies on the days the PLAN states -- weekday names, or the "
        "garage's own dates for a holiday or an event -- matched against the "
        "ENTRY's local date, and a window that did not match names the day that "
        "failed and the days it wanted. There is no built-in calendar and no "
        "preset: 'weekend' means different days in different countries."
    ),
    "F27": (
        "`enter_from` is CONSULTED, not merely validated and stored. A window "
        "states BOTH ends of its entry range, which is what makes an evening rate "
        "expressible, and a stay arriving one minute before it opens does not "
        "qualify."
    ),
    "F28": (
        "`day_span` `next_day` is BOUNDED: an exit on the following local day "
        "qualifies and one the day after that does not, where `any_span` accepts "
        "both. Proven on one stay, so the three spans are an axis rather than "
        "three unrelated scenarios."
    ),
    "F29": (
        "A `rate` effect is priced by `increment`'s own builder and applier, not "
        "by a copy of them: identical parameters produce identical lines on the "
        "same stay, and a change to `increment`'s period counting moves the "
        "window's lines with it."
    ),
    "F30": (
        "An `adjust` effect applies to the fee AFTER the caps and the surcharges. "
        "A percentage taken any earlier is a percentage of a number the customer "
        "is not being charged."
    ),
    "F31": (
        "An `adjust` percentage is integer basis points and its `rounding` is "
        "CONSULTED: the same stay under `up` and under `down` differs by one minor "
        "unit, and when the amount was rounded the breakdown line says which way "
        "it went; when the division was exact there is no rounding clause to state."
    ),
    "F32": (
        "`grace` is TERMINAL, and free means free: a stay at or under the stated "
        "minutes costs zero and picks up no surcharge, no cap and no adjustment. "
        "Terminality is DECLARED by the rule type at registration -- the engine "
        "never knows its name -- and a special it beat says so on the receipt."
    ),
    "F33": (
        "Two caps on one stay leave the LOWER ceiling standing, the total after CAP "
        "is the same in both application orders, and the breakdown names both. Caps "
        "COMPOSE; two of them are not a conflict."
    ),
    "F34": (
        "More than one rule qualifying at one stage means three different things, "
        "and the stage's category decides which: RESOLVING is settled by the plan's "
        "resolution mode (one rule applies, a tie included -- F48), COMPOSING "
        "order-independent is not reported at all, and COMPOSING order-dependent is "
        "refused unless the plan states the order."
    ),
    "F35": (
        "Two qualifying ADJUST rules with no stated `adjust_order` are REFUSED "
        "naming both. With an order, the car pays the cheapest order of the "
        "specials that apply (20% off then a fixed amount is not the same fee as "
        "the fixed amount then 20% off): up to five applying, every order is "
        "priced; beyond five, every arrangement of their kinds, each kind kept "
        "together (at most 24), so the order the plan lists them in never moves "
        "the price, and the orders tried for each way are bounded; the whole quote "
        "has a budget of single pricings, past which a way takes the specials in rule "
        "id order and its receipt says so. One line says which order. Only "
        "the specials that apply are priced per order; where the order changes "
        "nothing the plan's own order is the receipt's."
    ),
    "F36": (
        "The resolution modes decide which rule is NAMED, never the money. Two "
        "windows qualifying on one stay are charged the cheaper under either mode "
        "(F63); where they charge the same, `cheapest_wins` names the lowest rule id "
        "and `stated_order` the first in its order, on the SAME stay, and reversing "
        "the order reverses the name -- and the rules that lost still appear, each "
        "naming the winner, both prices and the mode."
    ),
    "F38": (
        "Every identifier the published documents name in backticks is one the "
        "code actually holds -- rule types, stages, finding codes, plan and rule "
        "fields, stated values, traits and guarantee ids -- and every file path "
        "they point at exists. Derived from both documents rather than from a "
        "list of the sentences somebody remembered to check."
    ),
    "F37": (
        "A `stated_order` must name every rule at its stage EXACTLY ONCE, and one "
        "that does not is refused at LOAD, naming what is missing. A rule left out "
        "would take a silent position, and array position deciding money is what "
        "this module refuses everywhere else."
    ),
    "F39": (
        "A window's exit limit runs to the day its `day_span` allows. Under a "
        "bounded span the limit is `exit_by` on the entry date plus the span, so "
        "an evening window with an after-midnight limit applies to the car that "
        "leaves the SAME evening as well as the one that leaves after midnight. "
        "A limit that would have to WRAP to be reached is refused at load under "
        "`same_day` and `any_span`, neither of which can say what day it falls on."
    ),
    "F40": (
        "A window's exit limit is compared as WALL-CLOCK readings, never as two "
        "instants, so a window behaves the same on the night the clocks change. "
        "On the hour that occurs twice at a fall-back, two stays leaving at the "
        "same stated time an hour apart in real time both qualify; a limit at a "
        "wall time that a spring-forward skips entirely still reads, and a stay "
        "past it is still refused."
    ),
    "F41": (
        "A tax rounds the way its rule states: `rounding` is required, with no "
        "default, and is one of `up`, `down` and `nearest`, where `nearest` takes "
        "EXACTLY half up, decided in integers on the exact remainder. Each mode is "
        "asserted on figures where it differs from the others, the exact half "
        "included, and when the amount was rounded the line shows the unrounded "
        "figure and which way it went; when the division was exact there is no "
        "rounding clause to state."
    ),
    "F42": (
        "Taxes never compound. Every rule in a set is a percentage of the same "
        "`subtotal_minor` -- the money actually paid -- and never of a total that "
        "already includes another tax line. A rule cannot state a base at all: the "
        "key is refused as the unknown key it is, and so is a flat amount."
    ),
    "F43": (
        "The tax set in force is chosen by the instant: the latest set taking "
        "effect at or before it, whatever order the sets arrive in. A new set is "
        "how a rate changes, a tax is added and a tax is repealed. An instant "
        "before every set is REFUSED, never taxed at zero, and two sets taking "
        "effect at the same instant are refused at load, both named."
    ),
    "F44": (
        "Taxes come out in the `sequence` each rule states, never in the order the "
        "list arrived in. A rule with no `sequence`, or two rules in one set "
        "sharing one, is refused at load."
    ),
    "F45": (
        "Tax on nothing is nothing. A subtotal of zero produces no tax lines, and "
        "the same rules on a positive subtotal produce them. A negative subtotal, "
        "or one that is not an integer of minor units, is refused."
    ),
    "F46": (
        "A tax set is judged by the loader and nowhere else. `/v1/validate-tax-sets` "
        "and `rate-engine validate-tax-sets` hand it to `load_tax_sets` and answer "
        "what it answers: every refusal it makes reaches both surfaces as the same "
        "named refusal, byte for byte, and what it loads is valid from both -- so a "
        "caller that stores only what this door accepted stores nothing the engine "
        "will refuse when it computes the tax."
    ),
    "F47": (
        "A tax figure is reached the same way from both surfaces. `/v1/tax` and "
        "`rate-engine tax` hand the request to one function, which calls `tax_lines` "
        "and writes its lines as a breakdown's are written, with their total: the "
        "same status and the same bytes from both, for a figure, a refusal and a "
        "request that cannot be read."
    ),
    "F48": (
        "A tie at the cheapest charge is PRICED, not refused. Two rules qualifying at "
        "one resolving stage and charging the same amount under `cheapest_wins` "
        "validate clean; the stay is priced at that amount, the lowest rule id is "
        "named as applied, and every other says it charged the same. A cheaper rule "
        "still wins whatever its id. Replaces F11, which refused the tie."
    ),
    "F49": (
        "Every `validate-plan` finding names the stay that found it: `probe`, the "
        "entry and exit of the first probe stay that produced it, and that stay "
        "produces it. A refusal at quote time carries no `probe` key."
    ),
    "F50": (
        "Under either resolution mode a special that qualifies is never dearer than "
        "the time-based rate: the stay is priced through the whole pipeline both ways "
        "-- with the special, and by the time-based rate alone -- and charged the "
        "lower, a tie keeping the special. The breakdown says which way was used and "
        "what the other would have charged (`compared_minor`). Grace still prices a "
        "stay alone, `stated_order` no longer lets a dearer special replace the "
        "time-based charge (F63), and a "
        "stay the time-based rate alone cannot price is priced by the special. When "
        "the time-based rate is charged, every other special still has its line, as "
        "on the special's way: its own reason, or that it qualified and a cheaper "
        "special was compared instead -- never that one was applied."
    ),
    "F51": (
        "A fill rule prices on how full the garage was AT ENTRY. It applies at its "
        "threshold and above and not one basis point below; it raises the charge for "
        "the time -- the total after the base and the caps, less any discount taken "
        "before it -- and nothing else, and a plan ordering it before another ADJUST "
        "rule does not load; its "
        "line says how full the garage was and by how much the charge rose, and below "
        "the threshold says it was not raised. A stay in a class it covers with no "
        "figure is refused with GAP_NO_OCCUPANCY_AT_ENTRY; a plan without one prices "
        "the same with or without the figure. Two fill rules applying to one stay are "
        "CONFLICT_OVERLAPPING_FILL_RULES whatever `adjust_order` says. A threshold, a "
        "percent or a figure out of range, not a whole number, or a bool is refused "
        "by name."
    ),
    "F52": (
        "A VIP surcharge may be a percent of the stay's time-based charge -- the "
        "total after the base and the caps -- rounded the way the rule says, and "
        "never of another surcharge, so two surcharges total the same in any order. "
        "The flat form prices exactly as it did. A rule stating both forms, or a "
        "percent out of range, is refused by name."
    ),
    "F53": (
        "`validate-plan` probes the occupancy axis of every fill rule: one basis "
        "point below each threshold, on it, and at 100% full, across every other "
        "axis, so two fill rules colliding only when the garage is full are reported "
        "before a stay is refused for it, and the finding names the figure that found "
        "it. A plan with no fill rule is probed exactly as before, and a missing "
        "figure is not reported as a gap in the plan."
    ),
    "F54": (
        "A fill rule states the owner's two answers, `raises_specials` and "
        "`raises_vip_extra`, each \"yes\" or \"no\", and a rule that omits either or "
        "states anything else does not load, naming the field. `raises_specials` "
        "no leaves a charge a special priced unraised and says so; yes raises it. "
        "`raises_vip_extra` yes raises the space-class extra by the same percent on "
        "its own line; no leaves it as set. All four combinations, on each side of "
        "the threshold, price to the cent worked by hand, and flipping one answer "
        "moves the fee by exactly what that answer governs."
    ),
    "F55": (
        "Where a discount and a fill rule both apply, the driver pays the CHEAPEST "
        "order, to the cent after rounding: the discounts first and the fill rule on "
        "what is left; the fill rule first; the discounts first with each part (time "
        "charge, space-class extra) carrying its share; and the fill rule between "
        "the specials that apply (between any two up to five, between kinds beyond). "
        "The plan's stated order does not decide the price. A tie charges "
        "the first of those, and one line says which order was charged and what the "
        "others would have charged. Every pair of the owner's two answers, a percent "
        "and a flat discount, each side of the threshold, prices to the cent worked "
        "by hand."
    ),
    "F56": (
        "A cap counts only the days and weeks the car is in for more than zero time: "
        "an exit at exactly local midnight, at a 24-hour mark or at the start of a "
        "week adds no day or week, and one minute past it does. A week holds only its "
        "own days, so it costs no more than the daily max for the days the car is in "
        "it: at 30 a day and 100 a week, seven days and an hour is 100 + 4 by the "
        "hour and 100 + 30 for a flat price, not 100 twice. The two caps still "
        "compose in either order."
    ),
    "F57": (
        "A fixed discount and a fixed increase are each taken in full, so fixed "
        "amounts commute: 5 off and 4 added on a stay of 3 is 2 either way. A total "
        "the adjustments take below zero is brought back to zero once, after all "
        "of them, by its own line (adjust.floor), so a stay cheaper than its "
        "discount is priced at zero, not refused. A percentage is never worked out "
        "on a total below zero. A total already below zero before the adjustments "
        "is not floored (F21). The 150% discount no longer loads (F60)."
    ),
    "F58": (
        "The HTTP door reads a request body only within a bound. A negative "
        "Content-Length is a named 400 rather than a read to the end of the "
        "connection, and every connection carries a socket timeout, so a caller that "
        "stops part-way through a body is disconnected rather than holding a thread."
    ),
    "F59": (
        "A daily max caps each day on its own (decided 2026-10-16: per calendar day). "
        "The stay is cut at each local midnight, or each 24 hours from entry under "
        "`rolling_24h`, and each day pays the time charged in it or the max, whichever "
        "is less: at 8 the first hour, 4 an hour after and 30 a day, Monday 09:00 to "
        "Tuesday 00:15 is 30 + 4 = 34, not 60. A period is charged on the day it "
        "starts, the rate does not start again at midnight, a day with a clock change "
        "is one day, and a day the car is in for no time adds nothing. A weekly max "
        "caps each of the plan's weeks the same way, after the daily max for each of "
        "its days. The caps compose in either order, the answer is the same on every "
        "run and in every server zone, and no fee is higher than the max times the "
        "days touched. A flat special, one price for the stay it covers, is capped "
        "as one price at the max times the days the car is in (F63), as is a rule "
        "type that does not say how its charge builds up. What a base says it "
        "charged is checked against its lines on every quote."
    ),
    "F60": (
        "A percent discount can never exceed 100%. A `time_window` discount whose "
        "`percent_bp` is above 10000 does not load: `validate-plan`, `quote` and the "
        "HTTP door answer 400 with the code INVALID_PERCENT_DISCOUNT_OVER_100 beside "
        "a sentence naming the field, so no plan carrying one is saved and no stay is "
        "priced on it. 10000 loads and makes the stay free. A percent increase over "
        "100% still loads, a fixed discount larger than the charge is F57's, and "
        "every other load refusal carries no code."
    ),
    "F61": (
        "A long stay is priced in the memory of a short one. A cap finds the stay's "
        "days and weeks as it walks them and lists none of them, each day's or week's "
        "amount goes into a running tally, the base remembers only its last few "
        "answers, and a cap's line spells out a bounded number of runs of equal "
        "amounts, then says how many more there were and what they came to. The work "
        "still grows with the stay, by a step a day: ten years take ten times the work "
        "of one, and a century no more a day than a year. The engine refuses a stay "
        "longer than 90 days before any of this work (F62); these are measured with "
        "that limit lifted, so they hold for the caps whatever it is set to."
    ),
    "F62": (
        "The longest stay the engine prices is 90 days of 24 hours, entry to exit "
        "(decided 2026-10-16). Exactly 90 days is priced; 90 days and one second is "
        "REFUSED with GAP_STAY_LONGER_THAN_MAX_STAY, a 422 naming the limit, at every "
        "door -- before the plan is read, before a day of the stay is walked and "
        "before a base is asked what it charged, so a stay of about ten thousand "
        "years is refused with no more work than one of 90 days and a second. It is "
        "elapsed time, so a clock change does not move it. The limit is one constant, "
        "`MAX_STAY_DAYS`, read at every use, and `validate-plan` answers it as "
        "`max_stay_minutes` for a rate setup to show."
    ),
    "F63": (
        "The cheapest price always wins (decided 2026-10-16): where more than one "
        "price could apply to the same time, the car pays the cheapest, and whole-stay "
        "alternatives are compared (2026-10-17). A flat special is one price for the "
        "stay it covers, held to the max for each day and week the car is in, and is "
        "compared with the time-based rate's whole stay, each calendar day capped by "
        "the daily max and each week by the weekly max: with a 50 Friday-to-Sunday "
        "flat, a 30 daily max and an hourly rate that reaches 30 within a day, "
        "Saturday only is 30 and Friday 18:00 to Sunday 18:00 is 50. A stay past a "
        "special's exit limit is not covered by it. Two specials, or two time-based "
        "rates, are compared on the whole fee, caps and all -- a rate of 100 the "
        "first hour and 0.50 after beats one of 2 an hour over two days at 30 a day, "
        "42 against 60 -- and the losing line gives both figures where the rules' own "
        "prices do not say why. Under `stated_order` the cheapest way is charged too, "
        "the time-based rate included. On every stay swept, the fee is the least of "
        "the fees each way charges on its own. Additive rules are not made a choice: "
        "a surcharge and a fixed increase are still added in full."
    ),
    "F64": (
        "A quote prices each way once, and asks nothing again per way or per pair. "
        "With N ways that qualify -- specials and time-based rates -- the stay goes "
        "through the pipeline N + 1 times (once, with one way), which is F63 itself. "
        "Beside that, each rule is asked once a quote whether it qualifies, a rule is "
        "found by its id and two rules are never compared field by field, a special "
        "that did not qualify is asked for its line once, and a way at most three "
        "times. 400 qualifying specials beside 400 that do not, on a 90-day stay with "
        "a daily and a weekly max, are priced within a fixed time budget. No limit is "
        "set on the rules a plan may hold or the ways a stay may have."
    ),
    "F12b": (
        "A decision is an ACKNOWLEDGEMENT, not a price. A stay hitting a SETTLED gap is "
        "refused exactly as one hitting an outstanding gap is; no entry in `decisions[]` "
        "can cause a fee to be produced."
    ),
}

#: Environment variable naming ids this job cannot run. Exact ids, comma
#: separated. Empty everywhere in CI on purpose.
ALLOW_ENV = "RATE_ENGINE_ALLOW_UNRUN"
