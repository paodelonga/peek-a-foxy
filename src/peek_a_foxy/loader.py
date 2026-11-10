"""The fx-autoconfig loader, which lets Firefox run the ``*.uc.js`` script.

It is fetched at a pinned commit and the checkout is verified, so a moved branch or tag cannot
change what gets installed. ``FXAC_REPO`` / ``FXAC_COMMIT`` can override the source (used by the
tests).
"""

from __future__ import annotations

import filecmp
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from peek_a_foxy import elevate, errors, platform
from peek_a_foxy.errors import LoaderError

log = logging.getLogger(__name__)

DEFAULT_REPO = "https://github.com/MrOtherGuy/fx-autoconfig.git"
DEFAULT_COMMIT = "dfdab5684faffc112b76ccb1d8cab7f75da0102c"

# Relative to the Firefox install directory (and to ``program/`` in the fx-autoconfig checkout).
LOADER_FILES = ("config.js", "defaults/pref/config-prefs.js")


def repo_url() -> str:
    return os.environ.get("FXAC_REPO", DEFAULT_REPO)


def pinned_commit() -> str:
    """The commit to install, as a lowercase 40-digit hash; anything else is refused.

    A branch, tag or abbreviated hash could move or become ambiguous, and a value starting with
    ``-`` must never reach git as an option.
    """
    commit = os.environ.get("FXAC_COMMIT", DEFAULT_COMMIT)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise LoaderError(
            errors.BAD_PINNED_COMMIT,
            f"FXAC_COMMIT must be a full 40-digit commit hash, not {commit!r}",
        )
    return commit.lower()


# Git for Windows converts line endings by default (core.autocrlf=true), which would hand Firefox a
# config.js with CRLF, and long paths in a checkout can fail without core.longpaths. Both are set on
# every call, whatever the user's git configuration says.
GIT_SETTINGS = ("-c", "core.autocrlf=false", "-c", "core.longpaths=true")


def _git(*args: str, cwd: Path | None = None) -> str:
    log.debug("running: git %s", " ".join(args))
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["git", *GIT_SETTINGS, *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",  # not the console's code page: git writes UTF-8
            errors="replace",
        )
    except subprocess.CalledProcessError as error:
        log.error(
            "git %s exited with %d after %.2f s",
            args[0],
            error.returncode,
            time.monotonic() - started,
        )
        raise LoaderError(
            errors.GIT_FAILED,
            f"git {' '.join(args)} failed: {error.stderr.strip()}",
            detail=f"git {' '.join(args)} exited with code {error.returncode}",
        ) from error
    log.debug("git %s exited with 0 in %.2f s", args[0], time.monotonic() - started)
    return result.stdout.strip()


def remove_tree(path: Path) -> None:
    """Delete a directory tree, read-only files included (Windows refuses to delete them)."""
    # Top down: a folder is opened up before it is read.
    for root, directories, files in os.walk(path):
        for name in (*directories, *files):
            entry = os.path.join(root, name)
            if not os.path.islink(entry):  # a link's target is not ours to change
                os.chmod(entry, stat.S_IRWXU)
    shutil.rmtree(path)


def _fetch_commit(repo: str, commit: str, checkout: Path) -> None:
    """Fetch just ``commit`` (no history); fall back to a full clone if the server refuses that."""
    checkout.mkdir()
    try:
        _git("init", "--quiet", cwd=checkout)
        _git("fetch", "--quiet", "--depth", "1", "--", repo, commit, cwd=checkout)
    except LoaderError:
        log.info("the shallow fetch failed; cloning the whole repository instead")
        remove_tree(checkout)
        _git("clone", "--quiet", "--", repo, str(checkout))
    _git("checkout", "--quiet", "--detach", commit, cwd=checkout)


def _git_missing() -> LoaderError:
    try:
        windows = platform.system() == "windows"
    except platform.UnsupportedPlatformError:
        windows = False
    hint = errors.GIT_MISSING.hint
    if windows:
        hint = (
            "Install Git for Windows (https://git-scm.com/download/win, or run "
            "`winget install Git.Git` in a terminal) and run the command again. "
            "If fx-autoconfig is already set up in your Firefox, use --skip-loader."
        )
    return LoaderError(errors.GIT_MISSING, "git is required to fetch fx-autoconfig", hint=hint)


@contextmanager
def fetch_loader() -> Iterator[Path]:
    """Fetch fx-autoconfig into a temporary directory and yield the verified checkout."""
    if shutil.which("git") is None:
        raise _git_missing()
    commit = pinned_commit()
    with tempfile.TemporaryDirectory(prefix="peek-a-foxy-", ignore_cleanup_errors=True) as tmp:
        checkout = Path(tmp) / "fx-autoconfig"
        _fetch_commit(repo_url(), commit, checkout)
        if _git("rev-parse", "HEAD", cwd=checkout) != commit:
            raise LoaderError(
                errors.CHECKOUT_MISMATCH, "fx-autoconfig checkout does not match the pinned commit"
            )
        yield checkout


def conflicts(checkout: Path, firefox_dir: Path) -> list[Path]:
    """Loader files already in the Firefox directory that differ from the ones we would install."""
    return [
        firefox_dir / name
        for name in LOADER_FILES
        if (firefox_dir / name).is_file()
        and not filecmp.cmp(checkout / "program" / name, firefox_dir / name, shallow=False)
    ]


def install_utils(checkout: Path, chrome_dir: Path) -> None:
    """``chrome/utils`` belongs to the profile and is safe to refresh."""
    shutil.copytree(
        checkout / "profile" / "chrome" / "utils", chrome_dir / "utils", dirs_exist_ok=True
    )


def _sudo(*command: str) -> None:
    log.info("running: sudo %s", " ".join(command))
    try:
        subprocess.run(["sudo", *command], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        log.error("sudo failed: %r", error)
        raise LoaderError(
            errors.SUDO_FAILED,
            f"could not run 'sudo {' '.join(command)}'",
            detail=repr(error),
        ) from error


def _copy_direct(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o644)


def _copy(source: Path, destination: Path) -> None:
    """Copy a file, falling back to sudo when the directory is not writable."""
    try:
        _copy_direct(source, destination)
    except PermissionError:
        _sudo("mkdir", "-p", str(destination.parent))
        _sudo("install", "-m", "644", str(source), str(destination))


def privilege_hint() -> str:
    if platform.is_windows():
        return "asks for administrator permission if needed"
    return "uses sudo if needed"


def install_loader(
    checkout: Path,
    firefox_dir: Path,
    *,
    elevator: elevate.Elevator | None = None,
    is_admin: Callable[[], bool] | None = None,
) -> None:
    """Copy the loader files; where the folder is protected, ask for rights (sudo or UAC)."""
    if not platform.is_windows():
        for name in LOADER_FILES:
            _copy(checkout / "program" / name, firefox_dir / name)
        return
    try:
        for name in LOADER_FILES:
            _copy_direct(checkout / "program" / name, firefox_dir / name)
    except PermissionError as error:
        if (is_admin or elevate.is_admin)():
            raise LoaderError(
                errors.ADMIN_CANNOT_WRITE,
                f"cannot write to {firefox_dir} even as administrator",
                detail=repr(error),
            ) from error
        # Failures come back as ElevationError, which already has its own code (3xx).
        elevate.copy_as_administrator(checkout, firefox_dir, elevator)
