"""``--install-completion`` must never change the PowerShell execution policy.

Typer's installer for PowerShell runs ``Set-ExecutionPolicy Unrestricted -Scope CurrentUser``
first, without asking. Peek-a-Foxy replaces it with a refusal; the other shells install as usual.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import shellingham
import typer
from support import flat
from typer import _completion_shared
from typer.testing import CliRunner

from peek_a_foxy import cli
from peek_a_foxy.cli import app

runner = CliRunner()
POWERSHELLS = ("powershell", "pwsh")


@pytest.fixture
def no_process(monkeypatch) -> list[object]:
    """Any program started from here is recorded and then fails the test."""
    started: list[object] = []

    def refuse(*args: object, **kwargs: object):
        started.append(args)
        raise AssertionError(f"a program was started: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    return started


def detected_shell(monkeypatch, name: str) -> None:
    """Make Typer believe that the terminal runs ``name``.

    Typer 0.16 calls ``shellingham.detect_shell()`` inside its ``install`` function, while newer
    releases go through a private helper of their own that calls the same function. The one name
    that both look up on the ``shellingham`` module at the moment they need it is the function
    itself, so that is what is replaced; Typer's private helpers are not relied on.
    """
    monkeypatch.setattr(shellingham, "detect_shell", lambda *a, **k: (name, f"/bin/{name}"))


def home() -> Path:
    return Path(os.environ["HOME"])


def nothing_written() -> bool:
    return not any(home().iterdir())


@pytest.mark.parametrize("shell", POWERSHELLS)
def test_the_detected_powershell_is_refused_without_starting_any_program(
    monkeypatch, no_process, shell
):
    detected_shell(monkeypatch, shell)
    result = runner.invoke(app, ["--install-completion"])
    shown = flat(result.output)
    assert no_process == [] and result.exit_code == 1, (result.output, result.exception)
    assert "Unrestricted" in shown and "will not make" in shown
    assert "--show-completion" in shown  # what to do instead
    assert nothing_written()  # the profile was not touched either


@pytest.mark.parametrize("shell", POWERSHELLS)
def test_a_powershell_named_on_the_command_line_is_refused_too(monkeypatch, no_process, shell):
    monkeypatch.setenv("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")  # the shell is an arg
    result = runner.invoke(app, ["--install-completion", shell])
    assert no_process == [] and result.exit_code == 1, (result.output, result.exception)
    assert "Unrestricted" in flat(result.output) and nothing_written()


@pytest.mark.parametrize("shell", POWERSHELLS)
def test_typers_own_installer_function_is_the_refusal(no_process, shell):
    with pytest.raises(typer.Exit) as stopped:
        _completion_shared.install(shell=shell, prog_name="peek-a-foxy")
    assert stopped.value.exit_code == 1
    assert no_process == [] and nothing_written()
    assert _completion_shared.install_powershell is cli._refuse_powershell_completion


@pytest.mark.parametrize("shell", ["PowerShell", "PWSH"])
def test_a_powershell_name_in_another_case_starts_nothing_either(monkeypatch, no_process, shell):
    # Newer Typer releases lower-case the detected name (and so reach the refusal); older ones
    # report it as an unsupported shell. Either way no program is started and nothing is written.
    detected_shell(monkeypatch, shell)
    result = runner.invoke(app, ["--install-completion"])
    assert no_process == [] and result.exit_code == 1 and nothing_written()


def test_a_real_run_with_no_programs_to_start_is_refused_not_crashed(tmp_path: Path):
    # The real entry point, with nothing on PATH: if the refusal were missing, Typer would try to
    # start PowerShell (and crash on a missing program), and could not be mistaken for a refusal.
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {
        **os.environ,
        "PATH": str(empty),
        "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1",
        "PEEK_A_FOXY_LOG": "off",
    }
    result = subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", "--install-completion", "pwsh"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stderr
    assert "Unrestricted" in flat(result.stderr) and "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("shell", "expected"),
    [
        ("bash", Path(".bash_completions") / "peek-a-foxy.sh"),
        ("zsh", Path(".zfunc") / "_peek-a-foxy"),
        ("fish", Path(".config") / "fish" / "completions" / "peek-a-foxy.fish"),
    ],
)
def test_the_other_shells_still_install(monkeypatch, shell, expected):
    detected_shell(monkeypatch, shell)
    result = runner.invoke(app, ["--install-completion"], prog_name="peek-a-foxy")
    assert result.exit_code == 0, (result.output, result.exception)
    assert (home() / expected).is_file()
    assert "Unrestricted" not in result.output


def test_the_install_completion_option_says_what_it_does_not_do():
    shown = flat(runner.invoke(app, ["--help"]).output)
    assert "--install-completion" in shown
    assert "bash, zsh or fish" in shown and "PowerShell" in shown and "--show-completion" in shown
