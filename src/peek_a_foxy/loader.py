"""The fx-autoconfig loader, which lets Firefox run the ``*.uc.js`` script.

It is cloned at a pinned commit and the checkout is verified, so a moved branch or tag cannot change
what gets installed. ``FXAC_REPO`` / ``FXAC_COMMIT`` can override the source (used by the tests).
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_REPO = "https://github.com/MrOtherGuy/fx-autoconfig.git"
DEFAULT_COMMIT = "dfdab5684faffc112b76ccb1d8cab7f75da0102c"

# Relative to the Firefox install directory (and to ``program/`` in the fx-autoconfig checkout).
LOADER_FILES = ("config.js", "defaults/pref/config-prefs.js")


class LoaderError(RuntimeError):
    """The loader could not be fetched or installed."""


def repo_url() -> str:
    return os.environ.get("FXAC_REPO", DEFAULT_REPO)


def pinned_commit() -> str:
    return os.environ.get("FXAC_COMMIT", DEFAULT_COMMIT)


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise LoaderError(f"git {' '.join(args)} failed: {error.stderr.strip()}") from error
    return result.stdout.strip()


@contextmanager
def fetch_loader() -> Iterator[Path]:
    """Clone fx-autoconfig into a temporary directory and yield the verified checkout."""
    if shutil.which("git") is None:
        raise LoaderError("git is required to fetch fx-autoconfig (or use --skip-loader)")
    commit = pinned_commit()
    with tempfile.TemporaryDirectory(prefix="peek-a-foxy-") as tmp:
        checkout = Path(tmp) / "fx-autoconfig"
        _git("clone", "--quiet", repo_url(), str(checkout))
        _git("checkout", "--quiet", commit, cwd=checkout)
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


def _copy(source: Path, destination: Path) -> None:
    """Copy a file, falling back to sudo when the directory is not writable."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o644)
    except PermissionError:
        _sudo("mkdir", "-p", str(destination.parent))
        _sudo("install", "-m", "644", str(source), str(destination))


def install_loader(checkout: Path, firefox_dir: Path) -> None:
    for name in LOADER_FILES:
        _copy(checkout / "program" / name, firefox_dir / name)
