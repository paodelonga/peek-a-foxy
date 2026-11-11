"""The local log: a small rotating file on this machine, never sent anywhere.

Every run writes what it did (the plan's steps with their durations, the commands it started and
how they ended, warnings, errors with their traceback) so a problem can be understood afterwards,
and so a person asked for "the log" has something to hand over. Three promises:

* Redaction. Whatever reaches a handler goes through :class:`Redactor`: the home folder becomes
  ``~``, the user name and Firefox profile folder names disappear, and tokens in URLs are hidden.
* Logging never breaks a command. If the log cannot be created or written (read-only disk, full
  disk, a locked file) one warning is shown and the command goes on.
* The elevated process (the PowerShell script :data:`peek_a_foxy.elevate.HELPER_SCRIPT`) has no
  part in this: it uses nothing from this package and reports only through its exit code.

Where the file lives (``kind`` is ``windows``, ``macos`` or ``linux``) is decided by pure functions
that take the environment and the home folder as arguments, so every platform is tested anywhere.
"""

from __future__ import annotations

import contextlib
import copy
import getpass
import logging
import logging.handlers
import os
import platform as py_platform
import re
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import cast
from urllib.parse import quote

import peek_a_foxy
from peek_a_foxy import doctor, errors, fileio, platform, ui
from peek_a_foxy.errors import UserFileError

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
    source: str  # "default", "flag", "env", "off-flag", "off-env", "env-unusable" or "no-home"


def expand_user(value: str) -> Path:
    """``value`` as a path with ``~`` expanded; a ``~name`` that cannot be expanded is an error."""
    try:
        return Path(value).expanduser()
    except RuntimeError as error:  # an unknown user, or no home folder to expand ``~`` to
        raise UserFileError(
            errors.FILE_IO,
            f"the path {value!r} starts with ~, which cannot be expanded here",
            hint="Write the full path, or remove the ~ at its start.",
            detail=repr(error),
        ) from error


def _file_for(value: str) -> Path:
    path = expand_user(value)
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
        try:
            return Target(_file_for(env_value.strip()), "env")
        except UserFileError:  # a wrong variable must not stop the command that diagnoses it
            return Target(None, "env-unusable")
    try:
        base_home = Path.home() if home is None else home
    except (RuntimeError, OSError):  # no home folder to put a log in: go without one
        return Target(None, "no-home")
    folder = log_dir(kind or default_kind(), os.environ if environ is None else environ, base_home)
    return Target(Path(str(folder)) / LOG_NAME, "default")


# --- redaction ----------------------------------------------------------------------------------

