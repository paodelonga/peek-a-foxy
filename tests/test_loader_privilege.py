"""The copy of the loader into a folder that needs ``sudo``, and what runs before it (PF-04, 11-13).

The ``sudo`` used here is a real executable on ``PATH`` (see ``support.fake_sudo``): the code under
test starts it exactly as it would start the real one, so the exit code, the arguments and the bytes
on its standard input are what is checked, and not what a mock was told to say.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support import fake_sudo, needs_permissions, needs_posix_shell
from typer.testing import CliRunner

from peek_a_foxy import elevate, errors, loader
from peek_a_foxy.cli import app
from peek_a_foxy.errors import LoaderError

runner = CliRunner()

CONFIG = b"// the loader\n"
PREFS = b'pref("general.config.filename", "config.js");\n'


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / "program" / "defaults" / "pref").mkdir(parents=True)
    (root / "program" / "config.js").write_bytes(CONFIG)
    (root / "program" / "defaults" / "pref" / "config-prefs.js").write_bytes(PREFS)
    return root


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pins are those of the fixture files, and no override is set."""
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    monkeypatch.setitem(elevate.PINNED_SHA256, "config.js", hashlib.sha256(CONFIG).hexdigest())
    monkeypatch.setitem(
        elevate.PINNED_SHA256, "defaults/pref/config-prefs.js", hashlib.sha256(PREFS).hexdigest()
    )


