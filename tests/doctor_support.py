"""Fake machines for the doctor tests: a home folder, Firefox installs and profiles in tmp_path."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from peek_a_foxy import assets, elevate, userfiles
from peek_a_foxy.doctor import Context

CONFIG_JS = "// fake loader\nconst x = 1;\n"
CONFIG_PREFS = 'pref("general.config.filename", "config.js");\n'
LOADER_TEXT = {"config.js": CONFIG_JS, "defaults/pref/config-prefs.js": CONFIG_PREFS}
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
PROFILE_DIR = "abcd1234.default-release"
OLD = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


def write(path: Path, text: str) -> None:
    """Write ``text`` as UTF-8 with LF line endings on every system, as Firefox's files have.

    ``Path.write_text`` would use the locale's encoding and, on Windows, turn every LF into CRLF,
    which the doctor rightly reports as a different file.
    """
    path.write_bytes(text.encode("utf-8"))


def real_profiles_root(home: Path) -> Path:
    """Where the real program, run with :func:`real_home_environment`, looks for profiles.ini."""
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Firefox"
    if sys.platform == "win32":
        return home / "AppData" / "Roaming" / "Mozilla" / "Firefox"
    return home / ".mozilla" / "firefox"


def real_home_environment(home: Path) -> dict[str, str]:
    """The variables that make a real ``python -m peek_a_foxy`` take ``home`` for its home."""
    roaming = home / "AppData" / "Roaming"
    return {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(roaming)}


def pin_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the fake loader files the 'pinned' ones (the real hashes need the real files)."""
    for name, text in LOADER_TEXT.items():
        digest = hashlib.sha256(text.encode()).hexdigest()
        monkeypatch.setitem(elevate.PINNED_SHA256, name, digest)


def make_firefox(
    folder: Path,
    *,
    loader: bool = True,
    version: str = "150.0",
    channel: str | None = "release",
    application_ini: str | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "omni.ja").touch()
    if application_ini is None:
        application_ini = (
            f"[App]\nVendor=Mozilla\nName=Firefox\nVersion={version}\nBuildID=20261020000000\n"
        )
    if application_ini:
        write(folder / "application.ini", application_ini)
    if channel:
        pref = folder / "defaults" / "pref"
        pref.mkdir(parents=True, exist_ok=True)
        write(pref / "channel-prefs.js", f'pref("app.update.channel", "{channel}");\n')
    if loader:
        for name, text in LOADER_TEXT.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            write(path, text)
    return folder


def make_profile(
    home: Path,
    *,
    folder: str = PROFILE_DIR,
    name: str = "default-release",
    installed: bool = True,
    default: bool = True,
    with_ini: bool = True,
    root: Path | None = None,
) -> Path:
    """A profile that ``install`` would have produced (the real bundled files).

    ``root`` is the folder of profiles.ini, ``~/.mozilla/firefox`` (Linux's) unless given.
    """
    root = root or home / ".mozilla" / "firefox"
    path = root / folder
    chrome = path / "chrome"
    chrome.mkdir(parents=True, exist_ok=True)
    if with_ini:
        ini = root / "profiles.ini"
        existing = ini.read_text(encoding="utf-8") if ini.exists() else ""
        number = existing.count("[Profile")
        section = f"[Profile{number}]\nName={name}\nIsRelative=1\nPath={folder}\n"
        section += "Default=1\n\n" if default else "\n"
        write(ini, existing + section)
    if installed:
        source = assets.assets_dir()
        for rel in assets.FILES:
            target = chrome / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target)
        (chrome / "utils").mkdir(exist_ok=True)
        write(chrome / "utils" / "boot.sys.mjs", "boot\n")
        write(chrome / "userChrome.css", userfiles.CSS_IMPORT + "\n")
        write(
            path / "user.js",
            f'user_pref("{userfiles.STYLESHEETS_PREF}", true);\n'
            f'user_pref("{userfiles.SUBDOCUMENTS_PREF}", true);\n',
        )
    for file in root.rglob("*"):  # dated well before any test clock, so "newer than" is stable
        if file.is_file():
            os.utime(file, (OLD, OLD))
    return path


def make_context(home: Path, **overrides: object) -> Context:
    """A Linux machine whose every seam is fake; pass keyword arguments to change any of it."""
    values: dict[str, object] = {
        "kind": "linux",
        "unsupported": None,
        "home": home,
        "environ": {},
        "version": "1.2.3",
        "python": "3.13.0 (CPython)",
        "os_description": "Linux-6.0-x86_64",
        "machine": "x86_64",
        "frozen": False,
        "module_file": "/somewhere/site-packages/peek_a_foxy/doctor.py",
        "executable": "/usr/bin/python3",
        "is_admin": lambda: False,
        "can_write": lambda path: True,
        "run_command": lambda command: "git version 2.40.0",
        "which": lambda name: f"/usr/bin/{name}",
        "firefox_candidates": lambda: [],
        "profiles_root": lambda: home / ".mozilla" / "firefox",
        "assets_dir": assets.assets_dir,
        "loader_files": lambda: home,
        "encoding": "utf-8",
        "is_tty": False,
        "log_target": None,
        "now": lambda: NOW,
    }
    values.update(overrides)
    return Context(**values)  # type: ignore[arg-type]


def check_of(report, check_id: str, section: str | None = None):
    """The one check with this id (in the section with this id, if given)."""
    found = [
        check
        for s in report.sections
        if section is None or s.id == section
        for check in s.checks
        if check.id == check_id
    ]
    assert len(found) == 1, f"{check_id}: {len(found)} found"
    return found[0]
