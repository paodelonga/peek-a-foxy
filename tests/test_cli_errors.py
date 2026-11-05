"""Failures at the command line: code, what to do, exit codes, the log, the ``logs`` command."""

from __future__ import annotations

import errno
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from peek_a_foxy import cli, errors
from peek_a_foxy.cli import app

runner = CliRunner()


def install(profile: Path, *extra: str):
    return runner.invoke(
        app, ["install", "--profile", str(profile), "--skip-loader", "--yes", *extra]
    )


def bad_utf8(profile: Path) -> None:
    (profile / "chrome" / "userChrome.css").write_bytes(b"\xff\xfe\x00")


def blow_up(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def explode(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "plan_install", explode)


# --- expected failures --------------------------------------------------------------------------


def test_an_expected_failure_shows_code_message_and_what_to_do(profile: Path):
    bad_utf8(profile)
    result = install(profile)
    assert result.exit_code == errors.EXIT_FAILURE
    lines = result.output.splitlines()
    assert lines[0].startswith("error [PAF-401]: ") and "not valid UTF-8" in lines[0]
    assert lines[1].startswith("What to do: ") and "save it as UTF-8" in lines[1]
    assert "Traceback" not in result.output and "Details:" not in result.output


def test_a_file_system_error_is_an_expected_failure_with_a_code(profile: Path, monkeypatch):
    blow_up(monkeypatch, PermissionError(13, "Permission denied", "/some/file"))
    result = install(profile)
    assert (
        result.exit_code == 1 and "error [PAF-402]: Permission denied: /some/file" in result.output
    )


def test_a_broken_pipe_is_not_ours_to_explain(profile: Path, monkeypatch):
    blow_up(monkeypatch, BrokenPipeError(errno.EPIPE, "Broken pipe"))
    result = install(profile)
    # Click itself ends the program quietly on a broken pipe; we must not call it a bug.
    assert result.exit_code == 1 and "PAF-" not in result.output


def test_the_partial_progress_still_follows_the_error(profile: Path):
    (profile / "chrome" / "userChrome.css").mkdir()  # fails the second step
    result = install(profile)
    assert "error [PAF-402]" in result.output and "1 of 3 steps finished" in result.output


# --- unexpected failures ------------------------------------------------------------------------


def test_a_bug_in_the_middle_of_a_plan_still_says_what_was_done(profile: Path, monkeypatch):
    monkeypatch.setattr("peek_a_foxy.installer.userfiles.with_css_import", lambda text: 1 / 0)
    result = install(profile)
    assert result.exit_code == 70 and "1 of 3 steps finished" in result.output


def test_the_real_program_exits_with_70_on_a_bug(profile: Path, tmp_path: Path):
    script = textwrap.dedent(
        """
        import sys
        from peek_a_foxy import cli
        def explode(*a, **k):
            raise ValueError("boom")
        cli.plan_install = explode
        cli.app(prog_name="peek-a-foxy")
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "install",
            "--profile",
            str(profile),
            "--skip-loader",
            "--yes",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 70 and "PAF-900" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_wrong_option_is_a_usage_error_with_exit_code_2(profile: Path):
    result = runner.invoke(app, ["install", "--no-such-option"])
    assert result.exit_code == errors.EXIT_USAGE and "PAF-" not in result.output
