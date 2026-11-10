"""Adversarial tests of the doctor: hostile files, paths, symbolic links, permissions and sizes.

The invariant behind almost all of them: whatever is on the disk, ``collect`` returns a report,
every format renders, and no check says PAF-900 (that code means "a check crashed", a bug).
"""

from __future__ import annotations

import json
import os
import random
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest
from doctor_support import (
    check_of,
    make_context,
    make_firefox,
    make_profile,
    pin_loader,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from support import WINDOWS, needs_permissions, needs_symlinks

from peek_a_foxy import doctor, errors, logs, platform, report
from peek_a_foxy.report import FAIL, OK, WARN

BUG = errors.UNEXPECTED.code
HUNDRED_MB_LIMIT = 100 * 1024 * 1024
SRC = str(Path(__file__).resolve().parents[1] / "src")


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_loader(monkeypatch)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def run(home: Path, ff: Path | None = None, profile: Path | None = None, **overrides):
    candidates = [ff] if ff is not None else []
    context = make_context(home, firefox_candidates=lambda: candidates, **overrides)
    return doctor.collect(context, profile=profile)


def assert_sound(found) -> None:
    """The report exists, shows no crash, and every format renders."""
    bugs = [c.id for c in found.all_checks() if c.code == BUG]
    assert bugs == [], f"checks that crashed: {bugs}"
    safe = found.redacted(logs.Redactor(home="/nonexistent-home", user=None))
    json.loads(report.to_json(safe))
    assert report.to_markdown(safe).endswith("issues/new/choose\n")
    assert report.to_rich(safe)


def world(home: Path):
    """A complete, healthy fake world: a Firefox install and an installed profile."""
    return make_firefox(home / "ff"), make_profile(home)


# --- bytes that are not what they should be (adversarial) --------------------------------------

RNG = random.Random(7)
PAYLOADS = {
    "empty": b"",
    "nul": b"\x00" * 2000,
    "bad-utf8": b"\xff\xfe\xfd[Profile0]\nName=\xc3\x28\n",
    "binary": RNG.randbytes(8000),
    "nul-inside-ini": b"[Profile0]\x00\nName=a\x00b\nPath=x\x00y\n",
    "nul-inside-pref": b'user_pref("a\x00b", true\x00);\n',
    "bom-only": b"\xef\xbb\xbf",
    "only-newlines": b"\n" * 50000,
    "lone-surrogate-escape": b"\xed\xa0\x80",
}

HOSTILE_FILES = {
    "profiles.ini": lambda home, ff, profile: home / ".mozilla" / "firefox" / "profiles.ini",
    "application.ini": lambda home, ff, profile: ff / "application.ini",
    "channel-prefs.js": lambda home, ff, profile: ff / "defaults" / "pref" / "channel-prefs.js",
    "config.js": lambda home, ff, profile: ff / "config.js",
    "config-prefs.js": lambda home, ff, profile: ff / "defaults" / "pref" / "config-prefs.js",
    "local-settings.js": lambda home, ff, profile: ff / "defaults" / "pref" / "local-settings.js",
    "policies.json": lambda home, ff, profile: ff / "distribution" / "policies.json",
    "user.js": lambda home, ff, profile: profile / "user.js",
    "prefs.js": lambda home, ff, profile: profile / "prefs.js",
    "userChrome.css": lambda home, ff, profile: profile / "chrome" / "userChrome.css",
    "autohide.css": lambda home, ff, profile: profile / "chrome" / "autohide.css",
    "autohide.uc.js": lambda home, ff, profile: profile / "chrome" / "JS" / "autohide.uc.js",
    "status": lambda home, ff, profile: profile / "chrome" / "peekafoxy-status.json",
}


@pytest.mark.parametrize("payload", list(PAYLOADS), ids=list(PAYLOADS))
@pytest.mark.parametrize("name", list(HOSTILE_FILES))
def test_no_file_can_make_the_doctor_crash(home: Path, name: str, payload: str):
    ff, profile = world(home)
    target = HOSTILE_FILES[name](home, ff, profile)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PAYLOADS[payload])
    assert_sound(run(home, ff, profile=profile if name != "profiles.ini" else None))
    assert_sound(run(home, ff))  # and when the profile comes from profiles.ini


