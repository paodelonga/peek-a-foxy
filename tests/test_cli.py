import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from peek_a_foxy import __version__, cli
from peek_a_foxy.cli import app

runner = CliRunner()


def snapshot(*roots: Path) -> dict[Path, str]:
    return {p: p.read_text() for root in roots for p in root.rglob("*") if p.is_file()}


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_install_and_uninstall_roundtrip(profile: Path, firefox_dir: Path, fxac_repo: Path):
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert (profile / "chrome" / "autohide.css").is_file()
    assert (firefox_dir / "config.js").is_file()

    result = runner.invoke(app, ["uninstall", "--profile", str(profile), "--yes"])
    assert result.exit_code == 0, result.output
    assert not (profile / "chrome" / "autohide.css").exists()


def test_dry_run_changes_nothing(profile: Path, firefox_dir: Path, fxac_repo: Path):
    before = snapshot(profile, firefox_dir)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert snapshot(profile, firefox_dir) == before


def test_skip_loader_leaves_the_firefox_directory_alone(profile: Path, firefox_dir: Path):
    before = snapshot(firefox_dir)
    result = runner.invoke(
        app,
        [
            "install",
            "--profile",
            str(profile),
            "--firefox-dir",
            str(firefox_dir),
            "--skip-loader",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert snapshot(firefox_dir) == before


def test_snap_builds_are_refused(profile: Path, tmp_path: Path):
    snap = tmp_path / "snap" / "firefox" / "current"
    snap.mkdir(parents=True)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(snap), "--yes"]
    )
    assert result.exit_code == 1
    assert "not supported" in result.output


def test_missing_profile_directory_is_rejected(tmp_path: Path):
    result = runner.invoke(app, ["install", "--profile", str(tmp_path / "nope"), "--yes"])
    assert result.exit_code != 0


def _two_profiles(root: Path, defaults: tuple[str, ...]) -> None:
    sections = "".join(
        f"[Install{i}]\nDefault=Profiles/{name}\n\n" for i, name in enumerate(defaults)
    )
    (root / "profiles.ini").write_text(
        sections
        + "[Profile0]\nName=a\nIsRelative=1\nPath=Profiles/a\n\n"
        + "[Profile1]\nName=b\nIsRelative=1\nPath=Profiles/b\n"
    )
    for name in ("a", "b"):
        (root / "Profiles" / name).mkdir(parents=True)


def test_ambiguous_profiles_are_not_guessed(tmp_path: Path, monkeypatch):
    _two_profiles(tmp_path, defaults=("a", "b"))  # two installs, two different defaults
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    result = runner.invoke(app, ["install", "--skip-loader", "--yes"])
    assert result.exit_code == 1
    assert "cannot tell which profile" in result.output
    assert not (tmp_path / "Profiles" / "a" / "chrome").exists()


