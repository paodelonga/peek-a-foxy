"""Failures at the command line: code, what to do, exit codes, the log, the ``logs`` command."""

from __future__ import annotations

import errno
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from peek_a_foxy import cli, errors, logs
from peek_a_foxy.cli import app

runner = CliRunner()


@pytest.fixture
def log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Turn the log on, in a throwaway place (the suite default is off)."""
    path = tmp_path / "logs" / "peek-a-foxy.log"
    monkeypatch.setenv(logs.ENV_VAR, str(path))
    return path


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


def test_verbose_adds_the_technical_detail_and_the_cause(profile: Path):
    bad_utf8(profile)
    result = install(profile, "--verbose")
    assert result.exit_code == 1
    assert "Details: UnicodeDecodeError" in result.output
    assert "Caused by: UnicodeDecodeError" in result.output


def test_the_error_says_where_the_log_is_when_there_is_one(profile: Path, log_file: Path):
    bad_utf8(profile)
    result = install(profile)
    assert f"Details were saved to {log_file}" in result.output
    assert "[PAF-401]" in log_file.read_text(encoding="utf-8")
    assert "Traceback" in log_file.read_text(encoding="utf-8")  # the log keeps the traceback


def test_no_log_path_is_promised_when_logging_is_off(profile: Path):
    bad_utf8(profile)
    assert "Details were saved" not in install(profile).output


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


def test_an_unexpected_error_is_paf_900_with_exit_code_70(
    profile: Path, log_file: Path, monkeypatch
):
    blow_up(monkeypatch, ValueError("boom"))
    result = install(profile)
    assert result.exit_code == errors.EXIT_UNEXPECTED == 70
    assert "error [PAF-900]: Something unexpected went wrong" in result.output
    assert "this is a bug in Peek-a-Foxy" in result.output
    assert (
        errors.ISSUES_URL in result.output and f"Details were saved to {log_file}" in result.output
    )
    assert "Traceback" not in result.output and "boom" not in result.output
    logged = log_file.read_text(encoding="utf-8")
    assert "unexpected error [PAF-900]" in logged and "ValueError: boom" in logged


def test_verbose_prints_the_traceback_of_a_bug_but_never_local_variables(
    profile: Path, monkeypatch
):
    def explode(*args, **kwargs):
        secret_local = "a-value-held-in-a-local-variable"  # noqa: F841
        raise ValueError("boom")

    monkeypatch.setattr(cli, "plan_install", explode)
    result = install(profile, "-v")
    assert result.exit_code == 70
    assert "Traceback" in result.output and "ValueError: boom" in result.output
    assert "a-value-held-in-a-local-variable" not in result.output


def test_typer_is_told_never_to_show_locals():
    assert cli.app.pretty_exceptions_show_locals is False


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


def test_an_interrupt_is_not_a_bug(profile: Path, log_file: Path, monkeypatch):
    blow_up(monkeypatch, KeyboardInterrupt())
    result = install(profile)
    assert "PAF-900" not in result.output
    assert "exit code 130" in log_file.read_text(encoding="utf-8")


def test_a_wrong_option_is_a_usage_error_with_exit_code_2(profile: Path):
    result = runner.invoke(app, ["install", "--no-such-option"])
    assert result.exit_code == errors.EXIT_USAGE and "PAF-" not in result.output
    assert runner.invoke(app, ["logs", "--open", "--clear"]).exit_code == 2


# --- the flags ----------------------------------------------------------------------------------


def test_a_successful_run_is_logged_with_its_steps_and_how_it_ended(profile: Path, log_file: Path):
    assert install(profile).exit_code == 0
    text = log_file.read_text(encoding="utf-8")
    assert "run started: peek-a-foxy" in text and "--skip-loader" in text
    assert re.search(r"step 1/3: Copy autohide\.css", text)
    assert re.search(r"step 3/3 done in \d+\.\d\d s", text)
    assert "run finished: exit code 0" in text


def test_the_commands_of_the_loader_are_logged_with_their_exit_codes(
    profile: Path, firefox_dir: Path, fxac_repo: Path, log_file: Path
):
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 0, result.output
    text = log_file.read_text(encoding="utf-8")
    assert re.search(r"running: git .*fetch", text) and "git fetch exited with 0" in text
    assert "git checkout exited with 0" in text


def test_a_failing_command_is_logged_with_its_exit_code(
    profile: Path, firefox_dir: Path, fxac_repo: Path, log_file: Path, monkeypatch
):
    monkeypatch.setenv("FXAC_COMMIT", "1" * 40)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 1 and "error [PAF-202]" in result.output
    assert re.search(r"ERROR\s+\w+ git \w+ exited with \d+", log_file.read_text(encoding="utf-8"))


def test_each_run_has_its_own_id(profile: Path, log_file: Path):
    install(profile)
    install(profile)
    ids = re.findall(r"Z \w+\s+(\w{8}) run started", log_file.read_text(encoding="utf-8"))
    assert len(ids) == 2 and ids[0] != ids[1]


@pytest.mark.parametrize("position", ["before", "after"])
def test_verbose_works_before_and_after_the_command_name(profile: Path, position: str):
    base = ["install", "--profile", str(profile), "--skip-loader", "--yes"]
    args = ["-v", *base] if position == "before" else [*base, "-v"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0 and re.search(r"INFO\s+step 1/3", result.output)
    assert "DEBUG" in result.output
    quiet = runner.invoke(app, base)
    assert "DEBUG" not in quiet.output and "INFO" not in quiet.output


def test_log_file_and_no_log_before_and_after_the_command(profile: Path, tmp_path: Path):
    mine = tmp_path / "mine.log"
    assert (
        runner.invoke(
            app,
            ["--log-file", str(mine), "install", "--profile", str(profile), "--skip-loader", "-y"],
        ).exit_code
        == 0
    )
    assert "run started" in mine.read_text(encoding="utf-8")
    later = tmp_path / "later.log"
    install(profile, "--log-file", str(later))
    assert later.is_file()
    off = tmp_path / "off.log"
    install(profile, "--log-file", str(off), "--no-log")
    runner.invoke(
        app, ["--no-log", "uninstall", "--profile", str(profile), "-y", "--log-file", str(off)]
    )
    assert not off.exists()


def test_the_environment_variable_turns_the_log_off_or_picks_a_file(
    profile: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv(logs.ENV_VAR, "off")
    install(profile)
    assert not any(tmp_path.glob("**/*.log"))
    chosen = tmp_path / "env.log"
    monkeypatch.setenv(logs.ENV_VAR, str(chosen))
    install(profile)
    assert chosen.is_file()
    mine = tmp_path / "flag.log"
    install(profile, "--log-file", str(mine))  # the flag wins over the variable
    assert mine.is_file() and chosen.read_text(encoding="utf-8").count("run started") == 1


def test_an_unwritable_log_never_breaks_the_command(profile: Path, tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    result = install(profile, "--log-file", str(blocker / "x.log"))
    assert result.exit_code == 0, result.output
    assert "warning: could not write the log file" in result.output
    assert (profile / "chrome" / "autohide.css").is_file()


def test_the_log_never_holds_the_home_folder(profile: Path, log_file: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(
        logs.Redactor,
        "for_this_machine",
        lambda *a, **k: logs.Redactor(home=str(tmp_path), user=None),
    )
    install(profile)
    text = log_file.read_text(encoding="utf-8")
    # Whatever the spelling (either slash, doubled backslashes, any case) and the system's
    # separator: on Windows the redacted path is "~\\profile\\chrome", not "~/profile/chrome".
    flat = re.sub(r"[\\/]+", "/", text).lower()
    assert re.sub(r"[\\/]+", "/", str(tmp_path)).lower() not in flat
    assert "~/profile/chrome" in flat


# --- the logs command ---------------------------------------------------------------------------


def test_logs_says_there_is_no_log_yet(log_file: Path):
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert f"Log file: {log_file}" in result.output and "No log yet" in result.output
    assert not log_file.exists()  # looking must not create it


def test_logs_shows_the_size_and_the_last_run(profile: Path, log_file: Path):
    install(profile)
    before = log_file.read_text(encoding="utf-8")
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert f"Log file: {log_file}" in result.output and "Size: " in result.output
    assert "Last run:" in result.output and "run finished: exit code 0" in result.output
    assert log_file.read_text(encoding="utf-8") == before  # the logs command does not log itself


def test_logs_folds_a_very_long_last_run(log_file: Path):
    logs.start(target=log_file, verbose=False, argv=[], version="1")
    for number in range(100):
        cli.log.info("line %d", number)
    logs.stop(0)
    result = runner.invoke(app, ["logs"])
    assert "lines not shown" in result.output and "line 99" in result.output
    assert "line 50" not in result.output


def test_logs_open_opens_the_folder(profile: Path, log_file: Path, monkeypatch):
    install(profile)
    opened: list[Path] = []
    monkeypatch.setattr(cli.logs, "open_folder", lambda folder: opened.append(folder) or True)
    result = runner.invoke(app, ["logs", "--open"])
    assert result.exit_code == 0 and opened == [log_file.parent]


def test_logs_open_that_fails_prints_the_folder_to_open_by_hand(
    profile: Path, log_file: Path, monkeypatch
):
    install(profile)
    monkeypatch.setattr(cli.logs, "open_folder", lambda folder: False)
    result = runner.invoke(app, ["logs", "--open"])
    assert result.exit_code == 0 and "could not open the folder" in result.output
    assert str(log_file.parent) in result.output


def test_logs_open_before_there_is_a_folder(log_file: Path, monkeypatch):
    monkeypatch.setattr(cli.logs, "open_folder", lambda folder: pytest.fail("nothing to open"))
    result = runner.invoke(app, ["logs", "--open"])
    assert result.exit_code == 0 and "no log folder yet" in result.output


def test_logs_clear_deletes_after_a_yes(profile: Path, log_file: Path):
    install(profile)
    result = runner.invoke(app, ["logs", "--clear", "--yes"])
    assert result.exit_code == 0 and "Deleted 1 log file(s)." in result.output
    assert not log_file.exists()
    assert "there is no log yet" in runner.invoke(app, ["logs", "--clear", "--yes"]).output


def test_logs_clear_asks_first_and_a_no_keeps_the_files(profile: Path, log_file: Path, monkeypatch):
    install(profile)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    refused = runner.invoke(app, ["logs", "--clear"], input="n\n")
    assert refused.exit_code == 1 and log_file.is_file()
    accepted = runner.invoke(app, ["logs", "--clear"], input="y\n")
    assert accepted.exit_code == 0 and not log_file.exists()


def test_logs_clear_without_a_terminal_needs_yes(profile: Path, log_file: Path, monkeypatch):
    install(profile)
    monkeypatch.setattr(cli, "_interactive", lambda yes: False)
    result = runner.invoke(app, ["logs", "--clear"])
    assert result.exit_code == 1 and "error [PAF-502]" in result.output and log_file.is_file()


def test_logs_follows_the_log_file_flag_and_notes_when_logging_is_off(tmp_path: Path, monkeypatch):
    mine = tmp_path / "mine.log"
    logs.start(target=mine, verbose=False, argv=["x"], version="1")
    logs.stop(0)
    assert f"Log file: {mine}" in runner.invoke(app, ["--log-file", str(mine), "logs"]).output
    off = runner.invoke(app, ["logs"])  # the suite sets PEEK_A_FOXY_LOG=off
    assert "Logging is turned off" in off.output and "peek-a-foxy" in off.output


def test_logs_without_a_home_folder_says_there_is_no_log_location(
    monkeypatch: pytest.MonkeyPatch,
):
    def nowhere(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(nowhere))
    monkeypatch.delenv(logs.ENV_VAR, raising=False)
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0 and "PAF-900" not in result.output
    assert "No log location is available" in result.output
