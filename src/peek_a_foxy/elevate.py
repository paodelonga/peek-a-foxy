"""Copying the two loader files into a Firefox folder that needs administrator rights (Windows).

Only that copy is elevated; the rest of the command runs as the user. The elevated process is a
fresh ``python -I -S -c <code>``: no module or file from a user-writable place is loaded, the files
to write travel inside its command line, and it checks them against SHA-256 values pinned in this
package (next to the pinned fx-autoconfig commit) before writing anything. Its only way to report
is its exit code. A same-user attacker who can rewrite the Python installation can still abuse the
prompt the user approves; that cannot be removed from here and is stated in the README.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from peek_a_foxy import errors
from peek_a_foxy.errors import ElevationError

log = logging.getLogger(__name__)  # only the parent process logs; HELPER_CODE imports nothing

# SHA-256 of the files at DEFAULT_COMMIT of fx-autoconfig, with LF line endings. A test fetches the
# real commit and compares: bump them together with the commit.
PINNED_SHA256 = {
    "config.js": "80dc421264a3ea04275e1724b7b57234f89254e9582a6c17e9a911b65c3aa6d7",
    "defaults/pref/config-prefs.js": (
        "6bfd2ed139d18ff5178e0fc62a3b4058540ddbeba3adc912c0d69edb70c17ece"
    ),
}
TIMEOUT_SECONDS = 180

# How long the command may be. ShellExecuteEx ends up in CreateProcessW, and Microsoft documents for
# its lpCommandLine: "The maximum length of this string is 32,767 characters, including the Unicode
# terminating null character"
# (learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw).
# SHELLEXECUTEINFOW.lpParameters has no limit of its own documented
# (learn.microsoft.com/windows/win32/api/shellapi/ns-shellapi-shellexecuteinfow), so the limit is
# applied to the whole line that CreateProcessW is assumed to receive:
#     quoted executable + one space + parameters + the terminating null <= 32,767
# The executable is counted as always quoted ("<path>", two characters more than a path without
# spaces), which is the pessimistic case. The real command is about 3.4 thousand characters (3,443
# measured with the real payloads), a tenth of the limit; the guard only turns a command that cannot
# work into a clear error instead of an opaque Win32 failure.
MAX_COMMAND_LINE_CHARS = 32767

# Exit codes of the elevated process.
OK, USAGE, NOT_FIREFOX, MISMATCH, LINKED, WRITE_FAILED = 0, 10, 11, 12, 13, 14
MESSAGES = {
    USAGE: "the elevated process was started with bad arguments",
    NOT_FIREFOX: "it is not a Firefox installation folder (firefox.exe, omni.ja or application.ini "
    "is missing or says another product)",
    MISMATCH: "the files to install do not match the pinned fx-autoconfig",
    LINKED: "a symbolic link or junction is in the way, so nothing was written",
    WRITE_FAILED: "writing the files failed even with administrator rights",
}

# The code of the elevated process. It is plain text on purpose: it is handed to ``python -c``.
# {pinned} is replaced by a JSON list of the two SHA-256 values.
HELPER_CODE = r"""
import base64, hashlib, os, sys

PINNED = {pinned}
NAMES = ("config.js", os.path.join("defaults", "pref", "config-prefs.js"))

def is_firefox(folder):
    if not (os.path.isfile(os.path.join(folder, "omni.ja"))):
        return False
    if not any(os.path.isfile(os.path.join(folder, n)) for n in ("firefox.exe", "firefox")):
        return False
    try:
        with open(os.path.join(folder, "application.ini"), encoding="utf-8", errors="replace") as f:
            return any(line.strip() == "Name=Firefox" for line in f)
    except OSError:
        return False

def main(argv):
    if len(argv) != 4:
        return 10
    folder = argv[1]
    try:
        payloads = [base64.b64decode(item, validate=True) for item in argv[2:]]
    except ValueError:
        return 10
    if [hashlib.sha256(p).hexdigest() for p in payloads] != PINNED:
        return 12
    folder = os.path.abspath(folder)
    if not is_firefox(folder):
        return 11
    if os.path.normcase(os.path.realpath(folder)) != os.path.normcase(folder):
        return 13
    # Nothing on the way may be a link or a junction: check before anything is created.
    for part in ("defaults", os.path.join("defaults", "pref")) + NAMES:
        path = os.path.join(folder, part)
        same = os.path.normcase(os.path.realpath(path)) == os.path.normcase(path)
        if os.path.lexists(path) and not same:
            return 13
    temporary = None
    try:
        os.makedirs(os.path.join(folder, "defaults", "pref"), exist_ok=True)
        for name, data in zip(NAMES, payloads):
            target = os.path.join(folder, name)
            temporary = target + ".peek-a-foxy.tmp"
            if os.path.lexists(temporary):
                os.unlink(temporary)  # never write through whatever someone left under that name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(temporary, flags, 0o644)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            os.replace(temporary, target)
            temporary = None
    except OSError:
        if temporary and os.path.lexists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return 14
    return 0

