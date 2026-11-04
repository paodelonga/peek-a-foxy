"""Fetching the fx-autoconfig loader: what is accepted as a source, and what is actually fetched."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from peek_a_foxy import loader
from peek_a_foxy.loader import LoaderError, fetch_loader


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def add_commit(repo: Path, message: str) -> str:
    (repo / "program" / "config.js").write_text(f"// {message}\n")
    git(repo, "commit", "-q", "-am", message)
    return git(repo, "rev-parse", "HEAD")


# --- the commit must be a full hash --------------------------------------------------------------


@pytest.mark.parametrize(
    "commit",
    [
        "main",
        "HEAD",
        "abc123",  # abbreviated
        "g" * 40,  # not hex
        "0" * 39,
        "0" * 41,
        "--upload-pack=touch pwned",
        "-" + "a" * 39,
        "",
        " " + "a" * 39,
        "a" * 39 + "\n",
    ],
)
def test_only_a_full_hex_commit_is_accepted(fxac_repo: Path, monkeypatch, commit: str):
    monkeypatch.setenv("FXAC_COMMIT", commit)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(loader, "_git", lambda *args, **kwargs: calls.append(args) or "")
    with pytest.raises(LoaderError, match="40"), fetch_loader():
        pass
    assert calls == []  # rejected before git was started


def test_a_bad_commit_is_a_clean_error_even_for_a_dry_run(
    profile: Path, firefox_dir: Path, fxac_repo: Path, monkeypatch
):
    from typer.testing import CliRunner

    from peek_a_foxy.cli import app

    monkeypatch.setenv("FXAC_COMMIT", "main")
    result = CliRunner().invoke(
        app,
        ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--dry-run"],
    )
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "40" in result.output


def test_an_uppercase_full_hash_is_fine(fxac_repo: Path, monkeypatch):
    full = loader.pinned_commit()
    monkeypatch.setenv("FXAC_COMMIT", full.upper())
    with fetch_loader() as checkout:
        assert (checkout / "program" / "config.js").is_file()


# --- the repository is data, never an option to git -------------------------------------------


def test_a_repo_that_looks_like_a_git_option_is_not_run(tmp_path: Path, monkeypatch, fxac_repo):
    sentinel = tmp_path / "pwned"
    monkeypatch.setenv("FXAC_REPO", f"--upload-pack=touch {sentinel}")
    with pytest.raises(LoaderError), fetch_loader():
        pass
    assert not sentinel.exists()


# --- only the pinned commit is fetched ------------------------------------------------------------


def test_the_checkout_has_the_pinned_commit_and_no_history(fxac_repo: Path, monkeypatch):
    pinned = add_commit(fxac_repo, "pinned")  # has the fixture commit as its parent
    add_commit(fxac_repo, "later")
    monkeypatch.setenv("FXAC_COMMIT", pinned)
    with fetch_loader() as checkout:
        assert git(checkout, "rev-parse", "HEAD") == pinned
        assert git(checkout, "rev-list", "--count", "HEAD") == "1"  # shallow: no history
        assert (checkout / "program" / "config.js").read_text() == "// pinned\n"


def test_a_commit_that_is_not_in_the_repository_is_an_error(fxac_repo: Path, monkeypatch):
    monkeypatch.setenv("FXAC_COMMIT", "1" * 40)
    with pytest.raises(LoaderError), fetch_loader():
        pass


def test_a_server_that_refuses_a_fetch_by_hash_falls_back_to_a_clone(fxac_repo: Path, monkeypatch):
    real = loader._git

    def refuse_fetch(*args: str, **kwargs):
        if args[0] == "fetch":
            raise LoaderError("git fetch failed: not our ref")
        return real(*args, **kwargs)

    monkeypatch.setattr(loader, "_git", refuse_fetch)
    with fetch_loader() as checkout:
        assert git(checkout, "rev-parse", "HEAD") == loader.pinned_commit()


def test_a_clone_that_does_not_end_on_the_pinned_commit_is_refused(fxac_repo: Path, monkeypatch):
    real = loader._git
    wrong = "2" * 40

    def lie(*args: str, **kwargs):
        if args[:2] == ("rev-parse", "HEAD"):
            return wrong
        return real(*args, **kwargs)

    monkeypatch.setattr(loader, "_git", lie)
    with pytest.raises(LoaderError, match="does not match"), fetch_loader():
        pass


def test_the_temporary_checkout_is_removed(fxac_repo: Path):
    with fetch_loader() as checkout:
        assert checkout.is_dir()
    assert not checkout.exists()
