"""The elevated script run by PowerShell Core on Linux or macOS (opt in: it needs ``pwsh``).

``pwsh`` is not Windows PowerShell 5.1: it is another runtime (.NET instead of .NET Framework) and
the file system is POSIX. What this checks is the logic of the script (every exit code that a
POSIX folder can reach, hostile folder names, symbolic links, a read-only folder) with real
PowerShell semantics, which the text-level tests of ``test_elevate.py`` cannot. Windows APIs
(short names, junctions, ``File.Replace`` onto a read-only file) are exercised by the Windows-only
tests of that file, never here. The script is run as it is generated, except that a few literals
are adapted to POSIX separators (see ``adapt``), and every adaptation must still match the script.

``PEEK_A_FOXY_PWSH`` points at a ``pwsh`` that is not on PATH. Windows runs the real thing instead.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support import WINDOWS, needs_permissions, needs_symlinks

from peek_a_foxy import elevate

PWSH = os.environ.get("PEEK_A_FOXY_PWSH") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(
    WINDOWS or not PWSH or not Path(PWSH).is_file(),
    reason="needs pwsh (PEEK_A_FOXY_PWSH) on Linux or macOS",
)

CONFIG = b'// the loader\npref("x", 1);\n'
PREFS = b'pref("general.config.filename", "config.js");\n'


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        elevate,
        "PINNED_SHA256",
        {
            "config.js": hashlib.sha256(CONFIG).hexdigest(),
            "defaults/pref/config-prefs.js": hashlib.sha256(PREFS).hexdigest(),
        },
    )
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)


ADAPTATIONS = [
    (r"'^(?:[A-Za-z]:\\|\\\\[^\\?.])'", "'^/'"),  # a folder starts at a drive on Windows
    (r"'defaults\pref\config-prefs.js'", "'defaults/pref/config-prefs.js'"),
    (r"'defaults\pref'", "'defaults/pref'"),
    ("[char]92", "[char]47"),  # the separator the script trims
]


def adapt(script: str) -> str:
    for windows, posix in ADAPTATIONS:
        assert windows in script, f"the script no longer has {windows}: update the adaptation"
        script = script.replace(windows, posix)
    return script


def run(script: str) -> int:
    command = [
        str(PWSH),
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        elevate.encoded_command(script),
    ]
    environment = dict(os.environ, POWERSHELL_TELEMETRY_OPTOUT="1")
    done = subprocess.run(command, capture_output=True, timeout=120, env=environment, check=False)
    assert done.stdout == b"" and done.stderr == b"", (done.stdout, done.stderr)  # silent
    return done.returncode


def go(folder: Path | str, payloads: list[bytes] | None = None, *, adapted: bool = True) -> int:
    script = elevate.helper_script(str(folder), payloads or [CONFIG, PREFS])
    return run(adapt(script) if adapted else script)


def firefox(parent: Path, name: str = "Mozilla Firefox", product: str = "Firefox") -> Path:
    folder = parent / name
    folder.mkdir()
    (folder / "omni.ja").touch()
    (folder / "firefox.exe").touch()
    (folder / "application.ini").write_text(f"[App]\nVendor=Mozilla\nName={product}\n")
    return folder


def written(folder: Path) -> bool:
    return (folder / "config.js").exists() or (folder / "defaults").exists()


def assert_installed(folder: Path) -> None:
    assert (folder / "config.js").read_bytes() == CONFIG
    assert (folder / "defaults" / "pref" / "config-prefs.js").read_bytes() == PREFS
    assert not list(folder.rglob("*.peek-a-foxy.tmp"))


# --- 0: it works ----------------------------------------------------------------------------------


def test_both_files_are_written_byte_for_byte_and_again_over_the_old_ones(tmp_path):
    folder = firefox(tmp_path)
    assert go(folder) == elevate.OK
    assert_installed(folder)
    (folder / "config.js").write_bytes(b"older")
    assert go(folder) == elevate.OK
    assert_installed(folder)


@pytest.mark.parametrize(
    "name",
    [
        "it's here",
        "a\u2018b",  # the other four characters that PowerShell reads as a single quote
        "a\u2019b\u201ab\u201bc",
        "$(exit 7)",
        "`n",
        "$env:HOME",
        "@@CONFIG@@",
        "'; exit 0; '",
        "a b  c",
        "\u202eevil",  # a right-to-left override
        "x%PATH%x",
        "[ab]",
        "a{b}",
        "caf\u00e9",
        "-x",
        "..hidden",
        "a*b",
        "a?b",
        "a;b",
        "a&b",
        "a|b",
    ],
)
def test_a_hostile_folder_name_is_only_a_name(tmp_path, name):
    folder = firefox(tmp_path, name)
    assert go(folder) == elevate.OK
    assert_installed(folder)


def test_a_trailing_separator_is_the_same_folder(tmp_path):
    folder = firefox(tmp_path)
    assert go(f"{folder}/") == elevate.OK
    assert_installed(folder)


# --- 10: the arguments ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "folder", ["", "relative/path", "a\nb", "/tmp/a\tb", "/tmp/a\x7fb", "/tmp/a\x1bb"]
)
def test_a_folder_that_is_not_an_absolute_path_without_control_characters_is_usage(folder):
    assert go(folder) == elevate.USAGE


@pytest.mark.parametrize("folder", ["\\\\?\\C:\\x", "\\\\.\\C:", "\\\\", "C:", "C:x", "/tmp/x"])
def test_the_unadapted_script_takes_only_a_drive_or_a_unc_path(folder):
    assert go(folder, adapted=False) == elevate.USAGE


def test_a_payload_that_is_not_base64_is_usage(tmp_path):
    script = elevate.helper_script(str(firefox(tmp_path)), [CONFIG, PREFS])
    assert run(adapt(script.replace("Ly8g", "!!!!", 1))) == elevate.USAGE


# --- 11: not a Firefox ----------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["omni.ja", "firefox.exe", "application.ini"])
def test_a_missing_marker_file_is_not_firefox(tmp_path, missing):
    folder = firefox(tmp_path)
    (folder / missing).unlink()
    assert go(folder) == elevate.NOT_FIREFOX
    assert not written(folder)


@pytest.mark.parametrize(
    "ini",
    [
        b"[App]\nName=Thunderbird\n",
        b"[App]\nname=firefox\n",  # the comparison is case sensitive
        b"[App]\nName=Firefox Nightly\n",
        b"",
        b"\xff\xfe\x00\x00 garbage",
    ],
)
def test_an_application_ini_that_does_not_say_firefox_is_not_firefox(tmp_path, ini):
    folder = firefox(tmp_path)
    (folder / "application.ini").write_bytes(ini)
    assert go(folder) == elevate.NOT_FIREFOX
    assert not written(folder)


def test_a_byte_order_mark_and_windows_line_endings_are_fine(tmp_path):
    folder = firefox(tmp_path)
    (folder / "application.ini").write_bytes(b"\xef\xbb\xbf[App]\r\nName=Firefox\r\n")
    assert go(folder) == elevate.OK


def test_an_application_ini_that_is_a_folder_and_a_folder_that_is_missing_are_not_firefox(tmp_path):
    folder = firefox(tmp_path)
    (folder / "application.ini").unlink()
    (folder / "application.ini").mkdir()
    assert go(folder) == elevate.NOT_FIREFOX
    assert go(tmp_path / "nowhere") == elevate.NOT_FIREFOX


# --- 12: the pinned hashes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payloads", [[CONFIG + b"x", PREFS], [CONFIG, PREFS + b"x"], [PREFS, CONFIG], [b"", b""]]
)
def test_files_that_are_not_the_pinned_ones_are_refused_and_nothing_is_written(tmp_path, payloads):
    folder = firefox(tmp_path)
    assert go(folder, payloads) == elevate.MISMATCH
    assert not written(folder)


def test_the_hash_is_checked_before_the_folder_is_looked_at(tmp_path):
    assert go(tmp_path / "nowhere", [CONFIG + b"x", PREFS]) == elevate.MISMATCH


# --- 13: links and names that are not the folder's own --------------------------------------------


@needs_symlinks
def test_a_link_as_the_folder_or_anywhere_above_it_is_refused(tmp_path):
    real = firefox(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert go(link) == elevate.LINKED
    assert not written(real)
    parent = tmp_path / "parent"
    parent.mkdir()
    (tmp_path / "above").symlink_to(parent)
    inside = firefox(parent)
    assert go(tmp_path / "above" / inside.name) == elevate.LINKED
    assert not written(inside)


@needs_symlinks
@pytest.mark.parametrize("place", ["defaults", "defaults/pref"])
def test_a_link_in_place_of_a_folder_it_writes_into_stops_everything(tmp_path, place):
    folder = firefox(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if place == "defaults/pref":
        (folder / "defaults").mkdir()
    (folder / place).symlink_to(elsewhere)
    assert go(folder) == elevate.LINKED
    assert list(elsewhere.iterdir()) == []
    assert not (folder / "config.js").exists()


@needs_symlinks
def test_a_link_in_place_of_a_target_file_is_not_followed_even_when_it_dangles(tmp_path):
    folder = firefox(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("precious")
    (folder / "config.js").symlink_to(victim)
    assert go(folder) == elevate.LINKED
    assert victim.read_text() == "precious"
    (folder / "config.js").unlink()
    (folder / "config.js").symlink_to(tmp_path / "does-not-exist")
    assert go(folder) == elevate.LINKED


@needs_symlinks
def test_a_link_planted_at_the_temporary_name_is_removed_not_followed(tmp_path):
    folder = firefox(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("precious")
    (folder / "config.js.peek-a-foxy.tmp").symlink_to(victim)
    assert go(folder) == elevate.OK
    assert victim.read_text() == "precious"
    assert_installed(folder)


def test_a_path_the_system_would_rewrite_is_not_the_folder_that_was_given(tmp_path):
    folder = firefox(tmp_path)
    assert go(f"{folder}/../{folder.name}") == elevate.LINKED
    assert go(f"{folder.parent}//{folder.name}") == elevate.LINKED
    assert not written(folder)


def test_a_name_that_the_listing_of_its_folder_does_not_give_back_is_refused(tmp_path):
    """What a short 8.3 name does on Windows, simulated: the listing names the part differently.

    The real thing needs Windows (test_elevate.py); here the script's branch is driven by making
    the comparison of the listed name fail, so the exit code and the empty folder are checked in
    real PowerShell.
    """
    folder = firefox(tmp_path)
    script = adapt(elevate.helper_script(str(folder), [CONFIG, PREFS]))
    compare = "[string]::Equals([IO.Path]::GetFileName($entry), $leaf, $same)"
    assert compare in script
    assert run(script) == elevate.OK
    other = "[string]::Equals([IO.Path]::GetFileName($entry) + 'x', $leaf, $same)"
    (folder / "config.js").unlink()
    shutil.rmtree(folder / "defaults")
    assert run(script.replace(compare, other)) == elevate.LINKED
    assert not written(folder)


# --- 14: writing ----------------------------------------------------------------------------------


def test_a_file_where_a_folder_must_go_and_a_folder_where_a_file_goes_fail_to_write(tmp_path):
    folder = firefox(tmp_path)
    (folder / "defaults").write_text("a file where a folder must go")
    assert go(folder) == elevate.WRITE_FAILED
    other = firefox(tmp_path, "other")
    (other / "config.js").mkdir()
    assert go(other) == elevate.WRITE_FAILED
    assert not list(other.rglob("*.peek-a-foxy.tmp"))


def test_a_folder_at_the_temporary_name_is_a_write_failure(tmp_path):
    folder = firefox(tmp_path)
    (folder / "config.js.peek-a-foxy.tmp").mkdir()
    assert go(folder) == elevate.WRITE_FAILED


@needs_permissions
def test_a_read_only_folder_fails_and_leaves_nothing_behind(tmp_path):
    folder = firefox(tmp_path)
    folder.chmod(0o555)
    try:
        assert go(folder) == elevate.WRITE_FAILED
    finally:
        folder.chmod(0o755)
    assert not list(folder.rglob("*.peek-a-foxy.tmp"))
    assert not (folder / "config.js").exists()


@needs_permissions
def test_a_failure_on_the_second_file_leaves_the_first_in_place_and_no_temporary(tmp_path):
    """config.js goes first and the file that switches it on last, so a half-way stop is inert."""
    folder = firefox(tmp_path)
    pref = folder / "defaults" / "pref"
    pref.mkdir(parents=True)
    pref.chmod(0o555)
    try:
        assert go(folder) == elevate.WRITE_FAILED
    finally:
        pref.chmod(0o755)
    assert (folder / "config.js").read_bytes() == CONFIG
    assert not (pref / "config-prefs.js").exists()
    assert not list(folder.rglob("*.peek-a-foxy.tmp"))
