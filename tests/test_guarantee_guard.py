"""The guard on the guarantees, and the control that proves the guard works.

conftest.py fails the run when a registered guarantee did not run and pass. That
guard is itself a piece of evidence, so it needs the same treatment as everything
else: shown failing, on a run where a guarantee is genuinely missing.

The control runs pytest in a subprocess against a temporary suite -- a copy of the
registry with one extra id nothing proves. The run must go RED and must name the
missing id. Without this, "CI fails when a guarantee stops running" is a sentence
that has never been tested, which is the exact defect the guard exists for.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from _guarantees import ALLOW_ENV, GUARANTEES
from plant import ROOT

CONFTEST = (ROOT / "tests" / "conftest.py").read_text()


def _mini_suite(tmp_path: Path, registry_body: str, test_body: str) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "_guarantees.py").write_text(registry_body)
    (tests / "conftest.py").write_text(CONFTEST)
    (tests / "test_thing.py").write_text(test_body)
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\npythonpath = tests\n"
        "markers =\n    guarantee(id): proves a registered guarantee\n"
    )
    return tmp_path


def _run(cwd: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


REGISTRY = (
    'GUARANTEES = {"G1": "proved", "G2": "NOT proved by anything"}\n'
    f'ALLOW_ENV = "{ALLOW_ENV}"\n'
)
ONE_TEST = (
    "import pytest\n\n\n"
    '@pytest.mark.guarantee("G1")\n'
    "def test_one():\n    assert True\n"
)


@pytest.mark.guarantee("F14")
def test_a_guarantee_that_never_runs_turns_the_run_red(tmp_path):
    """The control. G2 is registered and nothing proves it."""
    result = _run(_mini_suite(tmp_path, REGISTRY, ONE_TEST))
    assert result.returncode != 0, (
        "a registered guarantee with no test at all left the run GREEN; the guard is "
        "not doing the one thing it exists for"
    )
    assert "G2" in result.stdout
    assert "REGISTERED GUARANTEES THAT DID NOT RUN AND PASS" in result.stdout


@pytest.mark.guarantee("F14")
def test_a_guarantee_whose_module_fails_to_import_is_caught(tmp_path):
    """The half a per-test hook structurally cannot see.

    A module that raises at import time produces no test items, so a guard that
    only inspects the items it was handed never learns the tests existed. This is
    how another repo in this project lost eight wiring guarantees while its build
    stayed green.
    """
    body = (
        "import pytest\n"
        "raise ImportError('this module cannot load')\n\n\n"
        '@pytest.mark.guarantee("G1")\n'
        "def test_one():\n    assert True\n"
    )
    registry = (
        'GUARANTEES = {"G1": "proved by a module that will not import"}\n'
        f'ALLOW_ENV = "{ALLOW_ENV}"\n'
    )
    result = _run(_mini_suite(tmp_path, registry, body))
    assert result.returncode != 0
    assert "G1" in result.stdout


@pytest.mark.guarantee("F14")
def test_a_failing_guarantee_does_not_count_as_run(tmp_path):
    """Collected and executed is not enough -- it has to PASS."""
    body = (
        "import pytest\n\n\n"
        '@pytest.mark.guarantee("G1")\n'
        "def test_one():\n    assert False\n"
    )
    registry = f'GUARANTEES = {{"G1": "proved"}}\nALLOW_ENV = "{ALLOW_ENV}"\n'
    result = _run(_mini_suite(tmp_path, registry, body))
    assert result.returncode != 0
    assert "G1" in result.stdout


@pytest.mark.guarantee("F14")
def test_an_explicit_allowance_is_honoured_and_is_matched_exactly(tmp_path):
    """The escape hatch is an exact id, never a substring of a skip reason.

    A substring match is not a structural guarantee anywhere in this project: it
    lets an unrelated skip reason silently satisfy an allowance somebody wrote for
    a different one.
    """
    suite = _mini_suite(tmp_path, REGISTRY, ONE_TEST)
    assert _run(suite, {ALLOW_ENV: "G2"}).returncode == 0
    # A near-miss is not a match.
    assert _run(suite, {ALLOW_ENV: "G"}).returncode != 0
    assert _run(suite, {ALLOW_ENV: "G22"}).returncode != 0


@pytest.mark.guarantee("F14")
def test_a_mark_naming_an_unregistered_id_is_rejected(tmp_path):
    """The reverse defect: a test claiming a guarantee the contract never publishes."""
    body = (
        "import pytest\n\n\n"
        '@pytest.mark.guarantee("NOT_IN_THE_REGISTRY")\n'
        "def test_one():\n    assert True\n"
    )
    registry = f'GUARANTEES = {{"G1": "x"}}\nALLOW_ENV = "{ALLOW_ENV}"\n'
    result = _run(_mini_suite(tmp_path, registry, body))
    assert result.returncode != 0
    assert "NOT_IN_THE_REGISTRY" in result.stdout + result.stderr


# --- P2: the hole that let a whole FILE of controls go unregistered -----------
#
# `test_contract_is_generated.py` and `test_fixture_axes.py` carried no mark at
# all, so deleting or skipping either left the suite green and this guard silent
# -- 21 of 80 tests, including all three anti-prose controls and the control on
# the plant helper itself. Registering those two by hand fixes today. This fixes
# tomorrow, and it is DERIVED: the module set comes off the filesystem and the
# marks come out of the AST, so a new file cannot arrive unnoticed.
#
# READ WITH THE AST, NEVER WITH A REGEX. This very file carries the text
# `@pytest.mark.guarantee("G1")` inside the string literals it writes into its
# mini-suites. A text scan would count those as marks on THIS module and report
# it guarded no matter what its real decorators said -- a check measuring the
# word instead of the shape, which is the failure this project keeps cataloguing.

#: Modules deliberately contributing no guarantee. EMPTY, and an entry here is a
#: decision somebody writes down -- the same shape as ALLOW_ENV, for the same
#: reason. A module that PLANTS may not be listed: see the second rule below.
UNGUARANTEED_MODULES: frozenset[str] = frozenset()


def _declared_guarantee_ids(tree: ast.AST) -> set[str]:
    """The ids on real `@pytest.mark.guarantee(...)` DECORATORS in one module."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            if call is None or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr != "guarantee":
                continue
            found |= {
                arg.value for arg in call.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            }
    return found


