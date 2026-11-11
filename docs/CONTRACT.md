# The rate engine contract

Version 6. One contract, five surfaces: `POST /v1/quote`, `POST
/v1/validate-plan`, `POST /v1/validate-tax-sets`, `POST /v1/tax`, and the
`rate-engine` CLI, which carries the same four operations. Our own platform is an ordinary
client of it — there is no private path and no in-process shortcut, so if this
interface is inadequate we find out before an integrator does.

**This module calculates. It takes no payment, holds no card, and stores
nothing.** A plan arrives on the call and is gone when the response is written.

<!--gen:schema_version kind=1-->
`schema_version` **6**
<!--/gen:schema_version-->

## Versioning, and the unknown key

This contract is versioned on the assumption that it will **gain fields**. A
commercial module's contract moves because businesses change, so consumers must
tolerate new fields appearing in a response.

The rule runs the other way for requests, and it is what makes the assumption
safe: **a key this engine does not understand is REJECTED and named, never
ignored.** An operator who adds a key to a plan running on a version that has no
rule for it would otherwise have a garage pricing something wrong and a document
saying it does not.

### What changed in version 6

**A fill rule states two answers the owner gives, and a rule without them does
not load** -- that is a plan that loaded on version 5 and does not load here, so
the number moved. `raises_specials` says whether a charge a special priced is
raised too; `raises_vip_extra` says whether the extra for the stay's space class
is raised by the same percent. Both are required, each `yes` or `no` -- words,
because no bool appears anywhere in a plan (see "Money") -- and there is no
default: the engine does not decide for the owner what the rule
raises (F54). Plans with no fill rule load and price exactly as on version 5.

**A discount and a fill rule: the cheapest order.** Where both apply, every order
is priced and the cheapest charged, to the cent after rounding (F55); the line
`fill_level.order` says which. A plan whose `adjust_order` puts a fill rule
before another ADJUST rule does not load. Version 6 had not been released when
this was settled, so it is part of version 6, not a version 7.

**What a caller must do.** Add both answers to every fill rule, and list every
fill rule last in `adjust_order`. A consumer
reading breakdown lines meets three new line codes, `fill_level.special_not_raised`,
`fill_level.extra_raised` and `fill_level.order`; no finding code was added.

**A daily max caps each day on its own, and a weekly max each week (F59).** The
garage owner's decision, 2026-10-16: the daily max is per calendar day. The stay
is cut at each local midnight -- or every 24 hours from entry under
`rolling_24h`, which stays the plan's choice -- and each day pays the time
charged in it, or the daily max where that is less. A day the car is in for no
time adds nothing. A weekly max caps each of the plan's weeks the same way, by
the week it already states (`calendar_week` from `week_starts_on`, or
`rolling_7d`), after the daily max for each of the week's days. At 8 the first
hour, 4 an hour after and 30 a day, Monday 09:00 to Tuesday 00:15 was 60 -- the
max times the two days it touched -- and is 30 + 4 = 34; at 100 a week, seven
days and an hour is 100 + 4. A time-based rate charges a period on the day the
period starts, and does not start again at midnight, so those fifteen minutes
are the stay's sixteenth hour at 4, not a new first hour at 8. A 23- or 25-hour
day is one day. A flat special is one price for the stay it covers, so it is
not split by the day: it is held, as before, to the max times the days the car
is in, and compared whole with the time-based rate (F63, below). This only
lowers a fee. The cap lines
list what each day or week paid when one paid less than the max; no line code
or finding code was added. A rule type that prices the time now says, when it
registers, how its charge builds up over the stay, and the engine checks that
against its lines on every quote; a type that says nothing is capped as one
price for the stay.

**A long stay is priced in the memory of a short one (F61).** Because each day
is capped on its own, a cap walks the stay a day at a time, so the time a quote
takes grows with the number of days in the stay. The memory it takes does not:
no list of the stay's days or weeks is kept. A cap's line lists what each day or
week paid up to a bounded number of runs, then says how many more there were and
what they came to. The longest stay priced is 90 days, and a longer one is
refused before any of this work (F62, below).

**The longest stay priced is 90 days (F62).** The garage owner's decision,
2026-10-16. A stay longer than 90 days of 24 hours, entry to exit, is refused
with a new gap code, `GAP_STAY_LONGER_THAN_MAX_STAY`: a 422 like every refusal,
so a door that closes a stay unpriced on a refusal closes this one unpriced, and
an operator prices it. Exactly 90 days is priced; one second more is not. The
limit is checked before the plan is read and before a day of the stay is walked,
so ten thousand years are refused as fast as 90 days and a second, and no quote
walks more than 90 days -- capping each day on its own made a quote's work grow
with the days in the stay. It is one constant, `MAX_STAY_DAYS`, and `validate-plan`
answers it as `max_stay_minutes` beside the findings, so a rate setup can show
it; `validate-plan` never reports the code, which is not a gap in any plan. See
"The longest stay priced" below. **What a caller must do.** Treat the new code as
the refusal it is: a consumer routing on finding codes meets one it has not seen.
Version 6 had not been released, so it is part of version 6.

**The cheapest price always wins (F63).** The garage owner's rule, 2026-10-16:
when more than one price could apply to the same time, the car pays the
cheapest; and, 2026-10-17, what is compared is the whole stay each way would
charge. Two places changed, and each only lowers a fee:

- Two specials, or two time-based rates, that qualify for one stay are compared
  on the whole FEE -- each priced through every stage, caps, surcharges and
  adjustments included -- not on what the rules themselves charge. Over two
  days, a rate of 100 the first hour and 0.50 an hour after charges 123.50 and
  one of 2 an hour 96; at 30 a day they come to 42 and 60. The first is
  charged, and the losing rule's line gives both figures.
- `stated_order` no longer charges a dearer rule. Under either mode the cheapest
  way is charged, the time-based rate included; the stated order names one of
  two ways that charge the same, as `cheapest_wins` names the lowest rule id. A
  stay a special qualified for under it gains the `special_used` or
  `time_based_used` line.

**A flat special is one price for the stay it covers**, as before. A daily or
weekly max does not split it by the day: it holds it to the max for each day and
week the car is in, and the engine charges the cheaper of it and the normal
price for the same stay, each calendar day capped by the daily max and each week
by the weekly max. With a 50 Friday-to-Sunday flat, a 30 daily max and an hourly
rate that reaches 30 within a day, Saturday only is 30, and Friday 18:00 to
Sunday 18:00 is 50, where by the hour it is 28 + 30 + 30 = 88. The stay a special
covers is the stay it qualifies for: a window is all of its conditions or
nothing, so a stay that runs past a special's exit limit is priced by the
time-based rate, as before.

Not changed, because nothing there is a choice between prices: a surcharge, a
fixed increase and a tax are added; the caps already leave the lowest ceiling
standing, whatever the kinds of day and week; and the ADJUST rules all apply, in
the plan's stated order, except the fill rule, whose place was already the
cheapest (F55). A rule type that says nothing about how its charge builds up is
still capped as one price for the stay, at the max times the days and weeks the
car is in: the engine cannot know where its charge fell. **What a caller must
do.** Nothing, to keep quoting: every plan that loaded loads. A stay may cost
less, and a consumer reading `resolved` lines meets a clause giving what the
stay comes to by each rule, where the rules' own prices do not say why one lost.

**A quote prices each way once (F64).** Because the cheapest price wins, a stay
with N ways that qualify -- specials and time-based rates -- is priced through
every stage N + 1 times: once for each way's fee, and once more for the
receipt. With one way it is priced once. Nothing else is repeated per way. Each
rule is asked once a quote whether it qualifies, a rule is found by its id
rather than by comparing it with the others, a special that did not qualify is
asked for its line once, and a way at most three times. So a quote's work grows
with its ways, times the plan's rules and the days in the stay, which are at
most 90. No limit is set on the rules a plan may hold or the ways a stay may
have. **What a caller must do.** Nothing.

