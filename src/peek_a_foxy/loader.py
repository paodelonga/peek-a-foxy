"""The fx-autoconfig loader, which lets Firefox run the ``*.uc.js`` script.

It is fetched at a pinned commit and the checkout is verified, so a moved branch or tag cannot
change what gets installed. ``FXAC_REPO`` / ``FXAC_COMMIT`` can override the source (used by the
tests).
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from peek_a_foxy import elevate, platform

DEFAULT_REPO = "https://github.com/MrOtherGuy/fx-autoconfig.git"
DEFAULT_COMMIT = "dfdab5684faffc112b76ccb1d8cab7f75da0102c"

# Relative to the Firefox install directory (and to ``program/`` in the fx-autoconfig checkout).
LOADER_FILES = ("config.js", "defaults/pref/config-prefs.js")


class LoaderError(RuntimeError):
    """The loader could not be fetched or installed."""


def repo_url() -> str:
    return os.environ.get("FXAC_REPO", DEFAULT_REPO)


def pinned_commit() -> str:
    """The commit to install, as a lowercase 40-digit hash; anything else is refused.

    A branch, tag or abbreviated hash could move or become ambiguous, and a value starting with
    ``-`` must never reach git as an option.
    """
    commit = os.environ.get("FXAC_COMMIT", DEFAULT_COMMIT)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise LoaderError(f"FXAC_COMMIT must be a full 40-digit commit hash, not {commit!r}")
    return commit.lower()


# Git for Windows converts line endings by default (core.autocrlf=true), which would hand Firefox a
# config.js with CRLF, and long paths in a checkout can fail without core.longpaths. Both are set on
# every call, whatever the user's git configuration says.
GIT_SETTINGS = ("-c", "core.autocrlf=false", "-c", "core.longpaths=true")


def _git(*args: str, cwd: Path | None = None) -> str:
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
        raise LoaderError(f"git {' '.join(args)} failed: {error.stderr.strip()}") from error
    return result.stdout.strip()


def remove_tree(path: Path) -> None:
    """Delete a directory tree, read-only files included (Windows refuses to delete them)."""
    # Top down: a folder is opened up before it is read.
    for root, directories, files in os.walk(path):
        for name in (*directories, *files):
            os.chmod(os.path.join(root, name), stat.S_IRWXU)
    shutil.rmtree(path)


def _fetch_commit(repo: str, commit: str, checkout: Path) -> None:
    """Fetch just ``commit`` (no history); fall back to a full clone if the server refuses that."""
    checkout.mkdir()
    try:
        _git("init", "--quiet", cwd=checkout)
        _git("fetch", "--quiet", "--depth", "1", "--", repo, commit, cwd=checkout)
    except LoaderError:
        remove_tree(checkout)
        _git("clone", "--quiet", "--", repo, str(checkout))
    _git("checkout", "--quiet", "--detach", commit, cwd=checkout)


def _git_missing() -> str:
    hint = "(or use --skip-loader)"
    try:
        windows = platform.system() == "windows"
    except platform.UnsupportedPlatformError:
        windows = False
    if windows:
        return (
            "git is required to fetch fx-autoconfig: install Git for Windows "
            f"(https://git-scm.com/download/win, or `winget install Git.Git`) {hint}"
        )
    return f"git is required to fetch fx-autoconfig {hint}"


@contextmanager
def fetch_loader() -> Iterator[Path]:
    """Fetch fx-autoconfig into a temporary directory and yield the verified checkout."""
    if shutil.which("git") is None:
        raise LoaderError(_git_missing())
    commit = pinned_commit()
    with tempfile.TemporaryDirectory(prefix="peek-a-foxy-", ignore_cleanup_errors=True) as tmp:
        checkout = Path(tmp) / "fx-autoconfig"
        _fetch_commit(repo_url(), commit, checkout)
        if _git("rev-parse", "HEAD", cwd=checkout) != commit:
            raise LoaderError("fx-autoconfig checkout does not match the pinned commit")
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
    try:
        subprocess.run(["sudo", *command], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        raise LoaderError(f"could not run 'sudo {' '.join(command)}'") from error


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
            raise LoaderError(f"cannot write to {firefox_dir} even as administrator") from error
        try:
            elevate.copy_as_administrator(checkout, firefox_dir, elevator)
        except elevate.ElevationError as failure:
            raise LoaderError(str(failure)) from failure
