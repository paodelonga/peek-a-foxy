"""Adversarial tests of what the doctor sends out or starts: stdout, files, clipboard, git.

The ones with real subprocesses run ``python -m peek_a_foxy`` for real, with a throwaway HOME.
"""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import pytest
from doctor_support import (
    make_context,
    make_firefox,
    make_profile,
    pin_loader,
    real_home_environment,
    real_profiles_root,
    write,
)
from support import IS_ROOT, WINDOWS, needs_permissions, needs_symlinks
from typer.testing import CliRunner

from peek_a_foxy import cli, doctor, errors, logs, report
from peek_a_foxy.cli import app
from peek_a_foxy.errors import UserFileError
from peek_a_foxy.report import FAIL, OK, WARN

runner = CliRunner()
SRC = str(Path(__file__).resolve().parents[1] / "src")
posix_only = pytest.mark.skipif(WINDOWS, reason="uses a POSIX shell, signals or scripts")


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_loader(monkeypatch)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def fake_machine(monkeypatch: pytest.MonkeyPatch, home: Path, **overrides) -> None:
    firefox = make_firefox(home / "ff")
    values = {"firefox_candidates": lambda: [firefox], "environ": {"HOME": str(home)}}
    values.update(overrides)
    monkeypatch.setattr(
        doctor.Context, "detect", classmethod(lambda cls, **kw: make_context(home, **values))
    )


@pytest.fixture
def healthy(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    profile = make_profile(home)
    fake_machine(monkeypatch, home)
    return profile


def real(home: Path, *args: str, extra_env: dict | None = None, **kwargs):
    """Run the real program in a subprocess with a throwaway home."""
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": SRC,
        "PEEK_A_FOXY_LOG": "off",
        "NO_COLOR": "1",
        "PYTHONUTF8": "1",
        **(extra_env or {}),
    }
    for name in ("XDG_STATE_HOME", "XDG_CACHE_HOME"):
        env.pop(name, None)
    return subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        **kwargs,
    )


# --- stdout closed or broken (adversarial) -----------------------------------------------------


