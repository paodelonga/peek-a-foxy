"""``peek-a-foxy doctor`` at the command line: formats, exit codes, saving, copying, redaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from doctor_support import make_context, make_firefox, make_profile, pin_loader
from typer.testing import CliRunner

from peek_a_foxy import cli, doctor, errors, logs, report
from peek_a_foxy.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_loader(monkeypatch)


@pytest.fixture(autouse=True)
def wide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.ui.console, "_width", 200)
    monkeypatch.setattr(cli.ui.errors, "_width", 200)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def machine(monkeypatch: pytest.MonkeyPatch, home: Path, **overrides) -> None:
    """Make the command look at the fake machine instead of this one."""
    firefox = make_firefox(home / "ff")
    values = {"firefox_candidates": lambda: [firefox], "environ": {"HOME": str(home)}}
    values.update(overrides)
    monkeypatch.setattr(
        doctor.Context, "detect", classmethod(lambda cls, **kw: make_context(home, **values))
    )
    monkeypatch.setattr(
        logs.Redactor,
        "for_this_machine",
        classmethod(lambda cls, *a, **k: logs.Redactor(home=str(home), user=None)),
    )


@pytest.fixture
def healthy(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A machine where everything is fine except that Firefox has not run the script (a warning)."""
    profile = make_profile(home)
    machine(monkeypatch, home)
    return profile


