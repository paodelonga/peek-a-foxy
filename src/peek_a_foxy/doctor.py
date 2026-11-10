"""``peek-a-foxy doctor``: look at this computer and say, in plain words, what is in the way.

Read-only as far as your files go: nothing here changes or deletes them, and the only program that
is run is ``git --version``. The one thing written is the local log (see :mod:`peek_a_foxy.logs`),
unless it is turned off. The result is a
:class:`~peek_a_foxy.report.Report` of checks in four groups:

* Program: version, how it runs, Python, system, rights, terminal, git, the pinned loader, the log.
* Firefox installs: every install found (not only the first): version, whether the folder can be
  written, sandboxed builds, the loader files against the pinned SHA-256, other autoconfig setups.
* Profiles: the profiles of ``profiles.ini`` and, for the selected ones, our files, the stylesheet
  ``@import``, the prefs Firefox needs, the startup cache and what the script itself reported.

Everything that touches the machine goes through :class:`Context`, so tests (and Linux CI) can fake
a Windows registry, an administrator, an MSIX folder or a missing clipboard. A check that fails to
run becomes a warning with the unexpected-error code; the doctor never crashes.
"""

from __future__ import annotations

import codecs
import configparser
import hashlib
import itertools
import logging
import os
import platform as py_platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from peek_a_foxy import (
    __version__,
    assets,
    elevate,
    errors,
    fileio,
    loader,
    platform,
    ui,
    userfiles,
)
from peek_a_foxy.errors import DiscoveryError, ErrorCode, PeekError
from peek_a_foxy.profiles import Profile, read_profiles
from peek_a_foxy.report import FAIL, OK, WARN, Check, Report, Section
from peek_a_foxy.status import STATUS_FILE, Status, StatusError, read_status

log = logging.getLogger(__name__)

GIT_TIMEOUT = 15  # seconds `git --version` gets before the doctor goes on without it
MAX_TEXT = 16 * 1024 * 1024  # a user.js, prefs.js or userChrome.css bigger than this is not read
MAX_FILE = 2 * 1024 * 1024  # nor is a loader or Peek-a-Foxy file: ours are a few hundred KB at most
MAX_PROFILES_LISTED = 50
MAX_PROFILES_CHECKED = 10
DAY = 86400
MAX_SHOWN = 200  # characters of a text that came out of a file (a status message, a note)
NEEDED_LOADER_FILES = loader.LOADER_FILES
AUTOCONFIG_PREF = "general.config.filename"
OUR_PREF_FILE = "config-prefs.js"
OUR_CONFIG = "config.js"


# --- the machine, behind seams --------------------------------------------------------------


def _home() -> Path:
    """The home folder; when the system cannot say, ``~``, which matches nothing."""
    try:
        return Path.home()
    except (RuntimeError, OSError):
        return Path("~")


def _default_is_admin(kind: str) -> Callable[[], bool]:
    if kind == "windows":
        return elevate.is_admin
    return lambda: hasattr(os, "geteuid") and os.geteuid() == 0


def _default_can_write(path: Path) -> bool:
    return os.access(path, os.W_OK)


def _run_git(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT,
    )
    return result.stdout.strip()[:200]


@dataclass
class Context:
    """Everything the doctor learns from the machine; each part can be replaced in a test."""

    kind: str  # "windows", "macos" or "linux"
    unsupported: str | None  # sys.platform when the system is not one we handle
    home: Path
    environ: Mapping[str, str]
    version: str
    python: str
    os_description: str
    machine: str
    frozen: bool
    module_file: str
    executable: str
    is_admin: Callable[[], bool]
    can_write: Callable[[Path], bool]
    run_command: Callable[[list[str]], str]  # runs a command and returns its output
    which: Callable[[str], str | None]
    firefox_candidates: Callable[[], list[Path]]
    profiles_root: Callable[[], Path]
    assets_dir: Callable[[], Path]
    encoding: str
    is_tty: bool
    log_target: Path | None
    now: Callable[[], datetime]

    @classmethod
    def detect(cls, *, log_target: Path | None) -> Context:
        unsupported: str | None = None
        try:
            kind = platform.system()
        except PeekError:
            kind, unsupported = "linux", sys.platform
        return cls(
            kind=kind,
            unsupported=unsupported,
            home=_home(),
            environ=os.environ,
            version=__version__,
            python=f"{py_platform.python_version()} ({py_platform.python_implementation()})",
            os_description=py_platform.platform(),
            machine=py_platform.machine(),
            frozen=bool(getattr(sys, "frozen", False)),
            module_file=__file__,
            executable=sys.executable,
            is_admin=_default_is_admin(kind),
            can_write=_default_can_write,
            run_command=_run_git,
            which=shutil.which,
            firefox_candidates=platform.firefox_dir_candidates,
            profiles_root=platform.profiles_root,
            assets_dir=assets.assets_dir,
            encoding=ui.console.encoding or "unknown",
            is_tty=sys.stdout is not None and sys.stdout.isatty(),
            log_target=log_target,
            now=lambda: datetime.now(timezone.utc),
        )


# --- building checks ---------------------------------------------------------------------------


def _ok(id: str, title: str, value: str, detail: str = "") -> Check:
    return Check(id, title, OK, value, detail=detail)


def _bad(
    id: str,
    title: str,
    status: str,
    code: ErrorCode,
    message: str,
    *,
    value: str = "",
    hint: str | None = None,
    detail: str = "",
) -> Check:
    return Check(id, title, status, value, message, hint or code.hint, code.code, detail)


