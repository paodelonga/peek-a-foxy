"""A named pipe, a device or a folder behind a file name is never replaced and never waited for.

PF-08: ``install`` swapped a FIFO behind ``userChrome.css`` for a plain file (as root, a link to
``/dev/null`` would have been renamed over). PF-14: ``doctor`` opened such a file and waited for a
writer for good. All adversarial: the default path of these files is covered elsewhere.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from support import WINDOWS, needs_symlinks
from typer.testing import CliRunner

from peek_a_foxy import errors, fileio
from peek_a_foxy.cli import app
from peek_a_foxy.status import STATUS_FILE, StatusError, read_status

runner = CliRunner()

needs_fifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")
needs_dev_null = pytest.mark.skipif(not os.path.exists("/dev/null"), reason="no /dev/null")


def snapshot(*roots: Path) -> dict[str, str]:
    """Every name under the roots, with its kind (and the bytes of a plain file)."""
    found: dict[str, str] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            mode = path.lstat().st_mode
            kind = "link" if stat.S_ISLNK(mode) else "file" if stat.S_ISREG(mode) else "special"
            found[str(path)] = kind + (":" + path.read_text() if kind == "file" else "")
    return found


@needs_fifo
@pytest.mark.parametrize("through_a_link", [False, True], ids=["fifo", "link-to-fifo"])
@pytest.mark.parametrize("name", ["chrome/userChrome.css", "user.js"])
def test_install_refuses_a_named_pipe_and_changes_nothing(
    profile: Path, tmp_path: Path, name: str, through_a_link: bool
):
    target = profile / name
    if through_a_link:
        if WINDOWS:
            pytest.skip("symlinks need a privilege on Windows")
        fifo = tmp_path / "dotfiles" / "real"
        fifo.parent.mkdir()
        os.mkfifo(fifo)
        os.symlink(fifo, target)
    else:
        os.mkfifo(target)
    before = snapshot(profile)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert errors.FILE_IO.code in result.output and "not a regular file" in result.output
    assert snapshot(profile) == before  # refused while planning: no file was copied either
    assert not (profile / "chrome" / "autohide.css").exists()
    if through_a_link:
        assert stat.S_ISFIFO(fifo.stat().st_mode)  # the thing behind the link is still a pipe
    else:
        assert stat.S_ISFIFO(target.lstat().st_mode)


@needs_symlinks
@needs_dev_null
@pytest.mark.parametrize("name", ["chrome/userChrome.css", "user.js"])
def test_a_file_linked_to_dev_null_stays_a_link_to_dev_null(profile: Path, name: str):
    """A file linked to /dev/null is switched off by its owner; it must not become a file."""
    target = profile / name
    os.symlink(os.devnull, target)
    for command in ("install", "uninstall"):
        result = runner.invoke(
            app,
            [
                command,
                "--profile",
                str(profile),
                *(["--skip-loader"] if command == "install" else []),
                "--yes",
            ],
        )
        assert result.exit_code == 1 and errors.FILE_IO.code in result.output, result.output
        assert target.is_symlink() and os.path.samefile(target, os.devnull)
        assert stat.S_ISCHR(os.stat(os.devnull).st_mode)
    assert not list(profile.rglob("*.peek-a-foxy.*"))  # no temporary file, no backup


@needs_fifo
def test_uninstall_refuses_a_named_pipe_too(profile: Path):
    os.mkfifo(profile / "user.js")
    result = runner.invoke(app, ["uninstall", "--profile", str(profile), "--yes"])
    assert result.exit_code == 1 and "not a regular file" in result.output


@needs_symlinks
def test_a_link_to_a_folder_is_a_coded_error_and_names_the_file(profile: Path, tmp_path: Path):
    folder = tmp_path / "somewhere"
    folder.mkdir()
    os.symlink(folder, profile / "chrome" / "userChrome.css", target_is_directory=True)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 1 and errors.FILE_IO.code in result.output
    assert "not a regular file" in result.output and "Traceback" not in result.output


# --- reading without waiting (the helper that doctor and the status reader use) ------------------


@needs_fifo
def test_reading_a_named_pipe_does_not_wait_for_a_writer(tmp_path: Path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(fileio.NotARegularFileError) as caught:
        fileio.read_regular(fifo, 100)  # would block for good with open()
    assert "named pipe" in str(caught.value.strerror)


def test_reading_a_folder_and_a_missing_file_are_the_usual_errors(tmp_path: Path):
    with pytest.raises(IsADirectoryError):
        fileio.read_regular(tmp_path, 10)
    with pytest.raises(FileNotFoundError):
        fileio.read_regular(tmp_path / "missing", 10)


def test_reading_gives_one_byte_more_than_the_limit_so_the_caller_can_tell(tmp_path: Path):
    path = tmp_path / "f"
    path.write_bytes(b"x" * 50)
    assert fileio.read_regular(path, 10) == b"x" * 11
    assert fileio.read_regular(path, 100) == b"x" * 50


@needs_dev_null
def test_a_character_device_is_not_read(tmp_path: Path):
    with pytest.raises(fileio.NotARegularFileError):
        fileio.read_regular(os.devnull, 10)


@needs_fifo
def test_the_status_reader_gives_a_status_error_for_a_named_pipe(profile: Path):
    os.mkfifo(profile / "chrome" / STATUS_FILE)
    with pytest.raises(StatusError, match="not a regular file"):
        read_status(profile / "chrome")


# --- doctor, in a real process with a real time limit ---------------------------------------------


def run_doctor(profile: Path, home: Path) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "HOME": str(home), "PEEK_A_FOXY_LOG": "off"}
    return subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", "doctor", "--json", "--profile", str(profile)],
        env=environment,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,  # the old code never came back: this is the whole test
    )


@needs_fifo
@pytest.mark.parametrize(
    "relative", ["chrome/userChrome.css", "user.js", "prefs.js", f"chrome/{STATUS_FILE}"]
)
def test_doctor_does_not_hang_on_a_named_pipe(profile: Path, tmp_path: Path, relative: str):
    os.mkfifo(profile / relative)
    done = run_doctor(profile, tmp_path)
    assert "Traceback" not in done.stderr, done.stderr
    data = json.loads(done.stdout)
    assert data["schema"] == 1
    text = json.dumps(data)
    assert "named pipe" in text or "not a regular file" in text


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no Unix sockets here")
def test_a_unix_socket_is_not_read_and_is_named_as_one(tmp_path: Path):
    path = str(tmp_path / "s")
    with socket.socket(socket.AF_UNIX) as server:
        try:
            server.bind(path)
        except OSError:
            pytest.skip("cannot bind a Unix socket in this folder")
        with pytest.raises(OSError) as caught:  # a socket cannot even be opened like a file
            fileio.read_regular(path, 10)
    assert caught.value.errno is not None


@pytest.mark.parametrize(
    ("mode", "word"),
    [
        (stat.S_IFIFO, "named pipe"),
        (stat.S_IFSOCK, "socket"),
        (stat.S_IFCHR, "character device"),
        (stat.S_IFBLK, "block device"),
        (stat.S_IFREG, "not an ordinary file"),
    ],
)
def test_every_kind_of_file_has_a_name_in_the_message(mode: int, word: str):
    assert word in fileio._kind(mode)