**A percent discount over 100% does not load (F60).** A `time_window` discount
whose `percent_bp` is above 10000 is refused when the plan is loaded, so
`validate-plan`, `quote` and every door answer 400, and the answer carries
`code`, `INVALID_PERCENT_DISCOUNT_OVER_100`, after `error`. It is the one load
refusal with a code, because the rule is that every place a plan is
saved refuses it, and a plan store routes on a code. A refusal without one is
the bytes it was. 100% loads and makes the stay free; a percent increase is not
bounded by this, and a fixed discount larger than the charge loads as below.
That is a plan that loaded and does not load here, and version 6 had not been
released, so it is part of version 6. A caller with stored plans should look
for such a discount before upgrading: the plan will not load.

**Three corrections that move a fee, with no change to the plan document.** A
cap no longer counts a day or a week the car is in for no time: an exit at
exactly local midnight, at a 24-hour mark or at the start of a week adds no day
or week. A week holds only its own days, so it costs no more than the daily
max for the days the car is in it (F56). These two only lower a fee. Fixed
discounts and fixed increases are each taken in full, and a total the
adjustments take below zero is brought back to zero once, after all of them,
by a new line, `adjust.floor` (F57), so a stay cheaper than its discount is
priced at zero, not refused. Fixed amounts commute: at 3 an hour, 5 off and
4 added on a one-hour stay is 2 either way. A percentage is never worked out
on a total below zero: there it is a percentage of nothing. And where a
percentage is among the specials that apply, the car pays the cheapest order
of them, as it already did for a discount and the fill rule (F35): with up to
five specials applying at once every order is priced, and beyond that every
arrangement of their kinds, each kind kept together, as the line
`adjust.order` says; the order a plan lists them in never moves the price.
Before rounding and above zero, some order that keeps each kind together is
always the cheapest; beyond five, rounding and the zero floor can leave
another order cheaper -- measured, by up to a few cents of rounding on
ordinary percentages, more on very large ones, and by over a dollar where a
fixed discount meets the zero floor. Up to five these lower a fee or leave it
as it was. The search has a budget for the whole quote: at most 40,000 single
pricings of the specials (one order, one place of the fill rule). The answer for
a set of inputs is found once a quote, and a way met after the budget is spent
takes the specials in rule id order and the fill rule last; its receipt then
says the limit was reached (`adjust.budget`). Five specials, the fill rule, 300
specials that do not apply and 400 flat specials that do quote in about a
second and a half on a laptop. Which way a fee moves, as said here, holds for every
plan that loads: the percentage discount over 100% that could move a fee
either way no longer loads (F60). The weekly cap's line says more in its text,
three line codes were added (`adjust.floor`, `adjust.order`, `adjust.budget`),
and no finding code was added. On the HTTP door, a negative
Content-Length is a 400 and a connection that stops sending is closed after a timeout (F58).

**A special for another space class charges nothing (F22c).** A special is
asked for its line whether it qualified or not, and a `time_window` or a
`grace` scoped to one space class did not ask the stay's class when it was. So
a stay of another class that met every time it states was told the special
"applied": a window added its price beside the time-based rate -- at 8 the first
hour and 4 an hour after, with a 30 flat for VIP spaces, two hours in a standard
space was 42, not 12 -- and a grace told the stay it was free on a receipt that
charged it. Such a special now gets its not-applied line, at zero, saying the
stay's class is not one it covers. The class is the reason whatever the times:
a special for another class that the stay also missed on a time used to give
that time, so a VIP car read that it came in too late for an early bird it could
never get, and that line now names the class too. This only lowers a fee, and
otherwise changes the words of a line at zero. No line code or finding code was
added.

### What changed in version 5

**A plan may price on how full the garage was when the car came in.** A new rule
type, `fill_level`, raises the stay's time-based charge by a stated percent when
the garage was at least a stated percent full at entry (F51). A quote request may
carry the figure as `occupancy_at_entry_bp`, an optional key: basis points of
full, 0 to 10000, absent or `null` meaning the caller has none. See "The fill
rule" below.

**A VIP surcharge may be a percent.** `space_surcharge` keeps its flat
`surcharge_minor` and gains a second form, an `amount` of kind `percent` with its
`percent_bp`, and a `rounding`: a percent of the stay's time-based charge (F52).

**`validate-plan` has a fourth axis.** A plan with a fill rule is probed one basis
point below each threshold, on it, and at 100% full; the probe a finding names
then carries `occupancy_at_entry_bp` too (F53). A plan with no fill rule is probed
exactly as before.

**What a caller must do.** Nothing, to keep quoting: every plan that loaded on
version 4 loads on version 5 and every stay it priced is priced the same, whether
or not the request carries the new key. To use a fill rule, send the figure; a
stay in a class a fill rule covers that arrives without one is refused with
`GAP_NO_OCCUPANCY_AT_ENTRY`. A consumer routing on finding codes meets that code
and `CONFLICT_OVERLAPPING_FILL_RULES`.

### What changed in version 4

**A tie at the cheapest charge is priced, and its finding code is gone.** Two
rules that qualify at QUALIFY or ACCUMULATE and charge the same amount under
`cheapest_wins` were refused as `CONFLICT_MULTIPLE_RULES_AT_STAGE`. The rule the
garage owner gave is "always cheaper goes first", and at a tie nothing is
cheaper: the driver pays that amount whichever rule is named. So the stay is
priced at that amount, the lowest rule id is named as applied, and every other
rule says it charged the same (F48, which replaces F11). With the tie gone,
nothing could produce the code, and a registered code nothing can produce is a
promise with no mechanism behind it -- so it was REMOVED, and a removal moves the
number.

**A special that qualifies is never dearer than the time-based rate.** Under
`cheapest_wins` at QUALIFY, a special that qualified used to REPLACE the
time-based charge whatever it cost: a weekday car in at 08:00 and out at 10:30
paid a 9.00 early bird where the hour came to 7.00. The rule is that the
driver always pays the cheapest way the stay can be priced, so the stay is now
priced through the whole pipeline twice -- with the special, and by the
time-based rate alone, caps, surcharges and adjustments included -- and charged
the lower; a tie keeps the special (F50). One engine line says which way was
used: `special_used` or `time_based_used`, its `rule_id` the special, delta zero,
and `compared_minor` what the other way would have charged -- absent when the
time-based rate alone cannot price the stay, in which case the special is the
only way. `stated_order` was unchanged (the special replaced; version 6 changed
that too, F63), and so is grace,
which prices a stay alone. When the time-based rate is charged, every other
special keeps its line, as on the special's way: its own reason for not
applying, or a line saying it qualified and which cheaper special was compared
-- "was the cheaper special", never "applied instead", because none was.

**`validate-plan` reads the days and times of a window at every stage.** It used
to read them at QUALIFY only. The conflict a plan can still state is two
adjustments with no order, and an adjustment's window states its days and times
exactly as a special does; two discounts colliding only before 05:30 were never
probed there (F19).

**A `validate-plan` finding names the stay that found it.** Each carries
`probe`, the `entry_at` and `exit_at` of the first probe stay that produced it, so
an owner can be told which car it was about (F49). A refusal at quote time is
unchanged: it is about the stay the caller sent, and has no `probe` key.

**What a caller must do.** A plan that loaded on version 3 loads on version 4.
A stay version 3 refused for a tie is now priced. A stay a special priced under
`cheapest_wins` is priced at the same fee or LESS, and its breakdown gains the
line above; a consumer reading breakdown lines must tolerate that line and its
`compared_minor` key, which no other line carries. A consumer routing on finding
codes stops seeing `CONFLICT_MULTIPLE_RULES_AT_STAGE`; no code was added.

### What changed in version 3

**Tax, surcharges and city fees -- the arithmetic, and only the arithmetic.**
This module now computes tax lines: a garage's taxes are percentages of the
money actually paid, and `tax_lines` turns them into breakdown lines. See "Tax,
surcharges and city fees" below.

**Nothing a plan can state changed, and `quote()` answers exactly as it did.** A
plan that loaded on version 2 loads on version 3 and prices to the identical fee
and the identical breakdown. Tax is not a stage of the pipeline and is not asked
for by `/v1/quote`: the engine never sees a validation, and tax is taken after
one. The division a percentage adjustment makes moved into one function,
`percent.py`, which a tax rule shares -- and an adjustment still offers exactly
the two roundings it offered, `up` and `down`.

