"""What the CLI tells the user at the end: the closing panel and what a failure left behind."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from peek_a_foxy import cli
from peek_a_foxy.cli import app
from peek_a_foxy.installer import Plan

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.ui.console, "_width", 500)
    monkeypatch.setattr(cli.ui.errors, "_width", 500)


def install(profile: Path, firefox: Path | None, *extra: str):
    args = ["install", "--profile", str(profile), "--yes", *extra]
    args += ["--skip-loader"] if firefox is None else ["--firefox-dir", str(firefox)]
    return runner.invoke(app, args)


# --- the closing panel says what is actually true ---------------------------------------------


def test_a_complete_install_has_no_caveat(profile: Path, firefox_dir: Path, fxac_repo: Path):
    result = install(profile, firefox_dir)
    assert result.exit_code == 0, result.output
    assert "Done" in result.output and "Close all Firefox windows" in result.output
    assert "--skip-loader" not in result.output and "caveat" not in result.output


def test_skipping_the_loader_is_not_reported_as_all_fine(profile: Path):
    result = install(profile, None)
    assert result.exit_code == 0, result.output
    panel = result.output.split("╭")[-1]
    assert "Installed, with a caveat" in panel
    assert "--skip-loader" in panel and "fx-autoconfig" in panel


def test_a_conflicting_loader_is_not_reported_as_all_fine(
    profile: Path, firefox_dir: Path, fxac_repo: Path
):
    (firefox_dir / "config.js").write_text("// somebody else's setup\n")
    result = install(profile, firefox_dir)
    assert result.exit_code == 0, result.output
    assert "warning:" in result.output
    panel = result.output.split("╭")[-1]
    assert "Installed, with a caveat" in panel
    assert "left untouched" in panel and "Turn them on with" not in panel
    assert (firefox_dir / "config.js").read_text() == "// somebody else's setup\n"


@pytest.mark.parametrize(
    ("skipped_loader", "loader_conflict", "caveat"),
    [(False, False, False), (True, False, True), (False, True, True), (True, True, True)],
)
def test_the_caveats_are_decided_by_what_happened(skipped_loader, loader_conflict, caveat):
    title, body = cli.done_summary(skipped_loader, loader_conflict)
    assert ("caveat" in title) is caveat
    assert ("--skip-loader" in body) is skipped_loader
    assert ("Turn them on with" in body) is (not caveat)


# --- a failure says what was left behind --------------------------------------------------------


def break_the_second_step(profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Writing userChrome.css is refused: the @import step fails after the files were copied."""

    def refused(path: Path, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr("peek_a_foxy.installer._write", refused)


def test_a_failure_in_the_middle_says_which_steps_were_done(profile: Path, monkeypatch):
    break_the_second_step(profile, monkeypatch)
    result = install(profile, None)
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert (profile / "chrome" / "autohide.css").is_file()  # step 1 really ran
    assert "1 of 3 steps finished" in result.output
    assert "Copy autohide.css, autohide.uc.js" in result.output  # which one
    assert "Running the same command again is safe" in result.output


def test_a_failure_before_any_step_finished_says_so(profile: Path, monkeypatch):
    def fail_copy(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("peek_a_foxy.installer.shutil.copyfile", fail_copy)
    result = install(profile, None)
    assert result.exit_code == 1
    assert "No step had finished" in result.output
    assert "Running the same command again is safe" in result.output


def test_a_failure_in_uninstall_is_reported_the_same_way(profile: Path, monkeypatch):
    install(profile, None)

    def broken(text: str) -> str:
        raise OSError("disk on fire")

    monkeypatch.setattr("peek_a_foxy.installer.userfiles.without_css_import", broken)
    result = runner.invoke(app, ["uninstall", "--profile", str(profile), "--yes"])
    assert result.exit_code == 1
    assert "2 of 4 steps finished" in result.output  # the status file step is the second


def test_the_failed_step_is_named_in_odd_paths_literally(tmp_path: Path, monkeypatch):
    profile = tmp_path / "[/x]"
    (profile / "chrome").mkdir(parents=True)
    break_the_second_step(profile, monkeypatch)
    result = install(profile, None)
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "1 of 3 steps finished" in result.output


def test_the_plan_remembers_what_it_finished(profile: Path):
    plan = Plan()
    plan.add("one", lambda: None)
    plan.add("two", lambda: (_ for _ in ()).throw(OSError("boom")))
    plan.add("three", lambda: None)
    with pytest.raises(OSError):
        plan.execute()
    assert [step.description for step in plan.completed] == ["one"]