sys.exit(main(sys.argv))
"""


Elevator = Callable[[list[str]], int]


def helper_code() -> str:
    return HELPER_CODE.replace("{pinned}", json.dumps(list(PINNED_SHA256.values())))


def helper_command(firefox_dir: Path, payloads: list[bytes]) -> list[str]:
    """Command line of the elevated process: isolated Python, the code, the folder, the bytes."""
    encoded = [base64.b64encode(data).decode("ascii") for data in payloads]
    # The base interpreter, not a virtual environment's copy (pipx, uv): a venv lives in the user's
    # profile, where another program could swap python.exe or pyvenv.cfg.
    python = getattr(sys, "_base_executable", None) or sys.executable
    return [python, "-I", "-S", "-c", helper_code(), str(firefox_dir), *encoded]


def parameters_of(command: list[str]) -> str:
    """The parameter string that ShellExecuteEx gets: every argument after the program, quoted."""
    return subprocess.list2cmdline(command[1:])


def command_line_length(command: list[str]) -> int:
    """Characters of the whole line CreateProcessW gets, with its terminating null (see above)."""
    return len(f'"{command[0]}"') + 1 + len(parameters_of(command)) + 1


def parameters_allowed(executable: str) -> int:
    """The longest parameter string that keeps the whole line within the limit."""
    return MAX_COMMAND_LINE_CHARS - len(f'"{executable}"') - 2


def windows_elevator(command: list[str]) -> int:
    from peek_a_foxy import _winapi

    try:
        return _winapi.run_elevated(command[0], parameters_of(command), TIMEOUT_SECONDS)
    except _winapi.ElevationFailed as error:
        if error.args[0] == _winapi.ERROR_CANCELLED:
            raise ElevationError(
                errors.UAC_CANCELLED, "the administrator prompt was cancelled"
            ) from error
        if error.args[0] == _winapi.WAIT_TIMEOUT:
            raise ElevationError(
                errors.UAC_TIMEOUT, "the administrator prompt was not answered in time"
            ) from error
        raise ElevationError(
            errors.UAC_UNAVAILABLE,
            f"could not ask for administrator rights ({error})",
            detail=repr(error),
        ) from error


def is_admin() -> bool:  # pragma: no cover - needs Windows
    from peek_a_foxy import _winapi

    return _winapi.is_admin()


def copy_as_administrator(
    checkout: Path, firefox_dir: Path, elevator: Elevator | None = None
) -> None:
    """Copy ``config.js`` and ``defaults/pref/config-prefs.js`` into ``firefox_dir`` as admin."""
    if os.environ.get("FXAC_REPO") or os.environ.get("FXAC_COMMIT"):
        raise ElevationError(
            errors.UAC_ENV_OVERRIDE,
            "FXAC_REPO and FXAC_COMMIT are set: the administrator copy only accepts the pinned "
            "fx-autoconfig, so unset them",
        )
    payloads = [(checkout / "program" / name).read_bytes() for name in PINNED_SHA256]
    run = elevator or windows_elevator
    command = helper_command(firefox_dir, payloads)
    length = command_line_length(command)
    if length > MAX_COMMAND_LINE_CHARS:
        raise ElevationError(
            errors.COMMAND_TOO_LONG,
            f"the command for the administrator step is {length} characters long, more than the "
            f"{MAX_COMMAND_LINE_CHARS} that Windows allows, so it was not started",
            detail=f"{length} characters for the command line of {len(payloads)} file(s)",
        )
    # The command carries the code and the file contents: log only what it is made of.
    log.info(
        "asking for administrator rights to copy %d file(s) into %s (%d bytes of payload)",
        len(payloads),
        firefox_dir,
        sum(len(data) for data in payloads),
    )
    started = time.monotonic()
    code = run(command)
    log.info("the elevated process exited with %d after %.2f s", code, time.monotonic() - started)
    if code != OK:
        reason = MESSAGES.get(code, f"the elevated process failed (exit code {code})")
        raise ElevationError(
            errors.UAC_HELPER_FAILED,
            f"could not install the loader into {firefox_dir}: {reason}",
            detail=f"the elevated process exited with code {code}",
        )