**What a caller must do.** Nothing, to keep quoting. To tax: hand `tax_lines` the
subtotal after every discount and validation line, and add the lines it returns
after them, so the fee is still the running total of the ledger. A consumer
routing on finding codes meets one new code, `GAP_NO_TAX_SET_IN_FORCE`, which
only the tax functions produce.

### A door added within version 3, and why the number did not move

`POST /v1/validate-tax-sets` and `rate-engine validate-tax-sets` hand a garage's
tax sets to `load_tax_sets` and answer what it answers (F46). **The number stays
3.** The specification moves it for a change a consumer must notice: version 2 for a removal,
version 3 for the tax arithmetic and a finding code nobody routing on codes had
seen. This round is neither. The loader's rules are the ones version 3 already
published; the door adds no rule, no finding code and no field to any existing
response; and a caller that never calls it gets byte-identical answers from every
other door -- including the `schema_version` stamp, which a bump would have
changed on every quote for no change in any price. A consumer that wants the door
asks `/v1/validate-tax-sets`, and an engine that predates it answers 404.

### A second door within version 3, and why the number still did not move

`POST /v1/tax` and `rate-engine tax` compute a garage's tax lines on a subtotal
(F47). **The number stays 3, by the same test.** The door adds no rule: it calls
`tax_lines`, whose arithmetic version 3 published. It adds no finding code:
`GAP_NO_TAX_SET_IN_FORCE` is the one it can return, and version 3 published that
too. And it adds no field to any existing response. A bump would change the
`schema_version` stamp on every quote with no price changing. A caller that never
asks `/v1/tax` gets byte-identical answers from every other door, and an engine
that predates it answers 404.

**The body of every POST is read as UTF-8, and nothing else is.** This is a
correction of a leak, not a removal, and it is recorded here because it changes
what a few bodies are answered. The contract never said a body could be anything
but JSON, and JSON over HTTP is UTF-8 (RFC 8259). But the body used to go to the
parser as bytes, and the parser guesses the encoding. A UTF-16 or UTF-32 body, a
UTF-8 body behind a byte-order mark, and surrogates encoded as bytes were all
decoded and answered. A malformed byte dropped the connection with no answer at
all. Now the body is decoded strictly first. A body that does not decode is a 400
saying it is not UTF-8. One that decodes and is not JSON gets the 400 it always
got, and an empty body still gets the request's own sentence. A caller whose
layer decodes the same bytes differently from this engine would otherwise be
judged on text it never sent.

### What changed in version 2

**A rule type was REMOVED, and that is why the number moved.** `early_bird` is
gone. It was a time window with its days hardcoded to every day and its effect
hardcoded to a flat price, and it is now expressible — with the days and the
effect stated — as a `time_window`. A plan written for version 1 does not load on
version 2: an unknown rule type is rejected rather than skipped, which is the
same rule that protects an unknown key.

No operator plans exist in the wild today, so removing a rule type costs nothing
now and could not be done quietly later. It is recorded here rather than left for
somebody to discover from a refusal.

**The other changes are additions.** `time_window` carries an `effect` that is a
flat price, a completely different time-based rate, or an adjustment up or down
on the whole fee — and the third of those brought the ADJUST stage live, so a
rule type now runs at a stage that depends on the rule rather than only on its
type. The stage is still stated in every plan, and the engine refuses a plan
whose stated stage disagrees with the one the rule's own shape implies.

Two rule types arrived with it: `grace`, and `weekly_max`. And two plan fields:
every plan now states `adjust_order`, null included, and `resolution` changed
shape.

**`resolution` is keyed by the RESOLVING stages only, and its values are
objects.** It used to require an entry for all five stages, as a bare mode
string, and to be acted on by nothing. It now decides which of several qualifying
rules applies — and the three stages it could never act on are refused as keys
this version does not understand, because a mode stated for CAP cannot choose
between two caps when both of them apply.

**Two classes of plan that used to be REFUSED now price, and that is a behaviour
change rather than a bug fix nobody notices.**

More than one rule qualifying at one stage was treated as a conflict at EVERY
stage. That is right where rules compete and wrong where they compose, and it was
harmless only while no second rule type existed at a composing stage.
`weekly_max` is that second type: without the fix, every plan carrying a daily
AND a weekly cap would have refused every stay in the garage.

And at a resolving stage, two rules at different prices are now settled by the
plan's mode instead of refused. The multi-rule conflict code therefore meant
something narrower than it did: a TIE. (Version 4 prices the tie too and removes
the code; see "What changed in version 4".)

**A window that would have to wrap past midnight is REFUSED, and that is a stated
gap.** `enter_from` later than `enter_by` — "enter between 22:00 and 02:00" — is
not expressible as one rule. It is refused at load, naming the field, and the
message says to write it as two rules: one running to 23:59 and one starting at
00:00, each stating its own days. The engine will not split it, because which
days each half applies on is a pricing decision.

## Money

Money is an **integer of minor units** — 800 means 8.00. A float, a bool or a
`Decimal` is refused at **any depth of a plan**, including in fields this version
does not read; and a string where money is expected is refused with them. A rate
that cannot be expressed in minor units is a rate this module refuses, and it
refuses it at load rather than at the point the arithmetic goes wrong. JSON
exponent form (`8e2`) parses to a float and is refused with the rest.

## Time

Every plan names an **IANA timezone**, and entry and exit arrive as offset-aware
ISO 8601. A naive timestamp is refused: it would be read in whatever zone the
server happens to run in, which is a different fee on a different machine.

This is not incidental. `time_window` speaks of "enter by 09:00" and `daily_max`
speaks of a day; both are wall-clock ideas, and a local day is 23 or 25 hours
across a daylight-saving transition. `daily_max` therefore requires the plan to
state whether a day means a local `calendar_day` or a `rolling_24h` window,
because those price a Friday-night-to-Saturday-morning stay differently and the
answer is the owner's to give. Whichever it states, the stay is cut at the start
of each of its days and each day is capped on its own (F59), so a 23- or 25-hour
local day is one day, capped once.

## The longest stay priced

<!--gen:max_stay kind=1-->
`MAX_STAY_DAYS` **90**: the longest stay priced is 90 days of 24 hours from entry to exit, `max_stay_minutes` **129600**.
<!--/gen:max_stay-->

A stay one second longer is REFUSED, `GAP_STAY_LONGER_THAN_MAX_STAY`, before the
plan is read and before a day of the stay is walked (F62). It is a refusal like
any other -- 422, the code, the sentence, nothing guessed -- so a caller that
closes a stay unpriced on a refusal closes this one unpriced, for an operator to
price. The limit is elapsed time, so a clock change does not move it, and it is
the same for every plan: `validate-plan` never reports it as a gap in one, and
answers it as `max_stay_minutes` beside the findings so a rate setup can show
the owner which stays will need an operator.

## The pipeline

<!--gen:stages kind=1-->
**QUALIFY** → **ACCUMULATE** → **CAP** → **SURCHARGE** → **ADJUST**
<!--/gen:stages-->

The order is load-bearing: a cap that ran before the surcharge would cap a number
the customer is not being charged, and a surcharge applied after the cap is a
surcharge that survives it.

<!--gen:rule_types kind=2-->
| rule type | stage |
| --- | --- |
| `daily_max` | CAP |
| `fill_level` | ADJUST |
| `grace` | QUALIFY |
| `increment` | ACCUMULATE |
| `space_surcharge` | SURCHARGE |
| `time_window` | QUALIFY or ADJUST |
| `weekly_max` | CAP |

Every stage has at least one rule type in this version.
<!--/gen:rule_types-->

<!--gen:window_limits kind=2-->
| `day_span` | where the exit limit falls | an `exit_by` BEFORE `enter_from` |
| --- | --- | --- |
| `same_day` | `exit_by` on the ENTRY date | **refused at load** |
| `next_day` | `exit_by` 1 local day after the entry date | carried -- this is the ordinary evening window |
| `any_span` | nowhere -- it names no last day, so the limit stays a bare clock reading | **refused at load** |

A wrapping `exit_by` is refused at load under `same_day` and `any_span`, neither of which can say what day the limit falls on, and carried under `next_day`. Stating a bounded span gives the limit a date; writing it as two rules is the other way to say it.