def _imports_the_plant_helper(tree: ast.AST) -> bool:
    """Does this module import `planted` -- i.e. does it break source on purpose?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "plant":
            if any(alias.name == "planted" for alias in node.names):
                return True
    return False


def _test_modules() -> dict[str, ast.AST]:
    return {
        path.name: ast.parse(path.read_text())
        for path in sorted((ROOT / "tests").glob("test_*.py"))
    }


def unguarded_modules() -> dict[str, str]:
    """Every test module that no registered guarantee names, and why that is wrong.

    Two rules, and the second is the one the brief asked for by name:

    1. A test module contributes at least one registered guarantee, or is named
       in UNGUARANTEED_MODULES.
    2. **A module that PLANTS a defect must contribute one, with no allowance.**
       Going to the trouble of breaking source on purpose means producing
       evidence, and evidence nothing names is evidence nothing protects.
    """
    problems: dict[str, str] = {}
    for name, tree in _test_modules().items():
        ids = _declared_guarantee_ids(tree)
        plants = _imports_the_plant_helper(tree)
        unknown = sorted(ids - set(GUARANTEES))
        if unknown:
            problems[name] = f"claims unregistered guarantee id(s): {', '.join(unknown)}"
        elif ids:
            continue
        elif plants:
            problems[name] = (
                "plants a defect but registers no guarantee, and a planting module "
                "may not be excused -- delete it and the suite stays green while a "
                "control silently stops existing"
            )
        elif name not in UNGUARANTEED_MODULES:
            problems[name] = (
                "carries no @pytest.mark.guarantee, so deleting or skipping it leaves "
                "the suite green and this guard silent"
            )
    return problems


@pytest.mark.guarantee("F14")
def test_every_test_module_contributes_a_registered_guarantee():
    problems = unguarded_modules()
    assert not problems, "test modules outside both guards:\n  " + "\n  ".join(
        f"{name}: {why}" for name, why in sorted(problems.items())
    )


@pytest.mark.guarantee("F14")
def test_a_module_that_plants_and_registers_nothing_is_REFUSED(tmp_path):
    """THE FAIL-CONTROL for the rule above, and it plants a real file in tests/.

    Not a temp directory: the guard reads the real `tests/` tree, so a control
    pointed at a copy would prove the derivation works somewhere the derivation
    never runs. Restored in a `finally`, from the bytes written -- never
    `git checkout`.
    """
    intruder = ROOT / "tests" / "test_zz_planted_intruder.py"
    assert not intruder.exists(), "the intruder path is already occupied"
    body = (
        "from plant import planted\n\n\n"
        "def test_it_plants_but_names_no_guarantee():\n"
        "    with planted('stages.py', 'ADJUST', 'ADJUST'):\n"
        "        pass\n"
    )
    try:
        intruder.write_text(body)
        problems = unguarded_modules()
        assert intruder.name in problems, (
            "a module that plants a defect and registers no guarantee was accepted, "
            "so the hole that hid 21 tests is still open"
        )
        assert "may not be excused" in problems[intruder.name]

        # And the allowance cannot buy it out -- rule 2 has no escape hatch.
        import test_guarantee_guard as self_module

        original_allowance = self_module.UNGUARANTEED_MODULES
        try:
            self_module.UNGUARANTEED_MODULES = frozenset({intruder.name})
            assert intruder.name in unguarded_modules(), (
                "naming a PLANTING module in UNGUARANTEED_MODULES excused it; the "
                "allowance is supposed to be unavailable to exactly those modules"
            )
        finally:
            self_module.UNGUARANTEED_MODULES = original_allowance
    finally:
        intruder.unlink(missing_ok=True)
        assert not intruder.exists(), (
            "the planted intruder module is still in tests/ -- remove it by hand "
            "before running anything else"
        )


@pytest.mark.guarantee("F14")
def test_this_suite_registers_a_control_for_every_guarantee():
    """Every registered guarantee has an entry in scripts/fail_controls.py.

    Derived from both registries, not from a list here -- so a guarantee added
    without a fail-control fails this immediately rather than shipping as an
    unproven promise.

    Compared on GUARANTEE ids, because a guarantee may need more than one plant:
    a control id is `F6b` or `F6b/imported-name-form`, and `guarantee_of` is the
    one place that knows it. The equality still runs in BOTH directions -- an arm
    naming a guarantee that does not exist is as much a defect as a guarantee
    with no arm.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from fail_controls import CONTROLS, guarantee_of

    covered = {guarantee_of(control) for control in CONTROLS}
    assert covered == set(GUARANTEES), (
        f"guarantees with no fail-control: {sorted(set(GUARANTEES) - covered)}; "
        f"controls with no guarantee: {sorted(covered - set(GUARANTEES))}"
    )
