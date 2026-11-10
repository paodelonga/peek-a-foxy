"""The local log: a small rotating file on this machine, never sent anywhere.

Every run writes what it did (the plan's steps with their durations, the commands it started and
how they ended, warnings, errors with their traceback) so a problem can be understood afterwards,
and so a person asked for "the log" has something to hand over. Three promises:

* Redaction. Whatever reaches a handler goes through :class:`Redactor`: the home folder becomes
  ``~``, the user name and Firefox profile folder names disappear, and tokens in URLs are hidden.
* Logging never breaks a command. If the log cannot be created or written (read-only disk, full
  disk, a locked file) one warning is shown and the command goes on.
* The elevated helper process (:data:`peek_a_foxy.elevate.HELPER_CODE`) has no part in this: it
  imports nothing from this package and reports only through its exit code.

Where the file lives (``kind`` is ``windows``, ``macos`` or ``linux``) is decided by pure functions
that take the environment and the home folder as arguments, so every platform is tested anywhere.
"""

from __future__ import annotations

import contextlib
import getpass
import logging
import logging.handlers
import os
import platform as py_platform
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import cast
from urllib.parse import quote

from peek_a_foxy import platform

ENV_VAR = "PEEK_A_FOXY_LOG"  # "off", or the path of the log file
LOG_NAME = "peek-a-foxy.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 2  # peek-a-foxy.log, .log.1 and .log.2: three files of at most 5 MB
RUN_MARKER = "run started:"
LOGGER = "peek_a_foxy"

# With no handler at all, Python prints warnings and errors to stderr on its own; this one keeps
# the package silent whenever a run has not (or no longer has) a log of its own.
_SILENCE = logging.NullHandler()
logging.getLogger(LOGGER).addHandler(_SILENCE)

# --- where the log lives ------------------------------------------------------------------------


def default_kind() -> str:
    """The system as ``windows``, ``macos`` or ``linux`` (anything else behaves as Linux)."""
    try:
        return platform.system()
    except platform.UnsupportedPlatformError:
        return "linux"


def log_dir(kind: str, environ: Mapping[str, str], home: PurePath) -> PurePath:
    """The folder of the log: the place each system keeps this kind of file."""
    if kind == "windows":
        base = environ.get("LOCALAPPDATA")
        local = PureWindowsPath(base) if base else PureWindowsPath(home) / "AppData" / "Local"
        return local / "peek-a-foxy" / "logs"
    if kind == "macos":
        return PurePosixPath(home) / "Library" / "Logs" / "peek-a-foxy"
    state = environ.get("XDG_STATE_HOME")
    # The XDG rule: a relative value must be ignored.
    base_dir = PurePosixPath(state) if state and state.startswith("/") else None
    return (base_dir or PurePosixPath(home) / ".local" / "state") / "peek-a-foxy"


@dataclass(frozen=True)
class Target:
    """Where this run logs: ``path`` is ``None`` when logging is off; ``source`` says why."""

    path: Path | None
    source: str  # "default", "flag", "env", "off-flag", "off-env" or "no-home"


def _file_for(value: str) -> Path:
    path = Path(value).expanduser()
    return path / LOG_NAME if path.is_dir() else path  # a folder is accepted for convenience


def resolve_target(
    *,
    log_file: str | None = None,
    no_log: bool = False,
    env_value: str | None = None,
    kind: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Target:
    """``--no-log`` beats ``--log-file``, then ``PEEK_A_FOXY_LOG``, then the default place."""
    if no_log:
        return Target(None, "off-flag")
    if log_file:
        return Target(_file_for(log_file), "flag")
    if env_value is not None and env_value.strip():
        if env_value.strip().lower() == "off":
            return Target(None, "off-env")
        return Target(_file_for(env_value.strip()), "env")
    try:
        base_home = Path.home() if home is None else home
    except (RuntimeError, OSError):  # no home folder to put a log in: go without one
        return Target(None, "no-home")
    folder = log_dir(kind or default_kind(), os.environ if environ is None else environ, base_home)
    return Target(Path(str(folder)) / LOG_NAME, "default")


# --- redaction ----------------------------------------------------------------------------------

_URL_CREDENTIALS = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@")
_QUERY_SECRET = re.compile(
    r"(?i)\b(?P<name>access_token|token|api[_-]?key|key|secret|password|passwd|auth|sig|signature)"
    r"=[^&\s\"']+"
)
_AUTH_HEADER = re.compile(r"(?i)(?P<head>authorization:\s*(?:bearer|basic|token)\s+)\S+")
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}")
# Firefox names profile folders like ``a1b2c3d4.default-release``.
_PROFILE_FOLDER = re.compile(r"(?<=[\\/])[a-z0-9]{8}\.[^\\/\s'\"]+")
_SEPARATORS = re.compile(r"[\\/]+")