**The limit this does NOT close, stated because it is a limit.** Only the window that NO stay could ever satisfy is refused. One that can fire for some entries and never for others still loads, and `validate-plan` reports it clean: `same_day` with `enter_from` 06:00, `enter_by` 23:00 and `exit_by` 20:00 is dead for every entry after 20:00 and alive for every entry before it. Both halves of that sentence were priced to write it. The engine refuses what is unsatisfiable, not what is partly unsatisfiable, because the second is a shape an operator may well mean -- and a refusal there would reject a plan that works.
<!--/gen:window_limits-->

## The plan document

Data, validated on load, never code. Every field is required and **there is no
default anywhere**, because a default is a pricing decision made by whoever wrote
the engine and applied to a garage whose owner never saw it. Where a plan is
silent, the engine refuses and names the field.

A plan states a resolution mode for each stage that can RESOLVE — QUALIFY and
ACCUMULATE — from: <!--gen:resolution kind=1-->
`cheapest_wins`, `stated_order`
<!--/gen:resolution-->. A mode stated for any other stage is
refused by name: CAP, SURCHARGE and ADJUST compose, so a mode there could never
choose anything, and a field that cannot change an answer is a decision the owner
made and the software ignored.

- `{"mode": "cheapest_wins"}` — the **lowest fee for the customer** wins, and of
  two ways that charge the same, the lowest rule id is named.
- `{"mode": "stated_order", "order": [...]}` — the lowest fee wins here too
  (F63); of two ways that charge the same, the first in the order is named. It
  must name every rule at that stage **exactly once**; a rule left out would
  take a silent position in the order.

**What is compared.** Every way the stay can be priced -- each special that
qualified, and each time-based rate that qualified where the time-based rate
alone can price the stay -- is priced through the whole pipeline, caps,
surcharges and adjustments included, and the lowest FEE is charged, under either
mode (F50, F63). A special keeps a tie with the time-based rate. Between two ways
that come to the same fee, the one whose own charge is lower is named; between
two that charge the same in both, the mode names one, and every other rule says
it charged the same (F48). Until version 6, two competing rules were compared on
what the rules themselves charged, which a cap can reverse.

`adjust_order` is a different thing and is stated separately: a list of rule ids,
or null, giving the sequence the ADJUST rules are written in. The car pays the
cheapest order of the specials that apply (F35); the stated order settles a
tie and is the receipt's order where the order changes nothing. **An order is
not a choice**, which is why it does not live in `resolution`. It is
required-and-nullable like `max_duration_minutes` and `week_starts_on` — a field
that may simply be absent is one somebody forgets while believing they set it —
and when it is stated it must name every ADJUST rule exactly once, because a rule
left out would take a silent position in the sequence.

## Gaps, conflicts, and the refusal

A **gap** is a stay the plan cannot price. A **conflict** is something the plan
leaves for the engine to decide about money -- two adjustments with no order
stated, two plan versions in force at one instant. One mechanism serves both
places it is needed: `validate-plan` reports them so an owner can decide, and at
quote time a gap is a **refusal that names what is missing**.

**More than one rule qualifying at one stage means three different things, and
the stage decides which.** This used to be one answer for all five stages, and it
was wrong in a way that only a second rule type could expose:

- **QUALIFY and ACCUMULATE resolve.** Two rules are a genuine either/or -- only
  one of them can be the price -- and the cheapest is charged (F63).
- **CAP and SURCHARGE compose, in any order.** Two caps are not a contradiction;
  they are two ceilings, and the lower one wins whichever ran first. Nothing is
  reported, because there is nothing for an owner to decide. Their lines are
  emitted in ascending rule id, never in the order the caller's array happened to
  carry them.
- **ADJUST composes, and the order changes the money.** Twenty per cent off then
  five dollars off is not five dollars off then twenty per cent off; the car pays
  the cheaper, but the plan still states an order (for a tie and the receipt),
  so two qualifying adjustments with no stated `adjust_order` are REFUSED under
  their own code -- a different question from "which of these is the price", and a
  consumer routing on codes can tell them apart.

**A TERMINAL rule is not a conflict either.** It wins outright by what its type
is, rather than by anything the plan says, so a grace period beating a weekend
rate is settled and the beaten rule gets a line saying so.

**And at a resolving stage the cheapest way is charged, every time** (F63). Two
windows that come to different fees are priced by the cheaper, under either
mode. Two that come to the SAME fee are priced at it too (version 4, F48): there
is nothing cheaper, the driver pays the same either way, and the plan's mode
names the rule on the receipt. Nothing at a resolving stage is refused any more.

**Every rule that lost is still on the receipt**, naming the winner, both prices
and the mode -- and, where the rules' own prices do not say why it lost, what
the stay comes to by each. A breakdown that silently omitted a rate the customer
nearly got could not answer the question an attendant is actually asked.

`validate-plan` probes every boundary the plan DECLARES -- each entry limit, each
exit limit, each period length and stated ceiling, either side of each, across
every space class -- rather than a written list of scenarios or a search over all
stays. That is exhaustive over what a rule can express today and is not a claim
about every possible stay; the probe axes are derived from the rules, so a rule
type qualifying on something new brings its own axis.

**Deciding a finding does not resolve it.** `decisions[]` records that an owner
has seen a gap — `validate-plan` reports it as SETTLED rather than OUTSTANDING,
so a list can be worked through — and that is all it does. A decision carries a
code and a free-text note, and a note cannot price a stay; a stay hitting a
settled gap is refused exactly as one hitting an outstanding gap is. The way to
make a gap priceable is to add a **rule** that covers it, which is a visible plan
change. See F12 and F12b.

**The engine never returns a number it had to guess.** That is this project's
standing acceptance, and in this module it is also the entire commercial
argument: a system that refuses when it is unsure can be trusted by someone who
cannot check its work.

<!--gen:findings kind=2-->
| code | kind |
| --- | --- |
| `GAP_UNDECLARED_SPACE_CLASS` | gap |
| `GAP_NO_ACCUMULATE_RULE` | gap |
| `GAP_STAY_EXCEEDS_MAX_DURATION` | gap |
| `GAP_NO_PLAN_IN_FORCE_AT_ENTRY` | gap |
| `GAP_NO_TAX_SET_IN_FORCE` | gap |
| `GAP_NO_OCCUPANCY_AT_ENTRY` | gap |
| `GAP_STAY_LONGER_THAN_MAX_STAY` | gap |
| `CONFLICT_AMBIGUOUS_PLAN_SELECTION` | conflict |
| `CONFLICT_NEGATIVE_TOTAL` | conflict |
| `CONFLICT_UNORDERED_ADJUSTMENTS` | conflict |
| `CONFLICT_OVERLAPPING_FILL_RULES` | conflict |
| `FAULT_RULE_RETURNED_NOT_LINES` | fault |
| `INVALID_PERCENT_DISCOUNT_OVER_100` | invalid -- the plan does not load |
<!--/gen:findings-->

## A worked example

<!--gen:example kind=2-->
```
POST /v1/quote
{
  "plans": [
    "<the plan document>"
  ],
  "entry_at": "2026-03-03T09:14:00-05:00",
  "exit_at": "2026-03-03T18:40:00-05:00",
  "space_class": "standard",
  "currency": "USD"
}
```

```
  Entered 09:14 Tue 03 Mar, 566 minutes, space class 'standard', plan
      downtown-2026-02                                                                       --
  Early bird NOT applied: entry 09:14 is after the 09:00 entry limit; exit 18:40
      on Tue 03 Mar is after the 17:00 limit on Tue 03 Mar. All of its
      conditions must hold, so the stay prices on the time-based rate                        --
  Time-based: first hour 8.00 USD                                                      8.00 USD
  Time-based: 9 additional hours at 4.00 USD = 36.00 USD                              36.00 USD
  Daily max 30.00 USD (calendar_day) applied over the day: 44.00 USD reduced to
      30.00 USD                                                                      -14.00 USD

  FEE  3000 minor units (USD)
```

The lines above sum to 3000, which is the fee. That is not a coincidence and not a check performed afterwards: the fee IS the running total of the breakdown, and the engine asserts it on every quote.
<!--/gen:example-->

