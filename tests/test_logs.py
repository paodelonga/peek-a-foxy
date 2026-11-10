"""The local log: where it lives, what it hides, how it rotates, and that it never breaks a run."""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from hypothesis import given
from hypothesis import strategies as st
from support import needs_permissions

from peek_a_foxy import elevate, logs

HOME_POSIX = PurePosixPath("/home/ana")


@pytest.fixture(autouse=True)
def _stop_logging():
    yield
    logs.stop()


# --- where the log lives -----------------------------------------------------------------------


def test_windows_log_goes_to_local_app_data():
    env = {"LOCALAPPDATA": r"C:\Users\Ana\AppData\Local"}
    folder = logs.log_dir("windows", env, PureWindowsPath(r"C:\Users\Ana"))
    assert str(folder) == r"C:\Users\Ana\AppData\Local\peek-a-foxy\logs"


def test_windows_log_without_the_variable_falls_back_to_the_home_folder():
    folder = logs.log_dir("windows", {}, PureWindowsPath(r"C:\Users\Ana"))
    assert str(folder) == r"C:\Users\Ana\AppData\Local\peek-a-foxy\logs"


def test_macos_log_goes_to_library_logs():
    folder = logs.log_dir("macos", {}, PurePosixPath("/Users/ana"))
    assert str(folder) == "/Users/ana/Library/Logs/peek-a-foxy"


def test_linux_log_follows_xdg_state_home_and_defaults_to_local_state():
    assert str(logs.log_dir("linux", {"XDG_STATE_HOME": "/x/state"}, HOME_POSIX)) == (
        "/x/state/peek-a-foxy"
    )
    assert str(logs.log_dir("linux", {}, HOME_POSIX)) == "/home/ana/.local/state/peek-a-foxy"
    # A relative XDG_STATE_HOME must be ignored, as the specification says.
    assert str(logs.log_dir("linux", {"XDG_STATE_HOME": "state"}, HOME_POSIX)) == (
        "/home/ana/.local/state/peek-a-foxy"
    )


def test_the_default_target_is_the_log_file_in_that_folder(tmp_path: Path):
    target = logs.resolve_target(kind="linux", environ={}, home=tmp_path)
    assert target.source == "default"
    assert target.path == tmp_path / ".local" / "state" / "peek-a-foxy" / logs.LOG_NAME


def test_the_choice_of_target_follows_the_documented_precedence(tmp_path: Path):
    flag, env = str(tmp_path / "flag.log"), str(tmp_path / "env.log")
    assert logs.resolve_target(no_log=True, log_file=flag, env_value=env).path is None
    assert logs.resolve_target(no_log=True).source == "off-flag"
    assert logs.resolve_target(log_file=flag, env_value=env).path == Path(flag)
    assert logs.resolve_target(env_value=env).path == Path(env)
    assert logs.resolve_target(env_value=env).source == "env"
    off = logs.resolve_target(env_value=" OFF ")
    assert off.path is None and off.source == "off-env"
    blank = logs.resolve_target(env_value="  ", kind="linux", environ={}, home=tmp_path)
    assert blank.source == "default"


def test_a_folder_given_as_the_log_file_gets_the_default_file_name(tmp_path: Path):
    assert logs.resolve_target(log_file=str(tmp_path)).path == tmp_path / logs.LOG_NAME


def test_an_unsupported_system_still_gets_a_log_place(monkeypatch):
    def unsupported():
        raise logs.platform.UnsupportedPlatformError(logs.platform.errors.UNSUPPORTED_OS, "x")

    monkeypatch.setattr(logs.platform, "system", unsupported)
    assert logs.default_kind() == "linux"


# --- redaction ---------------------------------------------------------------------------------


def redactor(**kwargs) -> logs.Redactor:
    kwargs.setdefault("home", "/home/ana")
    kwargs.setdefault("user", "ana-maria")
    return logs.Redactor(**kwargs)