def _name(part: str) -> str:
    """One folder name as a regex: as is, or percent-encoded as in a ``file://`` URL."""
    if re.fullmatch(r"[A-Za-z]:", part):  # a drive letter, in either case (``C:`` or ``C%3A``)
        return f"[{part[0].lower()}{part[0].upper()}](?::|%3[Aa])"
    # errors="replace": a name that is not valid text (undecodable bytes) must not break logging.
    forms = {part, quote(part, safe=":", errors="replace"), quote(part, safe="", errors="replace")}
    return "(?:" + "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True)) + ")"


def _folder_pattern(path: str) -> str:
    """A regex for one folder in any spelling a log line may hold it in.

    Every run of slashes and backslashes counts as one separator, which covers either slash, a
    mix of both, and the doubled backslashes of a ``repr()`` (or of the repr of a repr). A network
    share also matches in its ``\\\\?\\UNC\\`` form, names also match percent-encoded, and the
    drive letter matches in either case.
    """
    parts = [part for part in _SEPARATORS.split(path) if part]
    lead = ""
    if path[:2] in ("\\\\", "//"):  # a network share: \\server\share, or \\?\UNC\server\share
        lead = r"[\\/]{2,}(?:\?[\\/]+UNC[\\/]+)?"
    elif path.startswith(("\\", "/")):
        lead = r"[\\/]+"
    return lead + r"[\\/]+".join(_name(part) for part in parts)


def _home_text(home: Path | None) -> str | None:
    """The home folder as text; ``None`` when the system cannot say where it is."""
    if home is not None:
        return str(home)
    try:
        return str(Path.home())
    except (RuntimeError, OSError):
        return None


STANDARD_PROFILE_NAMES = frozenset(
    {"default", "default-release", "default-esr", "default-nightly", "dev-edition-default"}
)


