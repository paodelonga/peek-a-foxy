"""User text (paths, git output) must reach the terminal as typed, never as Rich markup."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from peek_a_foxy import cli
from peek_a_foxy.cli import app

runner = CliRunner()

# Directory names that Rich would read as markup: a style, a closing tag with no opening one, an
# emoji code, a link, an unbalanced bracket, and a plain backslash before a bracket.
ODD_NAMES = [
    "[bold red]p",
    "[/x]",
    "[red]a[/red]",
    ":fox_face:",
    "[link=http://x]y",
    "a[",
    "x\\[b]",
]


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wide enough that a path is never folded, so it can be compared as a whole."""
    monkeypatch.setattr(cli.ui.console, "_width", 500)
    monkeypatch.setattr(cli.ui.errors, "_width", 500)


def odd_profile(tmp_path: Path, name: str) -> Path:
    profile = tmp_path / name
    (profile / "chrome").mkdir(parents=True)
    return profile


@pytest.mark.parametrize("name", ODD_NAMES)
def test_the_plan_shows_odd_paths_literally(tmp_path: Path, name: str):
    profile = odd_profile(tmp_path, name)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--skip-loader", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert f"Install into {profile}" in result.output
    assert f"into {profile / 'chrome'}" in result.output


@pytest.mark.parametrize("name", ODD_NAMES)
def test_applying_announces_odd_paths_literally(tmp_path: Path, name: str):
    profile = odd_profile(tmp_path, name)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 0, result.output
    assert f"into {profile / 'chrome'}" in result.output
    assert (profile / "chrome" / "autohide.css").is_file()


@pytest.mark.parametrize("name", ODD_NAMES)
def test_errors_show_odd_paths_literally(tmp_path: Path, name: str):
    profile = odd_profile(tmp_path, name)
    css = profile / "chrome" / "userChrome.css"
    css.write_bytes(b"\xff\xfe\x00")
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 1
    assert str(css) in result.output
    assert "MarkupError" not in result.output and "Traceback" not in result.output


@pytest.mark.parametrize("name", ODD_NAMES)
def test_uninstall_shows_odd_paths_literally(tmp_path: Path, name: str):
    profile = odd_profile(tmp_path, name)
    result = runner.invoke(app, ["uninstall", "--profile", str(profile), "--yes"])
    assert result.exit_code == 0, result.output
    assert f"Uninstall from {profile}" in result.output


@pytest.mark.parametrize("name", ODD_NAMES)
def test_the_profile_picker_shows_odd_names_and_paths_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
):
    profile = tmp_path / "Profiles" / name
    profile.mkdir(parents=True)
    other = tmp_path / "Profiles" / "other"
    other.mkdir()
    (tmp_path / "profiles.ini").write_text(
        f"[Profile0]\nName={name}\nPath=Profiles/{name}\n\n[Profile1]\nName=b\nPath=Profiles/other\n"
    )
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--skip-loader"], input="1\ny\n")
    assert result.exit_code == 0, result.output
    assert str(profile) in result.output and name in result.output


@pytest.mark.parametrize("name", ODD_NAMES)
def test_the_firefox_picker_and_sandbox_error_show_odd_paths_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
):
    profile = odd_profile(tmp_path, "p")
    dirs = [tmp_path / name, tmp_path / "ff2"]
    for directory in dirs:
        directory.mkdir(parents=True)
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: dirs)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--profile", str(profile)], input="1\ny\n")
    assert str(dirs[0]) in result.output  # in the picker

    result = runner.invoke(app, ["install", "--profile", str(profile), "--yes"])
    assert result.exit_code == 1
    assert str(dirs[0]) in result.output and str(dirs[1]) in result.output  # in the error


@pytest.mark.parametrize("name", ODD_NAMES)
def test_warnings_show_odd_paths_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, fxac_repo: Path
):
    profile = odd_profile(tmp_path, "p")
    firefox = tmp_path / name
    firefox.mkdir(parents=True)
    (firefox / "config.js").write_text("// somebody else's loader\n")
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox), "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert str(firefox / "config.js") in result.output


def test_git_output_with_brackets_is_shown_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = odd_profile(tmp_path, "p")
    firefox = tmp_path / "ff"
    firefox.mkdir(parents=True)
    monkeypatch.setenv("FXAC_REPO", str(tmp_path / "no-such-[/bold]-repo"))
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox), "--yes"]
    )
    assert result.exit_code == 1
    assert "no-such-[/bold]-repo" in result.output and "Traceback" not in result.output


@pytest.mark.parametrize("option", ["--profile", "--firefox-dir"])
@pytest.mark.parametrize("name", ["[/x]nope", "[bold red]nope"])
def test_typers_own_errors_show_odd_paths_literally(tmp_path: Path, option: str, name: str):
    missing = tmp_path / name
    result = runner.invoke(app, ["install", option, str(missing), "--yes"])
    assert result.exit_code == 2 and "Traceback" not in result.output
    # Typer draws this error in an 80-column box, so compare without the wrapping.
    flat = "".join(result.output.replace("│", "").split())
    assert "".join(name.split()) in flat
