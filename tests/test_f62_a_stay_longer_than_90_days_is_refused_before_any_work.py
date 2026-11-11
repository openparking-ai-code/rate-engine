"""F62 -- the longest stay priced is 90 days, and a longer one is refused before
any work is done.

Decided 2026-10-16: the longest stay the rate engine prices is 90 days. A longer
stay is refused with a clear code, documented in the contract, so the platform or
the lane can show "needs an operator"; and the limit is visible during rate setup.

**It is also the bound a review asked for.** Capping each day on its own (F59)
walks the stay a day at a time, so a quote's time grew with the days in the stay
-- a stay running to the year 9999 took about fifteen seconds of CPU -- and
nothing bounded how long a stay a caller could send. The limit is checked FIRST:
before the plan is selected, before a day is walked, before a base is asked what
it charged. So the longest stay the request format can carry, year 1 to year
9999, is refused with no more work than ninety days and one second.

What this file pins:

* 90 days to the second is priced; one second more, and one minute more, is not.
* Elapsed time, not dates: across a clock change the limit is still 90 x 24 hours.
* The refusal is a 422 at every door -- the pricing path, HTTP, the CLI -- coded
  `GAP_STAY_LONGER_THAN_MAX_STAY`, naming the limit and the stay's length, alone.
* It comes first: a too-long stay that no plan is in force for, or that its plan
  would refuse for another reason, is refused for its length.
* No work: counted -- no base asked, no day start found, no plan selected -- and
  timed, best of five.
* One constant: `validate-plan` answers `max_stay_minutes`, and changing
  `MAX_STAY_DAYS` moves the limit and the answer together.

`scripts/fail_controls.py` removes the limit, moves it to refuse 90 days itself,
checks it only after the stay is priced, copies the number instead of reading the
constant, drops it from the `validate-plan` answer, and names the wrong code, and
requires this file to go red each time.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import timedelta

import pytest

from rate_engine import engine
from rate_engine.contract import encode, run_quote, run_validate
from rate_engine.engine import MAX_STAY_DAYS, make_stay, max_stay_minutes, quote
from rate_engine.findings import GAP_STAY_LONGER_THAN_MAX_STAY, Refused
from rate_engine.plan import load_plan, parse_instant
from rate_engine.rules import RULE_ACCRUALS, daily_max
from rate_engine.service import make_server

HOURLY = {
    "id": "hourly", "type": "increment", "stage": "ACCUMULATE",
    "space_classes": ["standard"], "first_period_minutes": 60,
    "first_period_minor": 800, "repeat_period_minutes": 60,
    "repeat_period_minor": 400, "rounding": "ceil", "max_duration_minutes": None,
}
#: A rolling day: 90 days from any entry are exactly 90 windows, each capped.
DAILY = {"id": "cap-daily", "type": "daily_max", "stage": "CAP",
         "space_classes": ["standard"], "max_minor": 3000, "day_boundary": "rolling_24h"}
WEEKLY = {"id": "cap-weekly", "type": "weekly_max", "stage": "CAP",
          "space_classes": ["standard"], "max_minor": 10000,
          "week_boundary": "calendar_week", "week_starts_on": "mon"}


def _plan(*rules: dict, effective_from: str = "2026-01-01T00:00:00-05:00") -> dict:
    return {
        "plan_version": "longest-stay-2026-10",
        "effective_from": effective_from,
        "timezone": "America/New_York",
        "currency": "USD",
        "space_classes": ["standard"],
        "resolution": {"QUALIFY": {"mode": "cheapest_wins"},
                       "ACCUMULATE": {"mode": "cheapest_wins"}},
        "adjust_order": None,
        "rules": [copy.deepcopy(r) for r in (rules or (HOURLY, DAILY))],
        "decisions": [],
    }


ENTRY = "2026-04-06T09:00:00-04:00"  # a Monday; no clock change for 90 days after


def _exit_after(**delta) -> str:
    return (parse_instant(ENTRY, "entry") + timedelta(**delta)).isoformat()


def _request(plan: dict, entry: str, exit_: str) -> dict:
    return {"plans": [copy.deepcopy(plan)], "entry_at": entry, "exit_at": exit_,
            "space_class": "standard", "currency": "USD"}


def _refusal(body: dict) -> dict:
    assert body.get("refused") is True, body
    assert [f["code"] for f in body["findings"]] == [GAP_STAY_LONGER_THAN_MAX_STAY], body
    return body["findings"][0]


# --- the limit ---------------------------------------------------------------


def test_the_limit_is_the_decision():
    """The control on the constant: the limit is 90 days, and a day is 24 hours
    of 60 minutes. If this moves, the decision moved with it -- or it did not."""
    assert MAX_STAY_DAYS == 90
    assert max_stay_minutes() == 90 * 24 * 60 == 129600


@pytest.mark.guarantee("F62")
def test_exactly_90_days_is_priced():
    """Ninety rolling days, each capped at 30.00: 2700.00."""
    status, body = run_quote(_request(_plan(), ENTRY, _exit_after(days=90)))
    assert status == 200, body
    assert body["fee_minor"] == 90 * 3000
    assert "129600 minutes" in body["breakdown"][0]["text"], body["breakdown"][0]


@pytest.mark.guarantee("F62")
@pytest.mark.parametrize("over", [{"seconds": 1}, {"minutes": 1}, {"hours": 24}])
def test_one_second_more_is_refused_and_says_why(over):
    status, body = run_quote(_request(_plan(), ENTRY, _exit_after(days=90, **over)))
    assert status == 422, body
    finding = _refusal(body)
    assert finding["kind"] == "gap"
    assert f"at most {MAX_STAY_DAYS} days ({max_stay_minutes()} minutes)" in finding["text"]
    minutes = make_stay(
        parse_instant(ENTRY, "entry"),
        parse_instant(_exit_after(days=90, **over), "exit"),
        "standard",
    ).duration_minutes
    assert f"this one is {minutes} minutes" in finding["text"], finding["text"]
    assert "an operator prices it" in finding["text"], finding["text"]


@pytest.mark.guarantee("F62")
def test_it_is_elapsed_time_so_a_clock_change_does_not_move_it():
    """In on 1 February, before the spring change: 90 days of 24 hours end at
    01:00 local on 2 May, not at midnight, because the clocks lost an hour."""
    entry = "2026-02-01T00:00:00-05:00"
    plan = _plan(effective_from="2026-01-01T00:00:00-05:00")
    for exit_, priced in (
        ("2026-05-02T00:00:00-04:00", True),   # 90 days less an hour
        ("2026-05-02T01:00:00-04:00", True),   # 90 days exactly
        ("2026-05-02T01:00:01-04:00", False),  # and a second
    ):
        status, body = run_quote(_request(plan, entry, exit_))
        assert (status == 200) is priced, (exit_, body)


# --- the refusal, at every door ------------------------------------------------


@pytest.fixture(scope="module")
def base_url():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.guarantee("F62")
def test_the_http_door_answers_the_same_422(base_url):
    request = _request(_plan(), ENTRY, _exit_after(days=90, seconds=1))
    http = urllib.request.Request(
        base_url + "/v1/quote", data=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(http) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    assert status == 422
    assert raw == encode(run_quote(request)[1])
    _refusal(json.loads(raw))


@pytest.mark.guarantee("F62")
def test_the_cli_refuses_it_by_name(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(_plan()))
    result = subprocess.run(
        [sys.executable, "-m", "rate_engine.cli", "quote", "--plan", str(plan_file),
         "--entry", ENTRY, "--exit", _exit_after(days=90, seconds=1),
         "--space-class", "standard", "--currency", "USD"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"[gap] {GAP_STAY_LONGER_THAN_MAX_STAY}" in result.stdout, result.stdout


# --- first, and with no work ------------------------------------------------------


@pytest.mark.guarantee("F62")
def test_it_is_asked_before_the_plan_is_read():
    """A stay too long AND entering before every plan: refused for its length, not
    for the plan -- the limit is the engine's, asked before any plan is."""
    early = _plan(effective_from="2027-01-01T00:00:00-05:00")
    status, body = run_quote(_request(early, ENTRY, _exit_after(days=91)))
    assert status == 422
    _refusal(body)
    # The control: the same plan refuses a SHORT stay for the plan.
    status, body = run_quote(_request(early, ENTRY, _exit_after(days=1)))
    assert [f["code"] for f in body["findings"]] == ["GAP_NO_PLAN_IN_FORCE_AT_ENTRY"]