def test_a_nul_in_profiles_ini_is_a_coded_finding_not_a_crash(home: Path):
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True)
    (root / "profiles.ini").write_bytes(PAYLOADS["nul-inside-ini"])
    found = run(home)
    assert_sound(found)
    # configparser accepts the NUL, so the profile is listed and its folder is what is missing
    assert (
        not found.ok
        and check_of(found, "profile.folder").code == errors.PROFILE_FOLDER_MISSING.code
    )


def test_invalid_utf8_in_profiles_ini_says_it_could_not_be_read(home: Path):
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True)
    (root / "profiles.ini").write_bytes(b"\xff\xfe\xfd")
    assert check_of(run(home), "profiles.ini").code == errors.PROFILES_UNREADABLE.code


def test_user_js_with_a_nul_byte_still_yields_the_prefs_after_it(home: Path):
    ff, profile = world(home)
    user = profile / "user.js"
    user.write_bytes(b"\x00\x00junk\n" + user.read_bytes())
    found = run(home, ff, profile=profile)
    assert check_of(found, "profile.pref_stylesheets").status == OK


# --- sizes (adversarial) -----------------------------------------------------------------------

SPARSE = 60 * 1024 * 1024  # more than the 50 MB of the brief; costs nothing on disk


def sparse(path: Path, size: int = SPARSE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)


@pytest.mark.parametrize("name", list(HOSTILE_FILES))
def test_a_huge_file_is_neither_read_whole_nor_slow(home: Path, name: str):
    ff, profile = world(home)
    sparse(HOSTILE_FILES[name](home, ff, profile))
    tracemalloc.start()
    started = time.monotonic()
    try:
        found = run(home, ff, profile=profile if name != "profiles.ini" else None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert time.monotonic() - started < 20
    assert peak < HUNDRED_MB_LIMIT, f"{peak / 1024 / 1024:.0f} MB held while reading {name}"
    assert_sound(found)


def test_a_huge_user_js_is_reported_as_too_big_not_ignored(home: Path):
    ff, profile = world(home)
    sparse(profile / "user.js")
    found = run(home, ff, profile=profile)
    assert check_of(found, "profile.read_user").code == errors.FILE_IO.code
    assert "bigger than" in check_of(found, "profile.read_user").message


def test_a_huge_status_file_is_refused_with_a_reason(home: Path):
    ff, profile = world(home)
    sparse(profile / "chrome" / "peekafoxy-status.json")
    check = check_of(run(home, ff, profile=profile), "status.file")
    assert check.code == errors.STATUS_UNUSABLE.code and "bigger" in check.message


def test_a_huge_profiles_ini_is_refused(home: Path):
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True)
    sparse(root / "profiles.ini")
    check = check_of(run(home), "profiles.ini")
    assert check.code == errors.PROFILES_UNREADABLE.code and "bigger" in check.message


def test_a_huge_loader_file_counts_as_unreadable(home: Path):
    ff, profile = world(home)
    sparse(ff / "config.js")
    check = check_of(run(home, ff, profile=profile), "firefox.loader")
    assert check.status == WARN and check.code == errors.FILE_IO.code


def test_our_file_that_is_huge_is_different_not_slurped(home: Path):
    ff, profile = world(home)
    sparse(profile / "chrome" / "autohide.css")
    check = check_of(run(home, ff, profile=profile), "profile.files")
    assert check.code == errors.PROFILE_FILES_DIFFERENT.code


# Inputs that make a naive regular expression take forever: each must finish quickly.
SLOW_FOR_NAIVE_CODE = {
    "unclosed-comments": b"/* " * 2_500_000,
    "empty-lines": b"\n" * 8_000_000,
    "spaces-then-no-paren": b'user_pref("a", ' + b" " * 8_000_000,
    "many-open-prefs": b'user_pref("a", ' * 400_000,
    "spaces-in-pref-calls": b"pref(" + b" " * 4_000_000,
}


