"""Locating the Firefox files (CSS and script) that get installed into a profile."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from peek_a_foxy import errors
from peek_a_foxy.errors import PlatformError

CSS_NAME = "autohide.css"
SCRIPT_NAME = "autohide.uc.js"
PREFS_SCRIPT_NAME = "autohide-prefs.uc.js"  # the settings page in about:preferences
MODULE_NAME = "peekafoxy.sys.mjs"  # shared by both scripts; fx-autoconfig serves resources/

# Where each file lives, relative to the profile's ``chrome`` folder (and to ``assets_dir()``).
FILES = (CSS_NAME, f"JS/{SCRIPT_NAME}", f"JS/{PREFS_SCRIPT_NAME}", f"resources/{MODULE_NAME}")


def assets_dir() -> Path:
    """Directory laid out like a profile's ``chrome`` folder.

    It holds the files listed in ``FILES``. Installed packages carry it as
    ``peek_a_foxy/assets``; a source checkout keeps it in ``chrome/``.
    """
    packaged = Path(str(resources.files("peek_a_foxy") / "assets"))
    if (packaged / CSS_NAME).is_file():
        return packaged
    checkout = Path(__file__).resolve().parents[2] / "chrome"
    if (checkout / CSS_NAME).is_file():
        return checkout
    raise PlatformError(errors.FILES_MISSING, "could not find the Peek-a-Foxy files to install")