@contextmanager
def _counted(budget: int):
    """Count the work a quote does: the times a base is asked what it charged,
    the day starts a cap finds, the plans selected. Past `budget` of any, stop
    the quote at once, so a refusal that came after the work fails in a moment
    rather than walking ten thousand years."""
    counts = {"asked": 0, "starts": 0, "selected": 0}

    def tick(name: str) -> None:
        counts[name] += 1
        if counts[name] > budget:
            raise AssertionError(f"{name} passed {budget}: the stay is being worked on")

    accrual = RULE_ACCRUALS["increment"]
    starts = daily_max._day_starts
    select = engine.select_plan

    def counted_accrual(rule, stay, plan):
        by = accrual(rule, stay, plan)

        def counted(minutes: int) -> int:
            tick("asked")
            return by(minutes)

        return counted

    def counted_starts(*args, **kwargs):
        for start in starts(*args, **kwargs):
            tick("starts")
            yield start

    def counted_select(plans, stay):
        tick("selected")
        return select(plans, stay)

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(RULE_ACCRUALS, "increment", counted_accrual)
        patch.setattr(daily_max, "_day_starts", counted_starts)
        patch.setattr(engine, "select_plan", counted_select)
        yield counts


#: The longest stay the request format can carry: ISO 8601 years run from 1 to
#: 9999. Noon UTC at both ends, so neither instant leaves the calendar in the
#: plan's own zone.
YEAR_ONE, YEAR_9999 = "0001-01-01T12:00:00+00:00", "9999-12-31T12:00:00+00:00"


