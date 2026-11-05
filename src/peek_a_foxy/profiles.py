"""Reading Firefox's ``profiles.ini``."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from peek_a_foxy import errors
from peek_a_foxy.errors import DiscoveryError

NoProfilesError = DiscoveryError  # the name this error had before codes: ``profiles.ini`` problems


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    is_default: bool = False


def read_profiles(root: Path) -> list[Profile]:
    """Profiles listed in ``root/profiles.ini``; each install's default one is flagged."""
    ini = root / "profiles.ini"
    if not ini.is_file():
        raise DiscoveryError(errors.NO_PROFILES_INI, f"no profiles.ini in {root}")

    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(ini, encoding="utf-8-sig")  # tolerate a BOM
    except (configparser.Error, UnicodeDecodeError) as error:
        raise DiscoveryError(
            errors.PROFILES_UNREADABLE, f"could not read {ini}", detail=repr(error)
        ) from error

    # Each [Install...] section names the default profile of one Firefox installation. With several
    # installations (release and developer edition, say) there are several, one per installation.
    install_defaults = {
        parser[section]["default"]
        for section in parser.sections()
        if section.startswith("Install") and "default" in parser[section]
    }

    profiles: list[Profile] = []
    for section in parser.sections():
        if not section.startswith("Profile"):
            continue
        entry = parser[section]
        raw_path = entry.get("path")
        if not raw_path:
            continue
        path = root / raw_path if entry.getboolean("isrelative", fallback=True) else Path(raw_path)
        if install_defaults:
            is_default = raw_path in install_defaults
        else:
            is_default = entry.get("default") == "1"
        profiles.append(Profile(name=entry.get("name", raw_path), path=path, is_default=is_default))

    if not profiles:
        raise DiscoveryError(errors.NO_PROFILE_LISTED, f"{ini} lists no profile")
    return profiles


def default_profile(profiles: list[Profile]) -> Profile | None:
    """The default profile, or ``None`` when it is ambiguous (zero or several candidates)."""
    defaults = [profile for profile in profiles if profile.is_default]
    return defaults[0] if len(defaults) == 1 else None