@pytest.fixture
def protected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every direct copy is refused, as in a folder that belongs to root."""

    def denied(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(loader, "_copy_direct", denied)


@pytest.fixture
def sudo_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ``sudo`` that succeeds, first on ``PATH``; the folder says what it was asked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "sudo-calls"
    fake_sudo(bin_dir, record)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return record


def calls_of(record: Path) -> list[tuple[list[str], bytes]]:
    return [
        (
            (record / f"{n}.args").read_text().splitlines(),
            (record / f"{n}.stdin").read_bytes(),
        )
        for n in range(len(list(record.glob("*.args"))))
    ]


# --- PF-04: what root copies is what was checked --------------------------------------------------


@needs_posix_shell
def test_the_bytes_that_were_verified_are_the_bytes_that_sudo_receives(
    checkout: Path, tmp_path: Path, pinned, protected, sudo_calls: Path, monkeypatch
):
    monkeypatch.setattr(loader.platform, "is_windows", lambda: False)
    monkeypatch.setattr(loader.platform, "system", lambda: "linux")  # GNU install, on any system
    firefox = tmp_path / "usr" / "lib" / "firefox"
    loader.install_loader(checkout, firefox)
    done = calls_of(sudo_calls)
    assert [args[:2] for args, _ in done] == [["mkdir", "-p"], ["install", "-m"]] * 2
    installs = [(args, data) for args, data in done if args[0] == "install"]
    assert installs == [
        (["install", "-m", "644", "/dev/stdin", str(firefox / "config.js")], CONFIG),
        (
            ["install", "-m", "644", "/dev/stdin", str(firefox / "defaults/pref/config-prefs.js")],
            PREFS,
        ),
    ]  # the source path of the checkout is not on any command line: nothing is read a second time


@needs_posix_shell
def test_on_macos_the_verified_bytes_go_through_tee_and_then_chmod(
    checkout: Path, tmp_path: Path, pinned, protected, sudo_calls: Path, monkeypatch
):
    """BSD install may refuse /dev/stdin, so macOS pipes the same checked bytes into tee."""
    monkeypatch.setattr(loader.platform, "is_windows", lambda: False)
    monkeypatch.setattr(loader.platform, "system", lambda: "macos")
    firefox = tmp_path / "usr" / "lib" / "firefox"
    loader.install_loader(checkout, firefox)
    config, prefs = firefox / "config.js", firefox / "defaults" / "pref" / "config-prefs.js"
    assert calls_of(sudo_calls) == [
        (["mkdir", "-p", str(config.parent)], b""),
        (["tee", str(config)], CONFIG),
        (["chmod", "644", str(config)], b""),
        (["mkdir", "-p", str(prefs.parent)], b""),
        (["tee", str(prefs)], PREFS),
        (["chmod", "644", str(prefs)], b""),
    ]


@needs_posix_shell
def test_a_file_swapped_in_the_checkout_is_refused_before_sudo_runs(
    checkout: Path, tmp_path: Path, pinned, protected, sudo_calls: Path, monkeypatch
):
    """Same-user malware rewrites config.js after the checkout was verified (PF-04)."""
    monkeypatch.setattr(loader.platform, "is_windows", lambda: False)
    (checkout / "program" / "config.js").write_bytes(b"// attacker code\n")
    with pytest.raises(LoaderError) as caught:
        loader.install_loader(checkout, tmp_path / "firefox")
    assert caught.value.code is errors.CHECKOUT_MISMATCH
    assert not list(sudo_calls.glob("*"))  # sudo never started


@needs_posix_shell
@pytest.mark.parametrize("variable", ["FXAC_REPO", "FXAC_COMMIT"])
def test_an_overridden_loader_is_not_copied_by_sudo_without_saying_so(
    checkout: Path, tmp_path: Path, protected, sudo_calls: Path, monkeypatch, variable: str
):
    monkeypatch.setenv(variable, "anything")
    monkeypatch.setattr(loader.platform, "is_windows", lambda: False)
    with pytest.raises(LoaderError) as caught:
        loader.install_loader(checkout, tmp_path / "firefox")
    assert caught.value.code is errors.LOADER_UNVERIFIED
    assert not list(sudo_calls.glob("*"))


@needs_posix_shell
def test_with_the_explicit_flag_an_overridden_loader_is_copied_and_logged_as_unverified(
    checkout: Path, tmp_path: Path, protected, sudo_calls: Path, monkeypatch, caplog
):
    monkeypatch.setenv("FXAC_REPO", "anything")
    monkeypatch.setattr(loader.platform, "is_windows", lambda: False)
    monkeypatch.setattr(loader.platform, "system", lambda: "linux")  # GNU install, on any system
    # The parent logger stops propagating once a run has started logging (logs.start), so the
    # capture handler goes straight onto the logger of the module.
    loader.log.addHandler(caplog.handler)
    try:
        loader.install_loader(checkout, tmp_path / "firefox", allow_unverified=True)
    finally:
        loader.log.removeHandler(caplog.handler)
    assert [data for args, data in calls_of(sudo_calls) if args[0] == "install"] == [CONFIG, PREFS]
    assert "WITHOUT checking" in caplog.text


def test_the_error_says_what_to_do_about_an_overridden_loader():
    assert "--allow-unverified-loader" in errors.LOADER_UNVERIFIED.hint
    assert "FXAC_REPO" in errors.LOADER_UNVERIFIED.hint


@needs_permissions
@needs_posix_shell
def test_the_whole_command_refuses_an_overridden_loader_for_a_protected_folder(
    profile: Path, firefox_dir: Path, fxac_repo, tmp_path: Path, monkeypatch
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sudo(bin_dir, tmp_path / "calls")
    git_path = shutil.which("git")
    assert git_path is not None
    (bin_dir / "git").symlink_to(git_path)
    monkeypatch.setenv("PATH", str(bin_dir))
    firefox_dir.chmod(0o555)
    try:
        result = runner.invoke(
            app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
        )
    finally:
        firefox_dir.chmod(0o755)
    assert result.exit_code == 1 and errors.LOADER_UNVERIFIED.code in result.output
    assert "--allow-unverified-loader" in result.output
    assert not list((tmp_path / "calls").glob("*"))


# --- PF-12: a loader that is already there is not copied, so nobody is asked ----------------------


@needs_permissions
@needs_posix_shell
def test_a_second_install_into_a_protected_folder_never_starts_sudo(
    profile: Path, firefox_dir: Path, fxac_repo, tmp_path: Path, monkeypatch
):
    first = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert first.exit_code == 0, first.output  # the folder was writable: a direct copy
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sudo(bin_dir, tmp_path / "calls", exit_code=1)  # would fail the command if it were run
    git_path = shutil.which("git")
    assert git_path is not None
    (bin_dir / "git").symlink_to(git_path)
    monkeypatch.setenv("PATH", str(bin_dir))
    firefox_dir.chmod(0o555)
    (firefox_dir / "defaults").chmod(0o555)
    (firefox_dir / "defaults" / "pref").chmod(0o555)
    try:
        second = runner.invoke(
            app,
            ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"],
        )
    finally:
        for folder in (firefox_dir, firefox_dir / "defaults", firefox_dir / "defaults" / "pref"):
            folder.chmod(0o755)
    assert second.exit_code == 0, second.output
    assert not list((tmp_path / "calls").glob("*"))  # sudo was not started at all


def test_a_copy_with_windows_line_endings_counts_as_the_same_loader(checkout: Path, tmp_path: Path):
    firefox = tmp_path / "firefox"
    (firefox / "defaults" / "pref").mkdir(parents=True)
    (firefox / "config.js").write_bytes(CONFIG.replace(b"\n", b"\r\n"))
    (firefox / "defaults" / "pref" / "config-prefs.js").write_bytes(PREFS)
    assert loader.conflicts(checkout, firefox) == []  # not a "conflict" that blocks the install
    assert loader.same_content(checkout / "program" / "config.js", firefox / "config.js")


@pytest.mark.parametrize("hostile", ["fifo", "folder", "huge", "missing"])
def test_what_cannot_be_compared_is_not_the_same(checkout: Path, tmp_path: Path, hostile: str):
    destination = tmp_path / "config.js"
    if hostile == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("no named pipes here")
        os.mkfifo(destination)  # reading it would wait for ever
    elif hostile == "folder":
        destination.mkdir()
    elif hostile == "huge":
        destination.write_bytes(CONFIG + b"x" * (loader.MAX_LOADER_FILE + 1))
    assert not loader.same_content(checkout / "program" / "config.js", destination)


# --- PF-27.10: a copy appears whole or not at all -------------------------------------------------


def test_a_copy_that_fails_half_way_leaves_the_old_file_and_no_temporary(
    checkout: Path, tmp_path: Path, monkeypatch
):
    destination = tmp_path / "firefox" / "config.js"
    destination.parent.mkdir()
    destination.write_bytes(b"old, whole file")

    def die(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(loader.shutil, "copyfileobj", die)
    with pytest.raises(OSError, match="No space"):
        loader._copy_direct(checkout / "program" / "config.js", destination)
    assert destination.read_bytes() == b"old, whole file"
    assert [p.name for p in destination.parent.iterdir()] == ["config.js"]


@pytest.mark.skipif(os.name == "nt", reason="file modes are advisory on Windows")
@pytest.mark.parametrize("umask", [0o022, 0o077, 0o277, 0o777])
@pytest.mark.parametrize("old_mode", [None, 0o600, 0o444])
def test_the_copied_loader_is_readable_by_everyone_whatever_the_umask(
    checkout: Path, tmp_path: Path, umask: int, old_mode: int | None
):
    """Firefox may be run by another user than the one who installed: ``config.js`` must be 0644.

    The temporary file is created under the umask of whoever runs us (0600 under 077, no rights
    at all under 777), so the mode is set on purpose and not left to chance.
    """
    destination = tmp_path / "firefox" / "config.js"
    destination.parent.mkdir()
    if old_mode is not None:
        destination.write_bytes(b"old")
        destination.chmod(old_mode)
    previous = os.umask(umask)
    try:
        loader._copy_direct(checkout / "program" / "config.js", destination)
    finally:
        os.umask(previous)
    assert destination.read_bytes() == CONFIG
    assert (destination.stat().st_mode & 0o777) == 0o644
    assert [p.name for p in destination.parent.iterdir()] == ["config.js"]


# --- PF-22: git never waits for ever and never asks -----------------------------------------------


def test_git_gets_a_time_limit_and_no_prompt(monkeypatch):
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(loader.subprocess, "run", fake_run)
    loader._git("status")
    assert seen["timeout"] == loader.GIT_TIMEOUT_SECONDS > 0
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["GIT_ASKPASS"] == ""


@needs_posix_shell
def test_a_git_that_stalls_is_stopped_with_a_coded_error(tmp_path: Path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stalled = bin_dir / "git"
    stalled.write_text("#!/bin/sh\nexec sleep 60\n")
    stalled.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(loader, "GIT_TIMEOUT_SECONDS", 1)
    # No clock: a git that was waited for would end its minute with exit 0 and no error at all.
    with pytest.raises(LoaderError, match="timed out") as caught:
        loader._git("fetch")
    assert caught.value.code is errors.GIT_FAILED


def test_an_offline_user_sees_one_failure_and_no_second_attempt(tmp_path: Path, monkeypatch):
    """Nothing listens on the port: the fetch fails, and a clone would fail in the same way."""
    monkeypatch.setenv("FXAC_REPO", "https://127.0.0.1:9/nothing.git")
    monkeypatch.setenv("FXAC_COMMIT", "a" * 40)
    calls: list[str] = []
    real = loader._git

    def counting(*args: str, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(loader, "_git", counting)
    with pytest.raises(LoaderError) as caught, loader.fetch_loader():
        pass
    assert calls == ["init", "fetch"]  # no "clone"
    assert caught.value.code is errors.GIT_FAILED


def test_a_server_that_only_refuses_the_hash_still_gets_the_clone(tmp_path: Path, monkeypatch):
    seen: list[str] = []

    def fake(*args: str, **kwargs):
        seen.append(args[0])
        if args[0] == "fetch":
            raise LoaderError(errors.GIT_FAILED, "git fetch failed: error: Server does not allow")
        return ""

    monkeypatch.setattr(loader, "_git", fake)
    monkeypatch.setenv("FXAC_COMMIT", "b" * 40)
    monkeypatch.setattr(loader, "remove_tree", lambda path: None)
    loader._fetch_commit("repo", "b" * 40, tmp_path / "checkout")
    assert seen == ["init", "fetch", "clone", "checkout"]


@pytest.mark.parametrize(
    "message",
    [
        "fatal: unable to access 'https://x/': Could not resolve host: x",
        "fatal: unable to access 'https://x/': Failed to connect to x port 443",
        "fatal: could not read Username for 'https://x': terminal prompts disabled",
        "git fetch timed out after 120 seconds",
        "fatal: Authentication failed for 'https://x/'",
    ],
)
def test_failures_of_the_connection_or_the_login_are_not_retried_as_a_clone(message: str):
    assert loader._server_unreachable(LoaderError(errors.GIT_FAILED, message))


# --- PF-13: a folder named by hand must be a Firefox ----------------------------------------------


def test_an_empty_folder_is_refused_as_a_firefox_folder(profile: Path, tmp_path: Path):
    empty = tmp_path / "not-firefox"
    empty.mkdir()
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(empty), "--dry-run"]
    )
    assert result.exit_code == 1 and errors.NOT_A_FIREFOX_FOLDER.code in result.output
    assert "Traceback" not in result.output and not (empty / "config.js").exists()


@pytest.mark.skipif(not Path("/usr/lib").is_dir(), reason="no /usr/lib here")
def test_a_system_library_folder_is_never_a_place_for_the_loader(profile: Path):
    """``--firefox-dir /usr/lib`` once planned to write /usr/lib/config.js as root."""
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", "/usr/lib", "--dry-run"]
    )
    assert result.exit_code == 1 and errors.NOT_A_FIREFOX_FOLDER.code in result.output


def test_a_folder_with_omni_ja_is_still_accepted(profile: Path, firefox_dir: Path, fxac_repo):
    result = runner.invoke(
        app,
        ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output


def test_a_snap_folder_is_still_reported_as_a_snap_not_as_a_missing_firefox(
    profile: Path, tmp_path: Path
):
    snap = tmp_path / "snap" / "firefox" / "current"
    snap.mkdir(parents=True)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(snap), "--dry-run"]
    )
    assert errors.FIREFOX_SANDBOXED.code in result.output
