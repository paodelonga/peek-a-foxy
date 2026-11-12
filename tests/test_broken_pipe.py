"""A reader that goes away (``| head -c1``), a closed stream or a full disk, for every command.

The rule: output that cannot be written is lost quietly, work that was started still finishes (a
half-done install because of ``| head`` would be the worst outcome), and no command prints a
traceback or "Exception ignored" at exit. Commands whose whole product is text (``logs``,
``doctor``) end with the failure exit code when the text did not arrive.

The tests with real subprocesses run ``python -m peek_a_foxy`` and are POSIX only (``head``, a
closed descriptor, ``/dev/full``).
"""

from __future__ import annotations

import errno
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from doctor_support import make_firefox, make_profile
from support import WINDOWS
from typer.testing import CliRunner

from peek_a_foxy import cli, errors, ui
from peek_a_foxy.cli import app

SRC = str(Path(__file__).resolve().parents[1] / "src")
posix_only = pytest.mark.skipif(WINDOWS, reason="uses head, a closed descriptor or /dev/full")
CSS = "autohide.css"
NOISE = ("Traceback", "Exception ignored", "BrokenPipe", "Broken pipe", "Errno", "PAF-9")


def env(home: Path) -> dict[str, str]:
    values = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    values["NO_COLOR"] = "1"
    values["PYTHONUTF8"] = "1"
    for name in ("XDG_STATE_HOME", "XDG_CACHE_HOME"):
        values.pop(name, None)
    return values


def command(*args: str) -> list[str]:
    return [sys.executable, "-m", "peek_a_foxy", *args]


def quiet(text: str) -> None:
    assert not any(word in text for word in NOISE), text


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def work(profile: Path) -> list[str]:
    """The arguments of an install that changes files and prints a lot."""
    return ["install", "--skip-loader", "--yes", "--profile", str(profile)]