## The guarantees

Each of these has a test proven able to fail, by planting the defect it guards
against and requiring red — `python scripts/fail_controls.py`. A test that has
never failed is a decoration.

<!--gen:guarantees kind=1-->
| id | what it proves |
| --- | --- |
| **F1** | The engine never guesses. A stay the plan cannot price is REFUSED, naming the gap, and no number is returned. |
| **F10** | Plan selection is never ambiguous. Two versions in force at the same instant are REFUSED and both named, never resolved by the order of the caller's list. |
| **F12** | `validate-plan` separates the findings an owner has still to look at from the ones they have recorded a decision for. Every finding is reported either way. |
| **F12b** | A decision is an ACKNOWLEDGEMENT, not a price. A stay hitting a SETTLED gap is refused exactly as one hitting an outstanding gap is; no entry in `decisions[]` can cause a fee to be produced. |
| **F13** | The fixture corpus holds a case either side of every threshold the rules branch on, read out of the plans rather than from a list -- so no guarantee is proven against a corpus that could only ever exercise one branch. |
| **F14** | A registered guarantee whose test stops running turns the build RED, including when its module fails to import; and a test module that plants a defect but registers no guarantee is refused. |
| **F15** | `increment.rounding` is CONSULTED by the applier, which refuses a mode it does not implement rather than pricing the stay under a different one. The applier checks what it implements, never what the loader accepts. |
| **F16** | Every refusal reaches the caller AS a refusal. A malformed number anywhere in a plan comes back as a named 400 naming the field, and a malformed rule return as a named 422 -- never as an exception escaping the quote contract, and never as a dropped connection. |
| **F17** | A rendered amount uses its own currency's ISO 4217 minor-unit exponent, never an assumed two decimal places -- and a code whose exponent this module does not know is REFUSED at load rather than rendered on a guess. |
| **F17b** | That refusal is at LOAD, so an unrenderable currency never reaches the renderer at all -- the membership check and the exponent read one table. |
| **F18** | A wall-clock limit is compared at the granularity it is written and rendered in: the stay is truncated to the minute, so no breakdown line can say a time is after itself. |
| **F18b** | And the LIMIT is refused rather than truncated. A plan may state 'HH:MM'; anything finer is rejected at load, because rounding it would silently discard a pricing decision the operator wrote. |
| **F19** | `validate-plan` probes every boundary the plan DECLARES -- entry limits and exit limits as well as durations, each side of each -- so a conflict the engine would refuse is one the owner was shown before the plan went live. |
| **F2** | A special rate is all-conditions-or-nothing: miss one condition by a minute and it does not apply at all -- no pro-rating and no partial credit. Enforced per rule type; `time_window` is the only special this module ships, so the property is proven of it rather than of a populated stage. |
| **F20** | There are TWO time roundings and both are declared: a part-minute is a whole minute (assumed, module-wide) and minutes into periods is stated per rule. Every comparison against a duration reads the same rounded value. |
| **F21** | A refusal's CODE names the cause that actually occurred. A negative total is CONFLICT_NEGATIVE_TOTAL, not the multi-rule conflict code it borrowed. |
| **F22** | Whether a non-qualifying rule appears in the breakdown depends on its STAGE: a QUALIFY rule always speaks, at delta zero; a rule at another stage that does not cover the stay is silent. |
| **F22b** | And the stage is not the whole answer. A rule TYPE may declare that it speaks when it did not qualify, so a weekend discount declining because it is a Tuesday says so on the receipt -- while a rule that was never about this space stays silent whatever it declared. |
| **F22c** | A special for another space class charges nothing. A QUALIFY rule that does not cover the stay's class did not qualify, whatever its times, so it adds no money and gets its not-applied line at zero, naming the class as the reason -- never a time for a special the stay could never get; the fee is what the plan without it charges. |
| **F23** | The production invariant that the fee IS the ledger's sum is itself guarded: deleting it, no-opping it or unwiring it from the pricing path turns the suite red. |
| **F24** | A zero-length stay pays the first period -- a decision, published in the contract with the divergence it was disclosed with, not left for an integrator to discover as an anomaly. |
| **F25** | Whether a time window may run past midnight is stated by the PLAN, in `day_span`, with no default -- the engine holds no day condition of its own. `day_span` also says WHERE the exit limit falls: under a bounded span it is `exit_by` on the entry date plus the span, so a limit past midnight is a moment rather than a clock reading. `any_span` names no last day and keeps the clock reading. |
| **F26** | A window applies on the days the PLAN states -- weekday names, or the garage's own dates for a holiday or an event -- matched against the ENTRY's local date, and a window that did not match names the day that failed and the days it wanted. There is no built-in calendar and no preset: 'weekend' means different days in different countries. |
| **F27** | `enter_from` is CONSULTED, not merely validated and stored. A window states BOTH ends of its entry range, which is what makes an evening rate expressible, and a stay arriving one minute before it opens does not qualify. |
| **F28** | `day_span` `next_day` is BOUNDED: an exit on the following local day qualifies and one the day after that does not, where `any_span` accepts both. Proven on one stay, so the three spans are an axis rather than three unrelated scenarios. |
| **F29** | A `rate` effect is priced by `increment`'s own builder and applier, not by a copy of them: identical parameters produce identical lines on the same stay, and a change to `increment`'s period counting moves the window's lines with it. |
| **F3** | The plan version in force at ENTRY prices the whole stay. A rate change mid-stay never splits it. |
| **F30** | An `adjust` effect applies to the fee AFTER the caps and the surcharges. A percentage taken any earlier is a percentage of a number the customer is not being charged. |
| **F31** | An `adjust` percentage is integer basis points and its `rounding` is CONSULTED: the same stay under `up` and under `down` differs by one minor unit, and when the amount was rounded the breakdown line says which way it went; when the division was exact there is no rounding clause to state. |
| **F32** | `grace` is TERMINAL, and free means free: a stay at or under the stated minutes costs zero and picks up no surcharge, no cap and no adjustment. Terminality is DECLARED by the rule type at registration -- the engine never knows its name -- and a special it beat says so on the receipt. |
| **F33** | Two caps on one stay leave the LOWER ceiling standing, the total after CAP is the same in both application orders, and the breakdown names both. Caps COMPOSE; two of them are not a conflict. |
| **F34** | More than one rule qualifying at one stage means three different things, and the stage's category decides which: RESOLVING is settled by the plan's resolution mode (one rule applies, a tie included -- F48), COMPOSING order-independent is not reported at all, and COMPOSING order-dependent is refused unless the plan states the order. |
| **F35** | Two qualifying ADJUST rules with no stated `adjust_order` are REFUSED naming both. With an order, the car pays the cheapest order of the specials that apply (20% off then a fixed amount is not the same fee as the fixed amount then 20% off): up to five applying, every order is priced; beyond five, every arrangement of their kinds, each kind kept together (at most 24), so the order the plan lists them in never moves the price, and the orders tried for each way are bounded; the whole quote has a budget of single pricings, past which a way takes the specials in rule id order and its receipt says so. One line says which order. Only the specials that apply are priced per order; where the order changes nothing the plan's own order is the receipt's. |
| **F36** | The resolution modes decide which rule is NAMED, never the money. Two windows qualifying on one stay are charged the cheaper under either mode (F63); where they charge the same, `cheapest_wins` names the lowest rule id and `stated_order` the first in its order, on the SAME stay, and reversing the order reverses the name -- and the rules that lost still appear, each naming the winner, both prices and the mode. |
| **F37** | A `stated_order` must name every rule at its stage EXACTLY ONCE, and one that does not is refused at LOAD, naming what is missing. A rule left out would take a silent position, and array position deciding money is what this module refuses everywhere else. |
| **F38** | Every identifier the published documents name in backticks is one the code actually holds -- rule types, stages, finding codes, plan and rule fields, stated values, traits and guarantee ids -- and every file path they point at exists. Derived from both documents rather than from a list of the sentences somebody remembered to check. |
| **F39** | A window's exit limit runs to the day its `day_span` allows. Under a bounded span the limit is `exit_by` on the entry date plus the span, so an evening window with an after-midnight limit applies to the car that leaves the SAME evening as well as the one that leaves after midnight. A limit that would have to WRAP to be reached is refused at load under `same_day` and `any_span`, neither of which can say what day it falls on. |
| **F4** | Money is an integer of minor units. A float, a bool or a Decimal anywhere in a plan is refused at load. |
| **F40** | A window's exit limit is compared as WALL-CLOCK readings, never as two instants, so a window behaves the same on the night the clocks change. On the hour that occurs twice at a fall-back, two stays leaving at the same stated time an hour apart in real time both qualify; a limit at a wall time that a spring-forward skips entirely still reads, and a stay past it is still refused. |
| **F41** | A tax rounds the way its rule states: `rounding` is required, with no default, and is one of `up`, `down` and `nearest`, where `nearest` takes EXACTLY half up, decided in integers on the exact remainder. Each mode is asserted on figures where it differs from the others, the exact half included, and when the amount was rounded the line shows the unrounded figure and which way it went; when the division was exact there is no rounding clause to state. |
| **F42** | Taxes never compound. Every rule in a set is a percentage of the same `subtotal_minor` -- the money actually paid -- and never of a total that already includes another tax line. A rule cannot state a base at all: the key is refused as the unknown key it is, and so is a flat amount. |
| **F43** | The tax set in force is chosen by the instant: the latest set taking effect at or before it, whatever order the sets arrive in. A new set is how a rate changes, a tax is added and a tax is repealed. An instant before every set is REFUSED, never taxed at zero, and two sets taking effect at the same instant are refused at load, both named. |
| **F44** | Taxes come out in the `sequence` each rule states, never in the order the list arrived in. A rule with no `sequence`, or two rules in one set sharing one, is refused at load. |
| **F45** | Tax on nothing is nothing. A subtotal of zero produces no tax lines, and the same rules on a positive subtotal produce them. A negative subtotal, or one that is not an integer of minor units, is refused. |
| **F46** | A tax set is judged by the loader and nowhere else. `/v1/validate-tax-sets` and `rate-engine validate-tax-sets` hand it to `load_tax_sets` and answer what it answers: every refusal it makes reaches both surfaces as the same named refusal, byte for byte, and what it loads is valid from both -- so a caller that stores only what this door accepted stores nothing the engine will refuse when it computes the tax. |
| **F47** | A tax figure is reached the same way from both surfaces. `/v1/tax` and `rate-engine tax` hand the request to one function, which calls `tax_lines` and writes its lines as a breakdown's are written, with their total: the same status and the same bytes from both, for a figure, a refusal and a request that cannot be read. |
| **F48** | A tie at the cheapest charge is PRICED, not refused. Two rules qualifying at one resolving stage and charging the same amount under `cheapest_wins` validate clean; the stay is priced at that amount, the lowest rule id is named as applied, and every other says it charged the same. A cheaper rule still wins whatever its id. Replaces F11, which refused the tie. |
| **F49** | Every `validate-plan` finding names the stay that found it: `probe`, the entry and exit of the first probe stay that produced it, and that stay produces it. A refusal at quote time carries no `probe` key. |
| **F4b** | That sentence is true at EVERY leaf of a plan, not at the fields the engine happens to read -- proven by probing every position in the document, so a field added in a later round is covered the day it exists. |
| **F5** | Determinism. The same plan version and the same stay produce the same fee AND the same breakdown, always, on any machine and at any wall-clock time. |
| **F50** | Under either resolution mode a special that qualifies is never dearer than the time-based rate: the stay is priced through the whole pipeline both ways -- with the special, and by the time-based rate alone -- and charged the lower, a tie keeping the special. The breakdown says which way was used and what the other would have charged (`compared_minor`). Grace still prices a stay alone, `stated_order` no longer lets a dearer special replace the time-based charge (F63), and a stay the time-based rate alone cannot price is priced by the special. When the time-based rate is charged, every other special still has its line, as on the special's way: its own reason, or that it qualified and a cheaper special was compared instead -- never that one was applied. |
| **F51** | A fill rule prices on how full the garage was AT ENTRY. It applies at its threshold and above and not one basis point below; it raises the charge for the time -- the total after the base and the caps, less any discount taken before it -- and nothing else, and a plan ordering it before another ADJUST rule does not load; its line says how full the garage was and by how much the charge rose, and below the threshold says it was not raised. A stay in a class it covers with no figure is refused with GAP_NO_OCCUPANCY_AT_ENTRY; a plan without one prices the same with or without the figure. Two fill rules applying to one stay are CONFLICT_OVERLAPPING_FILL_RULES whatever `adjust_order` says. A threshold, a percent or a figure out of range, not a whole number, or a bool is refused by name. |
| **F52** | A VIP surcharge may be a percent of the stay's time-based charge -- the total after the base and the caps -- rounded the way the rule says, and never of another surcharge, so two surcharges total the same in any order. The flat form prices exactly as it did. A rule stating both forms, or a percent out of range, is refused by name. |
| **F53** | `validate-plan` probes the occupancy axis of every fill rule: one basis point below each threshold, on it, and at 100% full, across every other axis, so two fill rules colliding only when the garage is full are reported before a stay is refused for it, and the finding names the figure that found it. A plan with no fill rule is probed exactly as before, and a missing figure is not reported as a gap in the plan. |
| **F54** | A fill rule states the owner's two answers, `raises_specials` and `raises_vip_extra`, each "yes" or "no", and a rule that omits either or states anything else does not load, naming the field. `raises_specials` no leaves a charge a special priced unraised and says so; yes raises it. `raises_vip_extra` yes raises the space-class extra by the same percent on its own line; no leaves it as set. All four combinations, on each side of the threshold, price to the cent worked by hand, and flipping one answer moves the fee by exactly what that answer governs. |
| **F55** | Where a discount and a fill rule both apply, the driver pays the CHEAPEST order, to the cent after rounding: the discounts first and the fill rule on what is left; the fill rule first; the discounts first with each part (time charge, space-class extra) carrying its share; and the fill rule between the specials that apply (between any two up to five, between kinds beyond). The plan's stated order does not decide the price. A tie charges the first of those, and one line says which order was charged and what the others would have charged. Every pair of the owner's two answers, a percent and a flat discount, each side of the threshold, prices to the cent worked by hand. |
| **F56** | A cap counts only the days and weeks the car is in for more than zero time: an exit at exactly local midnight, at a 24-hour mark or at the start of a week adds no day or week, and one minute past it does. A week holds only its own days, so it costs no more than the daily max for the days the car is in it: at 30 a day and 100 a week, seven days and an hour is 100 + 4 by the hour and 100 + 30 for a flat price, not 100 twice. The two caps still compose in either order. |
| **F57** | A fixed discount and a fixed increase are each taken in full, so fixed amounts commute: 5 off and 4 added on a stay of 3 is 2 either way. A total the adjustments take below zero is brought back to zero once, after all of them, by its own line (adjust.floor), so a stay cheaper than its discount is priced at zero, not refused. A percentage is never worked out on a total below zero. A total already below zero before the adjustments is not floored (F21). The 150% discount no longer loads (F60). |
| **F58** | The HTTP door reads a request body only within a bound. A negative Content-Length is a named 400 rather than a read to the end of the connection, and every connection carries a socket timeout, so a caller that stops part-way through a body is disconnected rather than holding a thread. |
| **F59** | A daily max caps each day on its own (decided 2026-10-16: per calendar day). The stay is cut at each local midnight, or each 24 hours from entry under `rolling_24h`, and each day pays the time charged in it or the max, whichever is less: at 8 the first hour, 4 an hour after and 30 a day, Monday 09:00 to Tuesday 00:15 is 30 + 4 = 34, not 60. A period is charged on the day it starts, the rate does not start again at midnight, a day with a clock change is one day, and a day the car is in for no time adds nothing. A weekly max caps each of the plan's weeks the same way, after the daily max for each of its days. The caps compose in either order, the answer is the same on every run and in every server zone, and no fee is higher than the max times the days touched. A flat special, one price for the stay it covers, is capped as one price at the max times the days the car is in (F63), as is a rule type that does not say how its charge builds up. What a base says it charged is checked against its lines on every quote. |
| **F6** | The test function IS the production path. `/v1/quote` and the CLI emit the same response bytes for the same request, from one code path and one encoder; the CLI's terminal newline is written outside the payload. |
| **F60** | A percent discount can never exceed 100%. A `time_window` discount whose `percent_bp` is above 10000 does not load: `validate-plan`, `quote` and the HTTP door answer 400 with the code INVALID_PERCENT_DISCOUNT_OVER_100 beside a sentence naming the field, so no plan carrying one is saved and no stay is priced on it. 10000 loads and makes the stay free. A percent increase over 100% still loads, a fixed discount larger than the charge is F57's, and every other load refusal carries no code. |
| **F61** | A long stay is priced in the memory of a short one. A cap finds the stay's days and weeks as it walks them and lists none of them, each day's or week's amount goes into a running tally, the base remembers only its last few answers, and a cap's line spells out a bounded number of runs of equal amounts, then says how many more there were and what they came to. The work still grows with the stay, by a step a day: ten years take ten times the work of one, and a century no more a day than a year. The engine refuses a stay longer than 90 days before any of this work (F62); these are measured with that limit lifted, so they hold for the caps whatever it is set to. |
| **F62** | The longest stay the engine prices is 90 days of 24 hours, entry to exit (decided 2026-10-16). Exactly 90 days is priced; 90 days and one second is REFUSED with GAP_STAY_LONGER_THAN_MAX_STAY, a 422 naming the limit, at every door -- before the plan is read, before a day of the stay is walked and before a base is asked what it charged, so a stay of about ten thousand years is refused with no more work than one of 90 days and a second. It is elapsed time, so a clock change does not move it. The limit is one constant, `MAX_STAY_DAYS`, read at every use, and `validate-plan` answers it as `max_stay_minutes` for a rate setup to show. |
| **F63** | The cheapest price always wins (decided 2026-10-16): where more than one price could apply to the same time, the car pays the cheapest, and whole-stay alternatives are compared (2026-10-17). A flat special is one price for the stay it covers, held to the max for each day and week the car is in, and is compared with the time-based rate's whole stay, each calendar day capped by the daily max and each week by the weekly max: with a 50 Friday-to-Sunday flat, a 30 daily max and an hourly rate that reaches 30 within a day, Saturday only is 30 and Friday 18:00 to Sunday 18:00 is 50. A stay past a special's exit limit is not covered by it. Two specials, or two time-based rates, are compared on the whole fee, caps and all -- a rate of 100 the first hour and 0.50 after beats one of 2 an hour over two days at 30 a day, 42 against 60 -- and the losing line gives both figures where the rules' own prices do not say why. Under `stated_order` the cheapest way is charged too, the time-based rate included. On every stay swept, the fee is the least of the fees each way charges on its own. Additive rules are not made a choice: a surcharge and a fixed increase are still added in full. |
| **F64** | A quote prices each way once, and asks nothing again per way or per pair. With N ways that qualify -- specials and time-based rates -- the stay goes through the pipeline N + 1 times (once, with one way), which is F63 itself. Beside that, each rule is asked once a quote whether it qualifies, a rule is found by its id and two rules are never compared field by field, a special that did not qualify is asked for its line once, and a way at most three times. 400 qualifying specials beside 400 that do not, on a 90-day stay with a daily and a weekly max, are priced within a fixed time budget. No limit is set on the rules a plan may hold or the ways a stay may have. |
| **F6b** | And there is exactly ONE encoder. No surface re-implements the response bytes, so the two doors cannot drift the way they silently did. |
| **F6c** | The CLI's payload is the route's payload BYTE FOR BYTE, with any terminal newline written outside it -- compared as bytes, never as decoded objects. |
| **F7** | Registering a new rule type changes no existing plan's answer -- fee and breakdown byte-identical. |
| **F8** | The fee is the sum of the breakdown's deltas, by construction. There is no second route to the total. |
| **F8b** | A rule's only channel to the fee is a list of Lines. A malformed return is REFUSED by name, not left to crash inside the ledger. |
| **F9** | The published contract is DERIVED, never transcribed. Every generated block matches the code, and every block that ASSERTS something about its values is proven to move when those values contradict it. |
<!--/gen:guarantees-->

