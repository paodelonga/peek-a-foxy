"""The help texts: each option says what it does for that command, and wraps like prose."""

from __future__ import annotations

from typing import Any

import pytest
from support import flat, plain
from typer.main import get_command
from typer.testing import CliRunner

from peek_a_foxy.cli import app

runner = CliRunner()
COMMANDS = ("install", "uninstall", "logs", "doctor")


def help_at(monkeypatch, width: int, *args: str) -> str:
    """The ``--help`` text as a terminal ``width`` columns wide draws it (colours removed)."""
    from typer import rich_utils

    monkeypatch.setattr(rich_utils, "MAX_WIDTH", width, raising=False)
    result = runner.invoke(app, [*args, "--help"])
    assert result.exit_code == 0, result.output
    return plain(result.output)


def option_help(monkeypatch, command: str, option: str, width: int = 200) -> str:
    """The text of one option's help, as the reader sees it in the box, in one line."""
    text = help_at(monkeypatch, width, command)
    rows = [line for line in text.splitlines() if f" {option} " in f" {flat(line)} "]
    assert rows, text
    start = text.splitlines().index(rows[0])
    block = [text.splitlines()[start]]
    for line in text.splitlines()[start + 1 :]:
        if line.strip("│ ").startswith("-"):
            break
        block.append(line)
    return flat(" ".join(block))


def walk(command: Any, path: tuple[str, ...] = ()):
    yield path, command
    for name, child in getattr(command, "commands", {}).items():
        yield from walk(child, (*path, name))


def test_no_help_text_has_a_line_break_inside_a_paragraph():
    # A hard break in the source shows in the list of commands as a short, ragged line.
    for path, command in walk(get_command(app)):
        for text in (command.help, *(getattr(p, "help", None) for p in command.params)):
            assert not text or "\n" not in text, (path, text)


def test_the_doctor_description_is_one_unbroken_sentence_pair():
    doctor = get_command(app).commands["doctor"]  # type: ignore[attr-defined]
    assert doctor.help == (
        "Checks this computer and tells you what is in the way of Peek-a-Foxy. Nothing is changed "
        "or sent anywhere; only the local log is written (use --no-log to avoid that)."
    )


def test_logs_yes_is_about_confirming_the_deletion(monkeypatch):
    said = option_help(monkeypatch, "logs", "--yes")
    assert "--clear" in said and "without asking" in said
    for wrong in ("profile", "Firefox", "apply", "installation"):
        assert wrong not in said, said


def test_logs_log_file_is_the_file_to_look_at_not_the_one_to_write(monkeypatch):
    said = option_help(monkeypatch, "logs", "--log-file")
    assert (
        said.count("--log-file") == 1 and "Write" not in said and "instead of the default" in said
    )


def test_uninstall_yes_does_not_mention_a_firefox_it_never_looks_for(monkeypatch):
    said = option_help(monkeypatch, "uninstall", "--yes")
    assert "profile" in said and "Firefox" not in said, said


def test_install_yes_still_covers_the_profile_and_the_firefox_choice(monkeypatch):
    said = option_help(monkeypatch, "install", "--yes")
    assert "profile" in said and "Firefox installation" in said


@pytest.mark.parametrize("width", [80, 120])  # at 60 columns --allow-unverified-loader cannot fit
@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_help_fits_and_keeps_every_option_name_whole(monkeypatch, width, command):
    text = help_at(monkeypatch, width, command)
    assert all(len(line) <= width for line in text.splitlines())
    for line in text.splitlines():  # a name that Rich had to shorten ends in an ellipsis
        assert not any(w.startswith("--") and w.endswith("\u2026") for w in line.split()), line