@pytest.mark.parametrize("kind", list(SLOW_FOR_NAIVE_CODE), ids=list(SLOW_FOR_NAIVE_CODE))
@pytest.mark.parametrize("name", ["user.js", "prefs.js", "userChrome.css", "local-settings.js"])
def test_text_built_to_stall_a_parser_does_not(home: Path, name: str, kind: str):
    """Run in a child process with a limit: a regular expression that never ends would otherwise
    hang the test run itself (the interpreter cannot interrupt it)."""
    ff, profile = world(home)
    HOSTILE_FILES[name](home, ff, profile).write_bytes(SLOW_FOR_NAIVE_CODE[kind])
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off"}
    args = ["doctor", "--json", "--profile", str(profile), "--firefox-dir", str(ff)]
    started = time.monotonic()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "peek_a_foxy", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the doctor was still working on {name} ({kind}) after 30 seconds")
    assert time.monotonic() - started < 30
    assert "Traceback" not in done.stderr, done.stderr
    data = json.loads(done.stdout)
    assert all(c["code"] != BUG for s in data["sections"] for c in s["checks"])


def test_unclosed_comments_are_cut_in_linear_time():
    started = time.monotonic()
    assert doctor.strip_comments("a/* b /* c") == "a"
    assert doctor.strip_comments("a/**/b/* x */c") == "abc"
    assert doctor.strip_comments("/* " * 2_000_000) == ""
    assert doctor.strip_comments("/*/*" * 1_000_000) != "x"  # closes at the first */, linear
    assert time.monotonic() - started < 2


# --- symbolic links (adversarial) --------------------------------------------------------------


def move_away(path: Path) -> None:
    """Take what is at ``path`` (a file or a folder) out of the way, if anything is."""
    if path.is_symlink() or path.exists():
        path.rename(path.with_name(path.name + ".moved"))
    path.parent.mkdir(parents=True, exist_ok=True)


def loop(path: Path) -> None:
    """A symbolic link that points at itself."""
    move_away(path)
    os.symlink(path.name, path)


def dangling(path: Path) -> None:
    move_away(path)
    os.symlink(str(path.parent / "does-not-exist-anywhere"), path)


PATHS_TO_BREAK = {
    "profile folder": lambda home, ff, profile: profile,
    "chrome": lambda home, ff, profile: profile / "chrome",
    "chrome/utils": lambda home, ff, profile: profile / "chrome" / "utils",
    "userChrome.css": lambda home, ff, profile: profile / "chrome" / "userChrome.css",
    "autohide.css": lambda home, ff, profile: profile / "chrome" / "autohide.css",
    "JS": lambda home, ff, profile: profile / "chrome" / "JS",
    "user.js": lambda home, ff, profile: profile / "user.js",
    "prefs.js": lambda home, ff, profile: profile / "prefs.js",
    "status": lambda home, ff, profile: profile / "chrome" / "peekafoxy-status.json",
    "firefox folder": lambda home, ff, profile: ff,
    "defaults/pref": lambda home, ff, profile: ff / "defaults" / "pref",
    "config.js": lambda home, ff, profile: ff / "config.js",
    "application.ini": lambda home, ff, profile: ff / "application.ini",
    "distribution": lambda home, ff, profile: ff / "distribution",
    "profiles.ini": lambda home, ff, profile: home / ".mozilla" / "firefox" / "profiles.ini",
    "profiles folder": lambda home, ff, profile: home / ".mozilla" / "firefox",
}


@needs_symlinks
@pytest.mark.parametrize("breaker", [loop, dangling], ids=["loop", "dangling"])
@pytest.mark.parametrize("what", list(PATHS_TO_BREAK))
def test_a_broken_symbolic_link_anywhere_is_survived(home: Path, what: str, breaker):
    ff, profile = world(home)
    breaker(PATHS_TO_BREAK[what](home, ff, profile))
    given = profile if what not in ("profiles.ini", "profiles folder") else None
    assert_sound(run(home, ff, profile=given))
    assert_sound(run(home, ff))


