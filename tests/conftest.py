import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def fxac_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal local stand-in for fx-autoconfig, wired in through the env overrides."""
    repo = tmp_path / "fxac-fixture"
    (repo / "program" / "defaults" / "pref").mkdir(parents=True)
    (repo / "profile" / "chrome" / "utils").mkdir(parents=True)
    (repo / "program" / "config.js").write_text("// loader\n")
    (repo / "program" / "defaults" / "pref" / "config-prefs.js").write_text("pref(1);\n")
    (repo / "profile" / "chrome" / "utils" / "boot.sys.mjs").write_text("boot\n")
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
    return path


@pytest.fixture(autouse=True)
def plain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """No colors, whatever the environment (CI sets FORCE_COLOR): tests compare plain text."""
    from peek_a_foxy import ui

    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")  # Typer's own output and subprocesses
    monkeypatch.setattr(ui.console, "_color_system", None)
    monkeypatch.setattr(ui.errors, "_color_system", None)


@pytest.fixture(autouse=True)
def no_log_file_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never write to the real log folder; the tests of the log itself turn it back on."""
    monkeypatch.setenv("PEEK_A_FOXY_LOG", "off")
