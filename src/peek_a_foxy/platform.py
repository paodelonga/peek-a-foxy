"""Where Firefox keeps its profiles and its installation, per operating system."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

FIREFOX_BINARIES = ("firefox", "firefox-developer-edition", "firefox-esr")
LINUX_INSTALL_DIRS = (
    "/usr/lib/firefox",
    "/usr/lib/firefox-developer-edition",
    "/usr/lib/firefox-esr",
    "/opt/firefox",
)
MACOS_APPS = (
    "/Applications/Firefox.app",
    "/Applications/Firefox Developer Edition.app",
    "/Applications/Firefox Nightly.app",
)
SANDBOX_MARKERS = ("/snap/", "/flatpak/")


class UnsupportedPlatformError(RuntimeError):
    """The current operating system is not supported."""


def system() -> str:
    """Return ``"linux"`` or ``"macos"``."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    raise UnsupportedPlatformError(
        f"unsupported platform '{sys.platform}': only Linux and macOS are handled"
    )


def profiles_root() -> Path:
    """Directory that holds ``profiles.ini`` and the profiles."""
    home = Path.home()
    if system() == "macos":
        return home / "Library" / "Application Support" / "Firefox"
    return home / ".mozilla" / "firefox"


def _has_omni(directory: Path) -> bool:
    return (directory / "omni.ja").is_file()


def firefox_dir_candidates() -> list[Path]:
    """Install directories that look like Firefox (they contain ``omni.ja``), best guess first."""
    found: list[Path] = []
    if system() == "macos":
        found = [Path(app) / "Contents" / "Resources" for app in MACOS_APPS]
    else:
        for name in FIREFOX_BINARIES:
            binary = shutil.which(name)
            if binary:
                found.append(Path(binary).resolve().parent)
        found += [Path(directory) for directory in LINUX_INSTALL_DIRS]
    unique = dict.fromkeys(found)  # keep order, drop duplicates
    return [directory for directory in unique if _has_omni(directory)]


def is_sandboxed(path: Path) -> bool:
    """Snap and Flatpak keep Firefox read-only, so the loader cannot be installed there."""
    text = f"{path.resolve().as_posix()}/"
    return any(marker in text for marker in SANDBOX_MARKERS)
