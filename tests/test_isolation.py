"""The suite does not depend on the machine of the person who runs it (PF-10)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from support import git


def test_the_home_folder_of_a_test_is_an_empty_throwaway_one(tmp_path_factory):
    home = Path.home()
    assert home.is_dir() and not any(home.iterdir())
    # Under the base directory of this run, whatever its name (--basetemp): never the real home.
    assert home.parent == tmp_path_factory.getbasetemp()
    assert os.environ["APPDATA"] == os.environ["LOCALAPPDATA"] == str(home)
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        assert name not in os.environ


def test_git_in_a_test_ignores_the_global_and_system_configuration():
    assert (
        os.environ["GIT_CONFIG_GLOBAL"] == os.devnull and os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    )
    assert "GIT_CONFIG_COUNT" not in os.environ and "GIT_CONFIG_PARAMETERS" not in os.environ


def test_the_git_helper_commits_even_when_signing_is_forced_by_the_environment(
    tmp_path: Path, monkeypatch
):
    """``GIT_CONFIG_COUNT`` gave 20 errors in the fixture of the loader tests before."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    git(tmp_path, "init", "-q")
    (tmp_path / "a").write_text("a")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "x")
    assert git(tmp_path, "rev-list", "--count", "HEAD") == "1"
    assert git(tmp_path, "branch", "--show-current") == "main"  # init.defaultBranch is set too


def test_the_git_helper_works_with_a_hostile_global_configuration(tmp_path: Path, monkeypatch):
    hostile = tmp_path / "gitconfig"
    hostile.write_text("[commit]\n\tgpgsign = true\n[core]\n\thooksPath = /nonexistent\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a").write_text("a")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    assert (
        subprocess.run(["git", "-C", str(repo), "log", "-1"], capture_output=True).returncode == 0
    )


DEVELOPER_VARIABLES = {
    "FXAC_REPO": "/nonexistent/fx-autoconfig",
    "FXAC_COMMIT": "not-a-hash",
    "DISPLAY": ":99",
    "WAYLAND_DISPLAY": "wayland-99",
}


def test_the_variables_of_a_developer_machine_are_gone_inside_a_test():
    """Run by the test below with the variables set; on its own it only shows their absence."""
    for name in DEVELOPER_VARIABLES:
        assert name not in os.environ, name
    # What reads them sees the defaults.
    from peek_a_foxy import loader

    assert (
        loader.pinned_commit() == loader.DEFAULT_COMMIT and loader.repo_url() == loader.DEFAULT_REPO
    )
    assert not loader.overridden()


def test_a_polluted_environment_does_not_reach_the_tests():
    """The real proof: start pytest with the variables set and see the test above still pass."""
    root = Path(__file__).resolve().parents[1]
    node = (
        f"{Path(__file__).name}::test_the_variables_of_a_developer_machine_are_gone_inside_a_test"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", node],
        cwd=root / "tests",
        env={**os.environ, **DEVELOPER_VARIABLES, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
