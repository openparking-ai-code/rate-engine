"""ISO 4217, only as far as this module needs it: which codes are money, and how
many minor units each has in a major one.

**Why this file exists.** `format_minor` did `divmod(abs(minor), 100)` for every
currency, so a fee of 800 minor units in a zero-decimal currency was returned
correctly as 800 and RENDERED as "8.00" -- the number right, the sentence a
hundred times wrong, in the breakdown that is the whole product. And the plan
loader's own diagnostic said "a three-letter uppercase ISO 4217 code" while it
checked only shape, so `ZZZ` loaded happily.

Those were one defect, and this is one fix: the exponent is a property of the
currency, so the module has to know the currency to render the money.

**Why the plan does not declare its own exponent.** It was the cheaper option and
it is wrong: the number of minor units in a yen is a fact the world already
fixed, and putting it on the plan invites an operator to state it incorrectly --
a wrong exponent silently multiplies every rendered amount by a hundred. A fact
nobody may vary does not belong in a document somebody writes.

**What is REFUSED, and why refusal is the right answer.** A code this table does
not carry cannot be rendered, because rendering needs the exponent. Refusing at
load is the same disposition as everywhere else in this module: say what is
missing rather than guess a value. That makes the loader's existing diagnostic
TRUE instead of retiring it.

**EXCLUSIONS ARE STATED AND CHECKED, NEVER LEFT AS ABSENCE.** They used to be a
paragraph of prose plus a code simply not appearing in the table -- which is an
OMISSION wearing a decision's clothes: nothing distinguished "we decided not to
price in this" from "we forgot it", and a prose range like "`XBA`-`XBD`" is not an
enumeration, so `XBB` and `XBC` were named by nobody. The sets below are the
decision, `REFUSED_BY_DECISION` is asserted disjoint from the table, and
`excluded_reason` puts the reason in the operator's refusal.

**THIS TABLE IS TRANSCRIBED, NOT DERIVED, AND IT IS THE ONLY ONE IN THE REPO.**
There is no dependency to read the register from and CI has no network, so it is
typed -- which this project's rules otherwise forbid. Two consequences, both
deliberate: `tests/test_f17_currency_is_rendered_by_its_exponent.py` asserts the
STRUCTURE (every value is a real ISO exponent, every key is well-formed, the
non-two groups are exactly the sets below), and an omission fails LOUDLY at load
rather than rendering wrongly -- so the failure mode of an incomplete table is a
refused plan somebody reports, never a wrong amount somebody pays.
"""

from __future__ import annotations

#: Codes whose minor unit is 1/1 of the major -- no decimal places at all.
#: These are the ones `divmod(minor, 100)` rendered a hundred times too small.
ZERO_DECIMAL: frozenset[str] = frozenset(
    {
        "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
        "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
    }
)

#: Codes with three decimal places -- 1000 minor units to the major.
THREE_DECIMAL: frozenset[str] = frozenset(
    {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}
)

#: Codes with four decimal places.
FOUR_DECIMAL: frozenset[str] = frozenset({"CLF", "UYW"})

#: Every code this module will price in. Two decimals unless named above.
_TWO_DECIMAL: frozenset[str] = frozenset(
    {
        "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
        "BAM", "BBD", "BDT", "BGN", "BMD", "BND", "BOB", "BRL", "BSD", "BTN",
        "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CNY", "COP", "CRC", "CUP",
        "CVE", "CZK", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD",
        "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GTQ", "GYD", "HKD", "HNL",
        "HTG", "HUF", "IDR", "ILS", "INR", "IRR", "JMD", "KES", "KGS", "KHR",
        "KPW", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "MAD", "MDL",
        "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MXN",
        "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "PAB", "PEN",
        "PGK", "PHP", "PKR", "PLN", "QAR", "RON", "RSD", "RUB", "SAR", "SBD",
        "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD", "SSP", "STN",
        "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TOP", "TRY", "TTD", "TWD",
        "TZS", "UAH", "USD", "UYU", "UZS", "VED", "VES", "WST", "XCD", "XCG",
        "YER", "ZAR", "ZMW", "ZWG",
    }
)


#: ISO 4217 gives these NO minor unit at all, so they cannot be expressed in the
#: only money type this module has. Enumerated one by one rather than written as
#: the range "XBA-XBD": a range in prose is not an enumeration, and XBB and XBC
#: were excluded by nobody's decision until they were written down here.
NO_MINOR_UNIT: frozenset[str] = frozenset(
    {
        "XAU", "XAG", "XPD", "XPT",                        # the precious metals
        "XDR", "XSU", "XUA", "XBA", "XBB", "XBC", "XBD",   # fund and bond-market codes
    }
)

