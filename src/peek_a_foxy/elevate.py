"""Copying the two loader files into a Firefox folder that needs administrator rights (Windows).

Only that copy is elevated; the rest of the command runs as the user. The elevated process is the
Windows PowerShell of the system folder (``System32``, found through ``GetSystemDirectoryW``, never
through ``PATH`` or an environment variable), started with ``-NoProfile -NonInteractive
-EncodedCommand``. The script it runs is generated here and carries everything it needs as
literals: the Firefox folder, the two files to write (base64) and their SHA-256 values pinned in
this package (next to the pinned fx-autoconfig commit). It checks the files and the folder before
writing anything, and its only way to report is its exit code. The same route serves the standalone
``peek-a-foxy.exe`` and an installation with Python, so there is one elevated program to test and
nothing from a user-writable place (a Python installation, the program itself) runs with the
rights the user approves. A same-user attacker can still abuse that prompt through what Windows
and .NET read from the user's own settings (for example environment variables that load a .NET
profiler); that cannot be removed from here and is stated in the README.
"""

from __future__ import annotations

import base64
import logging
import ntpath
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path

from peek_a_foxy import errors
from peek_a_foxy.errors import ElevationError

log = logging.getLogger(__name__)  # only the parent process logs; the script writes no log

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
# spaces), which is the pessimistic case. The script travels as base64 of its UTF-16LE text, so
# every character of it costs about 2.7 characters of command line. With the real files (429 and
# 194 bytes) and the usual folder the command is about 11 thousand characters, a third of the
# limit; the guard turns a command that cannot work into a clear error instead of an opaque Win32
# failure.
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

# Where Windows PowerShell 5.1 lives under the system folder, and how it is started.
POWERSHELL = ("WindowsPowerShell", "v1.0", "powershell.exe")
POWERSHELL_FLAGS = ("-NoProfile", "-NonInteractive", "-EncodedCommand")
# Only used to build and measure the command on Linux and macOS, where it never runs.
STAND_IN_SYSTEM_DIRECTORY = "C:\\Windows\\System32"
_SYSTEM_DIRECTORY = re.compile(r"[A-Za-z]:\\[^\x00-\x1f\"*<>?|]*")

# The script of the elevated process. It uses the language and .NET only: the one cmdlet is
# Set-StrictMode, which is built in, so nothing is auto-loaded from a module folder that the user
# can write (PSModulePath). It has no comment, no double-quoted string and no here-string, and every
# @@NAME@@ is replaced in one pass by a single-quoted literal (see helper_script). $failure is the
# exit code for an exception in the step that is running, so no exception ends with an unmapped 1.
# Its steps are those of the former Python helper: the arguments (USAGE), the pinned hashes
# (MISMATCH), a Firefox folder (NOT_FIREFOX), no link or junction from the drive root to the files
# (LINKED), then each file written aside with CreateNew and renamed over the old one (WRITE_FAILED).
HELPER_SCRIPT = r"""Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$failure = 10
$temporary = $null
function attributes([string]$path) {
    try {
        return [IO.File]::GetAttributes($path)
    } catch [IO.FileNotFoundException], [IO.DirectoryNotFoundException] {
        return $null
    }
}
try {
    $folder = '@@FOLDER@@'
    $encoded = @('@@CONFIG@@', '@@PREFS@@')
    $pinned = @('@@PINNED_CONFIG@@', '@@PINNED_PREFS@@')
    $names = @('config.js', 'defaults\pref\config-prefs.js')
    $reparse = [IO.FileAttributes]::ReparsePoint
    if ($folder -match '[\x00-\x1f\x7f]' -or $folder -notmatch '^(?:[A-Za-z]:\\|\\\\[^\\?.])') {
        exit 10
    }
    $full = [IO.Path]::GetFullPath($folder)
    $payloads = [Collections.Generic.List[byte[]]]::new()
    foreach ($item in $encoded) {
        $payloads.Add([Convert]::FromBase64String($item))
    }

    $failure = 12
    $sha = [Security.Cryptography.SHA256CryptoServiceProvider]::new()
    for ($i = 0; $i -lt 2; $i++) {
        $digest = [BitConverter]::ToString($sha.ComputeHash($payloads[$i])).Replace('-', '')
        if ($digest.ToLowerInvariant() -cne $pinned[$i]) {
            exit 12
        }
    }

    $failure = 11
    foreach ($name in @('omni.ja', 'firefox.exe', 'application.ini')) {
        if (-not [IO.File]::Exists([IO.Path]::Combine($full, $name))) {
            exit 11
        }
    }
    $named = $false
    foreach ($line in [IO.File]::ReadAllLines([IO.Path]::Combine($full, 'application.ini'))) {
        if ($line.Trim() -ceq 'Name=Firefox') {
            $named = $true
        }
    }
    if (-not $named) {
        exit 11
    }

    $failure = 13
    $same = [StringComparison]::OrdinalIgnoreCase
    if (-not [string]::Equals($full.TrimEnd([char]92), $folder.TrimEnd([char]92), $same)) {
        exit 13
    }
    $path = $full
    while ($path) {
        if ([IO.File]::GetAttributes($path).HasFlag($reparse)) {
            exit 13
        }
        $path = [IO.Path]::GetDirectoryName($path)
    }
    foreach ($part in @('defaults', 'defaults\pref') + $names) {
        $found = attributes ([IO.Path]::Combine($full, $part))
        if ($null -ne $found -and $found.HasFlag($reparse)) {
            exit 13
        }
    }

    $failure = 14
    [void][IO.Directory]::CreateDirectory([IO.Path]::Combine($full, 'defaults\pref'))
    for ($i = 0; $i -lt 2; $i++) {
        $target = [IO.Path]::Combine($full, $names[$i])
        $temporary = $target + '.peek-a-foxy.tmp'
        if ($null -ne (attributes $temporary)) {
            [IO.File]::Delete($temporary)
        }
        $mode = [IO.FileMode]::CreateNew
        $stream = [IO.File]::Open($temporary, $mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $stream.Write($payloads[$i], 0, $payloads[$i].Length)
            $stream.Flush($true)
        } finally {
            $stream.Dispose()
        }
        if ($null -ne (attributes $target)) {
            [IO.File]::Replace($temporary, $target, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $target)
        }
        $temporary = $null
    }
    exit 0
} catch {
    if ($null -ne $temporary) {
        try {
            [IO.File]::Delete($temporary)
        } catch {
        }
    }
    exit $failure
}
"""

