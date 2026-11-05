"""The error model: every code is registered once, belongs to its area and is actually used."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from peek_a_foxy import errors
from peek_a_foxy.errors import (
    CODES,
    DiscoveryError,
    ErrorCode,
    LoaderError,
    PeekError,
    PlatformError,
    UserFileError,
)

SRC = Path(errors.__file__).parent
ALL = list(CODES.values())


def test_every_code_has_the_documented_shape():
    for entry in ALL:
        assert re.fullmatch(r"PAF-[1-69]\d\d", entry.code), entry.code
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", entry.slug), entry.slug
        assert entry.meaning.endswith("."), entry.code
        assert entry.hint.endswith("."), entry.code
        assert entry.hint[0].isupper(), entry.code


def test_codes_and_slugs_are_unique_and_the_registry_is_complete():
    constants = [value for value in vars(errors).values() if isinstance(value, ErrorCode)]
    assert len(constants) == len({c.code for c in constants}) == len(CODES)
    assert len({c.slug for c in constants}) == len(constants)
    assert {c.code for c in constants} == set(CODES)
    assert all(CODES[c.code] is c for c in constants)


def test_registering_a_code_twice_or_a_malformed_one_is_refused():
    with pytest.raises(ValueError, match="twice"):
        errors._register("PAF-101", "other-slug", "Meaning.", "Hint.")
    with pytest.raises(ValueError, match="twice"):
        errors._register("PAF-199", errors.NO_PROFILES_INI.slug, "Meaning.", "Hint.")
    with pytest.raises(ValueError, match="PAF"):
        errors._register("E-12", "bad", "Meaning.", "Hint.")
    assert "PAF-199" not in CODES


def test_codes_in_the_source_are_only_written_in_the_registry():
    """No module may type a code by hand: it would escape the uniqueness check."""
    for path in SRC.glob("*.py"):
        if path.name == "errors.py":
            continue
        assert not re.search(r"PAF-\d{3}", path.read_text(encoding="utf-8")), path.name


def test_every_registered_code_is_raised_somewhere():
    elsewhere = [path for path in SRC.glob("*.py") if path.name != "errors.py"]
    helpers = (SRC / "errors.py").read_text(encoding="utf-8").split("class PeekError")[1]
    used = "\n".join([*(path.read_text(encoding="utf-8") for path in elsewhere), helpers])
    names = {value: name for name, value in vars(errors).items() if isinstance(value, ErrorCode)}
    unused = [entry.code for entry in ALL if not re.search(rf"\b{names[entry]}\b", used)]
    assert unused == []


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        (DiscoveryError, errors.NO_PROFILES_INI),
        (LoaderError, errors.GIT_FAILED),
        (errors.ElevationError, errors.UAC_CANCELLED),
        (UserFileError, errors.FILE_IO),
        (PlatformError, errors.NO_TERMINAL),
        (errors.UnexpectedError, errors.UNEXPECTED),
    ],
)
def test_each_error_family_accepts_its_own_area(kind, code):
    error = kind(code, "message")
    assert error.code is code and error.hint == code.hint and error.detail == ""
    assert str(error) == "message" == error.message


def test_a_family_refuses_a_code_of_another_area():
    with pytest.raises(ValueError, match="does not belong"):
        LoaderError(errors.UAC_CANCELLED, "wrong family")


def test_an_unregistered_code_is_refused():
    with pytest.raises(ValueError, match="not a registered"):
        PeekError(ErrorCode("PAF-999", "made-up", "Meaning.", "Hint."), "message")


def test_the_hint_and_detail_can_be_given_for_one_error():
    error = LoaderError(errors.GIT_MISSING, "m", hint="Do this.", detail="exit 2")
    assert error.hint == "Do this." and error.detail == "exit 2"


def test_a_file_system_error_becomes_a_coded_error_that_keeps_its_cause():
    original = PermissionError(13, "Permission denied", "/some/file")
    wrapped = errors.from_oserror(original)
    assert wrapped.code is errors.FILE_IO and wrapped.__cause__ is original
    assert "Permission denied" in wrapped.message and "/some/file" in wrapped.message
    assert "PermissionError" in wrapped.detail
    assert errors.from_oserror(OSError("disk on fire")).message == "disk on fire"


def test_context_travels_from_the_original_error_to_the_wrapper():
    original = OSError("x")
    errors.set_context(original, "2 of 3 steps finished.")
    assert errors.get_context(errors.from_oserror(original)) == "2 of 3 steps finished."
    assert errors.get_context(ValueError("no context")) == ""


def test_exit_codes_are_the_documented_ones():
    assert (errors.EXIT_OK, errors.EXIT_FAILURE, errors.EXIT_USAGE, errors.EXIT_UNEXPECTED) == (
        0,
        1,
        2,
        70,
    )


def test_old_names_still_point_at_the_new_families():
    from peek_a_foxy import platform, profiles

    assert profiles.NoProfilesError is DiscoveryError
    assert platform.UnsupportedPlatformError is PlatformError
