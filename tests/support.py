"""Helpers shared by the tests: which behaviours the current operating system can show."""

from __future__ import annotations

import os
import re
import sys

import pytest

WINDOWS = sys.platform == "win32"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0

# Directory permission bits are advisory on Windows (they only toggle a read-only flag on files),
# and root ignores them everywhere.
needs_permissions = pytest.mark.skipif(
    WINDOWS or IS_ROOT, reason="needs POSIX directory permissions, and not to be root"
)
# Creating symlinks needs a privilege that ordinary Windows users do not have.
needs_symlinks = pytest.mark.skipif(WINDOWS, reason="symlinks need a privilege on Windows")


# What decides whether (and how) a terminal program colours or wraps its output. A CI runner or a
# developer's shell may set any of them, and the tests compare plain text.
FORCING_COLOR = (
    "FORCE_COLOR",
    "CLICOLOR_FORCE",
    "PY_COLORS",
    "GITHUB_ACTIONS",  # Typer turns colours on when it sees it
    "TTY_COMPATIBLE",
    "TTY_INTERACTIVE",
    "TERMINAL_WIDTH",
    "JUPYTER_COLUMNS",
    "JUPYTER_LINES",
)
TEST_COLUMNS = 200  # wide enough for any help text or table row to stay on one line
TEST_LINES = 50


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def plain(text: str) -> str:
    """``text`` without the colour and style escape codes a terminal program may have added."""
    return _ANSI.sub("", text)


def flat(text: str) -> str:
    """``text`` as one line of single-spaced words: no escape codes, box borders or wrapping.

    Typer draws ``--help`` inside a box and wraps it to the terminal, so an option name or a
    sentence can be split by a border, a newline or padding; this puts it back together.
    """
    for border in "│╭╮╰╯─┃┏┓┗┛━┡┩┌┐└┘╞╡":
        text = plain(text).replace(border, " ")
    return " ".join(text.split())
