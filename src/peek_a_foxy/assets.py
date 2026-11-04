"""Locating the Firefox files (CSS and script) that get installed into a profile."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

CSS_NAME = "autohide.css"
SCRIPT_NAME = "autohide.uc.js"


def assets_dir() -> Path:
    """Directory laid out like a profile's ``chrome`` folder.

    It holds ``autohide.css`` and ``JS/autohide.uc.js``. Installed packages carry it as
    ``peek_a_foxy/assets``; a source checkout keeps it in ``chrome/``.
    """
    packaged = Path(str(resources.files("peek_a_foxy") / "assets"))
    if (packaged / CSS_NAME).is_file():
        return packaged
    checkout = Path(__file__).resolve().parents[2] / "chrome"
    if (checkout / CSS_NAME).is_file():
        return checkout
    raise FileNotFoundError("could not find the autohide.css/autohide.uc.js files to install")