@pytest.fixture
def broken(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    profile = make_profile(home)
    (profile / "chrome" / "autohide.css").unlink()
    machine(monkeypatch, home)
    return profile


# --- formats and exit codes -------------------------------------------------------------------


def test_with_nothing_wrong_but_warnings_the_exit_code_is_zero(healthy: Path):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "WARN" in result.output  # Firefox has not run the script yet


def test_any_fail_makes_the_exit_code_one(broken: Path):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == errors.EXIT_FAILURE
    assert "PAF-606" in result.output


def test_piped_output_is_markdown_and_ends_with_the_notice_and_the_link(healthy: Path):
    result = runner.invoke(app, ["doctor"])
    assert result.output.startswith("# Peek-a-Foxy doctor report")
    assert result.output.endswith(
        "Nothing was sent anywhere. Review it, then paste it into your issue.\n"
        "https://github.com/paodelonga/peek-a-foxy/issues/new/choose\n"
    )


def test_markdown_can_be_asked_for_on_a_terminal_too(
    home: Path, monkeypatch: pytest.MonkeyPatch, healthy: Path
):
    machine(monkeypatch, home, is_tty=True)
    assert runner.invoke(app, ["doctor", "--markdown"]).output.startswith("# Peek-a-Foxy")


def test_on_a_terminal_the_default_is_the_friendly_table(
    home: Path, monkeypatch: pytest.MonkeyPatch, healthy: Path
):
    machine(monkeypatch, home, is_tty=True)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Result: 0 FAIL" in result.output and "┏" in result.output
    assert "# Peek-a-Foxy doctor report" not in result.output


def test_verbose_shows_the_technical_details_in_the_table(
    home: Path, monkeypatch: pytest.MonkeyPatch, healthy: Path
):
    machine(monkeypatch, home, is_tty=True)
    assert "executable /usr/bin/python3" not in runner.invoke(app, ["doctor"]).output
    assert "executable /usr/bin/python3" in runner.invoke(app, ["doctor", "-v"]).output


def test_json_is_valid_stable_and_has_nothing_else_on_stdout(healthy: Path):
    result = runner.invoke(app, ["doctor", "--json"])
    data = json.loads(result.output)
    assert data["schema"] == 1 and data["ok"] is True and data["counts"]["fail"] == 0


def test_json_and_markdown_together_are_a_usage_error(healthy: Path):
    result = runner.invoke(app, ["doctor", "--json", "--markdown"])
    assert result.exit_code == errors.EXIT_USAGE and "but not both" in result.output


def test_the_failing_report_still_prints_before_the_exit_code(broken: Path):
    data = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    assert data["ok"] is False and data["counts"]["fail"] == 1


def test_a_given_profile_and_firefox_dir_are_used(home: Path, monkeypatch: pytest.MonkeyPatch):
    profile = make_profile(home, with_ini=False)
    ff = make_firefox(home / "other-ff")
    machine(monkeypatch, home, firefox_candidates=lambda: [])
    result = runner.invoke(
        app, ["doctor", "--json", "--profile", str(profile), "--firefox-dir", str(ff)]
    )
    data = json.loads(result.output)
    ids = {c["id"]: c["status"] for s in data["sections"] for c in s["checks"]}
    assert ids["profile.files"] == "ok" and ids["firefox.loader"] == "ok"
    assert ids["profiles.ini"] == "warn" and result.exit_code == 0


def test_a_profile_that_does_not_exist_is_refused_by_the_option_itself(healthy: Path, home: Path):
    result = runner.invoke(app, ["doctor", "--profile", str(home / "nowhere")])
    assert result.exit_code == errors.EXIT_USAGE


# --- nothing leaves unredacted ----------------------------------------------------------------


def test_the_home_folder_is_hidden_in_every_format(healthy: Path, home: Path):
    for flags in ([], ["--json"], ["--markdown"]):
        output = runner.invoke(app, ["doctor", *flags]).output
        assert str(home) not in output and "~" in output
        assert healthy.name not in output  # the profile folder name


def test_what_the_save_message_says_is_for_the_person_but_the_file_is_redacted(
    healthy: Path, home: Path, tmp_path: Path
):
    target = tmp_path / "out" / "r.md"
    result = runner.invoke(app, ["doctor", "--save", str(target)])
    assert result.exit_code == 0 and f"The report was saved to {target}." in result.output
    text = target.read_text(encoding="utf-8")
    assert str(home) not in text and healthy.name not in text


# --- saving -----------------------------------------------------------------------------------


def test_save_with_a_path_writes_the_same_text_it_prints(healthy: Path, tmp_path: Path):
    target = tmp_path / "r.json"
    result = runner.invoke(app, ["doctor", "--json", "--save", str(target)])
    printed = result.output.split("The report was saved")[0]
    assert json.loads(target.read_text()) == json.loads(printed)


def test_save_never_replaces_an_existing_file(healthy: Path, tmp_path: Path):
    target = tmp_path / "r.md"
    target.write_text("precious")
    result = runner.invoke(app, ["doctor", "--save", str(target)])
    assert result.exit_code == errors.EXIT_FAILURE
    assert "error [PAF-403]" in result.output and "What to do:" in result.output
    assert target.read_text() == "precious"


def test_save_into_a_folder_picks_a_dated_name(healthy: Path, tmp_path: Path):
    result = runner.invoke(app, ["doctor", "--save", str(tmp_path)])
    assert result.exit_code == 0
    assert [p.name for p in tmp_path.glob("doctor-*.md")] == ["doctor-20261105-120000.md"]


def test_save_without_a_path_goes_next_to_the_log(
    healthy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli, "_default_save_folder", lambda: tmp_path / "logfolder")
    assert runner.invoke(app, ["doctor", "--save"]).exit_code == 0
    assert runner.invoke(app, ["doctor", "--json", "--save"]).exit_code == 0
    names = sorted(p.name for p in (tmp_path / "logfolder").iterdir())
    assert names == ["doctor-20261105-120000.json", "doctor-20261105-120000.md"]
    # a second run in the same second does not replace the first
    runner.invoke(app, ["doctor", "--save"])
    assert len(list((tmp_path / "logfolder").glob("*.md"))) == 2


def test_the_default_place_is_the_log_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(logs, "default_kind", lambda: "linux")
    assert cli._default_save_folder() == tmp_path / "state" / "peek-a-foxy"


# --- copying ----------------------------------------------------------------------------------


def test_copy_puts_the_markdown_on_the_clipboard_and_says_so(
    healthy: Path, monkeypatch: pytest.MonkeyPatch
):
    copied: list[str] = []

    def fake(text, kind, environ, *, which, run=None):
        copied.append(text)
        return "wl-copy"

    monkeypatch.setattr(report, "copy_to_clipboard", fake)
    result = runner.invoke(app, ["doctor", "--copy"])
    assert (
        result.exit_code == 0
        and "The report was copied to the clipboard with wl-copy" in result.output
    )
    assert copied[0].startswith("# Peek-a-Foxy doctor report") and "~" in copied[0]


def test_copy_with_json_copies_json(healthy: Path, monkeypatch: pytest.MonkeyPatch):
    copied: list[str] = []
    monkeypatch.setattr(
        report, "copy_to_clipboard", lambda text, *a, **k: copied.append(text) or "clip"
    )
    runner.invoke(app, ["doctor", "--json", "--copy"])
    assert json.loads(copied[0])["schema"] == 1


def test_without_a_clipboard_tool_the_report_is_printed_and_the_person_told(
    healthy: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(report, "copy_to_clipboard", lambda *a, **k: None)
    result = runner.invoke(app, ["doctor", "--copy"])
    assert result.exit_code == 0
    assert (
        "could not be copied to the clipboard" in result.output
        and "copy it yourself" in result.output
    )
    assert result.output.count("# Peek-a-Foxy doctor report") == 1


def test_on_a_terminal_a_failed_copy_still_prints_the_text_to_copy(
    home: Path, monkeypatch: pytest.MonkeyPatch, healthy: Path
):
    machine(monkeypatch, home, is_tty=True)
    monkeypatch.setattr(report, "copy_to_clipboard", lambda *a, **k: None)
    result = runner.invoke(app, ["doctor", "--copy"])
    assert "┏" in result.output  # the friendly table, then the pasteable text
    assert result.output.count("# Peek-a-Foxy doctor report") == 1


def test_copy_uses_the_real_tools_of_the_machine_description(
    healthy: Path, home: Path, monkeypatch: pytest.MonkeyPatch
):
    seen = {}

    def fake(text, kind, environ, *, which, run=None):
        seen.update(kind=kind, display=environ.get("HOME"), which=which("wl-copy"))
        return None

    monkeypatch.setattr(report, "copy_to_clipboard", fake)
    runner.invoke(app, ["doctor", "--copy"])
    assert seen["kind"] == "linux" and seen["display"] == str(home) and seen["which"]


# --- the log and read-only behaviour ---------------------------------------------------


def test_doctor_writes_a_log_line_per_check_and_nothing_else(
    healthy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    log = tmp_path / "logs" / "peek-a-foxy.log"
    monkeypatch.setenv(logs.ENV_VAR, str(log))
    assert runner.invoke(app, ["doctor"]).exit_code == 0
    text = log.read_text(encoding="utf-8")
    assert "doctor: program.version ok" in text and "doctor: status.file warn" in text


def test_the_log_flags_work_after_the_command_name(healthy: Path, tmp_path: Path):
    log = tmp_path / "mine.log"
    assert runner.invoke(app, ["doctor", "--log-file", str(log)]).exit_code == 0
    assert "run started" in log.read_text(encoding="utf-8")
    other = tmp_path / "none.log"
    assert runner.invoke(app, ["--log-file", str(other), "doctor", "--no-log"]).exit_code == 0
    assert not other.exists()


def test_doctor_never_changes_the_firefox_files(healthy: Path, home: Path):
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    runner.invoke(app, ["doctor"])
    runner.invoke(app, ["doctor", "--json", "--no-log"])
    assert {p: p.read_bytes() for p in home.rglob("*") if p.is_file()} == before


def test_the_command_is_listed_in_help():
    result = runner.invoke(app, ["--help"])
    assert "doctor" in result.output
    assert "--save" in runner.invoke(app, ["doctor", "--help"]).output