## What this version does not do

Named here so nobody adds them helpfully:

- **No counting.** The engine prices on the occupancy figure it is handed and
  counts no cars and no spaces; the caller says how full the garage was.
- **No plan storage, no draft/approve workflow, no change log.** Round B. A plan
  arrives on the call.
- **No forecast and no competitor comparison.** Round C.
- **No rate import from a photograph.** Round D, and it will only ever produce a
  draft.

## The fill rule

**"When the garage is at least X% full, the time-based charge is Y% more."** A
`fill_level` rule states `threshold_bp` (X, 0 to 10000), `percent_bp` (Y, 1 to
10000) and `rounding` (`up` or `down`, no default), with the space classes it
covers. It runs at ADJUST.

**It reads how full the garage was AT ENTRY, and nothing else.** The figure is
`occupancy_at_entry_bp` on the stay, set by the caller when the stay opened: every
car inside against every switched-on space. The engine counts nothing. A car that
came in when the garage was 70% full keeps that price however full the garage is
when it leaves. The rule applies AT the threshold and above.

**It raises the charge for the TIME**: the running total when SURCHARGE begins,
after whichever base priced the stay and after the caps, less any discount
taken before it.

**With a discount, the driver pays the cheapest order** (F55). Where a discount
and a fill rule both apply, the engine prices every order and charges the
cheapest, to the cent after rounding: the discounts first and the fill rule on
what is left, the discount set against the time charge first; the fill rule
first, the discounts on the raised total; the discounts first with each part
(time charge, space-class extra) carrying its share in proportion, the raised
part's share rounded up; and, with more than one discount, the fill rule between
them. The discounts keep the plan's order among themselves. A tie charges the
first of those. One line, `fill_level.order`, at zero, says which order was
charged and what the others would have charged: "Discounts and the fill rule
taken in the cheapest order: the fill rule first, then the discounts; another
order would charge 16.38 USD". 10.00 with 20% or 2.00 off at +20% is 9.60.
A plan whose `adjust_order` puts a fill rule anywhere but after every other
ADJUST rule still does not load, naming the rule: the price no longer depends on
it, and a plan that reads as "raise, then discount" would say something the
engine does not do.