def test_a_single_default_profile_is_used(tmp_path: Path, monkeypatch):
    _two_profiles(tmp_path, defaults=("b",))
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    result = runner.invoke(app, ["install", "--skip-loader", "--yes"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Profiles" / "b" / "chrome" / "autohide.css").is_file()
    assert not (tmp_path / "Profiles" / "a" / "chrome").exists()


def test_several_firefox_installations_are_not_guessed(profile: Path, tmp_path: Path, monkeypatch):
    dirs = [tmp_path / "ff1", tmp_path / "ff2"]
    for directory in dirs:
        directory.mkdir()
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: dirs)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--yes"])
    assert result.exit_code == 1
    assert "several Firefox installations" in result.output


# --- -h and shell completion ----------------------------------------------------------------


@pytest.mark.parametrize("args", [["-h"], ["install", "-h"], ["uninstall", "-h"]])
def test_dash_h_is_help_everywhere(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0 and "Usage" in result.output


def _complete(words: str, cword: int, **env: str) -> list[str]:
    """What the shell would be offered, through the command's real completion protocol."""
    result = subprocess.run(
        [sys.executable, "-m", "peek_a_foxy"],
        env={
            **os.environ,
            "_PEEK_A_FOXY_COMPLETE": "complete_bash",
            "COMP_WORDS": words,
            "COMP_CWORD": str(cword),
            **env,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def test_commands_and_options_are_completed():
    assert _complete("peek-a-foxy ", 1) == ["install", "uninstall"]
    assert "--skip-loader" in _complete("peek-a-foxy install --s", 2)
    assert "--dry-run" in _complete("peek-a-foxy uninstall --d", 2)


def test_profile_option_completes_from_profiles_ini(tmp_path: Path):
    ini = "[Profile0]\nName=one\nPath=Profiles/one\n\n[Profile1]\nName=two\nPath=Profiles/two\n"
    # Where Firefox keeps profiles depends on the OS: write both so the test runs everywhere.
    for root in (
        tmp_path / ".mozilla" / "firefox",
        tmp_path / "Library" / "Application Support" / "Firefox",
    ):
        root.mkdir(parents=True)
        (root / "profiles.ini").write_text(ini)
    offered = _complete("peek-a-foxy install --profile ", 3, HOME=str(tmp_path))
    assert any(path.endswith("Profiles/one") for path in offered)
    assert any(path.endswith("Profiles/two") for path in offered)


def test_completion_scripts_are_available_for_the_common_shells():
    # --show-completion detects the parent shell, which is not reliable in CI; the completion
    # protocol itself can be asked for a given shell.
    for shell in ("bash", "zsh", "fish"):
        result = subprocess.run(
            [sys.executable, "-m", "peek_a_foxy"],
            env={**os.environ, "_PEEK_A_FOXY_COMPLETE": f"source_{shell}"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "PEEK_A_FOXY_COMPLETE" in result.stdout, shell


def test_completion_helpers_cope_with_missing_data(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)  # no profiles.ini there
    assert cli._complete_profile("") == []
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: [])
    assert cli._complete_firefox_dir("") == []

    def unsupported():
        raise cli.platform.UnsupportedPlatformError("nope")

    monkeypatch.setattr(cli.platform, "profiles_root", unsupported)
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", unsupported)
    assert cli._complete_profile("") == []
    assert cli._complete_firefox_dir("") == []


def test_firefox_dir_completion_filters_by_prefix(monkeypatch):
    found = [Path("/usr/lib/firefox"), Path("/opt/firefox")]
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: found)
    assert cli._complete_firefox_dir("/usr") == ["/usr/lib/firefox"]


def test_the_yes_help_says_everything_it_skips():
    result = runner.invoke(app, ["install", "--help"])
    flat = " ".join(result.output.replace("│", " ").split())
    help_text = flat.split("--yes -y")[1]
    for skipped in ("confirming", "profile", "Firefox installation"):
        assert skipped in help_text


def test_profile_completion_offers_the_profiles_that_match(tmp_path: Path, monkeypatch):
    _two_profiles(tmp_path, defaults=("a",))
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    offered = cli._complete_profile(str(tmp_path / "Profiles" / "b"))
    assert [name for _, name in offered] == ["b"]


def test_an_installation_without_a_competing_one_is_used_without_asking(
    profile: Path, tmp_path: Path, monkeypatch, fxac_repo
):
    only = tmp_path / "only-firefox"
    only.mkdir()
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: [only])
    result = runner.invoke(app, ["install", "--profile", str(profile), "--yes"])
    assert result.exit_code == 0, result.output
    assert (only / "config.js").is_file()


def test_a_platform_firefox_cannot_be_found_on_is_a_clean_error(profile: Path, monkeypatch):
    def unsupported():
        raise cli.platform.UnsupportedPlatformError("only Linux and macOS")

    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", unsupported)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--yes"])
    assert result.exit_code == 1 and "only Linux and macOS" in result.output


@pytest.mark.parametrize("answer", ["0", "3"])
def test_an_invalid_firefox_number_is_rejected(
    profile: Path, tmp_path: Path, monkeypatch, answer: str
):
    dirs = [tmp_path / "ff1", tmp_path / "ff2"]
    for directory in dirs:
        directory.mkdir()
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: dirs)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--profile", str(profile)], input=f"{answer}\n")
    assert result.exit_code == 1 and "choose a number between 1 and 2" in result.output
    assert not (profile / "chrome" / "autohide.css").exists()


def test_the_package_runs_as_a_module():
    result = subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0 and __version__ in result.stdout


def test_a_lone_profile_is_used_even_when_it_is_not_marked_as_default(tmp_path: Path, monkeypatch):
    (tmp_path / "Profiles" / "solo").mkdir(parents=True)
    (tmp_path / "profiles.ini").write_text("[Profile0]\nName=solo\nPath=Profiles/solo\n")
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    result = runner.invoke(app, ["install", "--skip-loader", "--yes"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Profiles" / "solo" / "chrome" / "autohide.css").is_file()


def test_the_module_entry_point_calls_the_app(monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(sys, "argv", ["peek-a-foxy", "--version"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("peek_a_foxy", run_name="__main__")
    assert stop.value.code == 0 and __version__ in capsys.readouterr().out
