"""The status file the Firefox script leaves in the profile, and a reader for it (schema 1).

The script (``Diag`` in ``chrome/resources/peekafoxy.sys.mjs``, through ``IOUtils``, debounced and
small) saves ``<profile>/chrome/peekafoxy-status.json`` so that ``peek-a-foxy doctor`` can see what
Firefox itself saw. This module only reads it; a missing, old or damaged file is a finding, never
a crash. The writer already redacts the home folder, the user name and the profile folder and name,
and cleans control characters; the reader redacts and cleans again, because it cannot trust a file.

Schema 1, one JSON object. Keys other than ``schema`` and ``updated`` may be missing; unknown keys
are ignored, so the writer can add keys without breaking the reader::

    {
      "schema": 1,                          integer, the version of this layout
      "scriptVersion": "0.2.0",             version of the Peek-a-Foxy script
      "firefoxVersion": "150.0",            Services.appinfo.version
      "buildID": "20261020000000",          Services.appinfo.appBuildID
      "channel": "release",                 update channel
      "os": "Linux",                        Services.appinfo.OS
      "locale": "en-US",
      "updated": "2026-11-04T12:00:00.000Z",  ISO 8601, when the file was written (UTC)
      "windows": 2,                         number of browser windows the script is running in
      "health": {                           one entry per thing the CSS and script depend on
        "navigator-toolbox": "ok",          the value is "ok" ...
        "nav-bar": "fail: element not found"  ... or "fail" with a note after a colon
      },
      "errors": [                           the most recent errors, newest last
        {"time": "2026-11-04T12:00:01.000Z", "level": "error",
         "where": "autohide:init", "message": "text"}
      ]
    }

The text of ``errors`` can contain paths: the report redacts it like everything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from peek_a_foxy import fileio, platform

STATUS_FILE = "peekafoxy-status.json"
STATUS_SCHEMA = 1
MAX_BYTES = 1024 * 1024  # the writer's file is a few KB; anything bigger is not ours
MAX_ERRORS = 20  # the writer keeps 50; a report only needs the latest ones


class StatusError(Exception):
    """The file exists but cannot be used; ``str(error)`` says why, in a sentence."""


@dataclass(frozen=True)
class ScriptError:
    time: str
    level: str
    where: str
    message: str


@dataclass(frozen=True)
class Status:
    updated: datetime  # timezone-aware, UTC
    script_version: str = ""
    firefox_version: str = ""
    build_id: str = ""
    channel: str = ""
    os: str = ""
    locale: str = ""
    windows: int | None = None
    health: dict[str, str] = field(default_factory=dict)
    errors: tuple[ScriptError, ...] = ()

    def failed(self) -> list[tuple[str, str]]:
        """The health checks that did not say ``ok``, with their notes."""
        found = []
        for name, value in self.health.items():
            if value.strip().lower() != "ok":
                note = value.split(":", 1)[1].strip() if ":" in value else ""
                found.append((name, note))
        return found


def parse_time(value: object) -> datetime | None:
    """An ISO 8601 time (JavaScript's ``toISOString`` included) as UTC, or ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _text(data: dict[str, object], key: str) -> str:
    value = data.get(key, "")
    return value if isinstance(value, str) else ""


def parse_status(text: str) -> Status:
    """Read the file's text; raises :class:`StatusError` when it cannot be used."""
    try:
        data = json.loads(text)
    except RecursionError as error:
        raise StatusError("it is nested too deeply to have been written by the script") from error
    except ValueError as error:
        raise StatusError(f"it is not valid JSON ({error})") from error
    if not isinstance(data, dict):
        raise StatusError("it is not a JSON object")
    schema = data.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int):
        raise StatusError("it has no schema number")
    if schema > STATUS_SCHEMA:
        raise StatusError(
            f"it uses format {schema}, which is newer than format {STATUS_SCHEMA}, the only one "
            "this doctor reads, so peek-a-foxy needs to be updated"
        )
    if schema < 1:
        raise StatusError(f"unknown format {schema}")
    updated = parse_time(data.get("updated"))
    if updated is None:
        raise StatusError("it has no valid 'updated' time")

    health: dict[str, str] = {}
    raw_health = data.get("health", {})
    if not isinstance(raw_health, dict):
        raise StatusError("its 'health' entry is not an object")
    for name, value in raw_health.items():
        health[str(name)] = value if isinstance(value, str) else "fail: unreadable value"

    raw_errors = data.get("errors", [])
    if not isinstance(raw_errors, list):
        raise StatusError("its 'errors' entry is not a list")
    found = tuple(
        ScriptError(
            _text(item, "time"), _text(item, "level"), _text(item, "where"), _text(item, "message")
        )
        for item in raw_errors[-MAX_ERRORS:]
        if isinstance(item, dict)
    )
    windows = data.get("windows")
    return Status(
        updated=updated,
        script_version=_text(data, "scriptVersion"),
        firefox_version=_text(data, "firefoxVersion"),
        build_id=_text(data, "buildID"),
        channel=_text(data, "channel"),
        os=_text(data, "os"),
        locale=_text(data, "locale"),
        windows=windows if isinstance(windows, int) and not isinstance(windows, bool) else None,
        health=health,
        errors=found,
    )


def _read_file(path: Path) -> bytes:
    return fileio.read_regular(path, MAX_BYTES)


def read_status(chrome_dir: Path) -> Status | None:
    """The status in ``chrome_dir``; ``None`` when there is no file; :class:`StatusError` if bad."""
    path = chrome_dir / STATUS_FILE
    try:
        # Firefox saves the file by renaming a new one over it, and while that happens Windows
        # refuses to open it for a moment.
        raw = platform.retry_if_denied(lambda: _read_file(path))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except fileio.NotARegularFileError as error:
        raise StatusError(error.strerror or "it is not a regular file") from error
    except OSError as error:
        raise StatusError(
            f"it could not be read ({error.strerror or type(error).__name__})"
        ) from error
    if len(raw) > MAX_BYTES:
        raise StatusError("it is much bigger than the few kilobytes that the script writes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise StatusError("it is not valid UTF-8 text") from error
    return parse_status(text)
