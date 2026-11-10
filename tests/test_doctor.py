"""The doctor's checks, each against fake machines, installs and profiles in tmp_path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from doctor_support import (
    LOADER_TEXT,
    NOW,
    PROFILE_DIR,
    check_of,
    make_context,
    make_firefox,
    make_profile,
    pin_loader,
)
from support import needs_permissions

from peek_a_foxy import assets, doctor, elevate, errors, loader, userfiles
from peek_a_foxy.errors import PeekError, PlatformError
from peek_a_foxy.report import FAIL, OK, WARN

CRLF = b"\r\n"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_loader(monkeypatch)


def run(home: Path, **overrides):
    return doctor.collect(make_context(home, **overrides))


# --- Program ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frozen", "file", "expected"),
    [
        (True, "C:/x/peek_a_foxy/doctor.py", "standalone"),
        (
            False,
            "/home/u/.local/pipx/venvs/peek-a-foxy/lib/p/site-packages/peek_a_foxy/d.py",
            "pipx",
        ),
        (
            False,
            "C:\\Users\\u\\pipx\\venvs\\peek-a-foxy\\Lib\\site-packages\\peek_a_foxy\\d.py",
            "pipx",
        ),
        (
            False,
            "/home/u/.local/share/uv/tools/peek-a-foxy/lib/site-packages/peek_a_foxy/d.py",
            "uv",
        ),
        (False, "/usr/lib/python3/site-packages/peek_a_foxy/doctor.py", "pip"),
        (False, "/usr/lib/python3/dist-packages/peek_a_foxy/doctor.py", "pip"),
        (False, "/nowhere/doctor.py", "unknown"),
        (False, "doctor.py", "unknown"),
    ],
)
def test_how_the_program_runs_is_guessed_from_where_it_lives(frozen, file, expected):
    assert expected in doctor.how_it_runs(frozen, file)


def test_a_source_checkout_is_recognised():
    assert "source checkout" in doctor.how_it_runs(False, doctor.__file__)


def test_the_program_section_reports_the_facts(home: Path):
    report = run(home, version="9.9.9", is_admin=lambda: True)
    program = {c.id: c for c in report.sections[0].checks}
    assert program["program.version"].value == "9.9.9"
    assert program["program.python"].value == "3.13.0 (CPython)"
    assert "Linux-6.0" in program["program.os"].value
    assert program["program.admin"].value == "yes, running as root"
    assert "encoding utf-8" in program["program.terminal"].value
    assert program["program.git"].value == "2.40.0"
    assert program["program.loader_pin"].value == f"commit {doctor.loader.DEFAULT_COMMIT}"
    assert program["program.assets"].status == OK
    assert program["program.log"].value == "turned off"
    assert all(c.status == OK for c in program.values())


def test_a_windows_administrator_is_called_that():
    check = doctor._admin_check(make_context(Path("."), kind="windows", is_admin=lambda: True))
    assert "an administrator" in check.value


def test_a_normal_user_is_not_an_administrator(home: Path):
    assert run(home).sections[0].checks[4].value == "no (normal user)"


def test_a_terminal_that_is_not_utf8_is_a_warning_with_a_hint(home: Path):
    check = check_of(run(home, encoding="cp1252", environ={"TERM": "xterm"}), "program.terminal")
    assert check.status == WARN and check.code == errors.CONSOLE_ENCODING.code
    assert "cp1252" in check.message and "TERM=xterm" in check.value and check.hint


def test_an_unknown_encoding_is_a_warning_not_a_crash(home: Path):
    assert check_of(run(home, encoding="unknown"), "program.terminal").status == WARN


def test_a_missing_git_is_a_warning_that_says_what_needs_it(home: Path):
    check = check_of(run(home, which=lambda name: None), "program.git")
    assert check.status == WARN and check.code == errors.GIT_MISSING.code
    assert "only the `install` command needs it" in check.message


def test_a_git_that_does_not_run_is_a_warning_too(home: Path):
    def broken(command):
        raise subprocess.CalledProcessError(1, command)

    check = check_of(run(home, run_command=broken), "program.git")
    assert check.status == WARN and "could not be run" in check.message


VALID = "a" * 40


def what_install_does(kind: str, environ: dict[str, str], monkeypatch, tmp_path: Path):
    """The code that ``install`` ends with for these variables, or ``None`` if it goes on.

    The pin is read the way ``install`` reads it (``loader.pinned_commit``); an override is then
    refused by the copy that needs rights: the administrator step on Windows, sudo elsewhere.
    """
    for name in ("FXAC_COMMIT", "FXAC_REPO"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    try:
        loader.pinned_commit()
        for name, text in LOADER_TEXT.items():  # the files that the pinned hashes stand for
            source = tmp_path / "program" / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(text)
        if kind == "windows":
            elevate.copy_as_administrator(tmp_path, tmp_path, lambda command: 0)
        else:
            loader.verified_bytes(
                tmp_path / "program" / "config.js", "config.js", allow_unverified=False
            )
    except PeekError as error:
        return error.code
    return None


@pytest.mark.parametrize("kind", ["linux", "macos", "windows"])
@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"FXAC_COMMIT": ""},  # `export FXAC_COMMIT=` in a shell file
        {"FXAC_REPO": ""},
        {"FXAC_COMMIT": "main"},
        {"FXAC_COMMIT": "a" * 39},
        {"FXAC_COMMIT": "--upload-pack=x"},
        {"FXAC_COMMIT": "a" * 40 + "\n"},
        {"FXAC_COMMIT": VALID},
        {"FXAC_COMMIT": VALID.upper()},
        {"FXAC_REPO": "/some/repo"},
        {"FXAC_REPO": "/some/repo", "FXAC_COMMIT": VALID},
        {"FXAC_REPO": "/some/repo", "FXAC_COMMIT": "main"},
        {"FXAC_REPO": "", "FXAC_COMMIT": ""},
    ],
    ids=lambda environ: ",".join(f"{k}={v[:12]!r}" for k, v in environ.items()) or "unset",
)
def test_the_doctor_names_the_loader_pin_the_way_install_would_refuse_it(
    home: Path, monkeypatch, tmp_path: Path, kind: str, environ: dict[str, str]
):
    """Three modules once read 'is it set' three ways; the doctor must agree with ``install``."""
    wanted = what_install_does(kind, environ, monkeypatch, tmp_path)
    check = check_of(run(home, kind=kind, environ=environ), "program.loader_pin")
    if wanted is None:  # install goes on with the pinned loader (the empty values mean "not set")
        assert check.status == OK and check.code == "", check
        assert check.value == f"commit {doctor.loader.DEFAULT_COMMIT}"
    else:
        assert check.status == WARN and check.code == wanted.code, (check, wanted.code)
        assert check.hint == wanted.hint  # the same way forward that the error would give


def test_a_pin_of_a_hostile_length_is_shortened_in_the_report(home: Path):
    check = check_of(run(home, environ={"FXAC_COMMIT": "x" * 100_000}), "program.loader_pin")
    assert check.code == errors.BAD_PINNED_COMMIT.code and len(check.value) < 500


def test_missing_bundled_files_fail(home: Path, tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    check = check_of(run(home, assets_dir=lambda: empty), "program.assets")
    assert check.status == FAIL and check.code == errors.FILES_MISSING.code
    assert "autohide.css" in check.message


def test_an_unlocatable_assets_folder_fails_with_its_own_code(home: Path):
    def nowhere():
        raise PlatformError(errors.FILES_MISSING, "could not find the Peek-a-Foxy files to install")

    report = run(home, assets_dir=nowhere)
    check = check_of(report, "program.assets")
    assert check.status == FAIL and check.code == errors.FILES_MISSING.code


def test_an_unsupported_system_fails_with_its_code(home: Path):
    check = check_of(run(home, unsupported="freebsd14"), "program.os")
    assert check.status == FAIL and check.code == errors.UNSUPPORTED_OS.code
    assert "freebsd14" in check.message


def test_the_log_place_is_shown_and_an_unwritable_one_is_a_warning(home: Path):
    target = home / "logs" / "x" / "peek-a-foxy.log"
    assert check_of(run(home, log_target=target), "program.log").value == str(target)
    bad = check_of(run(home, log_target=target, can_write=lambda path: False), "program.log")
    assert bad.status == WARN and bad.code == errors.FILE_IO.code


# --- Firefox installs ---------------------------------------------------------------------------


def test_a_good_install_is_all_ok(home: Path):
    ff = make_firefox(home / "ff")
    section = run(home, firefox_candidates=lambda: [ff]).sections[1]
    assert section.id == "firefox.1"
    assert [c.status for c in section.checks] == [OK] * len(section.checks)
    version = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.version")
    assert version.value == "Firefox 150.0 (build 20261020000000, channel release)"


def test_every_install_found_is_checked_not_only_the_first(home: Path):
    a, b, c = (make_firefox(home / n) for n in "abc")
    report = run(home, firefox_candidates=lambda: [a, b, c])
    assert [s.id for s in report.sections[1:4]] == ["firefox.1", "firefox.2", "firefox.3"]


def test_a_given_firefox_dir_replaces_the_search(home: Path):
    a, b = make_firefox(home / "a"), make_firefox(home / "b")
    report = doctor.collect(make_context(home, firefox_candidates=lambda: [a]), firefox_dir=b)
    folders = [c.value for s in report.sections for c in s.checks if c.id == "firefox.path"]
    assert folders == [str(b)]


def test_no_firefox_at_all_is_a_failure_with_a_hint(home: Path):
    check = check_of(run(home), "firefox.found")
    assert check.status == FAIL and check.code == errors.FIREFOX_NOT_FOUND.code
    assert "--firefox-dir" in check.hint


def test_a_search_that_raises_counts_as_nothing_found(home: Path):
    def refuse():
        raise PlatformError(errors.UNSUPPORTED_OS, "unsupported platform")

    assert check_of(run(home, firefox_candidates=refuse), "firefox.found").status == FAIL


@pytest.mark.parametrize("ini", ["", "[Other]\nx=1\n", "\x00\x01 not an ini", "[App\nbroken"])
def test_a_missing_or_malformed_application_ini_is_a_warning(home: Path, ini: str):
    ff = make_firefox(home / "ff", application_ini=ini)
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.version")
    assert check.status == WARN and check.code == errors.FIREFOX_INFO_UNREADABLE.code
    assert "version of this Firefox is unknown" in check.message


@pytest.mark.parametrize(
    ("version", "channel", "expected"),
    [
        ("150.0", "release", "release"),
        ("158.0", "aurora", "aurora"),
        ("152.0a1", None, "nightly"),
        ("151.0b3", None, "beta or developer edition"),
        ("150.0", None, "unknown"),
    ],
)
def test_the_channel_comes_from_the_prefs_or_from_the_version(home, version, channel, expected):
    ff = make_firefox(home / "ff", version=version, channel=channel)
    assert doctor.guess_channel(ff, version) == expected


def test_a_folder_the_user_cannot_write_is_normal_and_says_how_it_is_handled(home: Path):
    ff = make_firefox(home / "ff")
    check = check_of(
        run(home, firefox_candidates=lambda: [ff], can_write=lambda p: False), "firefox.writable"
    )
    assert check.status == OK and "sudo" in check.value
    windows = check_of(
        run(home, firefox_candidates=lambda: [ff], can_write=lambda p: False, kind="windows"),
        "firefox.writable",
    )
    assert windows.status == OK and "administrator prompt" in windows.value


def test_a_real_read_only_folder_is_seen_as_such(home: Path):
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("needs POSIX permissions and not root")
    ff = make_firefox(home / "ff")
    ff.chmod(0o555)
    try:
        report = doctor.collect(
            make_context(home, can_write=doctor._default_can_write, firefox_candidates=lambda: [ff])
        )
    finally:
        ff.chmod(0o755)
    assert check_of(report, "firefox.writable").value.startswith("no")


def test_program_files_counts_as_protected_on_windows_without_rights(home: Path):
    folder = home / "Program Files" / "Mozilla Firefox"
    ff = make_firefox(folder)
    environ = {"ProgramFiles": str(home / "Program Files")}
    kwargs = {"kind": "windows", "environ": environ, "firefox_candidates": lambda: [ff]}
    assert check_of(run(home, **kwargs), "firefox.writable").value.startswith("no")
    admin = check_of(run(home, is_admin=lambda: True, **kwargs), "firefox.writable")
    assert admin.value == "yes"


def test_an_msix_like_install_fails_as_sandboxed(home: Path):
    ff = make_firefox(home / "Program Files" / "WindowsApps" / "Mozilla.Firefox_1" / "app")
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.sandbox")
    assert check.status == FAIL and check.code == errors.FIREFOX_SANDBOXED.code
    assert "Microsoft Store (MSIX)" in check.message


@pytest.mark.parametrize(
    ("folder", "name"), [("snap/firefox/current", "Snap"), ("flatpak/app", "Flatpak")]
)
def test_snap_and_flatpak_installs_fail_as_sandboxed(home: Path, folder: str, name: str):
    ff = make_firefox(home / folder)
    assert name in check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.sandbox").message


def test_a_sandboxed_install_is_only_a_warning_when_another_one_works(home: Path):
    make_profile(home)
    bad = make_firefox(home / "snap" / "firefox")
    good = make_firefox(home / "good")
    report = run(home, firefox_candidates=lambda: [bad, good])
    sandbox = check_of(report, "firefox.sandbox", "firefox.1")
    assert sandbox.status == WARN and "only a warning" in sandbox.message
    assert sandbox.code == errors.FIREFOX_SANDBOXED.code
    assert check_of(report, "firefox.sandbox", "firefox.2").status == OK
    assert report.counts[FAIL] == 0 and report.ok


def test_all_installs_broken_stays_a_failure(home: Path):
    a = make_firefox(home / "a", loader=False)
    b = make_firefox(home / "snap" / "b")
    report = run(home, firefox_candidates=lambda: [a, b])
    assert check_of(report, "firefox.loader", "firefox.1").status == FAIL
    assert check_of(report, "firefox.sandbox", "firefox.2").status == FAIL
    assert not report.ok


def test_a_missing_loader_fails_and_names_the_files(home: Path):
    ff = make_firefox(home / "ff", loader=False)
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.loader")
    assert check.status == FAIL and check.code == errors.LOADER_MISSING.code
    assert "config.js" in check.message and "config-prefs.js" in check.message
    assert "peek-a-foxy install" in check.hint


def test_half_a_loader_is_missing_too(home: Path):
    ff = make_firefox(home / "ff")
    (ff / "config.js").unlink()
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.loader")
    assert check.status == FAIL and "config.js" in check.message
    assert "config-prefs.js" not in check.message


def test_a_loader_with_another_hash_is_a_warning(home: Path):
    ff = make_firefox(home / "ff")
    (ff / "config.js").write_text("// somebody else's\n")
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.loader")
    assert check.status == WARN and check.code == errors.LOADER_DIFFERENT.code
    assert "config.js" in check.message and "sha256" in check.detail


def test_crlf_line_endings_do_not_count_as_a_different_loader(home: Path):
    ff = make_firefox(home / "ff")
    path = ff / "config.js"
    path.write_bytes(path.read_bytes().replace(b"\n", CRLF))
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.loader")
    assert check.status == OK and "CRLF" in check.detail


def test_an_unreadable_loader_file_is_a_warning_with_the_file_code(home: Path, monkeypatch):
    ff = make_firefox(home / "ff")
    monkeypatch.setattr(doctor, "_read_bytes", lambda path: None)
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.loader")
    assert check.status == WARN and check.code == errors.FILE_IO.code


def write_pref(ff: Path, name: str, text: str) -> None:
    (ff / "defaults" / "pref").mkdir(parents=True, exist_ok=True)
    (ff / "defaults" / "pref" / name).write_text(text)


def test_a_foreign_autoconfig_is_found_with_its_file_and_target(home: Path):
    """What the Windows runner image has: local-settings.js pointing at mozilla.cfg."""
    ff = make_firefox(home / "ff")
    write_pref(
        ff,
        "local-settings.js",
        'pref("general.config.obscure_value", 0);\n'
        'pref("general.config.filename", "mozilla.cfg");\n',
    )
    (ff / "mozilla.cfg").write_text("// lock\n")
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.autoconfig")
    assert check.status == WARN and check.code == errors.AUTOCONFIG_FOREIGN.code
    assert "local-settings.js (points to mozilla.cfg)" in check.message
    assert "mozilla.cfg" in check.detail


def test_our_own_autoconfig_pref_is_not_foreign(home: Path):
    ff = make_firefox(home / "ff")
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.autoconfig")
    assert check.status == OK and check.value == "none"


def test_our_pref_file_pointing_elsewhere_is_foreign(home: Path):
    ff = make_firefox(home / "ff")
    write_pref(ff, "config-prefs.js", "pref('general.config.filename', 'mine.cfg');\n")
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.autoconfig")
    assert check.status == WARN and "config-prefs.js (points to mine.cfg)" in check.message


def test_a_commented_out_autoconfig_line_is_ignored(home: Path):
    ff = make_firefox(home / "ff")
    write_pref(
        ff,
        "old.js",
        '// pref("general.config.filename", "x.cfg");\n'
        '/* pref("general.config.filename", "y.cfg"); */\n',
    )
    assert check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.autoconfig").status == OK


def test_a_stray_cfg_file_alone_is_only_a_note(home: Path):
    ff = make_firefox(home / "ff")
    (ff / "old.cfg").write_text("x")
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.autoconfig")
    assert check.status == OK and "old.cfg" in check.value


def test_policies_json_is_reported_by_presence_only(home: Path):
    ff = make_firefox(home / "ff")
    assert (
        check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.policies").value
        == "not present"
    )
    (ff / "distribution").mkdir()
    (ff / "distribution" / "policies.json").write_text('{"policies": {"secret": "x"}}')
    check = check_of(run(home, firefox_candidates=lambda: [ff]), "firefox.policies")
    assert check.value.startswith("present") and "secret" not in check.value + check.detail


# --- profiles.ini -------------------------------------------------------------------------------


def test_a_missing_profiles_ini_fails_with_the_discovery_code(home: Path):
    check = check_of(run(home), "profiles.ini")
    assert check.status == FAIL and check.code == errors.NO_PROFILES_INI.code


def test_a_missing_profiles_ini_is_only_a_warning_when_the_profile_is_given(home: Path):
    profile = make_profile(home, with_ini=False)
    report = doctor.collect(make_context(home), profile=profile)
    assert check_of(report, "profiles.ini").status == WARN
    assert check_of(report, "profile.files").status == OK
    assert any(s.title == "Profile: given with --profile" for s in report.sections)


def test_a_malformed_profiles_ini_has_its_own_code(home: Path):
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True)
    (root / "profiles.ini").write_bytes(b"\xff\xfe[Profile0\x00")
    assert check_of(run(home), "profiles.ini").code in {
        errors.PROFILES_UNREADABLE.code,
        errors.NO_PROFILE_LISTED.code,
    }


def test_a_profiles_ini_without_profiles_says_so(home: Path):
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True)
    (root / "profiles.ini").write_text("[General]\nVersion=2\n")
    assert check_of(run(home), "profiles.ini").code == errors.NO_PROFILE_LISTED.code


def test_the_default_of_each_install_is_flagged_and_checked(home: Path):
    make_profile(home, folder="aaaa1111.release", name="release", default=True)
    make_profile(home, folder="bbbb2222.dev", name="dev", default=True)
    make_profile(home, folder="cccc3333.other", name="other", default=False, installed=False)
    report = run(home)
    listing = {c.id: c.value for c in next(s for s in report.sections if s.id == "profiles").checks}
    assert "default of an install" in listing["profiles.1"] and "installed" in listing["profiles.1"]
    assert "default of an install" not in listing["profiles.3"]
    assert listing["profiles.3"].startswith("not installed")
    assert [s.title for s in report.sections if s.id.startswith("profile.")] == [
        "Profile: <profile 1>",
        "Profile: <profile 2>",
    ]


def test_without_a_default_every_profile_is_checked_with_a_warning(home: Path):
    make_profile(home, folder="aaaa1111.one", name="one", default=False)
    make_profile(home, folder="bbbb2222.two", name="two", default=False)
    report = run(home)
    assert check_of(report, "profiles.default").code == errors.AMBIGUOUS_PROFILE.code
    assert len([s for s in report.sections if s.id.startswith("profile.")]) == 2


def test_a_single_profile_is_the_selected_one_even_without_a_default_flag(home: Path):
    make_profile(home, default=False)
    report = run(home)
    assert len([s for s in report.sections if s.id.startswith("profile.")]) == 1
    assert all(c.id != "profiles.default" for s in report.sections for c in s.checks)


def test_a_partly_installed_profile_is_listed_as_such(home: Path):
    path = make_profile(home)
    (path / "chrome" / "autohide.css").unlink()
    listing = check_of(run(home), "profiles.1")
    assert "partly installed (3 of 4 files)" in listing.value


def test_the_given_profile_is_matched_to_its_name_in_profiles_ini(home: Path):
    path = make_profile(home)
    report = doctor.collect(make_context(home), profile=path)
    assert any(s.title == "Profile: <profile 1>" for s in report.sections)


def test_a_profile_folder_that_does_not_exist_fails(home: Path):
    report = doctor.collect(make_context(home), profile=home / "nowhere")
    check = check_of(report, "profile.folder")
    assert check.status == FAIL and check.code == errors.PROFILE_FOLDER_MISSING.code


# --- a profile's files --------------------------------------------------------------------------


def profile_report(home: Path, path: Path):
    return doctor.collect(make_context(home), profile=path)


def test_a_complete_install_has_nothing_to_complain_about(home: Path):
    path = make_profile(home)
    report = profile_report(home, path)
    profile = next(s for s in report.sections if s.id == "profile.1")
    assert [c.status for c in profile.checks] == [OK] * len(profile.checks)
    assert check_of(report, "profile.files").value.startswith("all 4 present and identical")


def test_missing_files_fail_and_are_named(home: Path):
    path = make_profile(home)
    (path / "chrome" / "JS" / "autohide.uc.js").unlink()
    check = check_of(profile_report(home, path), "profile.files")
    assert check.status == FAIL and check.code == errors.PROFILE_FILES_MISSING.code
    assert "JS/autohide.uc.js" in check.message


def test_a_file_that_differs_from_the_bundled_one_is_a_warning(home: Path):
    path = make_profile(home)
    (path / "chrome" / "autohide.css").write_text("/* edited */\n")
    check = check_of(profile_report(home, path), "profile.files")
    assert check.status == WARN and check.code == errors.PROFILE_FILES_DIFFERENT.code
    assert "autohide.css" in check.message and "sha256" in check.detail


def test_only_the_line_endings_differing_is_a_note_not_a_difference(home: Path):
    path = make_profile(home)
    css = path / "chrome" / "autohide.css"
    css.write_bytes(css.read_bytes().replace(b"\n", CRLF))
    check = check_of(profile_report(home, path), "profile.files")
    assert check.status == OK and "line endings differ" in check.detail


def test_files_are_not_compared_when_the_bundled_ones_cannot_be_found(home: Path):
    def nowhere():
        raise PlatformError(errors.FILES_MISSING, "gone")

    path = make_profile(home)
    report = doctor.collect(make_context(home, assets_dir=nowhere), profile=path)
    assert "not compared" in check_of(report, "profile.files").value
    assert check_of(report, "program.assets").status == FAIL


def test_the_loaders_utils_must_be_there(home: Path):
    path = make_profile(home)
    (path / "chrome" / "utils" / "boot.sys.mjs").unlink()
    check = check_of(profile_report(home, path), "profile.utils")
    assert check.status == FAIL and check.code == errors.UTILS_MISSING.code
    (path / "chrome" / "utils").rmdir()
    assert check_of(profile_report(home, path), "profile.utils").status == FAIL


@pytest.mark.parametrize(
    ("css", "state"),
    [
        (f"{userfiles.CSS_IMPORT}\n", "ok"),
        (f'@charset "utf-8";\n{userfiles.CSS_IMPORT}\na {{ color: red }}\n', "ok"),
        (f"/* mine */\n{userfiles.CSS_IMPORT}\n", "ok"),
        (f"a {{ color: red }}\n{userfiles.CSS_IMPORT}\n", "late"),
        (f"@namespace url(x);\n{userfiles.CSS_IMPORT}\n", "late"),
        (f"/* {userfiles.CSS_IMPORT} */\n", "missing"),
        (f"{userfiles.LEGACY_CSS_IMPORT}\n", "legacy"),
        (f"a {{}}\n{userfiles.LEGACY_CSS_IMPORT}\n", "missing"),
        ("a { color: red }\n", "missing"),
        ("", "missing"),
    ],
)
def test_the_import_line_states(css: str, state: str):
    assert doctor.import_state(css) == state


@pytest.mark.parametrize(
    ("css", "status", "code"),
    [
        (f"a {{}}\n{userfiles.CSS_IMPORT}\n", FAIL, errors.CSS_IMPORT_LATE),
        ("a {}\n", FAIL, errors.CSS_IMPORT_MISSING),
        (f"{userfiles.LEGACY_CSS_IMPORT}\n", FAIL, errors.CSS_IMPORT_MISSING),
    ],
)
def test_a_wrong_import_line_fails_with_the_right_code(home, css, status, code):
    path = make_profile(home)
    (path / "chrome" / "userChrome.css").write_text(css)
    check = check_of(profile_report(home, path), "profile.import")
    assert (check.status, check.code) == (status, code.code)


def test_a_missing_user_chrome_css_fails(home: Path):
    path = make_profile(home)
    (path / "chrome" / "userChrome.css").unlink()
    check = check_of(profile_report(home, path), "profile.import")
    assert check.status == FAIL and "does not exist" in check.message


def test_a_user_chrome_css_that_is_not_text_does_not_crash(home: Path):
    path = make_profile(home)
    (path / "chrome" / "userChrome.css").write_bytes(
        b"\xff\xfe\x00" + userfiles.CSS_IMPORT.encode()
    )
    assert check_of(profile_report(home, path), "profile.import").status in (OK, FAIL)


# --- prefs --------------------------------------------------------------------------------------


def set_user_js(path: Path, text: str) -> None:
    (path / "user.js").write_text(text)


def test_prefs_are_parsed_from_pref_lines_only():
    text = (
        'user_pref("a.b", true);\n// user_pref("c", 1);\nuser_pref("d", "x y");\n'
        'user_pref("a.b", false);\n  user_pref( "e" , 5 ) ;\nnot a pref\n'
    )
    assert doctor.parse_prefs(text) == {"a.b": "false", "d": '"x y"', "e": "5"}


def test_a_user_js_with_both_prefs_is_ok(home: Path):
    report = profile_report(home, make_profile(home))
    assert check_of(report, "profile.pref_stylesheets").value == "true (user.js)"
    assert check_of(report, "profile.pref_subdocuments").status == OK


def test_a_pref_only_in_prefs_js_is_ok_but_says_where(home: Path):
    path = make_profile(home)
    set_user_js(path, "")
    (path / "prefs.js").write_text(f'user_pref("{userfiles.STYLESHEETS_PREF}", true);\n')
    check = check_of(profile_report(home, path), "profile.pref_stylesheets")
    assert check.status == OK and "prefs.js only" in check.value


def test_a_pref_turned_off_in_user_js_fails_even_if_prefs_js_says_true(home: Path):
    path = make_profile(home)
    set_user_js(path, f'user_pref("{userfiles.STYLESHEETS_PREF}", false);\n')
    (path / "prefs.js").write_text(f'user_pref("{userfiles.STYLESHEETS_PREF}", true);\n')
    check = check_of(profile_report(home, path), "profile.pref_stylesheets")
    assert check.status == FAIL and check.code == errors.PREFS_MISSING.code
    assert "false in user.js" in check.message


def test_the_stylesheet_pref_missing_fails_and_the_settings_page_one_only_warns(home: Path):
    path = make_profile(home)
    (path / "user.js").unlink()
    report = profile_report(home, path)
    css, page = (
        check_of(report, "profile.pref_stylesheets"),
        check_of(report, "profile.pref_subdocuments"),
    )
    assert (css.status, page.status) == (FAIL, WARN)
    assert "not set" in css.message and css.code == page.code == errors.PREFS_MISSING.code


def test_our_prefs_in_prefs_js_are_reported_with_their_values(home: Path):
    path = make_profile(home)
    (path / "prefs.js").write_text(
        'user_pref("peekafoxy.tabs.autohide", true);\nuser_pref("peekafoxy.strip.px", 6);\n'
        'user_pref("other.thing", 1);\n'
    )
    set_user_js(path, (path / "user.js").read_text() + 'user_pref("peekafoxy.show.ms", 90);\n')
    value = check_of(profile_report(home, path), "profile.own_prefs").value
    assert "peekafoxy.tabs.autohide=true" in value and "peekafoxy.strip.px=6" in value
    assert (
        "other.thing" not in value and "also in user.js" in value and "peekafoxy.show.ms" in value
    )


def test_no_own_prefs_means_the_defaults_are_used(home: Path):
    value = check_of(profile_report(home, make_profile(home)), "profile.own_prefs").value
    assert "defaults are used" in value


def test_a_user_js_that_is_not_utf8_does_not_crash_the_doctor(home: Path):
    path = make_profile(home)
    (path / "user.js").write_bytes(b"\xff\xfe\x00 garbage\n")
    report = profile_report(home, path)
    assert check_of(report, "profile.pref_stylesheets").status == FAIL


@needs_permissions
def test_an_unreadable_prefs_js_is_a_warning_with_the_file_code(home: Path):
    path = make_profile(home)
    prefs = path / "prefs.js"
    prefs.write_text("x")
    prefs.chmod(0)
    try:
        check = check_of(profile_report(home, path), "profile.read_prefs")
    finally:
        prefs.chmod(0o644)
    assert check.status == WARN and check.code == errors.FILE_IO.code


# --- the startup cache --------------------------------------------------------------------------


def make_cache(home: Path, age: int) -> Path:
    """A startup cache whose file is ``age`` seconds older than the newest installed file."""
    cache = home / ".cache" / "mozilla" / "firefox" / PROFILE_DIR / "startupCache"
    cache.mkdir(parents=True)
    file = cache / "startupCache.8.little"
    file.write_text("x")
    newest = max(p.stat().st_mtime for p in (home / ".mozilla").rglob("*") if p.is_file())
    os.utime(file, (newest - age, newest - age))
    return cache


def test_no_cache_found_is_fine(home: Path):
    assert check_of(profile_report(home, make_profile(home)), "profile.startup_cache").status == OK


def test_an_old_cache_and_a_script_that_never_reported_is_a_hint(home: Path):
    path = make_profile(home)
    make_cache(home, 3600)
    check = check_of(profile_report(home, path), "profile.startup_cache")
    assert check.status == WARN and check.code == errors.STARTUP_CACHE.code
    assert "about:support" in check.hint and "Clear startup cache" in check.hint


def test_a_new_cache_is_fine(home: Path):
    path = make_profile(home)
    make_cache(home, -3600)
    assert check_of(profile_report(home, path), "profile.startup_cache").status == OK


def test_an_old_cache_is_fine_once_firefox_has_reported(home: Path):
    path = make_profile(home)
    make_cache(home, 3600)
    (path / "chrome" / "peekafoxy-status.json").write_text(
        (Path(__file__).parent / "fixtures" / "peekafoxy-status.json").read_text()
    )
    assert check_of(profile_report(home, path), "profile.startup_cache").status == OK


@pytest.mark.parametrize(
    ("kind", "environ", "expected"),
    [
        ("linux", {}, "{home}/.cache/mozilla/firefox/p/startupCache"),
        ("linux", {"XDG_CACHE_HOME": "/x/cache"}, "/x/cache/mozilla/firefox/p/startupCache"),
        ("linux", {"XDG_CACHE_HOME": "relative"}, "{home}/.cache/mozilla/firefox/p/startupCache"),
        ("macos", {}, "{home}/Library/Caches/Firefox/Profiles/p/startupCache"),
        ("windows", {"LOCALAPPDATA": "/l"}, "/l/Mozilla/Firefox/Profiles/p/startupCache"),
        ("windows", {}, "{home}/AppData/Local/Mozilla/Firefox/Profiles/p/startupCache"),
    ],
)
def test_where_each_system_keeps_the_startup_cache(kind, environ, expected):
    home = Path("/h")
    found = doctor.cache_dirs(kind, environ, home, Path("/profiles/p"))
    assert str(found[0]) == Path(expected.format(home=home)).as_posix().replace("/", os.sep)


# --- what Firefox reported ----------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "peekafoxy-status.json"


def put_status(path: Path, text: str) -> None:
    (path / "chrome" / "peekafoxy-status.json").write_text(text)


def status_of(home: Path, path: Path, check_id: str = "status.file"):
    return check_of(profile_report(home, path), check_id)


def test_a_missing_status_file_says_what_to_do_in_plain_words(home: Path):
    check = status_of(home, make_profile(home))
    assert check.status == WARN and check.code == errors.STATUS_MISSING.code
    assert (
        check.message
        == "Firefox has not run the script yet; close all of its windows and start Firefox again."
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{not json",
        "[]",
        '{"updated": "2026-11-05T00:00:00Z"}',
        '{"schema": "1", "updated": "2026-11-05T00:00:00Z"}',
        '{"schema": 1}',
        '{"schema": 1, "updated": "yesterday"}',
        '{"schema": 1, "updated": "2026-11-05T00:00:00Z", "health": []}',
        '{"schema": 1, "updated": "2026-11-05T00:00:00Z", "errors": {}}',
        '{"schema": 0, "updated": "2026-11-05T00:00:00Z"}',
        '{"schema": true, "updated": "2026-11-05T00:00:00Z"}',
    ],
)
def test_a_damaged_status_file_is_a_clear_warning_never_a_crash(home: Path, text: str):
    path = make_profile(home)
    put_status(path, text)
    check = status_of(home, path)
    assert check.status == WARN and check.code == errors.STATUS_UNUSABLE.code
    assert "cannot be used" in check.message


def test_a_status_from_a_newer_script_asks_for_an_update(home: Path):
    path = make_profile(home)
    put_status(path, '{"schema": 2, "updated": "2026-11-05T00:00:00Z"}')
    assert "peek-a-foxy needs to be updated" in status_of(home, path).message


def test_a_status_file_that_is_not_utf8_is_a_warning(home: Path):
    path = make_profile(home)
    (path / "chrome" / "peekafoxy-status.json").write_bytes(b"\xff\xfe\x00\x01")
    assert status_of(home, path).status == WARN


def test_a_status_older_than_the_installed_files_means_firefox_did_not_restart(home: Path):
    path = make_profile(home)
    put_status(path, '{"schema": 1, "updated": "2000-01-01T00:00:00Z"}')
    check = status_of(home, path)
    assert check.status == WARN and check.code == errors.STATUS_UNUSABLE.code
    assert "has not been restarted since" in check.message and "start Firefox" in check.hint


def at(seconds: int) -> str:
    """The doctor's clock (``NOW``) plus ``seconds``, as the script writes a time."""
    return (NOW + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def date_the_installed_files(path: Path, seconds: int) -> None:
    stamp = (NOW + timedelta(seconds=seconds)).timestamp()
    for name in assets.FILES:
        os.utime(path / "chrome" / name, (stamp, stamp))


@pytest.mark.parametrize("skew", [1, 60, 600, 3600, 86400])
def test_a_status_a_little_ahead_of_the_clock_is_accepted(home: Path, skew: int):
    """Two clocks that differ by minutes (a VM, a laptop just back from sleep) are not a fault."""
    path = make_profile(home)
    put_status(path, f'{{"schema": 1, "updated": "{at(skew)}"}}')
    check = status_of(home, path)
    assert check.status == OK, check.message


@pytest.mark.parametrize("skew", [86401, 86400 * 2])
def test_a_status_more_than_a_day_ahead_is_a_clock_warning(home: Path, skew: int):
    path = make_profile(home)
    put_status(path, f'{{"schema": 1, "updated": "{at(skew)}"}}')
    check = status_of(home, path)
    assert check.status == WARN and "in the future" in check.message


@pytest.mark.parametrize("skew", [60, 600, 86400])
def test_installed_files_a_little_ahead_of_the_clock_still_count(home: Path, skew: int):
    """Not 'in the future so they prove nothing': a status from before them means no restart."""
    path = make_profile(home)
    date_the_installed_files(path, skew)
    put_status(path, f'{{"schema": 1, "updated": "{at(-3600)}"}}')
    check = status_of(home, path)
    assert check.status == WARN and "has not been restarted since" in check.message


def test_installed_files_more_than_a_day_ahead_prove_nothing(home: Path):
    path = make_profile(home)
    date_the_installed_files(path, 86400 + 1)
    put_status(path, f'{{"schema": 1, "updated": "{at(-3600)}"}}')
    assert status_of(home, path).status == OK


@pytest.mark.parametrize(
    ("behind", "fresh"),
    [(0, True), (1, True), (2, True), (3, False), (60, False)],
)
def test_a_status_up_to_two_seconds_older_than_the_files_still_counts_as_fresh(
    home: Path, behind: int, fresh: bool
):
    """The script reports in the same second that Firefox starts; file times are rounded."""
    path = make_profile(home)
    date_the_installed_files(path, -1000)
    put_status(path, f'{{"schema": 1, "updated": "{at(-1000 - behind)}"}}')
    check = status_of(home, path)
    assert (check.status == OK) is fresh, check.message


@pytest.mark.parametrize(
    ("failed", "tail"), [(1, ""), (5, ""), (6, "; and 1 more"), (7, "; and 2 more")]
)
def test_the_health_list_names_five_failures_and_counts_the_rest(
    home: Path, failed: int, tail: str
):
    path = make_profile(home)
    health = {f"check{n}": "fail: broken" for n in range(failed)}
    put_status(path, json.dumps({"schema": 1, "updated": at(-1000), "health": health}))
    message = check_of(profile_report(home, path), "status.health").message
    assert f"{failed} health check" in message
    assert message.endswith(f"broken{tail}.")
    assert ("and 0 more" in message) is False
    assert sum(f"check{n}:" in message for n in range(failed)) == min(failed, 5)


def test_a_good_status_reports_the_script_firefox_health_and_errors(home: Path):
    path = make_profile(home)
    put_status(path, FIXTURE.read_text())
    report = profile_report(home, path)
    assert "last update 2026-11-05 12:00 UTC, 2 window(s)" in check_of(report, "status.file").value
    script = check_of(report, "status.script").value
    assert script.startswith("script 0.2.0, Firefox 150.0 (build 20261020000000, release)")
    health = check_of(report, "status.health")
    assert health.status == WARN and health.code == errors.FIREFOX_REPORTS_PROBLEM.code
    assert health.message == "1 health check failed: nav-bar: element #nav-bar not found."
    problem = check_of(report, "status.errors")
    assert problem.status == WARN and problem.code == errors.FIREFOX_SCRIPT_ERRORS.code
    assert "recorded 1 error;" in problem.message and "autohide.uc.js:reveal" in problem.message
    assert "started" in problem.detail  # the info entry is kept in the detail, not counted


def test_a_healthy_status_with_no_errors_is_all_ok(home: Path):
    path = make_profile(home)
    put_status(
        path,
        '{"schema": 1, "updated": "2026-11-05T00:00:00Z", "health": {"a": "ok", "b": "ok"}, '
        '"errors": [{"level": "warn", "message": "meh"}]}',
    )
    report = profile_report(home, path)
    assert check_of(report, "status.health").value == "2 checks ok"
    assert check_of(report, "status.errors").value == "none"
    assert "windows" not in check_of(report, "status.file").value.replace("? window(s)", "")


def test_a_status_with_odd_value_types_is_still_read(home: Path):
    path = make_profile(home)
    put_status(
        path,
        '{"schema": 1, "updated": "2026-11-05T00:00:00+02:00", "windows": "two", '
        '"firefoxVersion": 5, '
        '"health": {"x": 3}, "errors": ["text", {"message": "m"}]}',
    )
    report = profile_report(home, path)
    assert "? window(s)" in check_of(report, "status.file").value
    assert check_of(report, "status.health").status == WARN


# --- the doctor never crashes ---------------------------------------------------------------------


def test_a_check_that_raises_becomes_a_warning_and_the_rest_still_runs(home: Path, monkeypatch):
    def explode(ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "_git_check", explode)
    report = run(home)
    git = check_of(report, "program.git")
    assert git.status == WARN and git.code == errors.UNEXPECTED.code
    assert "RuntimeError: boom" in git.detail
    assert check_of(report, "program.version").status == OK


def test_the_report_is_stamped_with_the_injected_time_and_version(home: Path):
    report = run(home)
    assert report.generated == NOW.strftime("%Y-%m-%dT%H:%M:%SZ") and report.version == "1.2.3"


def test_the_real_machine_context_works_here():
    ctx = doctor.Context.detect(log_target=None)
    assert ctx.kind in {"linux", "macos", "windows"} and ctx.version
    assert ctx.python.split()[0] == sys.version.split()[0]
    assert ctx.assets_dir() == assets.assets_dir()
    assert ctx.is_admin() in (True, False)
    assert ctx.run_command([sys.executable, "-c", "print('x')"]) == "x"


def test_doctor_changes_nothing_on_disk(home: Path):
    make_profile(home)
    ff = make_firefox(home / "ff")
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in home.rglob("*") if p.is_file()}
    dirs = {p for p in home.rglob("*") if p.is_dir()} | {home}
    doctor.collect(make_context(home, firefox_candidates=lambda: [ff]))
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in home.rglob("*") if p.is_file()}
    assert after == before
    assert {p for p in home.rglob("*") if p.is_dir()} | {home} == dirs


def test_a_long_health_note_is_cut_in_the_health_line(home: Path):
    path = make_profile(home)
    note = "n" * 500
    health = {"nav-bar": f"fail: {note}"}
    put_status(path, json.dumps({"schema": 1, "updated": at(-1000), "health": health}))
    message = check_of(profile_report(home, path), "status.health").message
    assert message == f"1 health check failed: nav-bar: {'n' * 97}...."
    assert note not in message