**The owner's two answers** (version 6), both required, `yes` or `no`, no default:

- `raises_specials` -- `yes`: a charge a special priced is raised like any
  other. `no`: it is not, and the line says so: "Early bird special: fill rule
  not applied (garage was 84% full at entry, at or above 80%; this plan does not
  raise specials)". The stay is still priced both ways, under either mode, so
  the driver pays the cheaper of the unraised special and the raised time-based
  rate.
- `raises_vip_extra` -- `yes`: what the stay's space-class surcharge added, flat
  or percent, is raised by the same percent, on its own line: "Space class 'vip'
  extra +20% on 5.00 USD (garage was 84% full at entry) -- 1.00 USD added".
  `no`: the extra stays as set.

Each raised line is rounded the rule's own way, on its own.

**Its lines**, in the breakdown like every other: "Garage was 84% full at entry (at
or above 80%): time-based charge +20% on 30.00 USD -- 6.00 USD added", and below
the threshold, at zero, "Garage was 62% full at entry (below 80%): time-based
charge not raised". A class the rule does not cover gets no line.

**Never a guess.** A stay with no figure, in a class a fill rule covers, is
REFUSED with `GAP_NO_OCCUPANCY_AT_ENTRY` -- never priced as if the garage were
empty or full. A plan with no fill rule never reads the figure. Two fill rules
that both apply to one stay are `CONFLICT_OVERLAPPING_FILL_RULES`, whatever
`adjust_order` says: they are two answers to one question, and an order would
charge both. A fill rule naming a class the plan does not declare does not load.

**`validate-plan` does not probe "no figure".** That gap is a fact about the
caller -- a garage that has not stated its number of spaces -- not about the
plan, and reporting it would put a finding on every plan that carries a fill rule.

## A percent VIP surcharge

