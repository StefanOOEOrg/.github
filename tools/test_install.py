"""Tests for ``tools/install.sh``: the installed copy must be complete and importable.

The script runs for real into a temporary profiles root. The installed ``scripts/`` must hold
every module of ``tools/loop`` (tests excluded) and import as the cron jobs and the listener
import it, so a module missing from the installation fails CI before a merge breaks the TC.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

TOOLS = pathlib.Path(__file__).resolve().parent
SCRIPT = TOOLS / "install.sh"
PROFILE = "sw-test"

IMPORT_ALL = """
import importlib, pkgutil, loop, loop.__main__
for info in pkgutil.walk_packages(loop.__path__, "loop."):
    importlib.import_module(info.name)
print("imported", loop.__file__)
"""


def _source_modules() -> set[str]:
    """Return the engine modules install.sh must copy, relative to ``tools/``."""
    return {
        path.relative_to(TOOLS).as_posix()
        for path in (TOOLS / "loop").rglob("*.py")
        if "tests" not in path.relative_to(TOOLS).parts and "__pycache__" not in path.parts
    }


def _run_install(root: pathlib.Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run install.sh into ``root`` and return the finished process."""
    return subprocess.run(
        ["bash", str(SCRIPT), "--profile", PROFILE, "--profiles-root", str(root), *extra],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.fixture(name="installed")
def fixture_installed(tmp_path: pathlib.Path) -> pathlib.Path:
    """Install into a temporary profiles root and return its ``scripts/`` directory."""
    result = _run_install(tmp_path)
    assert result.returncode == 0, result.stderr
    return tmp_path / PROFILE / "scripts"


def test_every_source_module_is_installed(installed: pathlib.Path) -> None:
    """Each module under tools/loop lands in the profile, no test module does."""
    expected = _source_modules()
    assert "loop/rules/failed_start.py" in expected
    installed_modules = {
        path.relative_to(installed).as_posix() for path in (installed / "loop").rglob("*.py")
    }
    assert installed_modules == expected


def test_installed_engine_imports(installed: pathlib.Path) -> None:
    """The installed package imports completely, from the installed directory only."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, '.')\n{IMPORT_ALL}"],
        cwd=installed,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert str(installed) in result.stdout


def test_second_run_changes_nothing(tmp_path: pathlib.Path) -> None:
    """A repeated install copies nothing and reports every file unchanged."""
    assert _run_install(tmp_path).returncode == 0
    second = _run_install(tmp_path)
    assert second.returncode == 0, second.stderr
    assert "copied" not in second.stdout
    assert "unchanged" in second.stdout


def test_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    """--dry-run lists the copies without creating the target."""
    result = _run_install(tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "would copy" in result.stdout
    assert "loop/rules/failed_start.py" in result.stdout
    assert not (tmp_path / PROFILE).exists()


def test_stale_module_is_reported_not_deleted(tmp_path: pathlib.Path) -> None:
    """An installed module the source no longer has is named and left in place."""
    assert _run_install(tmp_path).returncode == 0
    stale = tmp_path / PROFILE / "scripts" / "loop" / "rules" / "gone.py"
    stale.write_text("", encoding="utf-8")
    result = _run_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"stale      {stale}" in result.stdout
    assert stale.exists()
