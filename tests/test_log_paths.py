"""Where the log may be written, and who may read it (PF-05, PF-16, PF-17, PF-27.12).

A wrong ``PEEK_A_FOXY_LOG`` or ``--log-file`` must cost a warning on stderr and nothing else: not a
deleted or appended-to user file, not a hang, not a corrupted ``--json``, not a "bug" report.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from support import WINDOWS, needs_symlinks
from typer.testing import CliRunner

from peek_a_foxy import errors, logs
from peek_a_foxy.cli import app

runner = CliRunner()

RECORD = "2026-01-01T00:00:00Z INFO    abcd1234 run started: x\n"
needs_fifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")


def cli(
    *args: str, log: str | None = None, home: Path | None = None
) -> subprocess.CompletedProcess:
    environment = {**os.environ, "PEEK_A_FOXY_LOG": log if log is not None else "off"}
    if home is not None:
        environment["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", *args],
        env=environment,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


@pytest.fixture
def unwritable_log(tmp_path: Path) -> str:
    """A log path whose folder cannot be created: a file is in the way."""
    (tmp_path / "in-the-way").write_text("a file")
    return str(tmp_path / "in-the-way" / "x.log")


# --- PF-05: stdout is for the product -------------------------------------------------------------


def test_doctor_json_stays_json_when_the_log_cannot_be_written(unwritable_log: str, tmp_path: Path):
    done = cli("doctor", "--json", log=unwritable_log, home=tmp_path)
    assert json.loads(done.stdout)["schema"] == 1  # the old output began with "warning: ..."
    assert "could not write the log file" in done.stderr


def test_doctor_markdown_starts_with_its_title_when_the_log_cannot_be_written(
    unwritable_log: str, tmp_path: Path
):
    done = cli("doctor", "--markdown", log=unwritable_log, home=tmp_path)
    assert done.stdout.startswith("# Peek-a-Foxy doctor report")
    assert "could not write the log file" in done.stderr


def test_every_warning_goes_to_stderr_and_the_plan_stays_on_stdout(
    unwritable_log: str, profile: Path
):
    done = cli(
        "install", "--profile", str(profile), "--skip-loader", "--dry-run", log=unwritable_log
    )
    assert "could not write the log file" in done.stderr
    assert "warning:" not in done.stdout
    assert (
        "Dry run: none of your files was changed" in done.stdout
    )  # the plan, the product of this command


def test_a_conflict_warning_of_a_real_install_is_on_stderr(
    profile: Path, firefox_dir: Path, fxac_repo
):
    (firefox_dir / "config.js").write_text("// somebody else's setup\n")
    done = cli(
        "install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"
    )  # a real process: the runner of Click 8.1 cannot keep the two streams apart
    assert done.returncode == 0, done.stderr
    assert "warning:" in done.stderr and "warning:" not in done.stdout


# --- PF-16: ~name ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["~nosuchuser_zz/x.log", "~nosuchuser_zz"])
def test_a_tilde_name_in_the_environment_is_a_warning_not_a_bug(value: str, tmp_path: Path):
    done = cli("doctor", "--json", log=value, home=tmp_path)
    assert done.returncode in (0, 1), done.stderr
    assert "PAF-900" not in done.stderr and "Traceback" not in done.stderr
    assert json.loads(done.stdout)["schema"] == 1
    assert "PEEK_A_FOXY_LOG could not be used" in done.stderr


def test_a_tilde_name_in_the_flag_is_a_coded_error(tmp_path: Path):
    done = cli("doctor", "--log-file", "~nosuchuser_zz/x.log", home=tmp_path)
    assert done.returncode == 1 and errors.FILE_IO.code in done.stderr
    assert "PAF-900" not in done.stderr and "Traceback" not in done.stderr


def test_a_tilde_name_for_save_is_refused_before_the_report_is_made(tmp_path: Path):
    done = cli("doctor", "--json", "--save", "~nosuchuser_zz/r.json", home=tmp_path)
    assert done.returncode == 1 and errors.FILE_IO.code in done.stderr
    assert done.stdout == ""  # nothing printed and then lost
    assert "PAF-900" not in done.stderr and "Traceback" not in done.stderr


def test_the_logs_command_explains_a_tilde_environment_variable(tmp_path: Path):
    done = cli("logs", log="~nosuchuser_zz/x.log", home=tmp_path)
    assert done.returncode == 0, done.stderr
    assert "could not be used" in done.stdout and "turned off" not in done.stdout


def test_a_home_that_cannot_be_worked_out_is_the_same_kind_of_error(monkeypatch):
    def no_home(self):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "expanduser", no_home)
    with pytest.raises(errors.UserFileError):
        logs.expand_user("~/x.log")


# --- PF-17: the log path can be any file ----------------------------------------------------------


def test_clear_does_not_delete_a_file_that_is_not_a_log(tmp_path: Path):
    settings = tmp_path / "user.js"
    settings.write_text('user_pref("a", true);\n')
    (tmp_path / "user.js.1").write_text("x")
    result = runner.invoke(app, ["logs", "--clear", "--yes", "--log-file", str(settings)])
    assert result.exit_code == 0, result.output
    assert settings.read_text() == 'user_pref("a", true);\n' and (tmp_path / "user.js.1").exists()
    assert "Deleted" not in result.output


def test_clear_still_deletes_the_log_and_its_rotated_copies(tmp_path: Path):
    path = tmp_path / "peek-a-foxy.log"
    for suffix in ("", ".1", ".2"):
        (tmp_path / f"peek-a-foxy.log{suffix}").write_text(RECORD)
    result = runner.invoke(app, ["logs", "--clear", "--yes", "--log-file", str(path)])
    assert "Deleted 3 log file(s)" in result.output and not list(tmp_path.iterdir())


def test_the_environment_variable_does_not_append_log_text_to_a_settings_file(tmp_path: Path):
    settings = tmp_path / "user.js"
    settings.write_text('user_pref("a", true);\n')
    done = cli("doctor", "--json", log=str(settings), home=tmp_path)
    assert settings.read_text() == 'user_pref("a", true);\n'  # not one line was added
    assert "is not a log of Peek-a-Foxy" in done.stderr
    assert json.loads(done.stdout)["schema"] == 1


def test_an_empty_file_and_an_old_log_are_accepted_as_a_log(tmp_path: Path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    old = tmp_path / "old.log"
    old.write_text(RECORD)
    assert logs.unusable_reason(empty) is None and logs.unusable_reason(old) is None
    assert logs.unusable_reason(tmp_path / "missing.log") is None


@needs_fifo
def test_a_named_pipe_as_the_log_is_refused_and_does_not_wait_for_a_reader(tmp_path: Path):
    fifo = tmp_path / "pipe.log"
    os.mkfifo(fifo)
    done = cli("doctor", "--json", log=str(fifo), home=tmp_path)  # opening it would block for good
    assert "is not a regular file" in done.stderr and json.loads(done.stdout)["schema"] == 1


@needs_symlinks
def test_a_link_to_a_settings_file_is_refused_as_a_log(tmp_path: Path):
    settings = tmp_path / "user.js"
    settings.write_text("x\n")
    link = tmp_path / "link.log"
    link.symlink_to(settings)
    assert "not a log" in (logs.unusable_reason(link) or "")


# --- PF-27.12: only this account reads the log ----------------------------------------------------


@pytest.mark.skipif(WINDOWS, reason="Windows ignores POSIX modes")
def test_a_new_log_and_its_new_folder_are_private(tmp_path: Path):
    target = tmp_path / "new-folder" / "x.log"
    old_umask = os.umask(0o022)  # the common default, which would make them 0644 and 0755
    try:
        logs.start(target=target, verbose=False, argv=[], version="1")
        logs.stop(0)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(WINDOWS, reason="Windows ignores POSIX modes")
def test_the_file_that_a_rotation_starts_is_private_as_well(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 400)
    target = tmp_path / "x.log"
    old_umask = os.umask(0o022)
    try:
        logs.start(target=target, verbose=False, argv=[], version="1")
        for number in range(30):
            logging.getLogger("peek_a_foxy.test").info("line %d %s", number, "x" * 50)
        logs.stop(0)
    finally:
        os.umask(old_umask)
    rotated = list(tmp_path.glob("x.log*"))
    assert len(rotated) >= 2  # it did rotate
    assert {stat.S_IMODE(path.stat().st_mode) for path in rotated} == {0o600}