`space_surcharge` is a flat `surcharge_minor` per stay, or an `amount` of kind
`percent` whose `percent_bp` is 1 to 10000, with a `rounding` of `up` or `down`
and no default -- one form or the other, never both. The percent is taken of the same charge
for the time the fill rule reads, so two surcharges still compose in any order
with the same total. Its line: "Space class 'vip': 10% of the time-based charge
30.00 USD -- 3.00 USD on top of the base".

## Grace, and what "free" means

A plan may declare a grace period: `minutes`, a positive whole number, with **no
default and no grace unless the plan states the rule.** "Usually ten minutes" is
an observation about other people's garages, not a value to assume.

**A stay at or under that many minutes costs nothing, and nothing means nothing.**
Grace is TERMINAL: the pipeline stops after QUALIFY, so a graced stay in a VIP
space does not pick up the surcharge, does not reach a cap, and is not adjusted.
A receipt for a graced stay carries the grace line and nothing else. It also
beats any other special that qualified — and that special is not dropped
silently; it gets a line naming the rule that superseded it.

**All-or-nothing.** One minute over a ten-minute grace and the stay prices from
ENTRY on the ordinary rate, not from minute ten. That is the ordinary garage
convention and it is the same all-conditions rule every special here keeps.

**A grace of ten minutes covers 600.000 seconds and not 600.001.** Durations are
whole minutes rounded UP, module-wide, before any rule sees a stay — so a stay of
ten minutes and one millisecond is eleven minutes and misses a ten-minute grace.
That is coherent with every other duration comparison here, including the stated
ceiling on a time-based rule, and it is recorded rather than adjusted.

## A stay of zero length pays the first period

**Entry and exit at the same instant is priced, not free, and not refused.** The
first period covers `[0, first_period_minutes]`, so a car that enters and leaves
without stopping pays `first_period_minor` -- the same as a car that stayed one
minute or fifty-nine.

It is a DECISION, and it is published here because an integrator cannot otherwise
learn it: the number is correct under the rule as written, and it is the kind of
edge a garage owner will be asked about at the counter.

**It diverges from the platform's own older fee code, which returns zero for the
same stay.** That divergence is known and is a later round's to reconcile; it is
recorded rather than left for whoever notices the two answering differently.

A negative stay -- exit before entry -- is a different thing and is REFUSED as a
caller bug rather than priced at zero, because pricing it would hide it.

**And this paragraph now describes only a plan that declares NO grace.** A garage
that declares one makes a zero-length stay free by the grace rule, because zero
is at or under any positive number of minutes. Both behaviours are deliberate,
both are tested, and which one a garage gets is stated in its own plan rather
than assumed here.
- **No validations, no monthly parkers, no payments, no card.**
- **Tax only as arithmetic.** This bullet said "no tax" until version 3, and it
  is qualified rather than deleted: the module computes tax lines on an amount it
  is handed, and that is all. It stores no garage's taxes, applies none on its
  own, and `/v1/quote` does not add them -- see "Tax, surcharges and city fees".

## The first money rounding, and why money stays an integer

**A percentage adjustment is the first thing in this module that rounds MONEY,
and it arrives with the version bump the specification says a commercial contract makes.** Every
rule before it was an integer add or an integer replace, and `money.py` said in
as many words that this module rounds no money anywhere. That sentence is now
qualified rather than deleted: it rounds money in exactly one place, the place is
named, and the direction is the plan's to state. Since version 3 that one place,
`percent.py`, has two callers -- an adjustment and a tax -- and it is still one
function, so the two cannot drift into two answers.

**A percentage is INTEGER BASIS POINTS.** 20% is `2000`; 12.5% is `1250`. Not a
decimal, because a float anywhere in a plan is refused at load — so a percent
field that could hold `20.5` would either be rejected or would put a float into
the pricing path through a field nobody was watching. The arithmetic is
`total * percent_bp // 10000` with the division rounded the way the rule says,
and no float is constructed at any point.

**`rounding` is stated per rule with no default**, because a percentage of a fee
lands on a fraction of a minor unit and who keeps that fraction is the owner's
decision. When the amount was rounded, the breakdown line says which way it went
and by how much, so a customer disputing a cent can be shown the answer rather
than told it; when the division was exact there is no rounding clause to state.

**That rounding is not the rounding this module already had.**
`increment.rounding` rounds TIME into whole periods: it decides that a 61-minute
stay is two hours. **The applier reads that field and refuses a mode it does not
implement**, so adding a mode to the ones a plan may state is a real change
rather than a plan that quietly keeps pricing as `ceil` (F15). The two roundings
share a word and nothing else.

**One wart, recorded rather than hidden:** `rounding` is required on every
`adjust` effect, and a `fixed` amount has nothing to round — on that shape the
field is stated and never read. It is written down here rather than left for a
reader to notice.

Money stays an integer of minor units at every depth. Nothing here introduces a
float, and nothing here changes what a plan written against the previous version
answers, because such a plan no longer loads at all — see "What changed in
version 2".

## Tax, surcharges and city fees

**Tax applies to the money actually paid -- after every discount and
validation.** That is the one base there is. A tax rule states no base: the caller
hands in `subtotal_minor`, the running total after every discount and validation
line, and every rule is a percentage of that one number. A tax is **never taken
of another tax**: there is no way to write one, and the applier is never handed
anything but the subtotal (F42).

**Percentage only.** A flat tax amount is not expressible, and that is a stated
limit rather than a hidden one: there is no field for it, and a key this module
does not understand is refused by name -- a base and a flat amount included.

**Validating is a door, and so is computing.**
`POST /v1/validate-tax-sets` and `rate-engine validate-tax-sets` take a body
carrying one key, `tax_sets`, and hand its list to `load_tax_sets`, in
`validate-plan`'s shape: 200 with each
set's `effective_from` as read and its `rule_count`, or 400 with `invalid` and the
loader's own sentence naming the field. A caller that stores a garage's taxes
stores what this door accepted, and nothing else judges them (F46).

`POST /v1/tax` and `rate-engine tax` take the same `tax_sets` and the three
arguments `tax_lines` takes: `subtotal_minor`, `currency` and `at`. They answer
200 with `lines`, written exactly as a quote's breakdown lines are, and
`total_minor`, their sum. They answer 422 with the findings when no set is in
force at `at`, and 400 with `invalid` and the sentence of whichever check refused
-- the loader's, or `tax_lines`' own for a currency it does not render or a
subtotal that is not a whole, non-negative number of minor units (F47). The two
surfaces are one function, so a figure, a refusal and an unreadable request come
back as the same bytes from both. `/v1/quote` still does not call it: tax is taken
after a validation, and the engine never sees one. None of these doors knows
anything about a stay, a garage, a validation, a monthly agreement or a card.

A garage states its taxes as **sets**. A set carries `effective_from`, an
offset-aware instant, and `rules`; a rule carries `id`, `label`, `percent_bp`,
`rounding` and `sequence`, and every one of them is required.

- **`percent_bp` is integer basis points**, exactly as an adjustment's is: 8.5%
  is `850`. A float or a bool is refused at any depth, the same walk a plan gets.
- **`rounding` has no default**, and a tax's set is its own: `up`, `down` or
  `nearest`. Tax is conventionally taken to the nearest minor unit, which an
  adjustment cannot state; `nearest` takes EXACTLY half up, decided in integers
  on the exact remainder (F41). When the amount was rounded, the line shows the
  unrounded figure and which way it went, so a driver disputing a cent is shown
  the answer; when the division was exact there is no rounding clause to state.
- **`sequence` is the order the lines come out in**, a whole number unique within
  its set. The list order decides nothing (F44).

**The set in force is chosen by the instant** the caller hands in -- the latest
set taking effect at or before it. A rate changing, a tax added and a tax
repealed are all one thing: a new set. An instant before every set is refused
with `GAP_NO_TAX_SET_IN_FORCE`, **never taxed at zero**; two sets taking effect
at the same instant are refused at load, both named (F43). A set with no rules is
how a garage STATES it charges no tax. Which instant to hand in -- the exit, the
close or an invoice date -- is the caller's to state; this module only takes it.

**Tax on nothing is nothing.** A subtotal of zero produces no lines (F45). The
set in force is still selected first, so a gap in what the garage stated is not
hidden by an amount that happened to be zero.

---

Built by 72 Knots Method by 72Knots.ai