def test_the_home_folder_becomes_a_tilde_in_every_spelling():
    windows = logs.Redactor(home=r"C:\Users\Ana Maria", user="Ana Maria", ignore_case=True)
    assert windows(r"C:\Users\Ana Maria\AppData\x") == r"~\AppData\x"
    assert windows("c:/users/ana maria/AppData") == "~/AppData"  # case and slash differ
    assert windows(repr(r"C:\Users\Ana Maria\x")) == repr("~")[:-1] + r"\\x'"  # a repr: doubled
    assert redactor()("opened /home/ana/.mozilla") == "opened ~/.mozilla"


WIN_HOME = r"C:\Users\Ana Maria"


@pytest.mark.parametrize(
    "spelling",
    [
        r"C:\Users\Ana Maria",
        "C:/Users/Ana Maria",
        r"C:\Users/Ana Maria",  # a mix, as when a typed path is joined to a built one
        r"C:/Users\Ana Maria",
        r"C:\\Users\\Ana Maria",  # inside a repr()
        r"C:\\\\Users\\\\Ana Maria",  # inside the repr of a repr
        r"C://Users//Ana Maria",
        r"c:\users\ana maria",  # the drive letter and the names in lower case
        r"C:\USERS\ANA MARIA",
        "C:\\Users\\Ana Maria\\",  # a trailing separator
        r"\\?\C:\Users\Ana Maria",  # the long-path prefix
        "file:///C:/Users/Ana%20Maria",  # a file URL
        "file:///c%3A/Users/Ana%20Maria",
        r"\\?\c:\\Users\Ana Maria",
    ],
)
def test_a_windows_home_is_hidden_in_every_spelling_it_can_be_printed_in(spelling):
    shown = logs.Redactor(home=WIN_HOME, user=None, ignore_case=True)(f"open {spelling}\\x here")
    assert "ana" not in shown.lower() and "~" in shown, shown


def test_the_drive_letter_is_matched_in_either_case_even_without_ignore_case():
    shown = logs.Redactor(home=WIN_HOME, user=None)(r"c:\Users\Ana Maria\x")
    assert shown == r"~\x"


@pytest.mark.parametrize(
    "spelling",
    [
        r"\\srv\share\ana",
        "//srv/share/ana",
        r"\\\\srv\\share\\ana",  # in a repr()
        r"\\?\UNC\srv\share\ana",  # the long-path form of a network share
        r"\\?\UNC\srv\\share\ana",
    ],
)
def test_a_home_on_a_network_share_is_hidden_in_every_spelling(spelling):
    shown = logs.Redactor(home=r"\\srv\share\ana", user=None)(f"in {spelling}\\x")
    assert "ana" not in shown and "srv" not in shown, shown


def test_a_folder_that_only_looks_similar_is_left_alone():
    redact = logs.Redactor(home=WIN_HOME, user=None, ignore_case=True)
    for text in (r"C:\Users\Ana\x", r"C:\Users\Public\Ana Maria", r"D:\Users\Ana Maria\x"):
        assert redact(text) == text


def test_a_home_with_undecodable_bytes_in_its_name_does_not_break_the_redactor():
    odd = "/home/ana\udcff\ud800"  # what Python makes of bytes that are not valid UTF-8
    assert logs.Redactor(home=odd, user=None)(f"in {odd}/x") == "in ~/x"


def test_a_short_8_3_name_of_the_home_is_hidden_when_the_system_knows_it(tmp_path: Path):
    home = r"C:\Users\Ana Maria"
    short = {home: r"C:\Users\ANAMAR~1"}
    fake = logs.Redactor.for_this_machine(
        {"USERPROFILE": home}, Path(home), "windows", short_path=short.get
    )
    temp = r"git clone x C:\Users\ANAMAR~1\AppData\Local\Temp\t1 and C:\Users\Ana Maria\x"
    assert "ANAMAR" not in fake(temp) and "Ana Maria" not in fake(temp)

    # and a system that cannot say (or fails) just goes without it
    def broken(path: str) -> str:
        raise OSError("no short names on this volume")

    for fail in (broken, {}.get):
        quiet = logs.Redactor.for_this_machine({}, Path(home), "windows", short_path=fail)
        assert quiet(r"C:\Users\Ana Maria\x") == r"~\x"