@needs_symlinks
def test_a_loop_for_the_firefox_dir_is_not_a_bug(home: Path, monkeypatch: pytest.MonkeyPatch):
    ff = home / "ff-loop"
    os.symlink("ff-loop", ff)
    found = doctor.collect(make_context(home), firefox_dir=ff)
    assert_sound(found)
    assert check_of(found, "firefox.loader").status == FAIL


@needs_symlinks
def test_resolving_a_loop_may_raise_runtime_error_before_python_3_13(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    ff = make_firefox(home / "ff")

    real = Path.resolve

    def raising(self, strict=False):
        if str(self).startswith(str(ff)):
            raise RuntimeError("Symlink loop from " + str(self))
        return real(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", raising)
    assert platform.sandbox_kind(ff) is None
    assert_sound(run(home, ff))


@needs_symlinks
def test_a_symlinked_profile_is_followed_and_read_only(home: Path, tmp_path: Path):
    ff, profile = world(home)
    elsewhere = tmp_path / "elsewhere"
    profile.rename(elsewhere)
    os.symlink(elsewhere, profile)
    found = run(home, ff, profile=profile)
    assert check_of(found, "profile.files").status == OK


# --- permission denied (adversarial) -----------------------------------------------------------


@pytest.fixture
def restore_permissions():
    """Give back what a test took away, so the temporary folder can be cleaned up."""
    taken: list[tuple[Path, int]] = []
    yield taken
    for path, mode in reversed(taken):
        if path.exists():
            path.chmod(mode)


def deny(taken: list[tuple[Path, int]], path: Path) -> None:
    taken.append((path, path.stat().st_mode & 0o7777))
    path.chmod(0)


@needs_permissions
@pytest.mark.parametrize("what", list(PATHS_TO_BREAK))
def test_permission_denied_anywhere_is_a_finding_not_a_crash(
    home: Path, what: str, restore_permissions
):
    ff, profile = world(home)
    (profile / "prefs.js").write_text("x")
    (profile / "chrome" / "peekafoxy-status.json").write_text("{}")
    target = PATHS_TO_BREAK[what](home, ff, profile)
    target.mkdir(parents=True, exist_ok=True) if what == "distribution" else None
    deny(restore_permissions, target)
    found = run(home, ff, profile=profile if what != "profiles folder" else None)
    assert_sound(found)


@needs_permissions
def test_a_profile_folder_that_cannot_be_entered_is_a_coded_finding(
    home: Path, restore_permissions
):
    ff, profile = world(home)
    deny(restore_permissions, profile)
    found = run(home, ff, profile=profile)
    assert_sound(found)
    assert not found.ok


@needs_permissions
def test_an_unreadable_status_file_says_why(home: Path, restore_permissions):
    ff, profile = world(home)
    status = profile / "chrome" / "peekafoxy-status.json"
    status.write_text("{}")
    deny(restore_permissions, status)
    check = check_of(run(home, ff, profile=profile), "status.file")
    assert check.code == errors.STATUS_UNUSABLE.code and "could not be read" in check.message


# --- paths with odd characters (adversarial) ---------------------------------------------------

ODD_NAMES = [
    "with space",
    "line\nbreak",
    "tab\there",
    "\u202eevil\u202c",  # right-to-left override
    "\u05e9\u05dc\u05d5\u05dd",  # Hebrew
    "\u0627\u0644\u0639\u0631\u0628\u064a\u0629",  # Arabic
    "e\u0301\u0302\u0303 combining",
    "emoji \U0001f98a",
    "esc\x1b[31mred",
    "bell\x07",
    "pipe|and`tick`and<angle>",
    "[bold]markup[/bold]",
]
# Windows refuses these in any file or folder name, so no path on it can hold them. ("/" and "\"
# are left out: they only make the name a folder inside another, which Windows allows.)
WINDOWS_FORBIDDEN = set('<>:"|?*') | {chr(code) for code in range(32)}
ODD_PARAMS = [
    pytest.param(
        name,
        id=repr(name)[:20],
        marks=pytest.mark.skipif(
            WINDOWS and bool(WINDOWS_FORBIDDEN & set(name)),
            reason="Windows does not allow this character in a folder name",
        ),
    )
    for name in ODD_NAMES
]


@pytest.mark.parametrize("name", ODD_PARAMS)
def test_odd_characters_in_the_home_never_reach_any_format(tmp_path: Path, name: str):
    home = tmp_path / name
    profile = make_profile(home, folder="abcd1234.qx")
    ff = make_firefox(home / "ff")
    found = doctor.collect(
        make_context(home, firefox_candidates=lambda: [ff], log_target=home / "p.log"),
        profile=profile,
    )
    safe = found.redacted(logs.Redactor(home=str(home), user=None))
    texts = [report.to_json(safe), report.to_markdown(safe)]
    for text in texts:
        assert str(home) not in text
        assert "\x1b" not in text and "\x07" not in text and "\u202e" not in text
    assert json.loads(texts[0])


@pytest.mark.parametrize("name", ODD_PARAMS)
def test_odd_characters_in_a_path_cannot_break_the_markdown_table(tmp_path: Path, name: str):
    """The home is not under the redacted one here, so the odd name reaches the text itself."""
    home = tmp_path / "home"
    ff = make_firefox(tmp_path / name)
    profile = make_profile(home)
    found = doctor.collect(make_context(home, firefox_candidates=lambda: [ff]), profile=profile)
    safe = found.redacted(lambda text: text)
    markdown = report.to_markdown(safe)
    for line in markdown.splitlines():
        if line.startswith("| "):
            cells = [c for c in line.replace("\\|", "").split("|")[1:-1]]
            assert len(cells) == 3, line
    assert "\x1b" not in markdown and "\x07" not in markdown
    rich_text = "".join(str(part) for part in report.to_rich(safe))
    assert "\x1b" not in rich_text


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="/\x00"),
        min_size=1,
        max_size=12,
    ).filter(lambda n: n not in (".", "..") and n.strip(". ") != ""),
)
def test_any_folder_name_in_the_home_is_hidden(name: str):
    with tempfile.TemporaryDirectory() as root:
        home = Path(root) / name
        try:
            profile = make_profile(home, folder="abcd1234.qx")
        except OSError:
            return  # this file system does not take that name
        ff = make_firefox(home / "ff")
        found = doctor.collect(make_context(home, firefox_candidates=lambda: [ff]), profile=profile)
        safe = found.redacted(logs.Redactor(home=str(home), user=None))
        for text in (report.to_json(safe), report.to_markdown(safe)):
            assert str(home) not in text
            assert not any(ord(c) < 32 and c != "\n" for c in text)


