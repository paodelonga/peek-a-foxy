"""Fake machines for the doctor tests: a home folder, Firefox installs and profiles in tmp_path."""

from __future__ import annotations

import hashlib
import os
import shutil
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
        (folder / "application.ini").write_text(application_ini)
    if channel:
        pref = folder / "defaults" / "pref"
        pref.mkdir(parents=True, exist_ok=True)
        (pref / "channel-prefs.js").write_text(f'pref("app.update.channel", "{channel}");\n')
    if loader:
        for name, text in LOADER_TEXT.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    return folder


def make_profile(
    home: Path,
    *,
    folder: str = PROFILE_DIR,
    name: str = "default-release",
    installed: bool = True,
    default: bool = True,
    with_ini: bool = True,
) -> Path:
    """A profile that ``install`` would have produced (the real bundled files)."""
    root = home / ".mozilla" / "firefox"
    path = root / folder
    chrome = path / "chrome"
    chrome.mkdir(parents=True, exist_ok=True)
    if with_ini:
        ini = root / "profiles.ini"
        existing = ini.read_text() if ini.exists() else ""
        number = existing.count("[Profile")
        section = f"[Profile{number}]\nName={name}\nIsRelative=1\nPath={folder}\n"
        section += "Default=1\n\n" if default else "\n"
        ini.write_text(existing + section)
    if installed:
        source = assets.assets_dir()
        for rel in assets.FILES:
            target = chrome / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target)
        (chrome / "utils").mkdir(exist_ok=True)
        (chrome / "utils" / "boot.sys.mjs").write_text("boot\n")
        (chrome / "userChrome.css").write_text(userfiles.CSS_IMPORT + "\n")
        (path / "user.js").write_text(
            f'user_pref("{userfiles.STYLESHEETS_PREF}", true);\n'
            f'user_pref("{userfiles.SUBDOCUMENTS_PREF}", true);\n'
        )
    for file in (home / ".mozilla").rglob(
        "*"
    ):  # dated well before any test clock, so "newer than" is stable
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
