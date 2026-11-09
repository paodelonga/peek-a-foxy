"""The suite does not depend on the machine of the person who runs it (PF-10)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from support import git


def test_the_home_folder_of_a_test_is_an_empty_throwaway_one():
    home = Path.home()
    assert home.is_dir() and not any(home.iterdir())
    assert "pytest" in str(home)  # under the base directory pytest makes, never the real one
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
