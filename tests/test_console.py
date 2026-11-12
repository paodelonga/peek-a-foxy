"""Legacy Windows consoles (code page 1252, no UTF-8): nothing may crash on an emoji or a path."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from peek_a_foxy import cli, ui
from peek_a_foxy.cli import app


def console_with(encoding: str) -> Console:
    stream = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
    return Console(file=stream)


@pytest.mark.parametrize(
    ("encoding", "shown"), [("utf-8", True), ("cp1252", False), ("ascii", False)]
)
def test_the_fox_is_only_shown_where_it_can_be_printed(monkeypatch, encoding, shown):
    monkeypatch.setattr(ui, "has_emoji_font", lambda: True)
    monkeypatch.setattr(ui, "console", console_with(encoding))
    assert ui.can_print("\U0001f98a") is shown
    assert (ui.fox() != "") is shown
    assert ui.can_print("plain text")


def test_a_console_without_an_encoding_is_assumed_to_be_utf8(monkeypatch):
    class NoEncoding:
        encoding = None

    monkeypatch.setattr(ui, "console", NoEncoding())
    assert ui.can_print("\U0001f98a")


def test_the_streams_replace_what_they_cannot_encode(monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", io.StringIO())  # has no reconfigure(): must be tolerated
    ui.setup_streams()
    stream.write("fox \U0001f98a")  # would raise UnicodeEncodeError before
    stream.flush()
    assert stream.buffer.getvalue() == b"fox ?"  # type: ignore[attr-defined]


def test_the_closing_panel_has_no_emoji_when_the_console_cannot_show_it(monkeypatch):
    monkeypatch.setattr(ui, "console", console_with("cp1252"))
    _title, body = cli.done_summary(skipped_loader=False, loader_conflict=False)
    assert "\U0001f98a" not in body and "PEEK-A-BOO!" in body and "youtu.be" in body


@pytest.mark.parametrize(
    ("platform", "env", "drawn"),
    [
        ("linux", {}, True),
        ("darwin", {}, True),
        ("win32", {}, False),  # the classic console: an empty box instead of the fox
        ("win32", {"WT_SESSION": "1"}, True),
        ("win32", {"TERM_PROGRAM": "vscode"}, True),
        ("win32", {"WT_SESSION": ""}, False),  # set but empty is not set
    ],
)
def test_the_fox_needs_a_terminal_that_draws_emoji(monkeypatch, platform, env, drawn):
    for name in ("WT_SESSION", "TERM_PROGRAM", "ConEmuPID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ui.sys, "platform", platform)
    monkeypatch.setattr(ui, "console", console_with("utf-8"))
    assert (ui.fox() != "") is drawn
    # Whatever the terminal, the link after it is still printed.
    assert "youtu.be" in cli.done_summary(False, False)[1]


def test_the_closing_panel_has_the_fox_in_utf8(monkeypatch):
    monkeypatch.setattr(ui, "has_emoji_font", lambda: True)
    monkeypatch.setattr(ui, "console", console_with("utf-8"))
    assert "\U0001f98a" in cli.done_summary(False, False)[1]


def test_a_full_install_survives_a_cp1252_pipe(profile: Path, firefox_dir: Path, fxac_repo: Path):
    """The real command, its output piped through the Windows legacy code page."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    env.pop("FORCE_COLOR", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "peek_a_foxy",
            "install",
            "--profile",
            str(profile),
            "--firefox-dir",
            str(firefox_dir),
            "--yes",
        ],
        capture_output=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr.decode("cp1252", "replace")
    assert b"Traceback" not in result.stderr
    assert b"PEEK-A-BOO" in result.stdout


def test_the_no_terminal_error_mentions_winpty_on_windows_only(profile: Path, monkeypatch):
    runner = CliRunner()
    args = ["install", "--profile", str(profile), "--skip-loader"]
    monkeypatch.setattr(cli, "_interactive", lambda yes: False)
    monkeypatch.setattr(cli.platform, "is_windows", lambda: True)
    windows = runner.invoke(app, args).output
    monkeypatch.setattr(cli.platform, "is_windows", lambda: False)
    elsewhere = runner.invoke(app, args).output
    assert "winpty" in windows and "--yes" in windows
    assert "winpty" not in elsewhere and "--yes" in elsewhere
