"""Helpers shared by the tests: which behaviours the current operating system can show."""

from __future__ import annotations

import os
import sys

import pytest

WINDOWS = sys.platform == "win32"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0

# Directory permission bits are advisory on Windows (they only toggle a read-only flag on files),
# and root ignores them everywhere.
needs_permissions = pytest.mark.skipif(
    WINDOWS or IS_ROOT, reason="needs POSIX directory permissions, and not to be root"
)
# Creating symlinks needs a privilege that ordinary Windows users do not have.
needs_symlinks = pytest.mark.skipif(WINDOWS, reason="symlinks need a privilege on Windows")