# --- no home, missing home (adversarial) -------------------------------------------------------


def test_no_home_folder_at_all_is_a_finding_not_a_crash(monkeypatch: pytest.MonkeyPatch):
    def nowhere(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(nowhere))
    monkeypatch.setattr(platform, "system", lambda: "linux")
    ctx = doctor.Context.detect(log_target=None)
    assert ctx.home == Path("~")
    found = doctor.collect(ctx)
    assert_sound(found)
    ini = check_of(found, "profiles.ini")
    assert ini.code == errors.NO_PROFILES_INI.code


def test_the_log_place_without_a_home_is_no_log_not_an_exception(monkeypatch: pytest.MonkeyPatch):
    def nowhere(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(nowhere))
    target = logs.resolve_target(env_value="")
    assert target.path is None and target.source == "no-home"


@pytest.mark.parametrize("home_value", ["", "/nonexistent/folder/for/sure"])
def test_a_home_that_is_empty_or_missing_gives_a_clean_report(
    tmp_path: Path, home_value: str, monkeypatch: pytest.MonkeyPatch
):
    if os.name == "nt":
        pytest.skip("HOME is not what Windows reads")
    monkeypatch.setenv("HOME", home_value)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    ctx = doctor.Context.detect(log_target=None)
    assert_sound(doctor.collect(ctx))


