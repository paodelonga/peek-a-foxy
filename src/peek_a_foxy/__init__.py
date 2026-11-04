"""Peek-a-boo for Foxys: autohide the tab bar and navigation bar per window."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("peek-a-foxy")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0.0.0+unknown"
