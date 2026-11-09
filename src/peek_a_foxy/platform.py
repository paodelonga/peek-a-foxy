"""Where Firefox keeps its profiles and its installation, per operating system."""

from __future__ import annotations

import contextlib
import importlib
import ntpath
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import TypeVar

from peek_a_foxy import errors
from peek_a_foxy.errors import PlatformError

FIREFOX_BINARIES = ("firefox", "firefox-developer-edition", "firefox-esr")
LINUX_INSTALL_DIRS = (
    "/usr/lib/firefox",
    "/usr/lib/firefox-developer-edition",
    "/usr/lib/firefox-esr",
    "/usr/lib64/firefox",  # Fedora and openSUSE
    "/opt/firefox",
)
MACOS_APPS = (
    "/Applications/Firefox.app",
    "/Applications/Firefox Developer Edition.app",
    "/Applications/Firefox Nightly.app",
)
# Folder names Firefox's Windows installers use, under Program Files and in the user's local folder.
WINDOWS_APP_DIRS = ("Mozilla Firefox", "Firefox Developer Edition", "Firefox Nightly")
WINDOWS_BASE_VARIABLES = ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA")
# Windows refuses to open, replace or remove a file for a moment while another program has it open
# or is replacing it ("access denied"): a virus scanner, Firefox saving a file, a second run of this
# program. Elsewhere a denial comes from the permissions, which waiting does not change.
DENIED_WAITS: tuple[float, ...] = (
    (0.01, 0.02, 0.04, 0.08, 0.16, 0.32) if sys.platform == "win32" else ()
)
# Lowercase: Windows paths do not care about case. Each marker names the kind of build it betrays.
SANDBOX_MARKERS = {
    "/snap/": "Snap",
    "/flatpak/app/": "Flatpak",  # not any folder that happens to be called flatpak
    "/flatpak/runtime/": "Flatpak",
    "/windowsapps/": "Microsoft Store (MSIX)",
}


BACKSLASH = "\\"


UnsupportedPlatformError = PlatformError  # the name this error had before codes

_T = TypeVar("_T")


def retry_if_denied(action: Callable[[], _T]) -> _T:
    """``action()``, tried again after each wait of :data:`DENIED_WAITS` while it is denied.

    A denial that lasts (about 0.6 s on Windows, at once elsewhere) is raised as it is.
    """
    for wait in DENIED_WAITS:
        try:
            return action()
        except PermissionError:
            time.sleep(wait)
    return action()


def system() -> str:
    """Return ``"linux"``, ``"macos"`` or ``"windows"``."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise PlatformError(
        errors.UNSUPPORTED_OS,
        f"unsupported platform '{sys.platform}': only Linux, macOS and Windows are handled",
    )


def is_windows() -> bool:
    return sys.platform == "win32"


def profiles_root() -> Path:
    """Directory that holds ``profiles.ini`` and the profiles."""
    home = Path.home()
    kind = system()
    if kind == "macos":
        return home / "Library" / "Application Support" / "Firefox"
    if kind == "windows":
        appdata = os.environ.get("APPDATA")
        roaming = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return roaming / "Mozilla" / "Firefox"
    return home / ".mozilla" / "firefox"


def _looks_like_firefox(directory: Path) -> bool:
    """``omni.ja`` is Firefox's; on Windows also ``firefox.exe``, so Thunderbird is never taken."""
    if not (directory / "omni.ja").is_file():
        return False
    return system() != "windows" or (directory / "firefox.exe").is_file()


def is_firefox_dir(directory: Path) -> bool:
    """Whether ``directory`` looks like a Firefox install folder (the rule discovery uses)."""
    try:
        return _looks_like_firefox(directory)
    except (OSError, ValueError):
        return False


# --- Windows: registry and well-known folders ---------------------------------------------------


def _winreg() -> ModuleType:
    return importlib.import_module("winreg")


def _subkeys(winreg: ModuleType, hive: int, path: str, view: int) -> list[str]:
    try:
        key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
    except OSError:
        return []
    names: list[str] = []
    try:
        while True:
            try:
                names.append(winreg.EnumKey(key, len(names)))
            except OSError:
                return names
    finally:
        winreg.CloseKey(key)


