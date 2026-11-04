"""Reading Firefox's ``profiles.ini``."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


class NoProfilesError(RuntimeError):
    """``profiles.ini`` is missing or lists no profile."""


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    is_default: bool = False


def read_profiles(root: Path) -> list[Profile]:
    """Profiles listed in ``root/profiles.ini``; each install's default one is flagged."""
    ini = root / "profiles.ini"
    if not ini.is_file():
        raise NoProfilesError(f"no profiles.ini in {root}; pass --profile")

    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(ini, encoding="utf-8-sig")  # tolerate a BOM
    except (configparser.Error, UnicodeDecodeError) as error:
        raise NoProfilesError(f"could not parse {ini} ({error}); pass --profile") from error

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
        raise NoProfilesError(f"{ini} lists no profile; pass --profile")
    return profiles


def default_profile(profiles: list[Profile]) -> Profile | None:
    """The default profile, or ``None`` when it is ambiguous (zero or several candidates)."""
    defaults = [profile for profile in profiles if profile.is_default]
    return defaults[0] if len(defaults) == 1 else None
