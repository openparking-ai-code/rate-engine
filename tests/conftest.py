"""The guard that makes a guarantee test a guarantee: it must actually RUN.

Proving a test CAN fail is half of it. A test can also skip in every CI run, on
a condition nobody watches, while the build stays green and the file's own header
claims the opposite. A test that can quietly not run is not a guarantee.

This is that mechanism with the two properties this project forbids elsewhere
taken out of it -- see tests/_guarantees.py. The check is a SET COMPARISON
against the registry, so it catches the case a per-test hook structurally cannot:
a module that fails to import produces no test items at all, and a guard that
only inspects items it was given will never notice the ones it was not.
"""

from __future__ import annotations

import os

import pytest

from _guarantees import ALLOW_ENV, GUARANTEES

_ran: set[str] = set()


def pytest_configure(config):
    config.addinivalue_line("markers", "guarantee(id): proves a registered guarantee")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    marker = item.get_closest_marker("guarantee")
    if marker and report.passed:
        for gid in marker.args:
            _ran.add(gid)


def pytest_collection_modifyitems(config, items):
    """Every id on a mark must be in the registry.

    The registry is the source; a mark naming an id nobody registered is a test
    claiming a guarantee the contract does not publish, which is the same defect
    as the reverse and is caught here rather than at the end of the run.
    """
    unknown: list[str] = []
    for item in items:
        marker = item.get_closest_marker("guarantee")
        if marker:
            unknown += [
                f"{item.nodeid} -> {gid}" for gid in marker.args if gid not in GUARANTEES
            ]
    if unknown:
        raise pytest.UsageError(
            "guarantee mark(s) naming an id that is not in tests/_guarantees.py:\n  "
            + "\n  ".join(unknown)
        )


def _is_a_full_run(session) -> bool:
    """Judge a whole-suite run only.

    A developer running one file has not skipped a guarantee; they have selected
    something. Failing that would make this guard noise, and a guard people learn
    to ignore is how the last one died. CI always runs the whole suite, so CI is
    always judged.
    """
    if session.config.option.keyword:
        return False
    selected = [arg for arg in session.config.args if not arg.startswith("-")]
    testpaths = session.config.getini("testpaths")
    return not selected or selected == list(testpaths)


def pytest_sessionfinish(session, exitstatus):
    if not _is_a_full_run(session):
        return
    allowed = {
        part.strip() for part in os.environ.get(ALLOW_ENV, "").split(",") if part.strip()
    }
    unaccounted = sorted(set(GUARANTEES) - _ran - allowed)
    if not unaccounted:
        return
    lines = "\n".join(f"    {gid}  {GUARANTEES[gid]}" for gid in unaccounted)
    print(
        "\nREGISTERED GUARANTEES THAT DID NOT RUN AND PASS:\n"
        f"{lines}\n"
        "\nA guarantee whose test does not run is not a guarantee. Either make it run,\n"
        f"or name the id in {ALLOW_ENV} -- which is a decision somebody writes down,\n"
        "not a default.\n"
    )
    session.exitstatus = 1
