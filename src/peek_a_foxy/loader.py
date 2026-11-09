"""The fx-autoconfig loader, which lets Firefox run the ``*.uc.js`` script.

It is fetched at a pinned commit and the checkout is verified, so a moved branch or tag cannot
change what gets installed. ``FXAC_REPO`` / ``FXAC_COMMIT`` can override the source (used by the
tests).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from peek_a_foxy import elevate, errors, fileio, platform
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
# A stalled connection must not hang the command for good, and git must never wait for a password
# that nobody can type (a private repository in FXAC_REPO): it fails instead.
GIT_TIMEOUT_SECONDS = 120
GIT_ENVIRONMENT = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


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
            env={**os.environ, **GIT_ENVIRONMENT},
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        log.error("git %s timed out after %d s", args[0], GIT_TIMEOUT_SECONDS)
        raise LoaderError(
            errors.GIT_FAILED,
            f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS} seconds",
            detail=f"git {' '.join(args)} was stopped after {GIT_TIMEOUT_SECONDS} seconds",
        ) from error
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


# What git says when the connection or the login is what failed. A full clone would fail the same
# way, so it is not tried: someone who is offline waits for one failure, and reads that one.
_UNREACHABLE = (
    "could not resolve host",
    "unable to access",
    "failed to connect",
    "unable to connect",
    "connection timed out",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "could not read from remote",
    "terminal prompts disabled",
    "authentication failed",
    "timed out",
)


def _server_unreachable(error: LoaderError) -> bool:
    text = error.message.lower()
    return any(phrase in text for phrase in _UNREACHABLE)


def _fetch_commit(repo: str, commit: str, checkout: Path) -> None:
    """Fetch just ``commit`` (no history); fall back to a full clone if the server refuses that."""
    checkout.mkdir()
    try:
        _git("init", "--quiet", cwd=checkout)
        _git("fetch", "--quiet", "--depth", "1", "--", repo, commit, cwd=checkout)
    except LoaderError as error:
        if _server_unreachable(error):
            raise
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


MAX_LOADER_FILE = 1024 * 1024  # the real files are a few hundred bytes


def _unix(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def same_content(source: Path, destination: Path) -> bool:
    """Whether ``destination`` already holds what ``source`` has (a CRLF copy counts as the same).

    Anything that cannot be read as a small regular file is "not the same".
    """
    try:
        found = fileio.read_regular(destination, MAX_LOADER_FILE)
        wanted = fileio.read_regular(source, MAX_LOADER_FILE)
    except OSError:
        return False
    return len(found) <= MAX_LOADER_FILE and _unix(found) == _unix(wanted)


def conflicts(checkout: Path, firefox_dir: Path) -> list[Path]:
    """Loader files already in the Firefox directory that differ from the ones we would install."""
    return [
        firefox_dir / name
        for name in LOADER_FILES
        if (firefox_dir / name).is_file()
        and not same_content(checkout / "program" / name, firefox_dir / name)
    ]


def install_utils(checkout: Path, chrome_dir: Path) -> None:
    """``chrome/utils`` belongs to the profile and is safe to refresh (but not through a link)."""
    destination = chrome_dir / "utils"
    if destination.is_symlink():
        raise errors.UserFileError(
            errors.UTILS_IS_A_LINK, f"{destination} is a symbolic link, so it was left alone"
        )
    shutil.copytree(checkout / "profile" / "chrome" / "utils", destination, dirs_exist_ok=True)


def _sudo(*command: str, data: bytes | None = None) -> None:
    """Run ``sudo command``; ``data`` is what the command reads on its standard input."""
    log.info("running: sudo %s", " ".join(command))
    try:
        # ``tee`` echoes what it reads: the copy is not for the terminal.
        stdout = subprocess.DEVNULL if command[0] == "tee" else None
        if stdout is None:
            subprocess.run(["sudo", *command], check=True, input=data)
        else:
            subprocess.run(["sudo", *command], check=True, input=data, stdout=stdout)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        log.error("sudo failed: %r", error)
        raise LoaderError(
            errors.SUDO_FAILED,
            f"could not run 'sudo {' '.join(command)}'",
            detail=repr(error),
        ) from error


def overridden() -> bool:
    """Whether ``FXAC_REPO`` or ``FXAC_COMMIT`` replaces the pinned fx-autoconfig."""
    return bool(os.environ.get("FXAC_REPO") or os.environ.get("FXAC_COMMIT"))


def verified_bytes(source: Path, name: str, *, allow_unverified: bool) -> bytes:
    """The bytes of ``source``, checked against the SHA-256 pinned for ``name``.

    These are the bytes that go to a folder owned by root, so the check is done on the very bytes
    that are handed over: the file that was read is not read again. With ``FXAC_REPO`` or
    ``FXAC_COMMIT`` the files cannot match the pins; that is refused unless ``allow_unverified``.
    """
    data = source.read_bytes()
    if overridden():
        if not allow_unverified:
            raise LoaderError(
                errors.LOADER_UNVERIFIED,
                "FXAC_REPO or FXAC_COMMIT is set, so the loader cannot be checked against the "
                "pinned one before it is copied as administrator",
            )
        log.warning(
            "copying %s as administrator WITHOUT checking it: --allow-unverified-loader", name
        )
        return data
    if hashlib.sha256(data).hexdigest() != elevate.PINNED_SHA256[name]:
        raise LoaderError(
            errors.CHECKOUT_MISMATCH,
            f"{name} of the checkout does not match the pinned fx-autoconfig, so it was not "
            "copied as administrator",
            detail=f"sha256 {hashlib.sha256(data).hexdigest()[:16]}...",
        )
    return data


def _copy_direct(source: Path, destination: Path) -> None:
    """Copy a file so that it appears whole or not at all (written beside it, then renamed)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{os.getpid()}.{secrets.token_hex(4)}.peek-a-foxy.tmp"
    )
    try:
        with open(source, "rb") as reader, open(temporary, "xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, destination)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _copy(source: Path, destination: Path, name: str, *, allow_unverified: bool = False) -> None:
    """Copy a file, falling back to sudo when the directory is not writable.

    As root, the bytes are checked against the pinned hash and piped to ``install`` (a second read
    of a file that the user can write could hand over something else).
    """
    try:
        _copy_direct(source, destination)
    except PermissionError:
        data = verified_bytes(source, name, allow_unverified=allow_unverified)
        _sudo("mkdir", "-p", str(destination.parent))
        if platform.system() == "macos":
            # BSD install may refuse /dev/stdin, so the bytes go through tee and chmod.
            _sudo("tee", str(destination), data=data)
            _sudo("chmod", "644", str(destination))
        else:
            _sudo("install", "-m", "644", "/dev/stdin", str(destination), data=data)


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
    allow_unverified: bool = False,
) -> None:
    """Copy the loader files; where the folder is protected, ask for rights (sudo or UAC).

    A file that is already there with the same content is left alone, so a run that has nothing to
    do never asks for rights. ``allow_unverified`` lets sudo copy a loader that is not the pinned
    one (``FXAC_REPO``); the administrator copy on Windows has no such way.
    """
    wanted = [
        name
        for name in LOADER_FILES
        if not same_content(checkout / "program" / name, firefox_dir / name)
    ]
    if not wanted:
        log.info("the loader in %s is already in place", firefox_dir)
        return
    if not platform.is_windows():
        for name in wanted:
            _copy(
                checkout / "program" / name,
                firefox_dir / name,
                name,
                allow_unverified=allow_unverified,
            )
        return
    try:
        for name in wanted:
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