# Anchored on "://" and bounded: a scheme that is looked for in front of every letter makes a long
# run of letters take time quadratic in its length, and the user and password parts of a real URL
# are short. Nothing before the "://" is needed to hide what follows it.
_URL_CREDENTIALS = re.compile(r"(?P<scheme>://)[^/\s:@]{1,256}(?::[^/\s@]{0,256})?@")
# A secret that is named: ``GITHUB_TOKEN=x``, ``password: x``, ``"api_key": "x"``, ``x-api-key: x``.
# The part of the name before the keyword is not matched (it would have to be looked for at every
# letter); everything after the separator up to a space, quote or ``&`` is hidden. Every repeat is
# bounded.
_NAMED_SECRET = re.compile(
    r"(?i)(?P<name>(?:access[_-]?key|api[_-]?key|private[_-]?key|token|secret|passw(?:or)?d"
    r"|credential)[\w-]{0,40}[\"']?[ \t]{0,8}[:=][ \t]{0,8}[\"']?)[^\s\"'&;,}]+"
)
_BEARER = re.compile(r"(?i)\b(?P<head>bearer[ \t]+)[A-Za-z0-9._~+/=-]{8,}")
_QUERY_SECRET = re.compile(
    r"(?i)\b(?P<name>access_token|token|api[_-]?key|key|secret|password|passwd|auth|sig|signature)"
    r"=[^&\s\"']+"
)
_AUTH_HEADER = re.compile(r"(?i)(?P<head>authorization:\s*(?:bearer|basic|token)\s+)\S+")
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}")
# Firefox names profile folders like ``a1b2c3d4.default-release``. The same shape is a file name of
# eight letters in a stack frame (``autohide.uc.js:12``), which stays readable: the part after the
# dot says it is a script or another file of ours. The JavaScript side (``SCRIPT_SUFFIX`` in
# chrome/resources/peekafoxy.sys.mjs) keeps the same list, and the two must stay equal.
_SCRIPT_SUFFIX = r"(?i:uc\.js|sys\.mjs|m?js|css|json|py|x?html|ini)(?![A-Za-z0-9_-])"
_PROFILE_FOLDER = rf"(?<=[\\/])(?![a-z0-9]{{8}}\.{_SCRIPT_SUFFIX})[a-z0-9]{{8}}\.[^\\/\s'\"]+"
# What this module itself writes in place of a secret. Text that already holds one (the status
# file written by the Firefox script, a report that is redacted twice) must come out unchanged.
_PLACEHOLDER = r"<(?:profile(?: \d+)?|user)>"
# A drive on its own: ``C:``, ``c:/`` or ``\\?\C:\``. Not a home folder, whatever a broken
# environment says: using it as a pattern would blank every ``C:`` in the text.
_DRIVE_ROOT = re.compile(r"(?:\\\\[?.]\\)?[A-Za-z]:")
_SEPARATORS = re.compile(r"[\\/]+")


def _is_root(path: str) -> bool:
    """Whether ``path`` is only a root (a slash, or a drive such as C:), too common as a pattern."""
    bare = path.rstrip("/\\")
    return not path.strip("/\\") or _DRIVE_ROOT.fullmatch(bare) is not None


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


def _real(path: str | None) -> str | None:
    """``path`` with links resolved; ``None`` when that fails or changes nothing."""
    if not path:
        return None
    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError):
        return None
    return resolved if resolved != path else None


def _home_text(home: Path | None) -> str | None:
    """The home folder as text; ``None`` when the system cannot say where it is."""
    if home is not None:
        return str(home)
    try:
        return str(Path.home())
    except (RuntimeError, OSError):
        return None


