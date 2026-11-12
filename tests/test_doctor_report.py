"""The report: JSON contract, Markdown and table renderings, redaction, saving, clipboard."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from doctor_support import (
    make_context,
    make_firefox,
    make_profile,
    pin_loader,
    write,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rich.console import Console

from peek_a_foxy import doctor, errors, logs, report
from peek_a_foxy.errors import UserFileError
from peek_a_foxy.report import FAIL, OK, WARN, Check, Report, Section

SNAPSHOT = Path(__file__).parent / "snapshots" / "doctor-report.md"
FIXTURE = Path(__file__).parent / "fixtures" / "peekafoxy-status.json"


@pytest.fixture(autouse=True)
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_loader(monkeypatch)


def sample() -> Report:
    bad = Check(
        "x.bad",
        "A bad thing",
        FAIL,
        "value",
        "It is broken.",
        "Fix it.",
        errors.LOADER_MISSING.code,
        "detail text",
    )
    meh = Check("x.meh", "A so-so thing", WARN, "", "Odd.", "Look.", errors.STATUS_MISSING.code)
    fine = Check("x.fine", "A fine thing", OK, "all good")
    return Report("1.0", "2026-01-02T03:04:05Z", (Section("x", "Things", (fine, meh, bad)),))


# --- the model --------------------------------------------------------------------------------


def test_a_problem_needs_a_message_a_hint_and_a_code():
    with pytest.raises(ValueError, match="needs a message"):
        Check("x", "X", WARN)
    with pytest.raises(ValueError, match="needs a message"):
        Check("x", "X", FAIL, message="m", hint="h")


def test_a_check_cannot_have_an_unknown_status_or_an_unregistered_code():
    with pytest.raises(ValueError, match="unknown status"):
        Check("x", "X", "maybe")
    with pytest.raises(ValueError, match="not a registered"):
        Check("x", "X", OK, code="PAF-999")


def test_counts_and_the_verdict():
    result = sample()
    assert result.counts == {"ok": 1, "warn": 1, "fail": 1} and not result.ok
    warnings_only = Section("s", "S", result.sections[0].checks[:2])
    only_warnings = Report("1", "t", (warnings_only,))
    assert only_warnings.ok  # warnings are fine


# --- JSON -------------------------------------------------------------------------------------


def test_the_json_contract_is_pinned():
    data = json.loads(report.to_json(sample()))
    assert report.SCHEMA == 1 and data["schema"] == 1
    assert list(data) == [
        "schema",
        "tool",
        "version",
        "generated",
        "ok",
        "counts",
        "sections",
        "notice",
        "issues_url",
    ]
    assert list(data["sections"][0]) == ["id", "title", "checks"]
    assert list(data["sections"][0]["checks"][0]) == [
        "id",
        "title",
        "status",
        "value",
        "message",
        "hint",
        "code",
        "detail",
    ]
    assert data["tool"] == "peek-a-foxy" and data["ok"] is False
    assert data["counts"] == {"ok": 1, "warn": 1, "fail": 1}
    assert data["notice"] == "Nothing was sent anywhere. Review it, then paste it into your issue."
    assert data["issues_url"] == "https://github.com/paodelonga/peek-a-foxy/issues/new/choose"


def test_the_json_of_a_real_run_keeps_its_ids_and_status_words(tmp_path: Path):
    home = tmp_path / "home"
    make_profile(home)
    ff = make_firefox(home / "ff")
    found = doctor.collect(make_context(home, firefox_candidates=lambda: [ff]))
    data = json.loads(report.to_json(found))
    ids = [c["id"] for s in data["sections"] for c in s["checks"]]
    assert ids == [
        "program.version",
        "program.runs",
        "program.python",
        "program.os",
        "program.admin",
        "program.terminal",
        "program.loader_pin",
        "program.assets",
        "program.loader_files",
        "program.log",
        "firefox.path",
        "firefox.version",
        "firefox.writable",
        "firefox.sandbox",
        "firefox.loader",
        "firefox.autoconfig",
        "firefox.policies",
        "profiles.1",
        "profile.folder",
        "profile.files",
        "profile.utils",
        "profile.import",
        "profile.pref_stylesheets",
        "profile.pref_subdocuments",
        "profile.own_prefs",
        "profile.startup_cache",
        "status.file",
    ]
    assert [s["id"] for s in data["sections"]] == [
        "program",
        "firefox.1",
        "profiles",
        "profile.1",
        "status.1",
    ]
    statuses = {c["status"] for s in data["sections"] for c in s["checks"]}
    assert statuses <= {"ok", "warn", "fail"}


def test_json_is_utf8_and_a_long_detail_is_cut():
    long = Check("x", "X", OK, detail="é" * 1000)
    data = json.loads(report.to_json(Report("1", "t", (Section("s", "S", (long,)),))))
    detail = data["sections"][0]["checks"][0]["detail"]
    assert len(detail) == report.MAX_DETAIL and detail.endswith("...")


# --- Markdown ---------------------------------------------------------------------------------


def test_markdown_has_the_result_tables_what_to_do_and_the_closing_lines():
    text = report.to_markdown(sample())
    assert text.startswith("# Peek-a-Foxy doctor report\n")
    assert "**Result: 1 FAIL, 1 WARN, 1 OK**" in text
    assert "| FAIL | A bad thing | value - It is broken. |" in text
    assert "| OK | A fine thing | all good |" in text
    assert "- **A bad thing** (`PAF-601`): Fix it." in text
    assert text.endswith(
        "Nothing was sent anywhere. Review it, then paste it into your issue.\n"
        "https://github.com/paodelonga/peek-a-foxy/issues/new/choose\n"
    )
    assert "x.bad: detail text" in text


def test_markdown_cannot_be_broken_by_what_a_file_contains():
    nasty = Check("x", "T|itle", OK, "a|b\nline two ```fence")
    detail = Check("y", "Y", OK, detail="```\n# heading ``` | pipe")
    text = report.to_markdown(Report("1", "t", (Section("s", "S|S", (nasty, detail)),)))
    assert "| OK | T\\|itle | a\\|b line two ```fence |" in text
    block = text.split("```text\n")[1].split("\n```\n")[0]
    assert "```" not in block and "\n" not in block  # one line, no way out of the fence


# --- the table --------------------------------------------------------------------------------


def render(parts, width=100) -> str:
    out = io.StringIO()
    console = Console(file=out, width=width, color_system=None, force_terminal=False)
    for part in parts:
        console.print(part)
    return out.getvalue()


def test_the_table_shows_status_words_hints_and_the_closing_lines():
    text = render(report.to_rich(sample()))
    assert "FAIL" in text and "WARN" in text and "OK" in text
    assert "A bad thing [PAF-601] What to do: Fix it." in text
    assert "Result: 1 FAIL, 1 WARN, 1 OK" in text
    assert report.NOTICE in text and report.ISSUES_NEW_URL in text
    assert "detail text" not in text  # technical details only with --verbose
    assert "detail text" in render(report.to_rich(sample(), verbose=True))


def test_the_table_prints_brackets_literally():
    odd = Check("x", "[bold]T[/]", OK, "[red]v[/red]")
    text = render(report.to_rich(Report("1", "t", (Section("s", "[/x]", (odd,)),))))
    assert "[bold]T[/]" in text and "[red]v[/red]" in text and "[/x]" in text


# --- a whole report, as a snapshot ------------------------------------------------------------


def snapshot_report(tmp_path: Path) -> str:
    home = tmp_path / "home"
    profile = make_profile(home)
    (profile / "chrome" / "utils" / "boot.sys.mjs").unlink()
    ff = make_firefox(home / "opt" / "firefox")
    write(
        ff / "defaults" / "pref" / "local-settings.js",
        'pref("general.config.filename", "mozilla.cfg");\n',
    )
    context = make_context(home, firefox_candidates=lambda: [ff], log_target=home / "log" / "p.log")
    found = doctor.collect(context).redacted(logs.Redactor(home=str(home), user=None))
    return _with_slashes(report.to_markdown(found))


def _with_slashes(text: str) -> str:
    """The snapshot spells the redacted paths with "/"; Windows prints them with its own "\\".

    Only the paths under the hidden home (``~\\...``) change, and the Markdown escape of
    ``\\<profile>`` is kept, so every other difference still fails the comparison.
    """
    if os.sep != "\\":
        return text
    return re.sub(
        r"~\\\S*",
        lambda match: match.group(0).replace("\\", "/").replace("//<", "/\\<"),
        text,
    )


def test_a_full_report_reads_as_the_snapshot(tmp_path: Path):
    text = snapshot_report(tmp_path)
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
    assert text == SNAPSHOT.read_text(encoding="utf-8")


# --- redaction --------------------------------------------------------------------------------

words = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=4, max_size=10)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    user=words,
    folder=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=8),
    tail=words,
    pname=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 -_.", min_size=1, max_size=14),
)
def test_the_home_user_profile_folder_and_profile_name_never_appear_in_any_format(
    user, folder, tail, pname
):
    name = f"zq{user}"
    # The name a person chose for a profile (a personal one). A name of one or two characters is
    # never hidden (it would blank ordinary words), so the generated one always has three or more.
    chosen = f"zq{pname.strip() or 'n'}"
    with tempfile.TemporaryDirectory() as root:
        home = Path(root) / "users" / name
        profile = make_profile(home, folder=f"{folder}.qx{tail}", name=chosen)
        ff = make_firefox(home / "apps" / "firefox")
        (profile / "chrome" / "peekafoxy-status.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "updated": "2026-11-05T00:00:00Z",
                    "errors": [
                        {
                            "level": "error",
                            "where": f"in {chosen}",
                            "message": f"failed in {profile} for {chosen}",
                        }
                    ],
                    "health": {"a": f"fail: {home}/x and {chosen}"},
                }
            )
        )
        context = make_context(
            home,
            firefox_candidates=lambda: [ff],
            log_target=home / ".local" / "state" / "peek-a-foxy" / "peek-a-foxy.log",
        )
        collected = doctor.collect(context)
        assert collected.profile_names == (chosen,)
        found = collected.redacted(
            logs.Redactor(home=str(home), user=name, profile_names=collected.profile_names)
        )
        outputs = [
            report.to_json(found),
            report.to_markdown(found),
            render(report.to_rich(found, verbose=True), width=400),
        ]
        for text in outputs:
            assert str(home) not in text
            assert name not in text
            assert f"{folder}.qx{tail}" not in text
            assert chosen not in text
        assert "~" in outputs[1] and "<profile>" in outputs[1] and "<profile 1>" in outputs[1]


def test_windows_spellings_of_the_home_are_hidden_in_the_json_too():
    home = "C:\\Users\\ChrisExample"
    check = Check(
        "x", "X", OK, f"{home}\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\abcd1234.default"
    )
    found = Report("1", "t", (Section("s", "S", (check,)),)).redacted(
        logs.Redactor(home=home, user="ChrisExample", ignore_case=True)
    )
    text = report.to_json(found)
    assert "ChrisExample" not in text and "<profile>" in text and json.loads(text)


# --- saving -----------------------------------------------------------------------------------


def test_the_default_name_is_the_time_and_is_never_one_that_exists(tmp_path: Path):
    now = datetime(2026, 11, 5, 12, 30, 45, tzinfo=timezone.utc)
    first = report.default_save_path(tmp_path, "md", now)
    assert first == tmp_path / "doctor-20261105-123045.md"
    first.write_text("x")
    second = report.default_save_path(tmp_path, "md", now)
    assert second == tmp_path / "doctor-20261105-123045-2.md"
    second.write_text("y")
    assert report.default_save_path(tmp_path, "md", now).name.endswith("-3.md")


def test_saving_writes_utf8_with_lf_and_makes_the_folder(tmp_path: Path):
    path = report.save("a\nb é\n", tmp_path / "new" / "folder" / "r.md")
    assert path.read_bytes() == "a\nb é\n".encode()


def test_saving_never_replaces_a_file(tmp_path: Path):
    path = tmp_path / "r.md"
    path.write_text("precious")
    with pytest.raises(UserFileError) as caught:
        report.save("new", path)
    assert caught.value.code is errors.FILE_EXISTS and "already exists." in caught.value.message
    assert path.read_text() == "precious"


# --- the clipboard ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "environ", "expected"),
    [
        ("windows", {}, [["clip"]]),
        ("macos", {}, [["pbcopy"]]),
        ("linux", {}, []),
        ("linux", {"WAYLAND_DISPLAY": "w"}, [["wl-copy"]]),
        ("linux", {"DISPLAY": ":0"}, [["xclip", "-selection", "clipboard"]]),
        (
            "linux",
            {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"},
            [["wl-copy"], ["xclip", "-selection", "clipboard"]],
        ),
    ],
)
def test_which_tools_each_system_offers(kind, environ, expected):
    assert [c for c, _ in report.clipboard_commands(kind, environ)] == expected


class Recorder:
    def __init__(self, fail: set[str] = frozenset()):
        self.calls: list[tuple[list[str], bytes]] = []
        self.fail = fail

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs["input"]))
        if command[0] in self.fail:
            raise subprocess.CalledProcessError(1, command)
        assert kwargs["timeout"] and kwargs["check"]  # never hangs, never ignores a failure
        assert kwargs["stdout"] is subprocess.DEVNULL  # a forking tool must not hold a pipe


def have(*names):
    return lambda name: f"/bin/{name}" if name in names else None


def test_the_first_tool_that_works_gets_the_text():
    run = Recorder()
    env = {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}
    used = report.copy_to_clipboard("héllo", "linux", env, which=have("wl-copy", "xclip"), run=run)
    assert used == "wl-copy" and run.calls == [(["wl-copy"], "héllo".encode())]


def test_a_missing_tool_is_skipped_and_a_failing_one_falls_through():
    env = {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}
    run = Recorder()
    assert report.copy_to_clipboard("x", "linux", env, which=have("xclip"), run=run) == "xclip"
    run = Recorder(fail={"wl-copy"})
    assert (
        report.copy_to_clipboard("x", "linux", env, which=have("wl-copy", "xclip"), run=run)
        == "xclip"
    )
    assert [c[0][0] for c in run.calls] == ["wl-copy", "xclip"]


def test_a_tool_that_cannot_start_is_not_an_error():
    def broken(command, **kwargs):
        raise FileNotFoundError(command[0])

    assert report.copy_to_clipboard("x", "macos", {}, which=have("pbcopy"), run=broken) is None


def test_no_tool_at_all_gives_none_so_the_caller_can_print():
    assert report.copy_to_clipboard("x", "linux", {"DISPLAY": ":0"}, which=have()) is None
    assert report.copy_to_clipboard("x", "linux", {}, which=have("xclip")) is None


def test_windows_clip_gets_utf16_with_a_byte_order_mark():
    run = Recorder()
    assert report.copy_to_clipboard("é", "windows", {}, which=have("clip"), run=run) == "clip"
    assert (
        run.calls[0][1][:2] in (b"\xff\xfe", b"\xfe\xff")
        and "é".encode("utf-16-le") in run.calls[0][1]
    )


def test_the_real_runner_is_subprocess_run(tmp_path: Path):
    """A tool that exists gets the text on stdin (a stand-in script, not a real clipboard)."""
    script = tmp_path / "grab.py"
    out = tmp_path / "grabbed"
    script.write_text(f"import sys; open({str(out)!r}, 'wb').write(sys.stdin.buffer.read())\n")
    import sys

    commands = [([sys.executable, str(script)], "utf-8")]
    from unittest import mock

    with mock.patch.object(report, "clipboard_commands", return_value=commands):
        used = report.copy_to_clipboard("hello", "linux", {}, which=lambda n: n)
    assert used == sys.executable and out.read_bytes() == b"hello"


def test_the_notice_text_is_the_agreed_one():
    assert re.fullmatch(
        r"Nothing was sent anywhere\. Review it, then paste it into your issue\.", report.NOTICE
    )
