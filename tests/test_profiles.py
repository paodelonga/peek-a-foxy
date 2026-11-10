from pathlib import Path

import pytest

from peek_a_foxy.profiles import NoProfilesError, default_profile, read_profiles

INI = """\
[Install4F96D1932A9F858E]
Default=Profiles/abc.dev-edition
Locked=1

[Profile1]
Name=release
IsRelative=1
Path=Profiles/zzz.release
Default=1

[Profile0]
Name=dev
IsRelative=1
Path=Profiles/abc.dev-edition

[Profile2]
Name=elsewhere
IsRelative=0
Path=/data/ff
"""


def test_install_section_decides_the_default(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text(INI)
    profiles = read_profiles(tmp_path)
    assert [p.name for p in profiles] == ["release", "dev", "elsewhere"]
    assert default_profile(profiles).name == "dev"
    assert profiles[0].path == tmp_path / "Profiles/zzz.release"
    assert profiles[2].path == Path("/data/ff")


def test_default_flag_is_used_without_an_install_section(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text(INI.split("\n\n", 1)[1])
    assert default_profile(read_profiles(tmp_path)).name == "release"


def test_missing_or_empty_ini_is_an_error(tmp_path: Path):
    with pytest.raises(NoProfilesError):
        read_profiles(tmp_path)
    (tmp_path / "profiles.ini").write_text("[General]\nStartWithLastProfile=1\n")
    with pytest.raises(NoProfilesError):
        read_profiles(tmp_path)


def test_several_installs_have_several_defaults_and_none_is_picked(tmp_path: Path):
    ini = INI.replace(
        "[Profile1]",
        "[Install0000000000000000]\nDefault=Profiles/zzz.release\n\n[Profile1]",
    )
    (tmp_path / "profiles.ini").write_text(ini)
    profiles = read_profiles(tmp_path)
    assert [p.name for p in profiles if p.is_default] == ["release", "dev"]
    assert default_profile(profiles) is None


# --- awkward profiles.ini files -----------------------------------------------------------


def test_bom_and_crlf_are_tolerated(tmp_path: Path):
    (tmp_path / "profiles.ini").write_bytes(
        b"\xef\xbb\xbf"
        + b"[Profile0]\r\nName=a\r\nIsRelative=1\r\nPath=Profiles/a\r\nDefault=1\r\n"
    )
    [profile] = read_profiles(tmp_path)
    assert profile.name == "a" and profile.is_default


def test_garbage_is_reported_as_no_profiles_not_a_traceback(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text("this is not an ini file\n")
    with pytest.raises(NoProfilesError):
        read_profiles(tmp_path)
    (tmp_path / "profiles.ini").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(NoProfilesError):
        read_profiles(tmp_path)


def test_entries_without_a_path_are_skipped_and_name_falls_back_to_the_path(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text(
        "[Profile0]\nName=broken\n\n[Profile1]\nPath=Profiles/x\n"
    )
    [profile] = read_profiles(tmp_path)
    assert profile.name == "Profiles/x"
    assert profile.path == tmp_path / "Profiles/x"  # IsRelative defaults to relative


def test_duplicate_sections_do_not_crash(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text("[Profile0]\nPath=a\n[Profile0]\nPath=b\nDefault=1\n")
    assert read_profiles(tmp_path)


def test_a_folder_named_profiles_ini_is_not_found_rather_than_listing_no_profile(tmp_path: Path):
    from peek_a_foxy import errors
    from peek_a_foxy.errors import DiscoveryError

    (tmp_path / "profiles.ini").mkdir()
    with pytest.raises(DiscoveryError) as caught:
        read_profiles(tmp_path)
    assert caught.value.code is errors.NO_PROFILES_INI
