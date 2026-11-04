from pathlib import Path

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