# PowerShell ends a single-quoted string at any of these five characters, not only at the ASCII
# one; inside the string each is written twice (what its own EscapeSingleQuotedStringContent does).
SINGLE_QUOTES = "'\u2018\u2019\u201a\u201b"
_PLACEHOLDER = re.compile(r"@@([A-Z_]+)@@")
_BASE64 = re.compile(r"[A-Za-z0-9+/]*={0,2}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# Characters a folder name may not have here: control characters (NUL, line breaks, tabs...) and
# the Unicode line and paragraph separators. Windows forbids the control characters in file names
# anyway, so a real Firefox folder never has them.
_REFUSED_CATEGORIES = {"Cc", "Zl", "Zp"}


Elevator = Callable[[list[str]], int]


def quote(text: str) -> str:
    """``text`` as the inside of a PowerShell single-quoted string: nothing in it is code."""
    return "".join(char * 2 if char in SINGLE_QUOTES else char for char in text)


def refused_character(folder: str) -> str | None:
    """The first character of ``folder`` that the script does not accept, if any."""
    for char in folder:
        if unicodedata.category(char) in _REFUSED_CATEGORIES:
            return char
    return None


def helper_script(folder: str, payloads: list[bytes]) -> str:
    """The script of the elevated process for ``folder`` (taken as given) and the two files."""
    if len(payloads) != len(PINNED_SHA256):
        raise ValueError(f"expected {len(PINNED_SHA256)} files, got {len(payloads)}")
    pinned = list(PINNED_SHA256.values())
    encoded = [base64.b64encode(data).decode("ascii") for data in payloads]
    # Neither can hold a quote, so they need no escaping; checked anyway, the script depends on it.
    if not all(_SHA256.fullmatch(digest) for digest in pinned):
        raise ValueError("a pinned SHA-256 value is not 64 lowercase hexadecimal digits")
    if not all(_BASE64.fullmatch(item) for item in encoded):  # pragma: no cover - b64encode's
        raise ValueError("a payload is not plain base64")
    values = {
        "FOLDER": quote(folder),
        "CONFIG": encoded[0],
        "PREFS": encoded[1],
        "PINNED_CONFIG": pinned[0],
        "PINNED_PREFS": pinned[1],
    }
    # One pass: a value that looks like a placeholder (a folder called @@CONFIG@@) stays as it is.
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], HELPER_SCRIPT)


def encoded_command(script: str) -> str:
    """What ``-EncodedCommand`` takes: base64 of the UTF-16LE text, without a byte order mark.

    ``surrogatepass`` keeps a lone surrogate, which an NTFS name may have, as the same UTF-16 unit.
    """
    return base64.b64encode(script.encode("utf-16-le", "surrogatepass")).decode("ascii")


def system_directory() -> str:
    """The Windows system folder as ``GetSystemDirectoryW`` reports it (a stand-in elsewhere)."""
    if sys.platform != "win32":
        return STAND_IN_SYSTEM_DIRECTORY
    return _windows_system_directory()  # pragma: no cover - needs Windows


def _windows_system_directory() -> str:  # pragma: no cover - needs Windows
    from peek_a_foxy import _winapi

    try:
        return _winapi.system_directory()
    except _winapi.ElevationFailed as error:
        raise ElevationError(
            errors.UAC_UNAVAILABLE,
            "could not find the Windows system folder, where Windows PowerShell lives",
            detail=repr(error),
        ) from error


def powershell_path(system_dir: str) -> str:
    """Windows PowerShell under ``system_dir``, after checking that it is a plain local folder."""
    parts = system_dir.split("\\")
    if not _SYSTEM_DIRECTORY.fullmatch(system_dir) or ".." in parts or "." in parts:
        raise ElevationError(
            errors.UAC_UNAVAILABLE,
            f"Windows reported an unexpected system folder ({system_dir!r}), so Windows "
            "PowerShell cannot be found safely",
        )
    return ntpath.join(system_dir, *POWERSHELL)


def helper_command(firefox_dir: Path, payloads: list[bytes]) -> list[str]:
    """Command line of the elevated process: Windows PowerShell and the encoded script."""
    folder = os.path.abspath(firefox_dir)  # the elevated process starts in System32
    char = refused_character(folder)
    if char is not None:
        raise ElevationError(
            errors.UAC_HELPER_FAILED,
            f"could not install the loader into {folder!r}: the folder name has a character "
            f"({char!r}) that the administrator step does not accept, so it was not started",
        )
    script = helper_script(folder, payloads)
    return [powershell_path(system_directory()), *POWERSHELL_FLAGS, encoded_command(script)]


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

    if not os.path.isfile(command[0]):
        raise ElevationError(
            errors.UAC_UNAVAILABLE,
            f"{command[0]} was not found, so the administrator step cannot be started",
        )
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