class Redactor:
    """Hides what identifies the person or grants access, in any text."""

    def __init__(
        self,
        *,
        home: str | None,
        user: str | None,
        extra_homes: Sequence[str] = (),
        ignore_case: bool = False,
        profile_names: Sequence[str] = (),
    ) -> None:
        # A home that is just "/" or "C:\" would blank out every path. The longest goes first, so
        # that a folder inside another is not cut short.
        homes = sorted(
            {c for c in (home, *extra_homes) if c and len(c.strip("/\\")) >= 2},
            key=len,
            reverse=True,
        )
        flags = re.IGNORECASE if ignore_case else 0
        self._home = (
            re.compile("|".join(_folder_pattern(h.rstrip("/\\")) for h in homes), flags)
            if homes
            else None
        )
        # A profile name chosen by the person may be personal: each becomes ``<profile N>`` (N is
        # its place in profiles.ini, so a report stays readable). Standard names Firefox itself
        # gives, and names too short to tell apart from ordinary words, are kept.
        self._names: list[tuple[re.Pattern[str], str]] = []
        for number, name in enumerate(profile_names, start=1):
            if len(name) >= 3 and name not in STANDARD_PROFILE_NAMES:
                pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", flags)
                self._names.append((pattern, f"<profile {number}>"))
        # Short names would also match inside ordinary words, so only distinctive ones are hidden
        # on their own; the home folder (which contains the name) is always hidden.
        self._user = (
            re.compile(rf"(?<!\w){re.escape(user)}(?!\w)", flags)
            if user and len(user) >= 3
            else None
        )

    @classmethod
    def for_this_machine(
        cls,
        environ: Mapping[str, str] | None = None,
        home: Path | None = None,
        kind: str | None = None,
        short_path: Callable[[str], str | None] | None = None,
        profile_names: Sequence[str] = (),
    ) -> Redactor:
        """``short_path`` gives a folder's 8.3 name on Windows (``C:\\Users\\ANAMAR~1``)."""
        env = os.environ if environ is None else environ
        system = kind or default_kind()
        try:
            user: str | None = getpass.getuser()
        except Exception:  # no passwd entry, no environment: not worth failing over
            user = None
        names = [env.get(name) for name in ("USERNAME", "USER", "LOGNAME")]
        user = user or next((name for name in names if name), None)
        main = _home_text(home)
        homes = [value for value in (main, env.get("USERPROFILE"), env.get("HOME")) if value]
        if short_path is None and sys.platform == "win32":  # pragma: no cover - Windows only
            from peek_a_foxy._winapi import short_path
        # The same folders as the system itself may spell them: with links resolved, and (the
        # temporary folder is often spelled that way) by their 8.3 short names.
        for folder in list(homes):
            homes.append(os.path.realpath(folder))
            if system == "windows" and short_path:
                with contextlib.suppress(Exception):
                    homes.append(short_path(folder) or "")
        return cls(
            home=main,
            user=user,
            extra_homes=homes,
            ignore_case=system == "windows",
            profile_names=profile_names,
        )

    def __call__(self, text: str) -> str:
        if self._home:
            text = self._home.sub("~", text)
        for pattern, placeholder in self._names:
            text = pattern.sub(placeholder, text)
        if self._user:
            text = self._user.sub("<user>", text)
        text = _URL_CREDENTIALS.sub(r"\g<scheme>***@", text)
        text = _AUTH_HEADER.sub(r"\g<head>***", text)
        text = _QUERY_SECRET.sub(r"\g<name>=***", text)
        text = _GITHUB_TOKEN.sub("***", text)
        return _PROFILE_FOLDER.sub("<profile>", text)


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")  # all but \t \n \r


class _Formatter(logging.Formatter):
    """Formats a record (traceback included) and redacts the result."""

    converter = staticmethod(time.gmtime)  # the file is always in UTC

    def __init__(self, fmt: str, redact: Redactor, run_id: str) -> None:
        super().__init__(fmt, datefmt="%Y-%m-%dT%H:%M:%S")
        self._redact = redact
        self._run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        record.run_id = self._run_id
        # Escape sequences from a file's content must not reach a terminal when the log is shown.
        return _CONTROL.sub("\ufffd", self._redact(super().format(record)))


FILE_FORMAT = "%(asctime)sZ %(levelname)-7s %(run_id)s %(message)s"
CONSOLE_FORMAT = "%(levelname)-7s %(message)s"

# --- handlers and the run -----------------------------------------------------------------------


def _append_opener(path: str, flags: int) -> int:
    """Open the log to add lines at its end, whole, even while another run adds its own."""
    if sys.platform == "win32":  # pragma: no cover - Windows only
        from peek_a_foxy._winapi import open_for_appending

        return open_for_appending(path)
    return os.open(path, flags, 0o666)  # O_APPEND already writes at the end in one step here