def test_a_reader_that_went_away_ends_the_run_quietly_in_process(
    healthy: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    def broken(*args, **kwargs):
        raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    monkeypatch.setattr(cli.typer, "echo", broken)
    monkeypatch.setattr(cli, "_silence_stdout", lambda: None)
    target = tmp_path / "kept.md"
    result = runner.invoke(app, ["doctor", "--save", str(target)])
    assert result.exit_code == errors.EXIT_FAILURE
    assert "Traceback" not in result.output and "PAF-900" not in result.output
    assert target.read_text(encoding="utf-8").startswith("# Peek-a-Foxy")  # still saved


@posix_only
def test_a_pipe_closed_before_the_report_is_written_is_not_a_traceback(home: Path):
    make_profile(home)
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    with subprocess.Popen(
        [sys.executable, "-m", "peek_a_foxy", "doctor", "--markdown"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout is not None
        process.stdout.close()  # nobody reads: the first write fails with EPIPE
        stderr = process.stderr.read() if process.stderr else ""
        process.wait(timeout=60)
    assert "Traceback" not in stderr and "BrokenPipe" not in stderr, stderr
    assert process.returncode in (0, 1)


@posix_only
def test_a_closed_stdout_still_saves_the_report(home: Path, tmp_path: Path):
    make_profile(home)
    target = tmp_path / "saved.json"
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    done = subprocess.run(
        f"{sys.executable} -m peek_a_foxy doctor --json --save {target} 1>&-",
        shell=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "Traceback" not in done.stderr, done.stderr
    assert json.loads(target.read_text(encoding="utf-8"))["schema"] == 1
    assert done.returncode in (0, 1)


@posix_only
def test_a_closed_stderr_does_not_break_a_run_that_prints_nothing_there(home: Path):
    make_profile(home)
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    done = subprocess.run(
        f"{sys.executable} -m peek_a_foxy doctor --json 2>&-",
        shell=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert json.loads(done.stdout)["schema"] == 1


# --- real runs: hostile environment, concurrency -----------------------------------------------


@posix_only
@pytest.mark.parametrize("value", ["", "/nonexistent/for/sure", "relative/home"])
def test_the_real_program_with_a_strange_home_still_reports(home: Path, value: str):
    done = real(home, "doctor", "--json", extra_env={"HOME": value, "USERPROFILE": value})
    assert "Traceback" not in done.stderr, done.stderr
    data = json.loads(done.stdout)
    assert data["schema"] == 1
    assert all(c["code"] != errors.UNEXPECTED.code for s in data["sections"] for c in s["checks"])
    assert done.returncode == (0 if data["ok"] else 1)


@posix_only
def test_the_real_program_outside_any_folder_it_can_see(home: Path, tmp_path: Path):
    gone = tmp_path / "gone"
    gone.mkdir()
    done = subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", "doctor", "--json"],
        cwd=gone,
        env={**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert json.loads(done.stdout)["schema"] == 1


def test_two_runs_at_once_share_a_log_and_both_succeed(home: Path, tmp_path: Path):
    make_profile(home)
    log = tmp_path / "shared.log"
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": str(log)}
    with ExitStack() as stack:
        processes = [
            stack.enter_context(
                subprocess.Popen(
                    [sys.executable, "-m", "peek_a_foxy", "doctor", "--json"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
            for _ in range(4)
        ]
        outputs = [process.communicate(timeout=120) for process in processes]
    for (stdout, stderr), process in zip(outputs, processes, strict=True):
        assert "Traceback" not in stderr, stderr
        assert json.loads(stdout)["schema"] == 1
        assert process.returncode in (0, 1)
    text = log.read_text(encoding="utf-8")
    assert text.count("run started:") == 4  # every run left its own start line, none was lost


def test_two_runs_at_once_never_save_to_the_same_name(home: Path, tmp_path: Path):
    make_profile(home)
    folder = tmp_path / "reports"
    folder.mkdir()
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    with ExitStack() as stack:
        processes = [
            stack.enter_context(
                subprocess.Popen(
                    [sys.executable, "-m", "peek_a_foxy", "doctor", "--save", str(folder)],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
            for _ in range(6)
        ]
        for process in processes:
            _, stderr = process.communicate(timeout=120)
            assert "Traceback" not in stderr and "PAF-403" not in stderr, stderr
    assert len(list(folder.glob("doctor-*.md"))) == 6


def test_a_profile_given_as_a_symlink_loop_is_reported_not_a_traceback(tmp_path: Path):
    if WINDOWS:
        pytest.skip("symlinks need a privilege on Windows")
    loop = tmp_path / "loop"
    os.symlink("loop", loop)
    for option in ("--profile", "--firefox-dir"):
        result = runner.invoke(app, ["doctor", "--json", option, str(loop)])
        assert result.exit_code == errors.EXIT_FAILURE, result.output
        assert "Traceback" not in result.output
        assert json.loads(result.output)["schema"] == 1


# --- saving (adversarial) ----------------------------------------------------------------------


def test_save_into_a_folder_that_cannot_be_written_is_a_coded_error_and_leaves_nothing(
    healthy: Path, tmp_path: Path
):
    if WINDOWS or IS_ROOT:
        pytest.skip("needs POSIX permissions, and not root")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        result = runner.invoke(app, ["doctor", "--save", str(locked / "r.md")])
    finally:
        locked.chmod(0o700)
    assert result.exit_code == errors.EXIT_FAILURE
    assert "error [PAF-402]" in result.output and "What to do:" in result.output
    assert list(locked.iterdir()) == []


def test_a_full_disk_leaves_no_half_written_report(
    healthy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class Full:
        def __init__(self, path):
            self.path = path
            open(path, "x").close()  # the file exists, as it does when a disk fills mid-write

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, text):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(report, "open", lambda path, *a, **k: Full(path), raising=False)
    target = tmp_path / "r.md"
    result = runner.invoke(app, ["doctor", "--save", str(target)])
    assert result.exit_code == errors.EXIT_FAILURE
    assert "error [PAF-402]" in result.output and "No space left" in result.output
    assert not target.exists()


@posix_only
def test_a_real_device_that_is_full_is_not_replaced_or_crashed_on(healthy: Path):
    if not Path("/dev/full").exists():
        pytest.skip("no /dev/full")
    result = runner.invoke(app, ["doctor", "--save", "/dev/full"])
    assert result.exit_code == errors.EXIT_FAILURE and "PAF-403" in result.output
    assert stat.S_ISCHR(os.stat("/dev/full").st_mode)  # still the device


def test_save_to_an_existing_directory_gets_a_dated_file_inside(healthy: Path, tmp_path: Path):
    target = tmp_path / "folder.md"  # a folder with a file's name
    target.mkdir()
    assert runner.invoke(app, ["doctor", "--save", str(target)]).exit_code == 0
    assert len(list(target.glob("doctor-*.md"))) == 1


def test_save_under_a_file_is_a_file_system_error_not_an_already_exists_claim(
    healthy: Path, tmp_path: Path
):
    (tmp_path / "plain").write_text("x")
    result = runner.invoke(app, ["doctor", "--save", str(tmp_path / "plain" / "r.md")])
    assert result.exit_code == errors.EXIT_FAILURE
    assert "PAF-402" in result.output and "PAF-403" not in result.output


def test_save_with_dot_dot_segments_goes_where_the_path_leads(healthy: Path, tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    result = runner.invoke(app, ["doctor", "--save", str(work / "sub" / ".." / "r.md")])
    assert result.exit_code == 0 and (work / "r.md").is_file()


@needs_symlinks
def test_save_never_writes_through_a_dangling_symlink(healthy: Path, tmp_path: Path):
    victim = tmp_path / "victim.md"
    link = tmp_path / "link.md"
    os.symlink(victim, link)
    result = runner.invoke(app, ["doctor", "--save", str(link)])
    assert result.exit_code == errors.EXIT_FAILURE and "PAF-403" in result.output
    assert not victim.exists()


@needs_symlinks
def test_save_never_writes_through_a_symlink_to_a_precious_file(healthy: Path, tmp_path: Path):
    precious = tmp_path / "precious.txt"
    precious.write_text("keep me")
    link = tmp_path / "link.md"
    os.symlink(precious, link)
    runner.invoke(app, ["doctor", "--save", str(link)])
    assert precious.read_text() == "keep me"


def test_a_save_name_with_odd_characters_works(healthy: Path, tmp_path: Path):
    target = tmp_path / "re port ‮ש é.md"
    try:
        result = runner.invoke(app, ["doctor", "--save", str(target)])
    except OSError:
        pytest.skip("this file system does not take that name")
    assert result.exit_code == 0 and target.read_text(encoding="utf-8").startswith("# Peek")


def test_sixteen_threads_saving_the_same_name_produce_exactly_one_file(tmp_path: Path):
    path = tmp_path / "same.md"
    results: list[object] = []
    barrier = threading.Barrier(16)

    def attempt(number: int) -> None:
        barrier.wait()
        try:
            report.save(f"writer {number}\n" * 1000, path)
            results.append("saved")
        except UserFileError as error:
            results.append(error.code.code)

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("saved") == 1
    assert results.count(errors.FILE_EXISTS.code) == 15
    lines = set(path.read_text().splitlines())
    assert len(lines) == 1  # one writer's text, whole, never a mix


def test_sixteen_threads_saving_under_the_default_name_take_sixteen_names(tmp_path: Path):
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    barrier = threading.Barrier(16)
    paths: list[Path] = []

    def attempt() -> None:
        barrier.wait()
        paths.append(report.save_new("x\n", tmp_path, "md", now))

    threads = [threading.Thread(target=attempt) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(paths)) == 16 and len(list(tmp_path.iterdir())) == 16


def test_default_names_give_up_politely_when_a_thousand_are_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    taken = tmp_path / "doctor-x.md"
    taken.write_text("old")
    monkeypatch.setattr(report, "default_save_path", lambda folder, suffix, now: taken)
    with pytest.raises(UserFileError) as caught:
        report.save_new("new", tmp_path, "md", datetime.now(timezone.utc))
    assert caught.value.code is errors.FILE_EXISTS and taken.read_text() == "old"


# --- the clipboard (adversarial) ---------------------------------------------------------------


def tool(tmp_path: Path, body: str) -> list[tuple[list[str], str]]:
    script = tmp_path / "tool.py"
    script.write_text(textwrap.dedent(body))
    return [([sys.executable, str(script)], "utf-8")]


@pytest.fixture
def use_tool(monkeypatch: pytest.MonkeyPatch):
    def install(commands):
        monkeypatch.setattr(report, "clipboard_commands", lambda kind, environ: commands)

    return install


def copy(text: str = "report") -> str | None:
    return report.copy_to_clipboard(text, "linux", {}, which=lambda name: name)


def test_a_clipboard_tool_that_hangs_is_given_up_on(
    tmp_path: Path, use_tool, monkeypatch: pytest.MonkeyPatch
):
    use_tool(tool(tmp_path, "import time; time.sleep(60)\n"))
    monkeypatch.setattr(report, "CLIPBOARD_TIMEOUT", 0.5)
    # No clock: a tool that was not stopped would sleep its minute away and exit 0 without having
    # read the report, which is a "success"; only a timeout makes this None.
    assert copy() is None


def test_a_clipboard_tool_that_exits_with_an_error_is_not_a_success(tmp_path: Path, use_tool):
    use_tool(tool(tmp_path, "import sys; sys.stdin.read(); sys.exit(3)\n"))
    assert copy() is None


def test_a_clipboard_tool_that_does_not_exist_is_not_a_crash(use_tool):
    use_tool([(["/no/such/clipboard-tool"], "utf-8")])
    assert copy() is None


def test_a_clipboard_tool_that_is_not_executable_is_not_a_crash(tmp_path: Path, use_tool):
    plain = tmp_path / "plain"
    plain.write_text("not a program")
    use_tool([([str(plain)], "utf-8")])
    assert copy() is None


def test_a_clipboard_tool_that_never_reads_a_big_report_does_not_hang_us(tmp_path: Path, use_tool):
    use_tool(tool(tmp_path, "import sys; sys.exit(0)\n"))
    copy("x" * 5_000_000)  # the pipe breaks; whatever the answer, no exception and no hang


def test_a_clipboard_tool_that_floods_its_output_is_silenced(tmp_path: Path, use_tool, capfd):
    use_tool(
        tool(
            tmp_path,
            "import sys; sys.stdin.read(); print('x' * 100000); sys.stderr.write('e' * 1000)\n",
        )
    )
    assert copy() is not None
    captured = capfd.readouterr()
    assert captured.out == "" and captured.err == ""  # nothing of the tool reaches our terminal


def test_after_a_failing_tool_the_next_one_is_tried(tmp_path: Path, use_tool):
    out = tmp_path / "got"
    good = tool(tmp_path, f"import sys; open({str(out)!r}, 'wb').write(sys.stdin.buffer.read())\n")
    use_tool([([sys.executable, "-c", "import sys; sys.exit(1)"], "utf-8"), *good])
    assert copy("héllo") is not None and out.read_bytes() == "héllo".encode()


def test_the_command_survives_a_clipboard_that_hangs(
    healthy: Path, tmp_path: Path, use_tool, monkeypatch: pytest.MonkeyPatch
):
    use_tool(tool(tmp_path, "import time; time.sleep(60)\n"))
    monkeypatch.setattr(report, "CLIPBOARD_TIMEOUT", 0.5)
    result = runner.invoke(app, ["doctor", "--copy"])
    assert result.exit_code == 0 and "could not be copied to the clipboard" in result.output


# --- other blocking helpers (adversarial) ------------------------------------------------------


def test_an_is_admin_that_raises_is_a_warning_not_a_crash(home: Path):
    def boom():
        raise OSError("no")

    found = doctor.collect(make_context(home, is_admin=boom))
    admin = next(c for c in found.all_checks() if c.id == "program.admin")
    assert admin.status == WARN and admin.code == errors.UNEXPECTED.code


def test_loader_files_that_raise_something_odd_are_a_warning_not_a_crash(home: Path):
    def boom():
        raise OSError("the disk went away")

    found = doctor.collect(make_context(home, loader_files=boom))
    check = next(c for c in found.all_checks() if c.id == "program.loader_files")
    assert check.status == WARN and check.code == errors.UNEXPECTED.code
    assert found.all_checks()  # the rest of the report is there


# --- wrong clocks --------------------------------------------------------------------------------


def test_a_clock_before_1970_still_gives_a_report(home: Path):
    make_profile(home)
    early = datetime(1969, 12, 31, tzinfo=timezone.utc)
    found = doctor.collect(make_context(home, now=lambda: early))
    assert found.generated == "1969-12-31T00:00:00Z"
    assert all(c.code != errors.UNEXPECTED.code for c in found.all_checks())


def test_a_clock_in_the_year_9999_still_gives_a_report(home: Path):
    make_profile(home)
    late = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    found = doctor.collect(make_context(home, now=lambda: late))
    assert all(c.code != errors.UNEXPECTED.code for c in found.all_checks())
    assert report.to_markdown(found)


# --- redaction of profile names (decision of the owner) -----------------------------------------


def test_a_profile_name_is_replaced_by_its_number_everywhere(healthy: Path, home: Path):
    ini = home / ".mozilla" / "firefox" / "profiles.ini"
    ini.write_text(ini.read_text().replace("Name=default-release", "Name=Alices secret-project"))
    status = healthy / "chrome" / "peekafoxy-status.json"
    status.write_text(
        json.dumps(
            {
                "schema": 1,
                "updated": "2026-11-05T11:00:00Z",
                "errors": [
                    {"level": "error", "where": "x", "message": "bad in Alices secret-project"}
                ],
            }
        )
    )
    os.utime(status, (time.time() - 10**6,) * 2)
    for flags in ([], ["--json"], ["--markdown"]):
        out = runner.invoke(app, ["doctor", *flags]).output
        assert "secret-project" not in out and "Alices" not in out
        assert "<profile 1>" in out.replace("\\<", "<")


def test_standard_firefox_profile_names_are_kept_and_short_names_are_not_blanked():
    redact = logs.Redactor(home=None, user=None, profile_names=["default-release", "ab", "Work"])
    text = "default-release ab Work grab"
    assert redact(text) == "default-release ab <profile 3> grab"
    assert logs.Redactor(home=None, user=None, profile_names=[])("x") == "x"


def test_the_numbers_follow_profiles_ini_not_the_order_of_checking():
    redact = logs.Redactor(home=None, user=None, profile_names=["first one", "second one"])
    assert redact("second one then first one") == "<profile 2> then <profile 1>"


@pytest.mark.parametrize(
    "name", ["a.b", "x+y(z)", "[tag]", "\\d+", "名前テスト", "with  two spaces"]
)
def test_a_profile_name_with_regex_or_unicode_characters_is_matched_literally(name: str):
    redact = logs.Redactor(home=None, user=None, profile_names=["zzz1", "zzz2", name])
    assert redact(f"in {name} here") == "in <profile 3> here"


@needs_permissions
def test_permission_checks_in_this_file_run_unprivileged():
    assert not IS_ROOT
    assert FAIL != OK


def test_escape_sequences_from_a_status_file_do_not_reach_the_log(home: Path, tmp_path: Path):
    # In the folder this system's Firefox uses, or the real program never finds the status file.
    profile = make_profile(home, root=real_profiles_root(home))
    write(
        profile / "chrome" / "peekafoxy-status.json",
        json.dumps(
            {
                "schema": 1,
                "updated": "2026-11-05T11:00:00Z",
                "health": {"a": "fail: \x1b]0;pwned\x07\x1b[2J"},
            }
        ),
    )
    log = tmp_path / "doctor.log"
    env = {
        **os.environ,
        **real_home_environment(home),
        "PYTHONPATH": SRC,
        "PEEK_A_FOXY_LOG": str(log),
    }
    subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", "doctor", "--json"],
        env=env,
        capture_output=True,
        timeout=60,
    )
    text = log.read_text(encoding="utf-8")
    assert "pwned" in text and "\x1b" not in text and "\x07" not in text