def _longest_plan() -> dict:
    return _plan(HOURLY, DAILY, WEEKLY, effective_from="0001-01-01T00:00:00+00:00")


@pytest.mark.guarantee("F62")
def test_ten_thousand_years_are_refused_with_no_work_at_all():
    """No base asked, no day start found, no plan even selected -- the same as
    for ninety days and a second."""
    plan = load_plan(_longest_plan())
    longest = make_stay(parse_instant(YEAR_ONE, "e"), parse_instant(YEAR_9999, "x"), "standard")
    assert longest.duration_minutes > 9998 * 365 * 24 * 60, "the fixture is not that long"
    just_over = make_stay(
        parse_instant(ENTRY, "e"), parse_instant(_exit_after(days=90, seconds=1), "x"),
        "standard",
    )
    for stay in (longest, just_over):
        with _counted(budget=50) as counts, pytest.raises(Refused) as refused:
            quote([plan], stay)
        assert [f.code for f in refused.value.findings] == [GAP_STAY_LONGER_THAN_MAX_STAY]
        assert counts == {"asked": 0, "starts": 0, "selected": 0}, counts


@pytest.mark.guarantee("F62")
def test_ten_thousand_years_are_refused_in_a_moment():
    """Timed, best of five, with a margin no machine should need: the refusal
    reads two instants. Before the limit this stay took about fifteen seconds."""
    request = _request(_longest_plan(), YEAR_ONE, YEAR_9999)
    best = float("inf")
    for _ in range(5):
        # Inside the work budget: a refusal that came after the walk stops here
        # at once rather than walking ten thousand years five times.
        with _counted(budget=50):
            started = time.perf_counter()
            status, body = run_quote(request)
            best = min(best, time.perf_counter() - started)
        assert status == 422
        _refusal(body)
    assert best < 0.05, f"refusing the longest stay took {best:.3f} s"


# --- one constant, published -------------------------------------------------------


@pytest.mark.guarantee("F62")
def test_validate_plan_publishes_the_limit():
    status, body = run_validate({"plan": _plan()})
    assert status == 200, body
    assert body["max_stay_minutes"] == max_stay_minutes() == MAX_STAY_DAYS * 24 * 60


@pytest.mark.guarantee("F62")
@pytest.mark.parametrize("with_a_gap", [False, True])
def test_the_cli_shows_the_limit_where_the_rates_are_checked(tmp_path, with_a_gap):
    """On a clean plan and on one with a gap -- the two answers `validate-plan`
    prints -- the owner is told the longest stay priced."""
    document = _plan()
    if with_a_gap:
        document["rules"][0]["max_duration_minutes"] = 600  # nothing prices 601 minutes
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(document))
    result = subprocess.run(
        [sys.executable, "-m", "rate_engine.cli", "validate-plan", "--plan", str(plan_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == (1 if with_a_gap else 0), result.stdout + result.stderr
    assert (
        f"The longest stay priced is {MAX_STAY_DAYS} days ({max_stay_minutes()} minutes)."
        in result.stdout
    ), result.stdout


@pytest.mark.guarantee("F62")
def test_the_limit_is_ONE_constant_read_at_every_use():
    """Set the constant to one day, and the limit and the published answer both
    follow -- so there is no second copy of the number anywhere they are read."""
    plan = _plan()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine, "MAX_STAY_DAYS", 1)
        status, body = run_quote(_request(plan, ENTRY, _exit_after(days=1, minutes=1)))
        assert status == 422, body
        assert "at most 1 days (1440 minutes)" in _refusal(body)["text"]
        assert run_quote(_request(plan, ENTRY, _exit_after(days=1)))[0] == 200
        assert run_validate({"plan": plan})[1]["max_stay_minutes"] == 1440
    assert run_validate({"plan": plan})[1]["max_stay_minutes"] == 129600