def _short_name(user: str) -> str | None:
    """The first six letters of ``user`` as Windows writes them in an 8.3 name (before the ``~1``).

    Only a name that Windows has to shorten has one: longer than eight characters, or with a space
    or a dot in it.
    """
    usable = re.sub(r"[^A-Za-z0-9_$%'`@{}!#()&^-]", "", user)[:6]
    needs_short = len(user) > 8 or " " in user or "." in user
    return usable.upper() if needs_short and len(usable) >= 3 else None


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
        # A home that is just "/" or "C:\" would blank out every path.
        homes = {
            c for c in (home, *extra_homes) if c and len(c.strip("/\\")) >= 2 and not _is_root(c)
        }
        scoped = "(?i:{})" if ignore_case else "{}"
        # The things that are replaced by a placeholder are found in ONE pass over the text, so a
        # placeholder that was just written (or was already there) is never matched again: a user
        # named "profile" would otherwise turn "<profile>" into "<<user>>". The first alternative
        # that matches at a position wins, so the order below is the order of precedence.
        self._replacements: dict[str, str] = {"keep": "", "home": "~", "user": "<user>"}
        pieces = [f"(?P<keep>{_PLACEHOLDER})"]
        if homes:
            # The longest goes first, so that a folder inside another is not cut short.
            longest_first = sorted(homes, key=len, reverse=True)
            # Whole path components only: the home ``/home/al`` is not the start of ``/home/alice``,
            # whose name would otherwise be left half visible after the ``~``.
            alternatives = "|".join(_folder_pattern(h.rstrip("/\\")) for h in longest_first)
            # A "%" goes on a name (``ana%20x`` is the folder "ana x"), except as the start of an
            # encoded separator (``%2F``, ``%5C``), which ends it.
            ends = r"(?![\w-]|%(?!2[Ff]|5[Cc]))"
            pieces.append("(?P<home>" + scoped.format(rf"(?<!\w)(?:{alternatives}){ends}") + ")")
        # A profile name chosen by the person may be personal: each becomes ``<profile N>`` (N is
        # its place in profiles.ini, so a report stays readable). Standard names Firefox itself
        # gives, and names too short to tell apart from ordinary words, are kept.
        for number, name in enumerate(profile_names, start=1):
            if len(name) >= 3 and name not in STANDARD_PROFILE_NAMES:
                self._replacements[f"n{number}"] = f"<profile {number}>"
                pieces.append(
                    f"(?P<n{number}>" + scoped.format(rf"(?<!\w){re.escape(name)}(?!\w)") + ")"
                )
        # Short names would also match inside ordinary words, so only distinctive ones are hidden
        # on their own; the home folder (which contains the name) is always hidden.
        if user and len(user) >= 3:
            pieces.append("(?P<user>" + scoped.format(rf"(?<!\w){re.escape(user)}(?!\w)") + ")")
            short = _short_name(user)
            if short:  # Windows also spells a long name as JOHNSM~1, in temporary folders for one
                spelled = rf"(?i:(?<![\w~]){re.escape(short)}~[0-9]{{1,4}}(?![\w~]))"
                pieces.append(f"(?P<short>{spelled})")
                self._replacements["short"] = "<user>"
        self._replacements["folder"] = "<profile>"
        pieces.append(f"(?P<folder>{_PROFILE_FOLDER})")
        self._placeholders = re.compile("|".join(pieces))

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
        # The same folders as the system itself may spell them: with links resolved
        # (``/var/home/jo`` for ``/home/jo``), and (the temporary folder is often spelled that way)
        # by their 8.3 short names.
        for folder in list(homes):
            if (real := _real(folder)) is not None:
                homes.append(real)
            if system == "windows" and short_path:
                with contextlib.suppress(Exception):
                    homes.append(short_path(folder) or "")
        return cls(
            home=main,
            user=user,
            extra_homes=homes,
            # Windows and macOS file systems do not care about case, so a path may be spelled
            # either way in a message.
            ignore_case=system in ("windows", "macos"),
            profile_names=profile_names,
        )

    def _replace(self, found: re.Match[str]) -> str:
        kind = found.lastgroup or "keep"
        return found.group(0) if kind == "keep" else self._replacements[kind]

    def __call__(self, text: str) -> str:
        text = self._placeholders.sub(self._replace, text)
        text = _URL_CREDENTIALS.sub(r"\g<scheme>***@", text)
        text = _AUTH_HEADER.sub(r"\g<head>***", text)
        text = _BEARER.sub(r"\g<head>***", text)
        text = _NAMED_SECRET.sub(r"\g<name>***", text)
        text = _QUERY_SECRET.sub(r"\g<name>=***", text)
        return _GITHUB_TOKEN.sub("***", text)


_RECORD_START = re.compile(r"(?m)^(?=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ )")
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
        # A file name or an error text with a line break in it must not be able to start a line of
        # its own that looks like a record (a forged "run started:"): the message is one line.
        # The record is copied because the console and the file format the same one.
        one_line = copy.copy(record)
        one_line.msg = record.getMessage().replace("\r", "\\r").replace("\n", "\\n")
        one_line.args = None
        head, _, rest = super().format(one_line).partition("\n")
        # Whatever follows (a traceback) is indented where it looks like the start of a record.
        text = head + "\n" + _RECORD_START.sub("  ", rest) if rest else head
        # Escape sequences from a file's content must not reach a terminal when the log is shown.
        return _CONTROL.sub("\ufffd", self._redact(text))