def test_a_home_that_is_a_link_is_hidden_under_its_real_name_too(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(logs.getpass, "getuser", lambda: "zz")  # too short to be hidden itself
    real = tmp_path / "real-home"
    real.mkdir()
    link = tmp_path / "link-home"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:  # no right to make links here
        pytest.skip("symbolic links are not available")
    fake = logs.Redactor.for_this_machine({}, link, "linux")
    assert str(real) not in fake(f"seen {real}/x") and str(link) not in fake(f"seen {link}/x")


def test_extra_homes_such_as_userprofile_are_hidden_too():
    result = redactor(extra_homes=[r"D:\Profiles\ana"])(r"in D:\Profiles\ana\x and /home/ana/y")
    assert "Profiles" not in result and "/home/ana" not in result


def test_the_user_name_is_hidden_when_it_is_distinctive():
    assert redactor()("hello ana-maria, bye") == "hello <user>, bye"
    assert redactor(user="ana")("analysis by ana") == "analysis by <user>"  # whole words only
    assert redactor(user="al")("alpha al") == "alpha al"  # too short to hide on its own


def test_a_root_like_home_is_not_used_to_blank_everything():
    assert logs.Redactor(home="/", user=None)("/usr/lib/firefox") == "/usr/lib/firefox"
    assert logs.Redactor(home=None, user=None)("nothing to hide") == "nothing to hide"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "git clone https://me:s3cret@github.com/a/b.git",
            "git clone https://***@github.com/a/b.git",
        ),
        ("https://x-access-token@host/a", "https://***@host/a"),
        ("GET /a?token=abc123&x=1", "GET /a?token=***&x=1"),
        ("url?api_key=zzz", "url?api_key=***"),
        ("Authorization: Bearer abcdef", "Authorization: Bearer ***"),
        ("token ghp_" + "a" * 30, "token ***"),
        ("github_pat_" + "B1_" * 10, "***"),
        (
            "nothing secret at https://github.com/a/b.git",
            "nothing secret at https://github.com/a/b.git",
        ),
    ],
)
def test_tokens_are_hidden(text, expected):
    assert redactor()(text) == expected


def test_firefox_profile_folder_names_are_hidden():
    result = redactor()("/home/ana/.mozilla/firefox/a1b2c3d4.default-release/chrome")
    assert result == "~/.mozilla/firefox/<profile>/chrome"
    assert "<profile>" in redactor()(r"C:\x\Profiles\a1b2c3d4.dev-edition\user.js")


def test_a_redactor_for_this_machine_knows_the_user_and_home(tmp_path: Path):
    env = {"USERNAME": "carolina", "USERPROFILE": str(tmp_path / "carolina-profile")}
    fake = logs.Redactor.for_this_machine(env, tmp_path / "home", "linux")
    assert str(tmp_path / "home") not in fake(f"in {tmp_path / 'home' / 'x'}")
    assert "carolina-profile" not in fake(f"{tmp_path / 'carolina-profile'}/a")


def test_a_redactor_survives_a_machine_with_no_user_name(monkeypatch, tmp_path: Path):
    def broken():
        raise KeyError("no user")

    monkeypatch.setattr(logs.getpass, "getuser", broken)
    assert (
        logs.Redactor.for_this_machine({"USER": "dina-lee"}, tmp_path, "linux")("dina-lee")
        == "<user>"
    )
    assert logs.Redactor.for_this_machine({}, tmp_path, "linux")("plain") == "plain"


# Home folders as they exist: a root, some folders, with names of any letters (also non-ASCII).
names = st.text(
    st.characters(whitelist_categories=("Ll", "Lu", "Nd"), max_codepoint=0x2FFF),
    min_size=1,
    max_size=12,
)
homes = st.builds(lambda parts: "/" + "/".join(parts), st.lists(names, min_size=2, max_size=4))
noise = st.text(max_size=30)