class _SafeFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating file that gives up quietly (after one warning) when it cannot be written."""

    def __init__(self, path: Path, on_failure: Callable[[str], None]) -> None:
        super().__init__(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )  # the file is opened now: an unwritable place fails here, not at the first record
        self._on_failure = on_failure
        self.failed = False

    def _open(self) -> TextIOWrapper:
        # Also for the file that a rotation starts. (Two runs at once share the file.)
        opened = open(  # noqa: SIM115 - the handler owns the stream and closes it
            self.baseFilename,
            self.mode,
            encoding=self.encoding,
            errors=self.errors,
            opener=_append_opener,
        )
        return cast(TextIOWrapper, opened)

    def emit(self, record: logging.LogRecord) -> None:
        if not self.failed:
            super().emit(record)

    def handleError(self, record: logging.LogRecord) -> None:
        if self.failed:
            return
        self.failed = True
        error = sys.exc_info()[1]
        self._on_failure(f"{type(error).__name__}: {error}" if error else "unknown error")


@dataclass
class Session:
    run_id: str
    path: Path | None  # the file being written, or None
    started: float
    verbose: bool = False


_session: Session | None = None


def active_path() -> Path | None:
    """The log file of the current run, when there is one that works."""
    return _session.path if _session else None


def is_verbose() -> bool:
    return _session.verbose if _session else False


def start(
    *,
    target: Path | None,
    verbose: bool,
    argv: Sequence[str],
    version: str,
    redactor: Redactor | None = None,
    warn: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> Session:
    """Begin logging for this run. Never raises: a log that cannot be written is only a warning."""
    stop()
    redact = redactor or Redactor.for_this_machine()
    run = run_id or secrets.token_hex(4)
    logger = logging.getLogger(LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    def warn_once(reason: str) -> None:
        if warn:
            warn(f"could not write the log file ({reason}); going on without it")
        if _session and _session.path:
            _session.path = None

    path: Path | None = None
    if target is not None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = _SafeFileHandler(target, warn_once)
            handler.setFormatter(_Formatter(FILE_FORMAT, redact, run))
            logger.addHandler(handler)
            path = target
        except OSError as error:
            if warn:
                warn(f"could not write the log file ({error}); going on without it")
    if verbose:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(_Formatter(CONSOLE_FORMAT, redact, run))
        logger.addHandler(console)

    global _session
    _session = Session(run, path, time.monotonic(), verbose)
    frozen = "standalone program" if getattr(sys, "frozen", False) else "installed with pip"
    logger.info(
        "%s peek-a-foxy %s (%s), Python %s, %s %s, args: %s",
        RUN_MARKER,
        version,
        frozen,
        py_platform.python_version(),
        py_platform.platform(),
        py_platform.machine(),
        list(argv),
    )
    return _session


def stop(exit_code: int | None = None) -> None:
    """Say how the run ended and close the files (a no-op when nothing was started)."""
    global _session
    logger = logging.getLogger(LOGGER)
    if _session is not None and exit_code is not None:
        logger.info(
            "run finished: exit code %d after %.2f s",
            exit_code,
            time.monotonic() - _session.started,
        )
    for handler in list(logger.handlers):
        if handler is not _SILENCE:
            logger.removeHandler(handler)
            # A file that broke under us must not break the end of the run.
            with contextlib.suppress(Exception):
                handler.close()
    _session = None


# --- reading and clearing the log (the ``logs`` command) ----------------------------------------


def log_files(path: Path) -> list[Path]:
    """The log file and its rotated copies that exist, newest first."""
    names = [path, *(path.with_name(f"{path.name}.{n}") for n in range(1, BACKUP_COUNT + 1))]
    return [candidate for candidate in names if candidate.is_file()]


def last_run(path: Path) -> list[str]:
    """The lines of the most recent run in the newest file, redacted when written; may be empty."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for index in range(len(lines) - 1, -1, -1):
        if RUN_MARKER in lines[index]:
            return lines[index:]
    return []


def clear(path: Path) -> int:
    """Delete the log and its rotated copies (only those); return how many files were removed."""
    removed = 0
    for candidate in log_files(path):
        candidate.unlink()
        removed += 1
    return removed


def open_folder(
    folder: Path,
    *,
    kind: str | None = None,
    run: Callable[..., object] = subprocess.run,
    startfile: Callable[[str], object] | None = None,
) -> bool:
    """Show ``folder`` in the system's file manager; ``False`` when that did not work."""
    system = kind or default_kind()
    try:
        if system == "windows":
            (startfile or getattr(os, "startfile"))(str(folder))  # noqa: B009 - Windows only
        else:
            command = ["open" if system == "macos" else "xdg-open", str(folder)]
            # Nothing of the opener's own output belongs in our terminal.
            quiet = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            run(command, check=True, timeout=15, **quiet)
    except (OSError, AttributeError, subprocess.SubprocessError):
        return False
    return True
