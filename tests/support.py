"""Helpers shared by the tests: which behaviours the current operating system can show."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

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


def squeezed(text: str) -> str:
    """``text`` without whitespace and box-drawing characters, however the error panel wrapped it.

    The rich panel wraps at 80 columns, so a long temporary path can land on a line break (and
    between two borders). A needle squeezed the same way is found wherever that break fell.
    """
    return "".join(c for c in text if not c.isspace() and not "\u2500" <= c <= "\u257f")


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return its output, whatever the developer's git is set up to do.

    A global ``commit.gpgsign=true``, a ``core.hooksPath``, a different default branch or a
    ``GIT_CONFIG_COUNT`` in the environment must not decide whether the suite can run.
    """
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")
    }
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0"
    )
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "-c",
            "init.defaultBranch=main",
            "-c",
            "core.hooksPath=" + os.devnull,
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


needs_posix_shell = pytest.mark.skipif(WINDOWS, reason="the fake sudo is a shell script")


def fake_sudo(folder: Path, record: Path, *, exit_code: int = 0) -> Path:
    """Put an executable ``sudo`` in ``folder`` that records what it was asked and ends with a code.

    ``record`` gets one file per call: ``<n>.args`` (one argument per line) and ``<n>.stdin``.
    Returns ``folder``, to be put first on ``PATH``. The real ``_sudo`` then runs against it, so
    what it passes to ``subprocess.run`` (``check=True``, the input) is tested, not a stand-in.
    """
    record.mkdir(parents=True, exist_ok=True)
    script = folder / "sudo"
    script.write_text(
        "#!/bin/sh\n"
        f'n=$(ls "{record}" | grep -c args)\n'
        f'printf "%s\\n" "$@" > "{record}/$n.args"\n'
        f'cat > "{record}/$n.stdin"\n'
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    return folder