@pytest.mark.parametrize(
    "environ",
    [{}, {"APPDATA": ""}, {"APPDATA": "/does/not/exist", "LOCALAPPDATA": "/nor/this"}],
)
def test_windows_variables_unset_or_dangling_are_survived(
    home: Path, environ: dict, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(os, "environ", {**os.environ, **environ})
    ctx = make_context(home, kind="windows", environ=environ, profiles_root=platform.profiles_root)
    found = doctor.collect(ctx)
    assert_sound(found)
    assert check_of(found, "profiles.ini").code == errors.NO_PROFILES_INI.code


# --- profiles.ini that lies (adversarial) ------------------------------------------------------


def write_ini(home: Path, text: str) -> Path:
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles.ini").write_text(text, encoding="utf-8")
    return root


def test_duplicate_sections_and_keys_are_tolerated(home: Path):
    root = write_ini(
        home,
        "[Profile0]\nName=a\nPath=one\nDefault=1\n[Profile0]\nName=b\nPath=two\nPath=three\n",
    )
    (root / "three" / "chrome").mkdir(parents=True)
    assert_sound(run(home))


def test_ten_thousand_profiles_are_capped_and_fast(home: Path):
    sections = [
        f"[Profile{n}]\nName=user{n}\nIsRelative=1\nPath=p{n}\nDefault=1\n" for n in range(10_000)
    ]
    write_ini(home, "\n".join(sections))
    started = time.monotonic()
    found = run(home)
    assert time.monotonic() - started < 30
    assert_sound(found)
    listing = next(s for s in found.sections if s.id == "profiles")
    assert len(listing.checks) <= doctor.MAX_PROFILES_LISTED + 3
    assert check_of(found, "profiles.checked").code == errors.AMBIGUOUS_PROFILE.code
    assert len([s for s in found.sections if s.id.startswith("profile.")]) == (
        doctor.MAX_PROFILES_CHECKED
    )
    assert len(report.to_markdown(found)) < 300_000  # a hostile list does not make a huge report


def test_a_path_that_climbs_out_of_the_profiles_folder_only_ever_reads(home: Path, tmp_path: Path):
    outside = tmp_path / "outside" / "chrome"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("untouched")
    write_ini(home, "[Profile0]\nName=x\nIsRelative=1\nPath=../../../outside\nDefault=1\n")
    before = sorted(p.name for p in outside.parent.rglob("*"))
    assert_sound(run(home))
    assert sorted(p.name for p in outside.parent.rglob("*")) == before
    assert (outside / "keep.txt").read_text() == "untouched"


@pytest.mark.parametrize(
    "line", ["Path=/etc", "Path=", "Path=\x00", "Path=" + "a/" * 5000, "Path=C:\\nope"]
)
def test_odd_profile_paths_are_survived(home: Path, line: str):
    write_ini(home, f"[Profile0]\nName=x\nIsRelative=0\n{line}\nDefault=1\n")
    assert_sound(run(home))


def test_a_profile_name_with_control_characters_never_reaches_the_terminal(home: Path):
    write_ini(home, "[Profile0]\nName=evil\x1b[2J\x07name\nPath=p\nDefault=1\n")
    make_profile(home, folder="p", with_ini=False)
    found = run(home)
    safe = found.redacted(
        logs.Redactor(home=str(home), user=None, profile_names=found.profile_names)
    )
    for text in (report.to_json(safe), report.to_markdown(safe)):
        assert "\x1b" not in text and "\x07" not in text


# --- the status file lies (adversarial) --------------------------------------------------------

NOW_ISO = "2026-11-05T11:00:00Z"
STATUS_LIES = {
    "nan-schema": '{"schema": NaN, "updated": "' + NOW_ISO + '"}',
    "infinity": '{"schema": 1, "updated": "' + NOW_ISO + '", "windows": Infinity}',
    "nan-health": '{"schema": 1, "updated": "' + NOW_ISO + '", "health": {"a": NaN}}',
    "huge-int": '{"schema": ' + "9" * 5000 + ', "updated": "' + NOW_ISO + '"}',
    "float-schema": '{"schema": 1.0, "updated": "' + NOW_ISO + '"}',
    "future-schema": '{"schema": 99, "updated": "' + NOW_ISO + '"}',
    "negative-schema": '{"schema": -1, "updated": "' + NOW_ISO + '"}',
    "nested-array": "[" * 200_000 + "]" * 200_000,
    "nested-object": '{"a":' * 100_000 + "1" + "}" * 100_000,
    "nested-in-key": '{"schema": 1, "updated": "'
    + NOW_ISO
    + '", "health": '
    + '{"a":' * 50_000
    + "1"
    + "}" * 50_000
    + "}",
    "year-9999": '{"schema": 1, "updated": "9999-12-31T23:59:59Z"}',
    "year-0001": '{"schema": 1, "updated": "0001-01-01T00:00:00Z"}',
    "bad-zone": '{"schema": 1, "updated": "2026-11-05T11:00:00+99:99"}',
    "negative-windows": '{"schema": 1, "updated": "' + NOW_ISO + '", "windows": -5}',
    "windows-huge": '{"schema": 1, "updated": "' + NOW_ISO + '", "windows": ' + "9" * 300 + "}",
    "errors-null-items": '{"schema": 1, "updated": "'
    + NOW_ISO
    + '", "errors": [null, 1, [], {"message": null}]}',
    "duplicate-keys": '{"schema": 2, "schema": 1, "updated": "' + NOW_ISO + '"}',
    "escape-sequences": json.dumps(
        {
            "schema": 1,
            "updated": NOW_ISO,
            "errors": [
                {"level": "error", "where": "x\x1b]0;pwned\x07", "message": "\x1b[2Jboom\r\n"}
            ],
            "health": {"a\x1b[31m": "fail: \u202egnp.exe"},
        }
    ),
    "markup": json.dumps(
        {
            "schema": 1,
            "updated": NOW_ISO,
            "errors": [
                {"level": "error", "message": "[red]x[/red] [link=http://evil]click[/link]"}
            ],
        }
    ),
}


@pytest.mark.parametrize("name", list(STATUS_LIES))
def test_a_lying_status_file_never_crashes_and_never_reaches_the_terminal_raw(
    home: Path, name: str
):
    ff, profile = world(home)
    (profile / "chrome" / "peekafoxy-status.json").write_text(STATUS_LIES[name])
    found = run(home, ff, profile=profile)
    assert_sound(found)
    safe = found.redacted(logs.Redactor(home=str(home), user=None))
    for text in (report.to_json(safe), report.to_markdown(safe)):
        assert "\x1b" not in text and "\x07" not in text and "\u202e" not in text


def test_nesting_too_deep_is_a_reason_not_a_recursion_error(home: Path):
    ff, profile = world(home)
    (profile / "chrome" / "peekafoxy-status.json").write_text(STATUS_LIES["nested-array"])
    check = check_of(run(home, ff, profile=profile), "status.file")
    assert check.code == errors.STATUS_UNUSABLE.code and "nested too deeply" in check.message


def test_an_enormous_message_is_cut_before_it_reaches_the_report(home: Path):
    ff, profile = world(home)
    text = json.dumps(
        {
            "schema": 1,
            "updated": NOW_ISO,
            "errors": [{"level": "error", "where": "w" * 250_000, "message": "m" * 250_000}],
            "health": {"h" * 150_000: "fail: " + "n" * 150_000},
        }
    )
    assert len(text) < 1024 * 1024
    (profile / "chrome" / "peekafoxy-status.json").write_text(text)
    found = run(home, ff, profile=profile)
    assert_sound(found)
    assert len(report.to_markdown(found)) < 20_000
    assert len(report.to_json(found)) < 20_000


def test_a_hundred_thousand_health_entries_do_not_make_a_hundred_thousand_lines(home: Path):
    ff, profile = world(home)
    health = {f"check{n}": "fail: broken" for n in range(30_000)}
    (profile / "chrome" / "peekafoxy-status.json").write_text(
        json.dumps({"schema": 1, "updated": NOW_ISO, "health": health})
    )
    check = check_of(run(home, ff, profile=profile), "status.health")
    assert "and 29995 more" in check.message and len(check.message) < 1000


def test_a_status_from_the_future_is_a_clock_warning(home: Path):
    ff, profile = world(home)
    (profile / "chrome" / "peekafoxy-status.json").write_text(STATUS_LIES["year-9999"])
    check = check_of(run(home, ff, profile=profile), "status.file")
    assert check.code == errors.STATUS_UNUSABLE.code and "in the future" in check.message
    assert "clock" in check.message


def test_files_dated_in_the_future_do_not_make_a_fresh_status_look_stale(home: Path):
    """The clock went backwards: every installed file is 'newer' than any status."""
    ff, profile = world(home)
    future = time.time() + 5 * 365 * 86400
    for path in (profile / "chrome").rglob("*"):
        if path.is_file():
            os.utime(path, (future, future))
    (profile / "chrome" / "peekafoxy-status.json").write_text(
        json.dumps({"schema": 1, "updated": NOW_ISO})
    )
    os.utime(profile / "chrome" / "peekafoxy-status.json", (future, future))
    check = check_of(run(home, ff, profile=profile), "status.file")
    assert check.status == OK


# --- caps and guards -----------------------------------------------------------------------------


def test_a_part_that_crashes_is_a_warning_and_the_other_parts_remain(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    ff, profile = world(home)

    def explode(*args, **kwargs):
        raise MemoryError("no")

    monkeypatch.setattr(doctor, "_profile_sections_all", explode)
    found = run(home, ff)
    assert check_of(found, "profiles.crashed").code == BUG
    assert check_of(found, "program.version").status == OK

    monkeypatch.setattr(doctor, "_firefox_sections", explode)
    assert check_of(run(home, ff), "firefox.crashed").code == BUG


def test_tiny_terminals_do_not_crash_the_table():
    from io import StringIO

    from rich.console import Console

    ff_report = doctor.collect(make_context(Path("/nonexistent")))
    for width in (1, 2, 5, 10, 20):
        console = Console(file=StringIO(), width=width, color_system=None)
        for part in report.to_rich(ff_report, verbose=True):
            console.print(part)


def strict_is_file(self: Path) -> bool:
    """``Path.is_file`` as Python 3.10 to 3.12 have it: only 'not there' errors are swallowed."""
    try:
        return stat.S_ISREG(self.stat().st_mode)
    except OSError as error:
        if error.errno in (2, 20, 9, 40):  # ENOENT, ENOTDIR, EBADF, ELOOP
            return False
        raise


def strict_is_dir(self: Path) -> bool:
    try:
        return stat.S_ISDIR(self.stat().st_mode)
    except OSError as error:
        if error.errno in (2, 20, 9, 40):
            return False
        raise


@needs_permissions
@pytest.mark.parametrize("what", list(PATHS_TO_BREAK))
def test_permission_denied_with_the_stricter_path_checks_of_python_3_10(
    home: Path, what: str, restore_permissions, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(Path, "is_file", strict_is_file)
    monkeypatch.setattr(Path, "is_dir", strict_is_dir)
    ff, profile = world(home)
    (profile / "prefs.js").write_text("x")
    (profile / "chrome" / "peekafoxy-status.json").write_text("{}")
    target = PATHS_TO_BREAK[what](home, ff, profile)
    target.mkdir(parents=True, exist_ok=True) if what == "distribution" else None
    deny(restore_permissions, target)
    assert_sound(run(home, ff, profile=profile if what != "profiles folder" else None))
