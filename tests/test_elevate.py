"""The administrator copy of the loader (Windows): the helper for real, the rest with fakes."""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from support import needs_symlinks

from peek_a_foxy import elevate, errors, loader
from peek_a_foxy.elevate import ElevationError

CONFIG = b'// the loader\npref("x", 1);\n'
PREFS = b'pref("general.config.filename", "config.js");\n'


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the hashes of the test payloads instead of the real fx-autoconfig files."""
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


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / "program" / "defaults" / "pref").mkdir(parents=True)
    (root / "program" / "config.js").write_bytes(CONFIG)
    (root / "program" / "defaults" / "pref" / "config-prefs.js").write_bytes(PREFS)
    return root


def firefox(tmp_path: Path, name: str = "Mozilla Firefox", product: str = "Firefox") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "omni.ja").touch()
    (folder / "firefox.exe").touch()
    (folder / "application.ini").write_text(f"[App]\nVendor=Mozilla\nName={product}\n")
    return folder


def run_helper(folder: Path, payloads: list[bytes]) -> int:
    """Run the real helper exactly as the elevated process would (isolated Python)."""
    command = elevate.helper_command(folder, payloads)
    return subprocess.run(command, capture_output=True, check=False).returncode


# --- the helper itself, in a real isolated Python ------------------------------------------------


def test_the_helper_writes_both_files_byte_for_byte(pinned, tmp_path):
    folder = firefox(tmp_path)
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.OK
    assert (folder / "config.js").read_bytes() == CONFIG
    assert (folder / "defaults" / "pref" / "config-prefs.js").read_bytes() == PREFS
    assert not list(folder.rglob("*.peek-a-foxy.tmp"))


def test_the_helper_replaces_an_older_copy(pinned, tmp_path):
    folder = firefox(tmp_path)
    (folder / "config.js").write_bytes(b"old")
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.OK
    assert (folder / "config.js").read_bytes() == CONFIG


def test_the_helper_refuses_bytes_that_are_not_the_pinned_files(pinned, tmp_path):
    folder = firefox(tmp_path)
    assert run_helper(folder, [CONFIG + b"// evil\n", PREFS]) == elevate.MISMATCH
    assert run_helper(folder, [PREFS, CONFIG]) == elevate.MISMATCH  # swapped
    assert not (folder / "config.js").exists()


@pytest.mark.parametrize(
    "broken", ["no-omni", "no-exe", "other-product", "no-ini", "missing-folder"]
)
def test_the_helper_only_writes_into_a_firefox_folder(pinned, tmp_path, broken):
    folder = firefox(tmp_path, product="Thunderbird" if broken == "other-product" else "Firefox")
    if broken == "no-omni":
        (folder / "omni.ja").unlink()
    if broken == "no-exe":
        (folder / "firefox.exe").unlink()
    if broken == "no-ini":
        (folder / "application.ini").unlink()
    if broken == "missing-folder":
        folder = tmp_path / "nowhere"
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.NOT_FIREFOX
    assert not (folder / "config.js").exists()


@pytest.mark.parametrize("arguments", [[], ["x"], ["x", "!!notbase64!!", "AAAA"], ["x", "AAAA"]])
def test_the_helper_rejects_bad_arguments(pinned, tmp_path, arguments):
    command = [sys.executable, "-I", "-S", "-c", elevate.helper_code(), *arguments]
    assert subprocess.run(command, capture_output=True).returncode == elevate.USAGE


@needs_symlinks
def test_the_helper_does_not_follow_a_link_that_replaces_a_target(pinned, tmp_path):
    folder = firefox(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (folder / "config.js").symlink_to(victim)
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.LINKED
    assert victim.read_text() == "precious"


@needs_symlinks
def test_the_helper_does_not_follow_a_linked_firefox_folder(pinned, tmp_path):
    real = firefox(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert run_helper(link, [CONFIG, PREFS]) == elevate.LINKED
    assert not (real / "config.js").exists()


def test_the_helper_reports_a_write_failure_by_exit_code(pinned, tmp_path):
    folder = firefox(tmp_path)
    (folder / "defaults").write_text("a file where a folder must go")
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.WRITE_FAILED


def test_the_helper_runs_without_the_package_or_the_current_directory(pinned, tmp_path):
    """-I -S: nothing from the working directory or site-packages can be loaded in its place."""
    folder = firefox(tmp_path)
    planted = tmp_path / "cwd"
    planted.mkdir()
    (planted / "hashlib.py").write_text("raise SystemExit(99)\n")  # would win without -I
    command = elevate.helper_command(folder, [CONFIG, PREFS])
    assert subprocess.run(command, cwd=planted, capture_output=True).returncode == elevate.OK


# --- the pins ------------------------------------------------------------------------------------


def test_the_command_line_carries_the_bytes_and_no_path_to_read(pinned, tmp_path):
    command = elevate.helper_command(tmp_path, [CONFIG, PREFS])
    assert command[1:4] == ["-I", "-S", "-c"]
    assert command[5] == str(tmp_path)
    assert [base64.b64decode(item) for item in command[6:]] == [CONFIG, PREFS]


def test_the_pinned_hashes_are_embedded_in_the_helper_not_passed_in(pinned):
    code = elevate.helper_code()
    for digest in elevate.PINNED_SHA256.values():
        assert digest in code
    assert "{pinned}" not in code


# --- the parent: what it asks for and how it reports ---------------------------------------------


def test_the_parent_hands_the_elevator_the_helper_command(pinned, checkout, tmp_path):
    seen: list[list[str]] = []
    folder = firefox(tmp_path)
    elevate.copy_as_administrator(checkout, folder, lambda command: seen.append(command) or 0)
    assert seen == [elevate.helper_command(folder, [CONFIG, PREFS])]


@pytest.mark.parametrize(
    ("code", "words"),
    [
        (elevate.NOT_FIREFOX, "not a Firefox"),
        (elevate.MISMATCH, "pinned"),
        (elevate.LINKED, "symbolic link"),
        (elevate.WRITE_FAILED, "even with administrator"),
        (elevate.USAGE, "bad arguments"),
        (77, "exit code 77"),
    ],
)
def test_every_exit_code_has_a_clear_message(pinned, checkout, tmp_path, code, words):
    with pytest.raises(ElevationError, match=words):
        elevate.copy_as_administrator(checkout, firefox(tmp_path), lambda command: code)


def test_the_elevated_copy_refuses_to_run_with_the_pin_overridden(
    pinned, checkout, tmp_path, monkeypatch
):
    monkeypatch.setenv("FXAC_COMMIT", "a" * 40)
    called: list[int] = []
    with pytest.raises(ElevationError, match="FXAC_REPO and FXAC_COMMIT"):
        elevate.copy_as_administrator(
            checkout, firefox(tmp_path), lambda command: called.append(1) or 0
        )
    assert called == []


def test_an_elevator_that_fails_to_start_is_passed_on(pinned, checkout, tmp_path):
    def cancelled(command: list[str]) -> int:
        raise ElevationError(errors.UAC_CANCELLED, "the administrator prompt was cancelled")

    with pytest.raises(ElevationError, match="cancelled"):
        elevate.copy_as_administrator(checkout, firefox(tmp_path), cancelled)


# --- the loader: direct copy first, then the prompt, never a loop --------------------------------


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader.platform, "is_windows", lambda: True)


def deny_direct_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(source: Path, destination: Path) -> None:
        raise PermissionError(13, "access denied")

    monkeypatch.setattr(loader, "_copy_direct", denied)


def test_a_writable_folder_needs_no_prompt(on_windows, pinned, checkout, tmp_path):
    folder = firefox(tmp_path)
    asked: list[int] = []
    loader.install_loader(checkout, folder, elevator=lambda c: asked.append(1) or 0)
    assert asked == []
    assert (folder / "config.js").read_bytes() == CONFIG


def test_a_protected_folder_asks_for_rights(on_windows, pinned, checkout, tmp_path, monkeypatch):
    deny_direct_copy(monkeypatch)
    folder = firefox(tmp_path)
    asked: list[list[str]] = []
    loader.install_loader(
        checkout, folder, elevator=lambda c: asked.append(c) or 0, is_admin=lambda: False
    )
    assert len(asked) == 1


def test_an_administrator_who_still_cannot_write_gets_an_error_and_no_second_prompt(
    on_windows, pinned, checkout, tmp_path, monkeypatch
):
    deny_direct_copy(monkeypatch)
    asked: list[int] = []
    with pytest.raises(loader.LoaderError, match="even as administrator"):
        loader.install_loader(
            checkout,
            firefox(tmp_path),
            elevator=lambda c: asked.append(1) or 0,
            is_admin=lambda: True,
        )
    assert asked == []


def test_a_cancelled_prompt_keeps_its_own_error_code(
    on_windows, pinned, checkout, tmp_path, monkeypatch
):
    deny_direct_copy(monkeypatch)

    def cancelled(command: list[str]) -> int:
        raise ElevationError(errors.UAC_CANCELLED, "the administrator prompt was cancelled")

    # It used to be turned into a LoaderError; now it keeps its own code (PAF-301).
    with pytest.raises(ElevationError, match="cancelled") as caught:
        loader.install_loader(
            checkout, firefox(tmp_path), elevator=cancelled, is_admin=lambda: False
        )
    assert caught.value.code is errors.UAC_CANCELLED


def test_the_step_description_names_the_right_mechanism(monkeypatch):
    monkeypatch.setattr(loader.platform, "is_windows", lambda: True)
    assert "administrator" in loader.privilege_hint() and "sudo" not in loader.privilege_hint()
    monkeypatch.setattr(loader.platform, "is_windows", lambda: False)
    assert loader.privilege_hint() == "uses sudo if needed"


@pytest.mark.skipif(sys.platform != "win32", reason="the real ShellExecuteEx round trip")
def test_the_real_windows_elevator_runs_a_process_and_returns_its_exit_code(tmp_path):
    """The CI runner is already an administrator, so 'runas' starts the process without a prompt."""
    if not elevate.is_admin():
        pytest.skip("would show a real UAC prompt")
    marker = tmp_path / "ran.txt"
    code = "import sys; open(sys.argv[1], 'w').write('yes'); sys.exit(7)"
    result = elevate.windows_elevator([sys.executable, "-I", "-S", "-c", code, str(marker)])
    assert result == 7 and marker.read_text() == "yes"


def test_the_pin_check_helpers_agree_with_the_real_pins():
    assert set(elevate.PINNED_SHA256) == {"config.js", "defaults/pref/config-prefs.js"}
    assert all(len(digest) == 64 for digest in elevate.PINNED_SHA256.values())
    assert os.name  # the module imports on every platform


# --- the helper's file handling, and what the command line looks like -------------------------


@needs_symlinks
def test_a_link_in_place_of_a_folder_on_the_way_stops_everything_before_anything_is_created(
    pinned, tmp_path
):
    folder = firefox(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (folder / "defaults").symlink_to(elsewhere, target_is_directory=True)
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.LINKED
    assert list(elsewhere.iterdir()) == []  # not even defaults/pref was created through the link


def test_a_leftover_temp_file_is_replaced_not_written_through(pinned, tmp_path):
    folder = firefox(tmp_path)
    (folder / "config.js.peek-a-foxy.tmp").write_bytes(b"stale")
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.OK
    assert (folder / "config.js").read_bytes() == CONFIG
    assert not list(folder.rglob("*.peek-a-foxy.tmp"))


@needs_symlinks
def test_a_planted_link_at_the_temp_name_is_not_followed(pinned, tmp_path):
    folder = firefox(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (folder / "config.js.peek-a-foxy.tmp").symlink_to(victim)
    assert run_helper(folder, [CONFIG, PREFS]) == elevate.OK
    assert victim.read_text() == "precious"


def test_the_helper_uses_the_base_interpreter_not_a_virtual_environments(
    pinned, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sys, "_base_executable", str(tmp_path / "base" / "python.exe"), raising=False
    )
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv" / "Scripts" / "python.exe"))
    assert elevate.helper_command(tmp_path, [CONFIG, PREFS])[0].endswith(
        "base" + os.sep + "python.exe"
    )


def test_without_a_base_interpreter_the_current_one_is_used(pinned, tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "_base_executable", raising=False)
    assert elevate.helper_command(tmp_path, [CONFIG, PREFS])[0] == sys.executable


def test_the_command_line_stays_far_below_the_windows_limit_even_for_larger_files(pinned, tmp_path):
    big = [b"x" * 3000, b"y" * 3000]  # the real files are about 430 and 190 bytes
    line = subprocess.list2cmdline(elevate.helper_command(tmp_path, big))
    assert len(line) < 16000  # CreateProcess allows 32767 characters


@pytest.mark.skipif(sys.platform != "win32", reason="the real command line through ShellExecuteEx")
def test_the_real_helper_command_goes_through_the_real_elevator(pinned, tmp_path):
    """Quotes, newlines and the payloads of the real command line survive ShellExecuteEx."""
    if not elevate.is_admin():
        pytest.skip("would show a real UAC prompt")
    folder = firefox(tmp_path)
    code = elevate.windows_elevator(elevate.helper_command(folder, [CONFIG, PREFS]))
    assert code == elevate.OK
    assert (folder / "config.js").read_bytes() == CONFIG
    assert (folder / "defaults" / "pref" / "config-prefs.js").read_bytes() == PREFS