def run_with_closed_reader(home: Path, args: list[str]) -> tuple[int, str]:
    """stdout is a pipe whose reading end is closed before the program writes anything."""
    with subprocess.Popen(
        command(*args), env=env(home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        process.stdout.close()
        stderr = process.stderr.read()
        return process.wait(timeout=120), stderr


# --- the work still gets done ------------------------------------------------------------------


@posix_only
def test_an_install_whose_output_nobody_reads_still_installs_everything(
    home: Path, profile: Path, work: list[str]
):
    code, stderr = run_with_closed_reader(home, work)
    assert code == 0, stderr
    quiet(stderr)
    assert (profile / "chrome" / CSS).is_file()
    assert (profile / "chrome" / "userChrome.css").read_text().startswith("@import")
    assert "peekafoxy" not in (profile / "user.js").read_text()
    assert "legacyUserProfileCustomizations" in (profile / "user.js").read_text()


@posix_only
def test_head_c1_does_not_cut_an_install_short(home: Path, profile: Path, work: list[str]):
    """The real thing: ``peek-a-foxy install ... | head -c1``."""
    if shutil.which("head") is None:
        pytest.skip("no head")
    with (
        subprocess.Popen(
            command(*work),
            env=env(home),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as producer,
        subprocess.Popen(
            ["head", "-c1"], stdin=producer.stdout, stdout=subprocess.PIPE, text=True
        ) as head,
    ):
        assert producer.stdout is not None
        producer.stdout.close()
        shown = head.communicate(timeout=120)[0]
        stderr = producer.stderr.read() if producer.stderr else ""
        assert producer.wait(timeout=120) == 0 and len(shown) == 1
    quiet(stderr)
    assert (profile / "chrome" / CSS).is_file()
    assert (profile / "chrome" / "userChrome.css").is_file()


@posix_only
def test_an_uninstall_whose_output_nobody_reads_still_uninstalls(home: Path, profile: Path):
    cli_args = ["--yes", "--profile", str(profile)]
    assert run_with_closed_reader(home, ["install", "--skip-loader", *cli_args])[0] == 0
    code, stderr = run_with_closed_reader(home, ["uninstall", *cli_args])
    assert code == 0, stderr
    quiet(stderr)
    assert not (profile / "chrome" / CSS).exists()
    assert "@import" not in (profile / "chrome" / "userChrome.css").read_text()


@posix_only
def test_verbose_output_on_a_closed_stderr_pipe_does_not_stop_the_work(
    home: Path, profile: Path, work: list[str]
):
    with subprocess.Popen(
        command("-v", *work),
        env=env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stderr is not None and process.stdout is not None
        process.stderr.close()  # the verbose log goes to stderr: nobody reads it
        stdout = process.stdout.read()
        assert process.wait(timeout=120) == 0
    quiet(stdout)
    assert (profile / "chrome" / CSS).is_file()


@posix_only
def test_both_streams_closed_at_the_descriptor_level_still_install(
    home: Path, profile: Path, work: list[str]
):
    """``>&- 2>&-``: Python starts with no sys.stdout and no sys.stderr at all."""
    result = subprocess.run(
        ["sh", "-c", 'exec "$@" >&- 2>&-', "sh", *command(*work)],
        env=env(home),
        timeout=120,
        check=False,
    )
    assert result.returncode == 0
    assert (profile / "chrome" / CSS).is_file()


@posix_only
@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="Linux only")
def test_a_stdout_with_no_space_left_still_installs(home: Path, profile: Path, work: list[str]):
    with open("/dev/full", "wb") as full:
        result = subprocess.run(
            command(*work), env=env(home), stdout=full, stderr=subprocess.PIPE, timeout=120
        )
    assert result.returncode == 0, result.stderr
    quiet(result.stderr.decode())
    assert (profile / "chrome" / CSS).is_file()


# --- the failure of a command is still reported, and still the command's own -------------------


@posix_only
def test_an_error_whose_message_cannot_be_written_keeps_its_exit_code_and_is_quiet(
    home: Path, profile: Path, work: list[str]
):
    (profile / "chrome" / "userChrome.css").write_bytes(b"\xff\xfe")  # PAF-401
    with subprocess.Popen(
        command(*work), env=env(home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as process:
        assert process.stderr is not None and process.stdout is not None
        process.stderr.close()
        stdout = process.stdout.read()
        assert process.wait(timeout=120) == errors.EXIT_FAILURE
    quiet(stdout)


# --- commands whose product is the text --------------------------------------------------------


@posix_only
@pytest.mark.parametrize(
    "args",
    [["logs"], ["doctor", "--markdown"], ["doctor", "--json"]],
)
def test_a_report_nobody_reads_ends_quietly_with_the_failure_code(home: Path, args: list[str]):
    """The failure code must come from the lost output and from nothing else.

    In an empty home ``doctor`` exits 1 by itself (no Firefox, no profile), so this test used to
    pass for the wrong reason. Here the machine is healthy and a control run with a reader that
    stays proves that the same command exits 0.
    """
    if args[0] == "doctor":
        firefox = make_firefox(home / "firefox-install")
        profile = make_profile(home)
        args = [*args, "--profile", str(profile), "--firefox-dir", str(firefox)]
    control = subprocess.run(
        command(*args), env=env(home), capture_output=True, text=True, timeout=120, check=False
    )
    assert control.returncode == 0, control.stderr  # nothing wrong but the missing reader, below
    quiet(control.stderr)
    code, stderr = run_with_closed_reader(home, args)
    quiet(stderr)
    assert code == errors.EXIT_FAILURE, stderr


@posix_only
@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="Linux only")
def test_logs_to_a_full_disk_ends_quietly_with_the_failure_code(home: Path):
    with open("/dev/full", "wb") as full:
        result = subprocess.run(
            command("logs"), env=env(home), stdout=full, stderr=subprocess.PIPE, timeout=120
        )
    quiet(result.stderr.decode())
    assert result.returncode == errors.EXIT_FAILURE


@posix_only
@pytest.mark.parametrize("args", [["--version"], ["--help"], ["install", "--help"], ["--bogus"]])
def test_what_click_prints_itself_ends_quietly_too(home: Path, args: list[str]):
    """Help, version and usage errors are printed by Click and Typer, outside our commands."""
    code, stderr = run_with_closed_reader(home, args)
    quiet(stderr)
    assert code != 120, stderr  # 120 is Python failing to flush its stdout at exit


@posix_only
def test_a_usage_error_on_a_closed_stderr_pipe_is_quiet(home: Path):
    with subprocess.Popen(
        command("install", "--bogus"),
        env=env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stderr is not None and process.stdout is not None
        process.stderr.close()
        stdout = process.stdout.read()
        code = process.wait(timeout=60)
    quiet(stdout)
    assert code in (errors.EXIT_USAGE, errors.EXIT_FAILURE)


# --- in process: the seams ---------------------------------------------------------------------


class Broken(io.StringIO):
    """A stream that fails the way the given error says."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def write(self, text: str) -> int:
        raise self.error

    def flush(self) -> None:
        raise self.error


@pytest.fixture(autouse=True)
def _fresh_state():
    ui.reset_output_state()
    yield
    ui.reset_output_state()


@pytest.mark.parametrize(
    "error",
    [
        BrokenPipeError(errno.EPIPE, "Broken pipe"),
        OSError(errno.ENOSPC, "No space left on device"),
        OSError(errno.EIO, "Input/output error"),
        OSError(errno.EBADF, "Bad file descriptor"),
        OSError(errno.EINVAL, "Invalid argument"),  # what Windows may raise for a closed pipe
        ValueError("I/O operation on closed file"),
    ],
)
def test_output_that_cannot_be_written_is_lost_without_raising(error: BaseException):
    stream = Broken(error)
    for console in (ui._Console(file=stream), ui._Console(file=stream, stderr=True)):
        ui._print(console, "text")  # must not raise, and must not exit
    assert ui.output_lost()


def test_a_rich_console_does_not_end_the_program_on_a_broken_pipe():
    """Rich itself raises SystemExit(1) in print(); that would stop a half-done install."""
    console = ui._Console(file=Broken(BrokenPipeError(errno.EPIPE, "Broken pipe")))
    console.print("hello")  # no SystemExit
    assert ui.output_lost() and console.quiet


def test_output_that_works_is_not_marked_lost():
    ui._print(ui._Console(file=io.StringIO()), "fine")
    assert not ui.output_lost()


def test_each_run_starts_with_output_not_lost():
    ui.lost_output(None)
    assert ui.output_lost()
    CliRunner().invoke(app, ["--version"])
    assert not ui.output_lost()


def test_the_verbose_log_handler_gives_up_quietly_on_a_broken_pipe():
    import logging

    handler = ui.QuietStreamHandler(Broken(BrokenPipeError(errno.EPIPE, "Broken pipe")))
    logger = logging.getLogger("peek_a_foxy.test_broken_pipe")
    logger.addHandler(handler)
    try:
        logger.error("one")  # would print "--- Logging error ---" without the override
        logger.error("two")
    finally:
        logger.removeHandler(handler)
    assert ui.output_lost()


def test_a_non_output_error_in_the_verbose_handler_is_still_reported_by_logging(
    capsys: pytest.CaptureFixture[str],
):
    import logging

    class Bad:
        def write(self, text: str) -> None:
            raise RuntimeError("not a stream error")

        def flush(self) -> None:
            pass

    handler = ui.QuietStreamHandler(Bad())  # type: ignore[arg-type]
    logger = logging.getLogger("peek_a_foxy.test_broken_pipe_2")
    logger.addHandler(handler)
    try:
        logger.error("x")
    finally:
        logger.removeHandler(handler)
    assert "Logging error" in capsys.readouterr().err


def test_silencing_a_stream_without_a_descriptor_does_nothing_harmful():
    ui.silence(None)
    ui.silence(io.StringIO())  # fileno() raises: nothing to redirect


def test_a_pipe_error_that_reaches_the_failure_handler_is_quiet_with_the_failure_code(
    monkeypatch,
):
    monkeypatch.setattr(cli.ui, "silence", lambda stream: None)
    code = cli._handle_failure(BrokenPipeError(errno.EPIPE, "Broken pipe"))
    assert code == errors.EXIT_FAILURE


def test_an_oserror_from_click_itself_ends_the_program_quietly(monkeypatch):
    """Click prints help and usage errors; a failure of that printing is caught in main()."""
    from typer.core import TyperGroup

    def broken(self, *args, **kwargs):
        raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    monkeypatch.setattr(TyperGroup, "main", broken)
    monkeypatch.setattr(cli.ui, "silence", lambda stream: None)
    with pytest.raises(SystemExit) as caught:
        cli.app.registered_groups  # noqa: B018 - make sure the app is built
        cli._Group.main(cli._Group(name="x"), ["--help"])
    assert caught.value.code == errors.EXIT_FAILURE


def test_a_flush_that_fails_at_the_end_is_handled_before_the_interpreter_tries_again(monkeypatch):
    monkeypatch.setattr(sys, "stdout", Broken(BrokenPipeError(errno.EPIPE, "Broken pipe")))
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    cli._flush_quietly()
    assert ui.output_lost()


def test_a_flush_with_no_stdout_at_all_is_fine(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    cli._flush_quietly()
    assert not ui.output_lost()