def _guarded(id: str, title: str, make: Callable[[], Check | list[Check]]) -> list[Check]:
    """Run one check; whatever it raises becomes a warning, so one bug never hides the rest."""
    try:
        result = make()
    except Exception as error:
        log.error("check %s could not run", id, exc_info=error)
        return [
            _bad(
                id,
                title,
                WARN,
                errors.UNEXPECTED,
                "This check could not run because of a bug in Peek-a-Foxy.",
                detail=errors.clip(f"{type(error).__name__}: {error}"),
            )
        ]
    return result if isinstance(result, list) else [result]


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except (OSError, ValueError):  # permission denied, a symbolic link loop, a NUL byte...
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except (OSError, ValueError):
        return False


def _entries(path: Path, pattern: str = "*") -> list[Path]:
    """The first entries of a folder that match, or none if it cannot be listed."""
    try:
        return sorted(itertools.islice(path.glob(pattern), 1000))
    except (OSError, ValueError):
        return []


def _short(text: str, limit: int = MAX_SHOWN) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _read_bytes(path: Path, limit: int = MAX_FILE) -> bytes | None:
    """The bytes of a file; ``None`` if it cannot be read or is far bigger than it should be."""
    try:
        data = fileio.read_regular(path, limit)
    except (OSError, ValueError):
        return None
    return data if len(data) <= limit else None


def _read_text(path: Path) -> tuple[str | None, str]:
    """The text of a file, or ``None`` and why not (a missing file is not a problem here)."""
    try:
        data = fileio.read_regular(path, MAX_TEXT)
    except (FileNotFoundError, NotADirectoryError):
        return None, ""
    except IsADirectoryError:
        return None, "it is a folder"
    except fileio.NotARegularFileError as error:
        return None, error.strerror or "it is not a regular file"
    except (OSError, ValueError) as error:
        return None, getattr(error, "strerror", None) or type(error).__name__
    if len(data) > MAX_TEXT:
        return (
            None,
            f"it is bigger than {MAX_TEXT // (1024 * 1024)} MB, which no genuine file of this "
            "kind is",
        )
    return data.decode("utf-8-sig", errors="replace"), ""


def _unix(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


# --- Program -----------------------------------------------------------------------------------


def how_it_runs(frozen: bool, module_file: str) -> str:
    """How this copy of the program was installed, guessed from where its code lives."""
    if frozen:
        return "standalone program (no Python needed)"
    path = Path(module_file)
    text = f"/{module_file.replace(chr(92), '/').lower()}/"
    if "/pipx/" in text:
        return "installed with pipx"
    if "/uv/tools/" in text:
        return "installed with uv tool"
    try:
        if _is_file(path.resolve().parents[2] / "pyproject.toml"):
            return "source checkout (not installed)"
    except (IndexError, OSError, RuntimeError):
        pass
    if "/site-packages/" in text or "/dist-packages/" in text:
        return "installed with pip"
    return "unknown"


def _program_checks(ctx: Context) -> list[Check]:
    checks: list[Check] = []
    checks.append(_ok("program.version", "Peek-a-Foxy version", ctx.version))
    checks += _guarded(
        "program.runs",
        "How it runs",
        lambda: _ok(
            "program.runs",
            "How it runs",
            how_it_runs(ctx.frozen, ctx.module_file),
            detail=f"module {ctx.module_file}",
        ),
    )
    checks.append(
        _ok("program.python", "Python", ctx.python, detail=f"executable {ctx.executable}")
    )
    if ctx.unsupported:
        checks.append(
            _bad(
                "program.os",
                "System",
                FAIL,
                errors.UNSUPPORTED_OS,
                f"{ctx.unsupported} is not Linux, macOS or Windows, which are the only systems "
                "that Peek-a-Foxy supports.",
                value=f"{ctx.os_description}, {ctx.machine}",
            )
        )
    else:
        checks.append(_ok("program.os", "System", f"{ctx.os_description}, {ctx.machine}"))
    checks += _guarded("program.admin", "Administrator rights", lambda: _admin_check(ctx))
    checks += _guarded("program.terminal", "Terminal", lambda: _terminal_check(ctx))
    checks += _guarded("program.git", "git", lambda: _git_check(ctx))
    checks += _guarded("program.loader_pin", "Pinned loader (fx-autoconfig)", lambda: _pin(ctx))
    checks += _guarded("program.assets", "Bundled Firefox files", lambda: _assets_check(ctx))
    checks += _guarded("program.log", "Log file", lambda: _log_check(ctx))
    return checks


def _admin_check(ctx: Context) -> Check:
    admin = ctx.is_admin()
    if admin:
        who = "root" if ctx.kind != "windows" else "an administrator"
        return _ok("program.admin", "Administrator rights", f"yes, running as {who}")
    return _ok("program.admin", "Administrator rights", "no (normal user)")


def _terminal_check(ctx: Context) -> Check:
    term = ctx.environ.get("TERM", "")
    value = f"{'interactive' if ctx.is_tty else 'not interactive'}, encoding {ctx.encoding}"
    if term:
        value += f", TERM={term}"
    try:
        utf = codecs.lookup(ctx.encoding).name.startswith("utf")
    except LookupError:
        utf = False
    if utf:
        return _ok("program.terminal", "Terminal", value)
    return _bad(
        "program.terminal",
        "Terminal",
        WARN,
        errors.CONSOLE_ENCODING,
        f"The terminal uses the {ctx.encoding} encoding instead of UTF-8, so some characters "
        "may be shown incorrectly.",
        value=value,
    )


def _git_check(ctx: Context) -> Check:
    if ctx.which("git") is None:
        return _bad(
            "program.git",
            "git",
            WARN,
            errors.GIT_MISSING,
            "git is not installed on this computer; only the `install` command needs it, in order "
            "to download the loader.",
        )
    try:
        text = ctx.run_command(["git", "--version"])
    except (OSError, subprocess.SubprocessError):
        return _bad(
            "program.git",
            "git",
            WARN,
            errors.GIT_MISSING,
            "git is installed but could not be run; only the `install` command needs it.",
        )
    return _ok("program.git", "git", text.removeprefix("git version ").strip() or "found")


def _pin(ctx: Context) -> Check:
    commit = ctx.environ.get("FXAC_COMMIT")
    repo = ctx.environ.get("FXAC_REPO")
    title = "Pinned loader (fx-autoconfig)"
    if commit is not None and not loader.is_commit_hash(commit):
        # What `install` does with it, an empty value included: it refuses before any download.
        return _bad(
            "program.loader_pin",
            title,
            WARN,
            errors.BAD_PINNED_COMMIT,
            errors.BAD_PINNED_COMMIT.meaning,
            value=_short(commit),
        )
    if commit or repo:
        # Only Windows copies the loader through the administrator step (305); elsewhere the
        # same refusal belongs to the copy with sudo (207).
        code = errors.UAC_ENV_OVERRIDE if ctx.kind == "windows" else errors.LOADER_UNVERIFIED
        return _bad(
            "program.loader_pin",
            title,
            WARN,
            code,
            "The FXAC_REPO or FXAC_COMMIT environment variable is set, so the loader would not be "
            "downloaded from the usual place.",
            value=commit or loader.DEFAULT_COMMIT,
        )
    return _ok("program.loader_pin", title, f"commit {loader.DEFAULT_COMMIT}")


def _assets_check(ctx: Context) -> Check:
    try:
        folder = ctx.assets_dir()
    except PeekError as error:
        return _bad(
            "program.assets",
            "Bundled Firefox files",
            FAIL,
            error.code,
            f"{error.message}.",
            hint=error.hint,
        )
    missing = [name for name in assets.FILES if not _is_file(folder / name)]
    if missing:
        return _bad(
            "program.assets",
            "Bundled Firefox files",
            FAIL,
            errors.FILES_MISSING,
            f"These files are missing from this copy of Peek-a-Foxy: {', '.join(missing)}.",
        )
    return _ok("program.assets", "Bundled Firefox files", f"all {len(assets.FILES)} found")


def _log_check(ctx: Context) -> Check:
    target = ctx.log_target
    if target is None:
        return _ok("program.log", "Log file", "turned off")
    folder = target.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    if not ctx.can_write(folder):
        return _bad(
            "program.log",
            "Log file",
            WARN,
            errors.FILE_IO,
            "The folder for the log file cannot be written to, so no log is kept.",
            value=str(target),
        )
    return _ok("program.log", "Log file", str(target))


# --- Firefox installs --------------------------------------------------------------------------

UNUSABLE = ("firefox.sandbox", "firefox.loader")  # a FAIL here means this install cannot work
_FILENAME_PREF = re.compile(
    r"""pref\(\s*["']general\.config\.filename["']\s*,\s*["']([^"']+)["']\s*\)"""
)
# [ \t], not \s: \s also matches newlines, and a file of empty lines would make this quadratic.
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)
MAX_LINE = 4000  # a pref line longer than this is not one Firefox wrote


