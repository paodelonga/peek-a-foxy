"""Reading a file that may be anything: a regular file, but also a FIFO, a device or a folder.

``open()`` on a FIFO waits until another process opens its other end, so a program that only wants
to look at a file called ``user.js`` would hang for good if that name is a FIFO. The helpers here
open without waiting, look at what was opened and only then read.
"""

from __future__ import annotations

import errno
import os
import stat

_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_BINARY", 0)  # Windows: no newline translation
    | getattr(os, "O_NONBLOCK", 0)  # POSIX: opening a FIFO must not wait for a writer
)


class NotARegularFileError(OSError):
    """The path names something that is not a regular file (a FIFO, a socket, a device)."""

    def __init__(self, path: str | os.PathLike[str], kind: str) -> None:
        super().__init__(errno.EINVAL, f"it is {kind}, not a regular file", os.fspath(path))
        self.kind = kind


def _kind(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "a named pipe (FIFO)"
    if stat.S_ISSOCK(mode):
        return "a socket"
    if stat.S_ISCHR(mode):
        return "a character device"
    if stat.S_ISBLK(mode):
        return "a block device"
    return "not an ordinary file"


def read_regular(path: str | os.PathLike[str], limit: int) -> bytes:
    """Up to ``limit + 1`` bytes of a regular file, so the caller can tell that it is too big.

    Raises ``FileNotFoundError`` and the other ``OSError`` errors of ``open``, ``IsADirectoryError``
    for a folder and :class:`NotARegularFileError` for any other kind of file, none of which is
    read.
    """
    try:
        descriptor = os.open(path, _OPEN_FLAGS)
    except PermissionError:
        if os.path.isdir(path):  # Windows refuses to open a folder like a file
            raise IsADirectoryError(errno.EISDIR, "it is a folder", os.fspath(path)) from None
        raise
    try:
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISDIR(mode):
            raise IsADirectoryError(errno.EISDIR, "it is a folder", os.fspath(path))
        if not stat.S_ISREG(mode):
            raise NotARegularFileError(path, _kind(mode))
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(limit + 1)
    finally:
        os.close(descriptor)