#: Real ISO codes that are not money to price a garage in.
NOT_MONEY_TO_PRICE_IN: frozenset[str] = frozenset(
    {
        "XXX",  # "no currency". A rate plan denominated in no currency is not a thing.
        "XTS",  # reserved for testing. A test code reaching a real plan is a defect,
                # and accepting it here would make that defect silent.
    }
)

#: ISO FUNDS AND INDEX UNITS. Real ISO 4217 codes, and none of them is money a
#: garage charges in: each is a unit of account -- an inflation index, a
#: mutual-fund or bond unit, a settlement unit -- used to denominate an obligation,
#: not to take a payment at a barrier.
#:
#: These are listed for the same reason `UYI` was, and `UYI` is why the rest are
#: here. It is ZERO-DECIMAL, so leaving it out looked like an oversight in
#: `ZERO_DECIMAL` rather than a decision, and once it was written down the other
#: six were sitting in exactly its shape with nothing said about them. An
#: exclusion nobody wrote down is indistinguishable from a code somebody forgot,
#: which is the whole reason this file states its exclusions instead of expressing
#: them as absence.
NOT_A_CIRCULATING_CURRENCY: frozenset[str] = frozenset(
    {
        "UYI",  # Uruguay, Unidad Indexada -- an inflation index unit
        "BOV",  # Bolivia, Mvdol -- a dollar-indexed accounting unit
        "CHE",  # Switzerland, WIR Euro   -- complementary-currency fund units
        "CHW",  # Switzerland, WIR Franc  -- the same
        "COU",  # Colombia, Unidad de Valor Real -- an inflation index unit
        "MXV",  # Mexico, Unidad de Inversion (UDI) -- an inflation index unit
        "USN",  # United States, Dollar (Next day) -- a settlement unit, not cash
    }
)

#: Every code this module refuses ON PURPOSE. Asserted disjoint from the table
#: below, so a code can never be both priced and declared unpriceable.
REFUSED_BY_DECISION: frozenset[str] = (
    NO_MINOR_UNIT | NOT_MONEY_TO_PRICE_IN | NOT_A_CIRCULATING_CURRENCY
)

_WHY: tuple[tuple[frozenset[str], str], ...] = (
    (
        NO_MINOR_UNIT,
        "ISO 4217 gives it no minor unit at all, so no amount in it can be expressed "
        "in the integer minor units that are this module's only money type",
    ),
    (
        NOT_MONEY_TO_PRICE_IN,
        "it is an ISO placeholder rather than a currency -- XXX means 'no currency' "
        "and XTS is reserved for testing",
    ),
    (
        NOT_A_CIRCULATING_CURRENCY,
        "it is an ISO funds or index unit -- a unit of account used to denominate an "
        "obligation -- rather than a circulating currency, so it is not something a "
        "garage is paid in at a barrier",
    ),
)


def excluded_reason(code: object) -> str | None:
    """Why this module refuses `code`, or None if it was never a stated exclusion.

    An unknown code that is not on any list gets the generic refusal: it might be
    a real currency this table is missing, and claiming a reason we do not have
    would be a confident wrong answer about somebody's money.
    """
    for codes, reason in _WHY:
        if isinstance(code, str) and code in codes:
            return reason
    return None


def _build() -> dict[str, int]:
    table = {code: 2 for code in _TWO_DECIMAL}
    for codes, digits in ((ZERO_DECIMAL, 0), (THREE_DECIMAL, 3), (FOUR_DECIMAL, 4)):
        for code in codes:
            table[code] = digits
    return table


#: code -> how many decimal places its minor unit has.
MINOR_UNIT_DIGITS: dict[str, int] = _build()

# A code cannot be both priced and declared unpriceable. Checked at import rather
# than only in a test, because the two lists are edited by different hands at
# different times and the failure is silent: a metal quietly gaining an exponent
# renders an amount in a thing nobody is paid in.
_both = REFUSED_BY_DECISION & frozenset(MINOR_UNIT_DIGITS)
if _both:  # pragma: no cover - a construction error, not a runtime path
    raise AssertionError(
        f"{sorted(_both)} are both priced and refused by decision. One of the two "
        "lists is wrong, and which one is not guessable from here."
    )


def is_known(code: object) -> bool:
    return isinstance(code, str) and code in MINOR_UNIT_DIGITS


def minor_unit_digits(code: str) -> int:
    """How many decimal places `code` has. Raises if it is not one this module prices.

    Never returns a default. A guessed exponent is a rendered amount wrong by a
    factor of ten or a hundred, which is exactly the defect this file closes.
    """
    try:
        return MINOR_UNIT_DIGITS[code]
    except KeyError:
        raise KeyError(
            f"{code!r} is not an ISO 4217 currency this module prices in, so the "
            "number of minor units in a major one is unknown and no amount can be "
            "rendered. Currencies are refused at load rather than rendered on a "
            "guessed exponent."
        ) from None