def strip_comments(text: str) -> str:
    """``text`` without ``/* ... */`` comments (an unclosed one runs to the end), in linear time.

    A regular expression for this backtracks without end on a file made of ``/*`` repeated.
    """
    parts: list[str] = []
    position = 0
    while True:
        start = text.find("/*", position)
        if start < 0:
            parts.append(text[position:])
            return "".join(parts)
        parts.append(text[position:start])
        end = text.find("*/", start + 2)
        if end < 0:
            return "".join(parts)
        position = end + 2


def read_application_ini(folder: Path) -> dict[str, str]:
    """``[App]`` of Firefox's ``application.ini``; raises ``OSError`` or ``ValueError``."""
    text, problem = _read_text(folder / "application.ini")
    if text is None:
        if problem:
            raise OSError(problem)
        raise FileNotFoundError("application.ini")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise ValueError(str(error)) from error
    if not parser.has_section("App"):
        raise ValueError("no [App] section")
    return dict(parser["App"])


def guess_channel(folder: Path, version: str) -> str:
    """The update channel, from ``channel-prefs.js`` or else from the shape of the version."""
    text, _ = _read_text(folder / "defaults" / "pref" / "channel-prefs.js")
    match = re.search(r"""app\.update\.channel["']\s*,\s*["']([^"']+)""", text or "")
    if match:
        return match.group(1)
    if re.search(r"a\d+$", version):
        return "nightly"
    if re.search(r"b\d+$", version):
        return "beta or developer edition"
    return "unknown"


