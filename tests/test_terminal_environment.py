"""The test suite does not depend on the terminal it runs in (colours, width, CI variables).

A CI runner sets ``GITHUB_ACTIONS`` and ``FORCE_COLOR``, which make Typer draw ``--help`` with
escape codes that split option names; a developer's shell has none of that, so the difference only
showed up on the runner. The autouse fixture in ``conftest.py`` removes it, and these tests prove
it does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from support import FORCING_COLOR, TEST_COLUMNS, flat, plain
from typer import rich_utils
from typer.testing import CliRunner

from peek_a_foxy.cli import app

ROOT = Path(__file__).resolve().parent.parent
# What Typer decided when it was imported, before any fixture ran.
FORCED_AT_IMPORT = rich_utils.FORCE_TERMINAL
FORCED = "PEEK_A_FOXY_TEST_TYPER_FORCED"  # set by the nested run: what Typer must have seen


def test_the_fixture_gives_every_test_a_plain_wide_terminal():
    if FORCED in os.environ:  # run by the test below, in a deliberately noisy environment
        forced = os.environ[FORCED] == "1"
        assert bool(FORCED_AT_IMPORT) is forced, "the noise did not reach Typer"
    for name in FORCING_COLOR:
        assert name not in os.environ
    assert os.environ["NO_COLOR"] == "1" and os.environ["TERM"] == "dumb"
    assert os.environ["COLUMNS"] == str(TEST_COLUMNS)
    assert rich_utils.FORCE_TERMINAL is False and rich_utils.COLOR_SYSTEM is None
    for command in (["--help"], ["install", "--help"], ["doctor", "--help"], ["logs", "--help"]):
        output = CliRunner().invoke(app, command).output
        assert "\x1b" not in output, command
        assert output == plain(output)
        assert max(len(line) for line in output.splitlines()) <= TEST_COLUMNS


def test_the_option_names_stay_in_one_piece_in_the_help():
    options = flat(CliRunner().invoke(app, ["doctor", "--help"]).output)
    for name in ("--save", "--json", "--copy"):
        assert name in options


@pytest.mark.parametrize(
    ("noise", "typer_forced"),
    [
        ({"FORCE_COLOR": "1", "TERM": "xterm-256color", "GITHUB_ACTIONS": "true", "CI": "true"}, 1),
        ({"PY_COLORS": "1", "CLICOLOR_FORCE": "1", "COLUMNS": "40", "LINES": "10"}, 1),
        (
            {"TERMINAL_WIDTH": "30", "TTY_COMPATIBLE": "1", "TTY_INTERACTIVE": "1", "NO_COLOR": ""},
            0,
        ),
    ],
    ids=["github-actions", "forced-colours-and-narrow", "typer-width-and-tty-flags"],
)
def test_a_noisy_environment_changes_nothing_for_the_tests(
    noise: dict[str, str], typer_forced: int
):
    """The check above, run by a second pytest started in an environment like a CI runner's."""
    # Start from what this process had before the fixture changed it, then add the noise.
    ours = {*FORCING_COLOR, "NO_COLOR", "TERM", "COLUMNS", "LINES", "_TYPER_FORCE_DISABLE_TERMINAL"}
    env = {k: v for k, v in os.environ.items() if k not in ours}
    env.update(noise, **{FORCED: str(typer_forced), "PYTHONPATH": str(ROOT / "src")})
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"{Path(__file__)}::test_the_fixture_gives_every_test_a_plain_wide_terminal",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, plain(result.stdout + result.stderr)
