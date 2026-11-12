import os
from pathlib import Path

import pytest
from support import FORCING_COLOR, TEST_COLUMNS, TEST_LINES
from support import git as _git


@pytest.fixture
def fxac_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal local stand-in for fx-autoconfig, wired in through the env overrides."""
    repo = tmp_path / "fxac-fixture"
    (repo / "program" / "defaults" / "pref").mkdir(parents=True)
    (repo / "profile" / "chrome" / "utils").mkdir(parents=True)
    # Bytes, so the files are LF on Windows too: the commit below runs without the system git
    # settings (core.autocrlf), so it keeps whatever line endings it is given.
    (repo / "program" / "config.js").write_bytes(b"// loader\n")
    (repo / "program" / "defaults" / "pref" / "config-prefs.js").write_bytes(b"pref(1);\n")
    (repo / "profile" / "chrome" / "utils" / "boot.sys.mjs").write_bytes(b"boot\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    monkeypatch.setenv("FXAC_REPO", str(repo))
    monkeypatch.setenv("FXAC_COMMIT", _git(repo, "rev-parse", "HEAD"))
    return repo


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile"
    (path / "chrome").mkdir(parents=True)
    return path


@pytest.fixture
def firefox_dir(tmp_path: Path) -> Path:
    path = tmp_path / "firefox"
    path.mkdir()
    (path / "omni.ja").touch()
    (path / "firefox.exe").touch()  # what Windows needs to take the folder for Firefox's
    return path


@pytest.fixture(autouse=True)
def plain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same plain, wide terminal for every test, whatever the environment it runs in.

    Typer reads ``GITHUB_ACTIONS``, ``FORCE_COLOR`` and ``PY_COLORS`` once, when it is imported
    (long before this fixture runs), and Rich reads ``COLUMNS`` once when a console is created;
    changing the environment afterwards does not undo that, so the values they kept are replaced.
    """
    from typer import rich_utils

    from peek_a_foxy import ui

    for name in FORCING_COLOR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")  # Rich and the subprocesses
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", str(TEST_COLUMNS))
    monkeypatch.setenv("LINES", str(TEST_LINES))
    monkeypatch.setenv("_TYPER_FORCE_DISABLE_TERMINAL", "1")  # for a Typer imported by a subprocess
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", False, raising=False)
    monkeypatch.setattr(rich_utils, "COLOR_SYSTEM", None, raising=False)
    monkeypatch.setattr(rich_utils, "MAX_WIDTH", TEST_COLUMNS, raising=False)
    for console in (ui.console, ui.errors):
        monkeypatch.setattr(console, "_color_system", None)
        monkeypatch.setattr(console, "_width", TEST_COLUMNS)
        monkeypatch.setattr(console, "_height", TEST_LINES)


@pytest.fixture(autouse=True)
def no_log_file_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never write to the real log folder; the tests of the log itself turn it back on."""
    monkeypatch.setenv("PEEK_A_FOXY_LOG", "off")


@pytest.fixture(autouse=True)
def isolated_machine(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test sees the developer's home, Firefox profiles, git configuration, XDG folders, pin
    overrides (``FXAC_*``) or display variables.

    A test that forgets to say where its profile is would otherwise read (and, for an install,
    change) the real ``~/.mozilla``. Tests that need a particular home set their own on top of this.
    """
    home = tmp_path_factory.mktemp("home")
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(home))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    # Read by the loader and the doctor (the pin) and by the clipboard detection: a developer who
    # keeps FXAC_COMMIT in their shell, or runs the suite from a desktop session, must get the same
    # result as CI. (PEEK_A_FOXY_FIREFOX stays: only the browser tests read it, and need it.)
    for name in ("FXAC_REPO", "FXAC_COMMIT", "DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"):
        monkeypatch.delenv(name, raising=False)
