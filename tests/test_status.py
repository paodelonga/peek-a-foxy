"""The status file the Firefox script will write (schema 1): its reader and its fixture."""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest

from peek_a_foxy import platform, status
from peek_a_foxy.status import StatusError, parse_status, read_status

FIXTURE = Path(__file__).parent / "fixtures" / "peekafoxy-status.json"


def test_the_fixture_is_the_documented_example():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["schema"] == status.STATUS_SCHEMA == 1
    assert {"scriptVersion", "firefoxVersion", "buildID", "channel", "os", "locale"} <= set(data)
    assert {"updated", "windows", "health", "errors"} <= set(data)
    assert set(data["errors"][0]) == {"time", "level", "where", "message"}


def test_the_fixture_is_read_completely():
    result = parse_status(FIXTURE.read_text(encoding="utf-8"))
    assert result.updated.tzinfo is timezone.utc and result.updated.year == 2026
    assert (result.script_version, result.firefox_version) == ("0.2.0", "150.0")
    assert (result.build_id, result.channel, result.os, result.locale) == (
        "20261020000000",
        "release",
        "Linux",
        "en-US",
    )
    assert result.windows == 2
    assert result.failed() == [("nav-bar", "element #nav-bar not found")]
    assert [e.level for e in result.errors] == ["info", "error"]
    assert result.errors[1].where == "autohide.uc.js:reveal"


@pytest.mark.parametrize(
    ("windows", "expected"),
    [
        (2, 2),
        (0, 0),
        (True, None),  # a boolean is an int to Python, but not a number of windows
        (False, None),
        (1.5, None),
        (2.0, None),
        ("3", None),
        ([2], None),
        (None, None),
        (-1, -1),  # odd, but it is a number: showing it is the doctor's job, not the reader's
    ],
)
def test_the_number_of_windows_is_an_integer_or_nothing(windows, expected):
    text = json.dumps({"schema": 1, "updated": "2026-11-05T00:00:00Z", "windows": windows})
    assert parse_status(text).windows == expected


def test_unknown_keys_are_ignored_so_the_writer_can_add_some():
    data = json.loads(FIXTURE.read_text(encoding="utf-8")) | {"future": {"x": 1}}
    assert parse_status(json.dumps(data)).script_version == "0.2.0"


def test_only_the_latest_errors_are_kept():
    items = [{"message": str(n)} for n in range(status.MAX_ERRORS + 5)]
    text = json.dumps({"schema": 1, "updated": "2026-11-05T00:00:00Z", "errors": items})
    kept = parse_status(text).errors
    assert len(kept) == status.MAX_ERRORS and kept[-1].message == str(status.MAX_ERRORS + 4)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-05T12:00:00.000Z", True),
        ("2026-11-05T12:00:00z", True),
        ("2026-11-05T12:00:00", True),
        ("2026-11-05T12:00:00+02:00", True),
        ("not a time", False),
        (12345, False),
        (None, False),
    ],
)
def test_times_are_read_as_iso_8601_in_any_common_form(value, expected):
    assert (status.parse_time(value) is not None) is expected


def test_a_time_without_a_zone_is_taken_as_utc():
    assert status.parse_time("2026-11-05T12:00:00").tzinfo is timezone.utc


def test_health_values_other_than_ok_are_failures_with_their_notes():
    text = json.dumps(
        {
            "schema": 1,
            "updated": "2026-11-05T00:00:00Z",
            "health": {"a": "OK", "b": "fail", "c": "fail: gone: really", "d": 5},
        }
    )
    assert parse_status(text).failed() == [
        ("b", ""),
        ("c", "gone: really"),
        ("d", "unreadable value"),
    ]


def test_reading_a_folder_without_the_file_gives_none(tmp_path: Path):
    assert read_status(tmp_path) is None


def test_reading_a_folder_with_the_file(tmp_path: Path):
    (tmp_path / status.STATUS_FILE).write_bytes(  # a BOM is tolerated
        ("\ufeff" + FIXTURE.read_text(encoding="utf-8")).encode("utf-8")
    )
    assert read_status(tmp_path).windows == 2


def test_an_unreadable_file_is_a_status_error(tmp_path: Path):
    (tmp_path / status.STATUS_FILE).write_bytes(b"\xff\xfe\x00")
    with pytest.raises(StatusError, match="not valid UTF-8"):
        read_status(tmp_path)


def test_a_file_being_replaced_is_read_once_windows_lets_go_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Adversarial: the doctor reads the status at the moment Firefox renames a new one over it."""
    data = FIXTURE.read_bytes()
    attempts: list[int] = []

    def read_file(path: Path) -> bytes:
        attempts.append(1)
        if len(attempts) <= 3:  # Windows says "access denied" while the rename happens
            raise PermissionError(13, "Permission denied", str(path))
        return data

    monkeypatch.setattr(platform, "DENIED_WAITS", (0.01,) * 5)
    monkeypatch.setattr(platform.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(status, "_read_file", read_file)
    assert read_status(tmp_path).windows == 2
    assert len(attempts) == 4


def test_a_denial_that_lasts_is_still_a_status_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def read_file(path: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(platform, "DENIED_WAITS", (0.01,) * 5)
    monkeypatch.setattr(platform.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(status, "_read_file", read_file)
    with pytest.raises(StatusError, match=r"could not be read \(Permission denied\)"):
        read_status(tmp_path)


def test_the_file_name_is_the_documented_one():
    assert status.STATUS_FILE == "peekafoxy-status.json"


@pytest.mark.parametrize(("extra", "bigger"), [(0, False), (1, True)])
def test_a_status_file_of_exactly_the_size_limit_is_read_and_one_byte_more_is_not(
    tmp_path: Path, extra: int, bigger: bool
):
    body = FIXTURE.read_text(encoding="utf-8").rstrip()
    padding = " " * (status.MAX_BYTES + extra - len(body.encode("utf-8")))
    # Bytes: text mode on Windows would add a CR to every line and miss the size by 20 bytes.
    (tmp_path / status.STATUS_FILE).write_bytes((body + padding).encode("utf-8"))
    assert (tmp_path / status.STATUS_FILE).stat().st_size == status.MAX_BYTES + extra
    if bigger:
        with pytest.raises(StatusError, match="much bigger"):
            read_status(tmp_path)
    else:
        assert read_status(tmp_path).windows == 2