def _value(winreg: ModuleType, hive: int, path: str, view: int, name: str) -> str | None:
    try:
        key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
    except OSError:
        return None
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)
    return value if isinstance(value, str) and value.strip() else None


def _clean(value: str, *, parent: bool = False) -> Path:
    """A registry path: quotes and ``%VAR%`` removed; for an executable, its folder."""
    path = Path(ntpath.expandvars(value.strip().strip('"')))  # always Windows syntax: %VAR%
    return path.parent if parent else path


def registry_install_dirs(winreg: ModuleType) -> Iterator[Path]:
    """Install folders Firefox registered, in HKLM and HKCU, in the 64 and 32 bit views.

    Installers write ``SOFTWARE\\Mozilla\\<brand>\\<version>\\Main`` (``Install Directory``,
    ``PathToExe``) and ``App Paths\\firefox.exe``. The brand strings of Developer Edition and
    Nightly are not known for certain, so every brand under ``SOFTWARE\\Mozilla`` is read; whether a
    folder is Firefox's is decided later (``firefox.exe`` and ``omni.ja`` must be there).
    """
    app_paths = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for brand in _subkeys(winreg, hive, r"SOFTWARE\Mozilla", view):
                root = rf"SOFTWARE\Mozilla\{brand}"
                for version in _subkeys(winreg, hive, root, view):
                    main = rf"{root}\{version}\Main"
                    directory = _value(winreg, hive, main, view, "Install Directory")
                    if directory:
                        yield _clean(directory)
                    exe = _value(winreg, hive, main, view, "PathToExe")
                    if exe:
                        yield _clean(exe, parent=True)
            exe = _value(winreg, hive, app_paths, view, "")
            if exe:
                yield _clean(exe, parent=True)


def _windows_folder_guesses() -> Iterator[Path]:
    for variable in WINDOWS_BASE_VARIABLES:
        base = os.environ.get(variable)
        if base:
            for name in WINDOWS_APP_DIRS:
                yield Path(base) / name


def _windows_candidates() -> Iterator[Path]:
    # No registry to ask (or no access to it) is fine: the well-known folders still apply.
    with contextlib.suppress(ImportError, OSError):
        yield from registry_install_dirs(_winreg())
    yield from _windows_folder_guesses()


def _same_place(path: Path) -> str:
    """Key under which two spellings of one folder (case, ``..``, junctions) collapse."""
    return os.path.normcase(os.path.realpath(path))


def firefox_dir_candidates() -> list[Path]:
    """Install directories that look like Firefox, best guess first."""
    found: list[Path] = []
    kind = system()
    if kind == "macos":
        found = [Path(app) / "Contents" / "Resources" for app in MACOS_APPS]
    elif kind == "windows":
        found = list(_windows_candidates())
        binary = shutil.which("firefox")  # a portable copy, or one the user put on PATH
        if binary:
            found.append(Path(binary).resolve().parent)
    else:
        for name in FIREFOX_BINARIES:
            binary = shutil.which(name)
            if binary:
                found.append(Path(binary).resolve().parent)
        found += [Path(directory) for directory in LINUX_INSTALL_DIRS]
    seen: set[str] = set()
    ordered: list[Path] = []
    for directory in found:  # keep the first spelling of each place, drop the repeats
        key = _same_place(directory)
        if key not in seen:
            seen.add(key)
            ordered.append(directory)
    return [directory for directory in ordered if _looks_like_firefox(directory)]


def sandbox_kind(path: Path) -> str | None:
    """Name of the sandbox that keeps this Firefox read-only (so no loader), or ``None``."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):  # a symbolic link loop (RuntimeError before Python 3.13)
        resolved = Path(os.path.abspath(path))
    text = f"{str(resolved).replace(BACKSLASH, '/')}/".lower()
    return next((kind for marker, kind in SANDBOX_MARKERS.items() if marker in text), None)


def is_sandboxed(path: Path) -> bool:
    """Snap, Flatpak and Microsoft Store builds are read-only, so the loader cannot go there."""
    return sandbox_kind(path) is not None