def autoconfig_pointers(folder: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Files of ``defaults/pref`` that set ``general.config.filename``, and ``*.cfg`` files.

    Ours (``config-prefs.js`` pointing at ``config.js``) is left out of the first list.
    """
    foreign: list[tuple[str, str]] = []
    pref_dir = folder / "defaults" / "pref"
    if _is_dir(pref_dir):
        for path in _entries(pref_dir, "*.js"):
            text, _ = _read_text(path)
            if text is None:
                continue
            text = _LINE_COMMENT.sub("", strip_comments(text))
            match = _FILENAME_PREF.search(text)
            if match and not (path.name == OUR_PREF_FILE and match.group(1) == OUR_CONFIG):
                foreign.append((path.name, match.group(1)))
    cfgs = sorted(path.name for path in _entries(folder, "*.cfg") if _is_file(path))
    return foreign, cfgs


def _version_check(folder: Path) -> Check:
    id, title = "firefox.version", "Version"
    try:
        info = read_application_ini(folder)
    except (OSError, ValueError) as error:
        return _bad(
            id,
            title,
            WARN,
            errors.FIREFOX_INFO_UNREADABLE,
            "Firefox's application.ini file could not be read, so the version of this Firefox is "
            "unknown.",
            detail=f"{type(error).__name__}: {error}",
        )
    version = info.get("version", "")
    build = info.get("buildid", "")
    channel = guess_channel(folder, version)
    name = info.get("name", "Firefox")
    return _ok(id, title, f"{name} {version or '?'} (build {build or '?'}, channel {channel})")


def _writable_check(ctx: Context, folder: Path) -> Check:
    protected = False
    if ctx.kind == "windows" and not ctx.is_admin():
        text = str(folder).replace("\\", "/").lower()
        bases = [
            ctx.environ.get(v, "") for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
        ]
        protected = any(b and text.startswith(b.replace("\\", "/").lower()) for b in bases)
    can = ctx.can_write(folder) and not protected
    if can:
        return _ok("firefox.writable", "Folder can be changed by you", "yes")
    how = "an administrator prompt" if ctx.kind == "windows" else "sudo"
    return _ok(
        "firefox.writable",
        "Folder can be changed by you",
        f"no (this is normal for this folder; `install` uses {how} to copy the loader)",
    )


def _sandbox_check(folder: Path) -> Check:
    kind = platform.sandbox_kind(folder)
    if kind is None:
        return _ok("firefox.sandbox", "Snap, Flatpak or Microsoft Store build", "no")
    return _bad(
        "firefox.sandbox",
        "Snap, Flatpak or Microsoft Store build",
        FAIL,
        errors.FIREFOX_SANDBOXED,
        f"This is a {kind} build of Firefox, which cannot be modified, so the loader cannot "
        "be installed in it.",
        value=kind,
    )


def _loader_check(folder: Path) -> Check:
    id, title = "firefox.loader", "Loader files (fx-autoconfig)"
    missing: list[str] = []
    different: list[str] = []
    unreadable: list[str] = []
    notes: list[str] = []
    for name in NEEDED_LOADER_FILES:
        path = folder / name
        if not _is_file(path):
            missing.append(name)
            continue
        data = _read_bytes(path)
        if data is None:
            unreadable.append(name)
            continue
        if _sha256(_unix(data)) != elevate.PINNED_SHA256[name]:
            different.append(name)
            notes.append(f"{name} sha256 {_sha256(_unix(data))[:16]}")
        elif b"\r\n" in data:
            notes.append(f"{name} has Windows (CRLF) line endings; same content")
    detail = "; ".join(notes)
    if missing:
        return _bad(
            id,
            title,
            FAIL,
            errors.LOADER_MISSING,
            f"These loader files are missing from the Firefox folder: {', '.join(missing)}. "
            "Firefox cannot run the script without them.",
            detail=detail,
        )
    if unreadable:
        return _bad(
            id,
            title,
            WARN,
            errors.FILE_IO,
            f"These loader files could not be read: {', '.join(unreadable)}.",
            detail=detail,
        )
    if different:
        return _bad(
            id,
            title,
            WARN,
            errors.LOADER_DIFFERENT,
            f"These loader files are not the version that Peek-a-Foxy installs: "
            f"{', '.join(different)}. They may still work.",
            detail=detail,
        )
    return _ok(
        id,
        title,
        f"present and identical to the pinned version ({len(NEEDED_LOADER_FILES)} files)",
        detail,
    )


def _autoconfig_check(folder: Path) -> Check:
    id, title = "firefox.autoconfig", "Other autoconfig setups"
    foreign, cfgs = autoconfig_pointers(folder)
    if foreign:
        listed = ", ".join(f"defaults/pref/{name} (points to {target})" for name, target in foreign)
        return _bad(
            id,
            title,
            WARN,
            errors.AUTOCONFIG_FOREIGN,
            f"Firefox is also configured to load another config file: {listed}. Firefox reads "
            "only one of them, and depending on the order of the files it may not be the one "
            "from Peek-a-Foxy.",
            detail=f"cfg files beside Firefox: {', '.join(cfgs)}" if cfgs else "",
        )
    if cfgs:
        return _ok(id, title, f"none active; unused file(s) beside Firefox: {', '.join(cfgs)}")
    return _ok(id, title, "none")


def _policies_check(folder: Path) -> Check:
    present = _is_file(folder / "distribution" / "policies.json")
    return _ok(
        "firefox.policies",
        "distribution/policies.json",
        "present (an administrator manages some Firefox settings)" if present else "not present",
    )


def _install_section(ctx: Context, n: int, folder: Path) -> Section:
    checks = [_ok("firefox.path", "Folder", str(folder))]
    checks += _guarded("firefox.version", "Version", lambda: _version_check(folder))
    checks += _guarded(
        "firefox.writable", "Folder can be changed by you", lambda: _writable_check(ctx, folder)
    )
    checks += _guarded(
        "firefox.sandbox", "Snap, Flatpak or Microsoft Store build", lambda: _sandbox_check(folder)
    )
    checks += _guarded(
        "firefox.loader", "Loader files (fx-autoconfig)", lambda: _loader_check(folder)
    )
    checks += _guarded(
        "firefox.autoconfig", "Other autoconfig setups", lambda: _autoconfig_check(folder)
    )
    checks += _guarded(
        "firefox.policies", "distribution/policies.json", lambda: _policies_check(folder)
    )
    return Section(f"firefox.{n}", f"Firefox install {n}", tuple(checks))


def _soften(sections: list[Section]) -> list[Section]:
    """A broken install is only a warning when another one on this computer can work."""
    usable = [
        s for s in sections if not any(c.id in UNUSABLE and c.status == FAIL for c in s.checks)
    ]
    if not usable or len(usable) == len(sections):
        return sections
    softened = []
    for section in sections:
        checks = tuple(
            Check(
                c.id,
                c.title,
                WARN,
                c.value,
                f"{c.message} Another Firefox on this computer works, so this is only a warning.",
                c.hint,
                c.code,
                c.detail,
            )
            if c.id in UNUSABLE and c.status == FAIL
            else c
            for c in section.checks
        )
        softened.append(Section(section.id, section.title, checks))
    return softened


def _firefox_sections(ctx: Context, firefox_dir: Path | None) -> list[Section]:
    folders: list[Path] = []
    if firefox_dir is not None:
        folders = [firefox_dir]
    else:
        try:
            folders = ctx.firefox_candidates()
        except PeekError as error:
            log.warning("could not look for Firefox: %s", error.message)
    if not folders:
        missing = _bad(
            "firefox.found",
            "Firefox install folder",
            FAIL,
            errors.FIREFOX_NOT_FOUND,
            "No Firefox install folder was found in the usual places.",
        )
        return [Section("firefox", "Firefox installs", (missing,))]
    return _soften([_install_section(ctx, n, folder) for n, folder in enumerate(folders, start=1)])


# --- Profiles ----------------------------------------------------------------------------------

_PREF_LINE = re.compile(r"""^\s*user_pref\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(.*?)\s*\)\s*;""")
OWN_PREFIX = "peekafoxy."


def parse_prefs(text: str) -> dict[str, str]:
    """``user_pref("name", value);`` lines of ``user.js`` or ``prefs.js`` as name to raw value."""
    found: dict[str, str] = {}
    # Comments are skipped as Firefox skips them; lines end at "\n" only, as in userfiles, because
    # splitlines() would also break at U+2028, \x0b and \x1c and read other lines than Firefox does.
    for line in userfiles.mask_comments(text, line_comments=True).split("\n"):
        if len(line) > MAX_LINE:
            continue
        match = _PREF_LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2)  # the last one wins, as in Firefox
    return found


def import_state(css: str) -> str:
    """``ok``, ``late`` (below other rules, so ignored), ``legacy`` (old name) or ``missing``."""
    text = strip_comments(css)
    seen_rule = False
    legacy = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == userfiles.CSS_IMPORT:
            return "late" if seen_rule else "ok"
        if line == userfiles.LEGACY_CSS_IMPORT:
            legacy = legacy or not seen_rule
        elif not line.startswith(("@import", "@charset")):
            seen_rule = True
    return "legacy" if legacy else "missing"


def _profile_label(profiles: list[Profile], path: Path) -> str:
    """``<profile N>`` (N: its place in profiles.ini): the name chosen for a profile may be
    personal, so a report never shows it."""
    for number, profile in enumerate(profiles, start=1):
        if _same(profile.path, path):
            return f"<profile {number}>"
    return "given with --profile"


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError):
        return False


def _installed_files(chrome: Path) -> list[Path]:
    return [chrome / name for name in assets.FILES if _is_file(chrome / name)]


def _files_check(ctx: Context, chrome: Path, bundled: Path | None) -> Check:
    id, title = "profile.files", "Peek-a-Foxy files"
    missing = [name for name in assets.FILES if not _is_file(chrome / name)]
    if missing:
        return _bad(
            id,
            title,
            FAIL,
            errors.PROFILE_FILES_MISSING,
            f"These files are missing from the profile's chrome folder: {', '.join(missing)}.",
        )
    if bundled is None:
        return _ok(id, title, f"all {len(assets.FILES)} present (not compared: see bundled files)")
    different: list[str] = []
    notes: list[str] = []
    for name in assets.FILES:
        ours, theirs = _read_bytes(bundled / name), _read_bytes(chrome / name)
        if ours is None or theirs is None:
            different.append(name)
            notes.append(f"{name} could not be read, or it is far bigger than expected")
        elif ours != theirs:
            if _unix(ours) == _unix(theirs):
                notes.append(f"{name}: only the line endings differ")
            else:
                different.append(name)
                notes.append(
                    f"{name}: sha256 {_sha256(theirs)[:16]}, expected {_sha256(ours)[:16]}"
                )
    if different:
        return _bad(
            id,
            title,
            WARN,
            errors.PROFILE_FILES_DIFFERENT,
            f"These files are not the ones that came with this version: {', '.join(different)}.",
            detail="; ".join(notes),
        )
    return _ok(
        id,
        title,
        f"all {len(assets.FILES)} present and identical to this version",
        "; ".join(notes),
    )


def _utils_check(chrome: Path) -> Check:
    folder = chrome / "utils"
    if _is_dir(folder) and _entries(folder):
        return _ok("profile.utils", "chrome/utils (the loader's helpers)", "present")
    return _bad(
        "profile.utils",
        "chrome/utils (the loader's helpers)",
        FAIL,
        errors.UTILS_MISSING,
        "The chrome/utils folder is missing or empty, and the loader needs it.",
    )


def _import_check(chrome: Path) -> Check:
    id, title = "profile.import", "userChrome.css loads our stylesheet"
    text, problem = _read_text(chrome / "userChrome.css")
    if problem:
        return _bad(
            id,
            title,
            WARN,
            errors.FILE_IO,
            f"The file userChrome.css could not be read ({problem}).",
        )
    if text is None:
        return _bad(
            id, title, FAIL, errors.CSS_IMPORT_MISSING, "The file userChrome.css does not exist."
        )
    state = import_state(text)
    if state == "ok":
        return _ok(id, title, f"yes ({userfiles.CSS_IMPORT})")
    if state == "late":
        return _bad(
            id, title, FAIL, errors.CSS_IMPORT_LATE, "The @import line is placed below other rules."
        )
    message = "The file userChrome.css does not contain the @import line."
    if state == "legacy":
        message = (
            "The file userChrome.css contains the @import line only under its old name "
            "(tabs-autohide.css)."
        )
    return _bad(id, title, FAIL, errors.CSS_IMPORT_MISSING, message)


def _pref_check(
    id: str,
    title: str,
    name: str,
    user: dict[str, str] | None,
    prefs: dict[str, str] | None,
    *,
    needed: bool,
) -> Check:
    """A pref Firefox needs: ``user.js`` is read at every start and wins over ``prefs.js``."""
    from_user = (user or {}).get(name)
    from_prefs = (prefs or {}).get(name)
    if from_user == "true":
        return _ok(id, title, "true (user.js)")
    if from_user is None and from_prefs == "true":
        return _ok(id, title, "true (prefs.js only: it lasts until it is reset)")
    state = (
        f"{from_user} in user.js"
        if from_user is not None
        else f"{from_prefs} in prefs.js"
        if from_prefs is not None
        else "not set"
    )
    return _bad(
        id,
        title,
        FAIL if needed else WARN,
        errors.PREFS_MISSING,
        f"The setting {name} is {state}, and Firefox needs it to be true.",
    )


def _own_prefs_check(user: dict[str, str] | None, prefs: dict[str, str] | None) -> Check:
    id, title = "profile.own_prefs", "Peek-a-Foxy settings found"
    from_prefs = {k: v for k, v in (prefs or {}).items() if k.startswith(OWN_PREFIX)}
    from_user = sorted(k for k in (user or {}) if k.startswith(OWN_PREFIX))
    parts = [f"{k}={v}" for k, v in sorted(from_prefs.items())]
    value = ", ".join(parts) if parts else "none in prefs.js (the defaults are used)"
    if from_user:
        value += f"; also in user.js (reset at every start): {', '.join(from_user)}"
    return _ok(id, title, value)


def cache_dirs(kind: str, environ: Mapping[str, str], home: Path, profile: Path) -> list[Path]:
    """Where Firefox keeps the startup cache of ``profile`` (it is not inside the profile)."""
    name = profile.name
    if kind == "windows":
        base = environ.get("LOCALAPPDATA")
        local = Path(base) if base else home / "AppData" / "Local"
        return [local / "Mozilla" / "Firefox" / "Profiles" / name / "startupCache"]
    if kind == "macos":
        return [home / "Library" / "Caches" / "Firefox" / "Profiles" / name / "startupCache"]
    xdg = environ.get("XDG_CACHE_HOME")
    bases = ([Path(xdg)] if xdg and xdg.startswith("/") else []) + [home / ".cache"]
    return [base / "mozilla" / "firefox" / name / "startupCache" for base in bases]


def _newest(paths: list[Path]) -> float | None:
    times = []
    for path in paths:
        try:
            times.append(path.stat().st_mtime)
        except (OSError, ValueError):
            continue
    return max(times) if times else None


def _cache_check(ctx: Context, profile: Path, chrome: Path, script_ran: bool) -> Check:
    id, title = "profile.startup_cache", "Firefox's startup cache"
    ours = _newest(_installed_files(chrome))
    cached: float | None = None
    for folder in cache_dirs(ctx.kind, ctx.environ, ctx.home, profile):
        if _is_dir(folder):
            cached = _newest([p for p in _entries(folder) if _is_file(p)])
            if cached is not None:
                break
    if cached is None or ours is None:
        return _ok(id, title, "no cache found (Firefox builds one when it starts)")
    if cached < ours and not script_ran:
        return _bad(
            id,
            title,
            WARN,
            errors.STARTUP_CACHE,
            "The startup cache is older than the installed files, and Firefox has not reported "
            "back since the installation.",
        )
    return _ok(id, title, "not older than the installed files, or Firefox has reported since")


def _status_checks(ctx: Context, chrome: Path) -> tuple[list[Check], bool]:
    """The checks of what the script reported; and whether it ran since the files were put."""
    try:
        status = read_status(chrome)
    except StatusError as error:
        return [
            _bad(
                "status.file",
                "Status written by Firefox",
                WARN,
                errors.STATUS_UNUSABLE,
                f"The status file {STATUS_FILE} cannot be used: {error}.",
            )
        ], False
    if status is None:
        return [
            _bad(
                "status.file",
                "Status written by Firefox",
                WARN,
                errors.STATUS_MISSING,
                "Firefox has not run the script yet; close all of its windows and start Firefox "
                "again.",
            )
        ], False
    now = ctx.now().timestamp()
    ours = _newest(_installed_files(chrome))
    if ours is not None and ours > now + DAY:
        ours = None  # files dated in the future (a clock that went backwards) prove nothing
    stamp = status.updated.strftime("%Y-%m-%d %H:%M UTC")
    if status.updated.timestamp() > now + DAY:
        return [
            _bad(
                "status.file",
                "Status written by Firefox",
                WARN,
                errors.STATUS_UNUSABLE,
                f"The status file says it was written on {stamp}, which is in the future, so the "
                "clock of this computer may be wrong.",
                hint="Check the date and time of this computer, start Firefox again and run "
                "`peek-a-foxy doctor` once more.",
            )
        ], False
    if ours is not None and status.updated.timestamp() < ours - 2:
        return [
            _bad(
                "status.file",
                "Status written by Firefox",
                WARN,
                errors.STATUS_UNUSABLE,
                f"Firefox last reported on {stamp}, which is before the files were last installed, "
                "so it has not been restarted since.",
                hint="Close all Firefox windows, start Firefox and then run `peek-a-foxy doctor` "
                "again.",
            )
        ], False
    return _live_status_checks(status, stamp), True


def _live_status_checks(status: Status, stamp: str) -> list[Check]:
    windows = "?" if status.windows is None else str(status.windows)
    checks = [
        _ok(
            "status.file", "Status written by Firefox", f"last update {stamp}, {windows} window(s)"
        ),
        _ok(
            "status.script",
            "Script and Firefox as the script saw them",
            f"script {_short(status.script_version, 40) or '?'}, "
            f"Firefox {_short(status.firefox_version, 40) or '?'} "
            f"(build {_short(status.build_id, 40) or '?'}, "
            f"{_short(status.channel, 40) or 'unknown'}), "
            f"{_short(status.os, 40) or '?'}, {_short(status.locale, 40) or '?'}",
        ),
    ]
    failed = status.failed()
    if failed:
        listed = "; ".join(
            f"{_short(name, 60)}: {_short(note, 100) or 'failed'}" for name, note in failed[:5]
        )
        if len(failed) > 5:
            listed += f"; and {len(failed) - 5} more"
        checks.append(
            _bad(
                "status.health",
                "Script health inside Firefox",
                WARN,
                errors.FIREFOX_REPORTS_PROBLEM,
                f"{_plural(len(failed), 'health check')} failed: {listed}.",
            )
        )
    else:
        checks.append(
            _ok(
                "status.health",
                "Script health inside Firefox",
                f"{_plural(len(status.health), 'check')} ok",
            )
        )
    problems = [
        e for e in status.errors if e.level.lower() not in ("info", "debug", "warn", "warning")
    ]
    detail = " | ".join(
        f"{_short(e.time, 40)} {_short(e.level, 20)} {_short(e.where, 80)}: {_short(e.message)}"
        for e in status.errors
    )
    if problems:
        last = problems[-1]
        checks.append(
            _bad(
                "status.errors",
                "Errors recorded by the script",
                WARN,
                errors.FIREFOX_SCRIPT_ERRORS,
                f"The script recorded {_plural(len(problems), 'error')}; the latest one, in "
                f"{_short(last.where, 80) or '?'}, says: {_short(last.message)}",
                detail=detail,
            )
        )
    else:
        checks.append(_ok("status.errors", "Errors recorded by the script", "none", detail))
    return checks


def _profile_sections(
    ctx: Context, n: int, name: str, path: Path, bundled: Path | None
) -> list[Section]:
    chrome = path / "chrome"
    title = f"Profile: {name}"
    if not _is_dir(path):
        gone = _bad(
            "profile.folder",
            "Profile folder",
            FAIL,
            errors.PROFILE_FOLDER_MISSING,
            "The profile folder does not exist.",
            value=str(path),
        )
        return [Section(f"profile.{n}", title, (gone,))]
    checks = [_ok("profile.folder", "Profile folder", str(path))]
    checks += _guarded(
        "profile.files", "Peek-a-Foxy files", lambda: _files_check(ctx, chrome, bundled)
    )
    checks += _guarded("profile.utils", "chrome/utils", lambda: _utils_check(chrome))
    checks += _guarded("profile.import", "userChrome.css", lambda: _import_check(chrome))

    def read_prefs() -> list[Check]:
        user_text, user_problem = _read_text(path / "user.js")
        prefs_text, prefs_problem = _read_text(path / "prefs.js")
        user = parse_prefs(user_text) if user_text is not None else None
        prefs = parse_prefs(prefs_text) if prefs_text is not None else None
        found = [
            _pref_check(
                "profile.pref_stylesheets",
                "Setting: userChrome.css is loaded",
                userfiles.STYLESHEETS_PREF,
                user,
                prefs,
                needed=True,
            ),
            _pref_check(
                "profile.pref_subdocuments",
                "Setting: script runs in the settings page",
                userfiles.SUBDOCUMENTS_PREF,
                user,
                prefs,
                needed=False,
            ),
            _own_prefs_check(user, prefs),
        ]
        for file, problem in (("user.js", user_problem), ("prefs.js", prefs_problem)):
            if problem:
                found.append(
                    _bad(
                        f"profile.read_{file.split('.')[0]}",
                        f"Reading {file}",
                        WARN,
                        errors.FILE_IO,
                        f"The file {file} could not be read ({problem}).",
                    )
                )
        return found

    checks += _guarded("profile.prefs", "Firefox settings", read_prefs)
    status_checks, ran = _status_checks(ctx, chrome)
    checks += _guarded(
        "profile.startup_cache", "Startup cache", lambda: _cache_check(ctx, path, chrome, ran)
    )
    return [
        Section(f"profile.{n}", title, tuple(checks)),
        Section(f"status.{n}", f"Script status: {name}", tuple(status_checks)),
    ]


def _profile_list_section(
    ctx: Context, profiles: list[Profile] | None, problems: list[Check]
) -> Section:
    checks = list(problems)
    for number, profile in enumerate((profiles or [])[:MAX_PROFILES_LISTED], start=1):
        have = len(_installed_files(profile.path / "chrome"))
        installed = (
            "installed"
            if have == len(assets.FILES)
            else "not installed"
            if have == 0
            else f"partly installed ({have} of {len(assets.FILES)} files)"
        )
        flag = ", default of an install" if profile.is_default else ""
        checks.append(
            _ok(
                f"profiles.{number}",
                f"Profile <profile {number}>",
                f"{installed}{flag}; {profile.path}",
            )
        )
    more = len(profiles or []) - MAX_PROFILES_LISTED
    if more > 0:
        checks.append(
            _ok("profiles.more", "More profiles", f"{more} more profiles are not listed here")
        )
    return Section("profiles", "Profiles (profiles.ini)", tuple(checks))


def _read_profile_list(ctx: Context) -> list[Profile]:
    """``profiles.ini`` as the discovery code reads it, with every way it can go wrong coded."""
    try:
        root = ctx.profiles_root()
    except (RuntimeError, OSError) as error:  # no home folder to look in
        raise DiscoveryError(
            errors.NO_PROFILES_INI,
            "The folder where Firefox keeps its profiles could not be worked out because this "
            "account has no home folder",
            detail=repr(error),
        ) from error
    ini = root / "profiles.ini"
    try:
        size = ini.stat().st_size
    except (OSError, ValueError):
        size = 0
    if size > MAX_FILE:
        raise DiscoveryError(
            errors.PROFILES_UNREADABLE, f"{ini} is far bigger than a profiles.ini file should be"
        )
    try:
        return read_profiles(root)
    except (OSError, ValueError) as error:
        raise DiscoveryError(
            errors.PROFILES_UNREADABLE, f"could not read {ini}", detail=errors.clip(repr(error))
        ) from error


def _profile_sections_all(
    ctx: Context, profile: Path | None, bundled: Path | None
) -> tuple[list[Section], tuple[str, ...]]:
    profiles: list[Profile] | None = None
    problems: list[Check] = []
    try:
        profiles = _read_profile_list(ctx)
    except PeekError as error:
        problems.append(
            _bad(
                "profiles.ini",
                "profiles.ini",
                WARN if profile is not None else FAIL,
                error.code,
                f"{error.message}.",
                hint=error.hint,
                detail=error.detail,
            )
        )
    chosen: list[tuple[str, Path]] = []
    if profile is not None:
        chosen = [(_profile_label(profiles or [], profile), profile)]
    elif profiles:
        numbered = [(f"<profile {n}>", p) for n, p in enumerate(profiles, start=1)]
        defaults = [item for item in numbered if item[1].is_default]
        if len(profiles) == 1:
            defaults = numbered
        elif not defaults:
            defaults = numbered
            problems.append(
                _bad(
                    "profiles.default",
                    "Default profile",
                    WARN,
                    errors.AMBIGUOUS_PROFILE,
                    "No profile is marked as the default one, so all of them are checked.",
                )
            )
        chosen = [(label, p.path) for label, p in defaults]
        if len(chosen) > MAX_PROFILES_CHECKED:
            problems.append(
                _bad(
                    "profiles.checked",
                    "Profiles checked",
                    WARN,
                    errors.AMBIGUOUS_PROFILE,
                    f"There are {len(chosen)} candidate profiles, and only the first "
                    f"{MAX_PROFILES_CHECKED} were checked.",
                    hint="Name the profile you mean with --profile.",
                )
            )
            chosen = chosen[:MAX_PROFILES_CHECKED]
    sections = [_profile_list_section(ctx, profiles, problems)]
    for n, (name, path) in enumerate(chosen, start=1):
        sections += _profile_sections(ctx, n, name, path, bundled)
    names = tuple(p.name for p in profiles or [])
    return sections, names


# --- the whole report --------------------------------------------------------------------------


def _crashed(id: str, title: str, error: Exception) -> Section:
    log.error("%s could not be checked", id, exc_info=error)
    check = _bad(
        f"{id}.crashed",
        title,
        WARN,
        errors.UNEXPECTED,
        "This part could not be checked because of a bug in Peek-a-Foxy.",
        detail=f"{type(error).__name__}: {error}",
    )
    return Section(id, title, (check,))


def collect(
    ctx: Context, *, profile: Path | None = None, firefox_dir: Path | None = None
) -> Report:
    """Run every check and return the report (redacted by the caller, see ``Report.redacted``)."""
    program = _program_checks(ctx)
    bundled: Path | None
    try:
        bundled = ctx.assets_dir()
    except PeekError:
        bundled = None
    sections = [Section("program", "Program", tuple(program))]
    names: tuple[str, ...] = ()
    try:
        sections += _firefox_sections(ctx, firefox_dir)
    except Exception as error:  # a bug in one part must not hide the others
        sections.append(_crashed("firefox", "Firefox installs", error))
    try:
        found, names = _profile_sections_all(ctx, profile, bundled)
        sections += found
    except Exception as error:
        sections.append(_crashed("profiles", "Profiles", error))
    report = Report(ctx.version, ctx.now().strftime("%Y-%m-%dT%H:%M:%SZ"), tuple(sections), names)
    for check in report.all_checks():
        log.info("doctor: %s %s", check.id, check.status)
        if check.status != OK:
            log.info("doctor: %s: %s [%s]", check.id, check.message, check.code)
    return report