@given(
    parts=st.lists(names, min_size=2, max_size=4),
    separators=st.lists(
        st.sampled_from(["\\", "/", "\\\\", "//", "\\/", "\\" * 4]), min_size=4, max_size=4
    ),
    tail=st.sampled_from(["", "\\chrome", "/a b/c.txt"]),
)
def test_a_windows_home_never_survives_any_mix_of_separators(parts, separators, tail):
    home = "C:\\" + "\\".join(parts)
    spelled = "C:" + "".join(sep + part for sep, part in zip(separators, parts, strict=False))
    assert logs.Redactor(home=home, user=None)(spelled + tail) == "~" + tail


@given(home=homes, before=noise, after=noise, tail=st.sampled_from(["", "/chrome", "/a b/c.txt"]))
def test_a_random_home_folder_never_appears_in_redacted_text(home, before, after, tail):
    shown = logs.Redactor(home=home, user=None)(f"{before}{home}{tail}{after}")
    assert home not in shown


@given(home=homes, text=noise)
def test_a_random_home_folder_never_reaches_the_log_file(home, text):
    """End to end: through the handler and the formatter, traceback included."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "log"
        logs.start(
            target=target,
            verbose=False,
            argv=["install", "--profile", home],
            version="0",
            redactor=logs.Redactor(home=home, user=None),
        )
        logger = logging.getLogger("peek_a_foxy.test")
        logger.warning("opening %s%s", home, text)
        try:
            raise ValueError(f"cannot read {home}/x")
        except ValueError:
            logger.error("failed in %s", home, exc_info=True)
        logs.stop(1)
        written = target.read_text(encoding="utf-8")
    assert home not in written


# --- the file: format, rotation, failure ------------------------------------------------------


def test_a_run_writes_utc_lines_with_a_run_id_and_the_start_facts(tmp_path: Path):
    target = tmp_path / "logs" / "x.log"  # the folder does not exist yet
    session = logs.start(
        target=target, verbose=False, argv=["install", "--yes"], version="9.8.7", run_id="abcd1234"
    )
    logging.getLogger("peek_a_foxy.test").info("héllo — ünïcode")
    logs.stop(0)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert session.run_id == "abcd1234"
    assert re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ INFO    abcd1234 run started: peek-a-foxy 9.8.7 "
        r"\(installed with pip\), Python \d+\.\d+\.\d+, .+, args: \['install', '--yes'\]",
        lines[0],
    ), lines[0]
    assert lines[1].endswith("abcd1234 héllo — ünïcode")
    assert re.search(r"abcd1234 run finished: exit code 0 after \d+\.\d\d s$", lines[-1])


def test_a_frozen_program_says_so(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    logs.start(target=tmp_path / "f.log", verbose=False, argv=[], version="1")
    logs.stop()
    assert "(standalone program)" in (tmp_path / "f.log").read_text(encoding="utf-8")


def test_every_run_gets_its_own_id(tmp_path: Path):
    ids = set()
    for _ in range(5):
        ids.add(logs.start(target=None, verbose=False, argv=[], version="1").run_id)
    assert len(ids) == 5 and all(re.fullmatch(r"[0-9a-f]{8}", i) for i in ids)


def test_the_run_is_recorded_as_active_only_while_it_has_a_file(tmp_path: Path):
    assert logs.active_path() is None and not logs.is_verbose()
    logs.start(target=tmp_path / "a.log", verbose=True, argv=[], version="1")
    assert logs.active_path() == tmp_path / "a.log" and logs.is_verbose()
    logs.stop()
    assert logs.active_path() is None


def test_nothing_logged_while_no_run_is_active_reaches_the_terminal(capsys):
    logging.getLogger("peek_a_foxy.test").error("nobody is listening")
    assert capsys.readouterr() == ("", "")


def test_the_log_rotates_at_the_size_limit_keeping_three_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 2000)
    target = tmp_path / "r.log"
    logs.start(target=target, verbose=False, argv=[], version="1")
    logger = logging.getLogger("peek_a_foxy.test")
    for number in range(400):
        logger.info("line %d %s", number, "x" * 60)
    logs.stop()
    files = sorted(path.name for path in tmp_path.iterdir())
    assert files == ["r.log", "r.log.1", "r.log.2"]
    assert all(path.stat().st_size <= 2200 for path in tmp_path.iterdir())
    assert logs.log_files(target) == [target, tmp_path / "r.log.1", tmp_path / "r.log.2"]


def test_the_real_limits_are_the_agreed_ones():
    assert logs.MAX_BYTES == 5 * 1024 * 1024 and logs.BACKUP_COUNT + 1 == 3


def test_a_log_folder_that_cannot_be_created_only_warns(tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    warnings: list[str] = []
    session = logs.start(
        target=blocker / "sub" / "x.log", verbose=False, argv=[], version="1", warn=warnings.append
    )
    logging.getLogger("peek_a_foxy.test").info("still works")  # must not raise
    assert session.path is None and logs.active_path() is None
    assert len(warnings) == 1 and "going on without it" in warnings[0]


@needs_permissions
def test_a_read_only_log_folder_only_warns(tmp_path: Path):
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        warnings: list[str] = []
        logs.start(
            target=folder / "x.log", verbose=False, argv=[], version="1", warn=warnings.append
        )
        logging.getLogger("peek_a_foxy.test").info("still works")
    finally:
        folder.chmod(0o755)
    assert len(warnings) == 1 and logs.active_path() is None


def test_a_write_that_fails_later_warns_once_and_stops_writing(tmp_path: Path, monkeypatch):
    warnings: list[str] = []
    logs.start(target=tmp_path / "w.log", verbose=False, argv=[], version="1", warn=warnings.append)
    handler = next(
        h for h in logging.getLogger("peek_a_foxy").handlers if isinstance(h, logs._SafeFileHandler)
    )

    def full_disk(record):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(logging.FileHandler, "emit", lambda self, record: full_disk(record))
    logger = logging.getLogger("peek_a_foxy.test")
    for _ in range(3):
        logger.info("one")  # FileHandler.emit is replaced; the error must be swallowed
    handler.handleError(logging.makeLogRecord({}))  # what Python calls when emit fails
    handler.handleError(logging.makeLogRecord({}))
    assert len(warnings) == 1 and "going on without it" in warnings[0]
    assert logs.active_path() is None


def test_a_log_that_breaks_while_writing_never_raises_into_the_command(tmp_path: Path):
    warnings: list[str] = []
    logs.start(target=tmp_path / "b.log", verbose=False, argv=[], version="1", warn=warnings.append)
    handler = next(
        h for h in logging.getLogger("peek_a_foxy").handlers if isinstance(h, logs._SafeFileHandler)
    )
    assert handler.stream is not None
    handler.stream.close()  # as if the file had been taken away: the next write fails
    logging.getLogger("peek_a_foxy.test").info("after the break")
    logging.getLogger("peek_a_foxy.test").info("and again")
    assert len(warnings) == 1


def test_verbose_prints_redacted_debug_lines_on_stderr(capsys):
    logs.start(
        target=None,
        verbose=True,
        argv=[],
        version="1",
        redactor=logs.Redactor(home="/home/ana", user=None),
    )
    logging.getLogger("peek_a_foxy.test").debug("reading /home/ana/x")
    logs.stop()
    err = capsys.readouterr().err
    assert "DEBUG   reading ~/x" in err and "/home/ana" not in err


def test_the_traceback_of_a_logged_error_is_redacted_and_has_no_local_variables(tmp_path: Path):
    target = tmp_path / "t.log"
    logs.start(
        target=target,
        verbose=False,
        argv=[],
        version="1",
        redactor=logs.Redactor(home="/home/ana", user=None),
    )

    def fails():
        secret_local = "value-of-a-local-variable"  # noqa: F841
        raise ValueError("cannot open /home/ana/file")

    try:
        fails()
    except ValueError:
        logging.getLogger("peek_a_foxy.test").error("failed", exc_info=True)
    logs.stop()
    text = target.read_text(encoding="utf-8")
    assert "Traceback" in text and "ValueError: cannot open ~/file" in text
    assert "value-of-a-local-variable" not in text and "/home/ana" not in text


# --- reading, clearing and opening --------------------------------------------------------------


def test_the_last_run_is_everything_after_the_last_start_line(tmp_path: Path):
    path = tmp_path / "l.log"
    for run in ("first", "second"):
        logs.start(target=path, verbose=False, argv=[run], version="1", run_id=run.ljust(8, "0"))
        logging.getLogger("peek_a_foxy.test").info("work of %s", run)
        logs.stop(0)
    lines = logs.last_run(path)
    assert "second" in lines[0] and any("work of second" in line for line in lines)
    assert not any("first" in line for line in lines)


def test_the_last_run_of_a_missing_or_foreign_file_is_empty(tmp_path: Path):
    assert logs.last_run(tmp_path / "missing.log") == []
    (tmp_path / "other.log").write_text("no marker here\n")
    assert logs.last_run(tmp_path / "other.log") == []


def test_clearing_removes_only_the_log_and_its_rotated_copies(tmp_path: Path):
    path = tmp_path / "peek-a-foxy.log"
    for name in ("peek-a-foxy.log", "peek-a-foxy.log.1", "peek-a-foxy.log.2", "notes.txt"):
        (tmp_path / name).write_text("x")
    assert logs.clear(path) == 3
    assert [p.name for p in tmp_path.iterdir()] == ["notes.txt"]
    assert logs.clear(path) == 0


@pytest.mark.parametrize(("kind", "opener"), [("linux", "xdg-open"), ("macos", "open")])
def test_opening_the_folder_uses_the_systems_opener(kind, opener):
    folder = Path("/some/dir")
    calls: list[list[str]] = []
    assert logs.open_folder(folder, kind=kind, run=lambda c, **kw: calls.append(c))
    # str(folder) is how the program spells it on the machine running the test: on Windows a
    # Path turns "/some/dir" into "\some\dir", whatever the opener being tested.
    assert calls == [[opener, str(folder)]]


def test_opening_the_folder_on_windows_uses_startfile():
    opened: list[str] = []
    assert logs.open_folder(Path("x"), kind="windows", startfile=opened.append)
    assert opened == ["x"]


@pytest.mark.parametrize("kind", ["linux", "windows"])
def test_a_folder_that_cannot_be_opened_is_reported_not_raised(kind):
    def broken(*args, **kwargs):
        raise OSError("no opener")

    assert not logs.open_folder(Path("x"), kind=kind, run=broken, startfile=broken)


def test_without_startfile_windows_opening_is_a_failure_not_a_crash(monkeypatch):
    monkeypatch.delattr(logs.os, "startfile", raising=False)
    assert not logs.open_folder(Path("x"), kind="windows")


# --- the elevated helper stays out of this ------------------------------------------------------


def test_the_elevated_helper_has_no_logging_and_imports_nothing_of_ours():
    code = elevate.helper_code()
    assert "logging" not in code and "peek_a_foxy" not in code
    assert re.findall(r"^import .*$", code, re.MULTILINE) == ["import base64, hashlib, os, sys"]


@pytest.mark.skipif(sys.platform == "win32", reason="runs a shell script as the opener")
def test_a_real_opener_gets_the_folder_and_cannot_write_to_our_terminal(tmp_path, monkeypatch):
    seen = tmp_path / "seen.txt"
    opener = tmp_path / "bin" / "xdg-open"
    opener.parent.mkdir()
    opener.write_text(
        f'#!/bin/sh\n{{ echo "$1"; [ -t 0 ] && echo tty || echo no-tty; }} > "{seen}"\n'
        "echo NOISE\necho NOISE >&2\n"
    )
    opener.chmod(0o755)
    monkeypatch.setenv("PATH", f"{opener.parent}{os.pathsep}{os.environ['PATH']}")
    folder = tmp_path / "logs"
    assert logs.open_folder(folder, kind="linux")
    assert seen.read_text().split() == [str(folder), "no-tty"]