FILE_FORMAT = "%(asctime)sZ %(levelname)-7s %(run_id)s %(message)s"
CONSOLE_FORMAT = "%(levelname)-7s %(message)s"

# --- handlers and the run -----------------------------------------------------------------------


def _append_opener(path: str, flags: int) -> int:
    """Open the log to add lines at its end, whole, even while another run adds its own."""
    if sys.platform == "win32":  # pragma: no cover - Windows only
        from peek_a_foxy._winapi import open_for_appending

        return open_for_appending(path)
    # O_APPEND already writes at the end in one step here. Readable by this account only: the
    # text is redacted but still describes this machine.
    return os.open(path, flags, 0o600)


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
    redact: Callable[[str], str] | None = None  # the redaction that the records go through


_session: Session | None = None


def redact_text(text: str) -> str:
    """``text`` as the log would write it: the same redaction, for what is printed to the terminal.

    A person who is asked to re-run a command with ``--verbose`` pastes what the terminal shows, so
    that must hide the user name and the home folder just as the log does.
    """
    redactor = _session.redact if _session and _session.redact else Redactor.for_this_machine()
    return _CONTROL.sub("\ufffd", redactor(text))


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
    unusable = unusable_reason(target) if target is not None else None
    if unusable and warn:
        warn(f"could not write the log file ({unusable}); going on without it")
    if target is not None and not unusable:
        try:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)  # private, if it is new
            handler = _SafeFileHandler(target, warn_once)
            handler.setFormatter(_Formatter(FILE_FORMAT, redact, run))
            logger.addHandler(handler)
            path = target
        except OSError as error:
            if warn:
                warn(f"could not write the log file ({error}); going on without it")
    if verbose:
        console = ui.QuietStreamHandler(sys.stderr)
        console.setFormatter(_Formatter(CONSOLE_FORMAT, redact, run))
        logger.addHandler(console)

    global _session
    _session = Session(run, path, time.monotonic(), verbose, redact)
    how = doctor.how_it_runs(bool(getattr(sys, "frozen", False)), peek_a_foxy.__file__)
    logger.info(
        "%s peek-a-foxy %s, %s, Python %s, %s %s, args: %s",
        RUN_MARKER,
        version,
        how,
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


_RECORD = re.compile(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ [A-Z]+ +\S+ ")
_RUN_LINE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ INFO +\S+ " + re.escape(RUN_MARKER))


def unusable_reason(path: Path) -> str | None:
    """Why ``path`` must not be written as a log, or ``None`` when it may be.

    A path that names anything but a log (a settings file, a device, a named pipe) is refused: a
    wrong ``PEEK_A_FOXY_LOG`` or ``--log-file`` would add text to it, and opening a named pipe
    waits for a reader for good.
    """
    try:
        found = os.stat(path)
    except OSError:  # missing (the usual case) or not reachable: opening it will say which
        return None
    if not stat.S_ISREG(found.st_mode):
        return f"{path} is not a regular file"
    if found.st_size and not looks_like_log(path):
        return f"{path} already exists and is not a log of Peek-a-Foxy"
    return None


def looks_like_log(path: Path) -> bool:
    """Whether the first line of the file is a record as :data:`FILE_FORMAT` writes it."""
    try:
        return _RECORD.match(fileio.read_regular(path, 200)) is not None
    except OSError:
        return False


def log_files(path: Path) -> list[Path]:
    """The log file and its rotated copies that exist, newest first.

    Only files that are logs: a file that has the name but other contents is not one.
    """
    names = [path, *(path.with_name(f"{path.name}.{n}") for n in range(1, BACKUP_COUNT + 1))]
    return [
        candidate
        for candidate in names
        if candidate.is_file() and (candidate.stat().st_size == 0 or looks_like_log(candidate))
    ]


def last_run(path: Path) -> list[str]:
    """The lines of the most recent run in the newest file, redacted when written; may be empty."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for index in range(len(lines) - 1, -1, -1):
        if _RUN_LINE.match(lines[index]):
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
