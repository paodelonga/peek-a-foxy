"""Hostile input at the command line and in the readers of Firefox's files (PF-06, 20, 21, 27).

Adversarial throughout: hand-edited ``profiles.ini``, Ctrl-C half way through a plan, a report path
that starts with ``-``, messages that must read as sentences.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support import needs_symlinks, squeezed
from typer.testing import CliRunner

from peek_a_foxy import doctor, errors, installer, platform, report
from peek_a_foxy.cli import app
from peek_a_foxy.errors import DiscoveryError, PeekError
from peek_a_foxy.profiles import read_profiles

runner = CliRunner()

# --- PF-06: a malformed IsRelative is a message, not a bug ----------------------------------------


@pytest.mark.parametrize("value", ["", "maybe", "2", "yes please", "é", " ", "1.0"])
def test_a_malformed_isrelative_is_a_coded_error_for_every_command(
    tmp_path: Path, monkeypatch, value: str
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    firefox = tmp_path / "home" / ".mozilla" / "firefox"
    firefox.mkdir(parents=True)
    # Where this system's Firefox keeps profiles.ini differs (macOS, Windows): name this folder.
    monkeypatch.setattr(platform, "profiles_root", lambda: firefox)
    (firefox / "profiles.ini").write_text(
        f"[Profile0]\nName=x\nPath=p1\nIsRelative={value}\nDefault=1\n", encoding="utf-8"
    )
    (tmp_path / "home" / ".mozilla" / "firefox" / "p1").mkdir()
    for command in ("install", "uninstall"):
        result = runner.invoke(app, [command, "--yes", "--dry-run"])
        assert result.exit_code == 1, result.output
        assert errors.PROFILES_UNREADABLE.code in result.output
        assert errors.UNEXPECTED.code not in result.output and "Traceback" not in result.output


def test_isrelative_that_is_fine_still_works(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text("[Profile0]\nName=x\nPath=p\nIsRelative=0\n")
    assert read_profiles(tmp_path)[0].path == Path("p")
    (tmp_path / "profiles.ini").write_text("[Profile0]\nName=x\nPath=p\nIsRelative=yes\n")
    assert read_profiles(tmp_path)[0].path == tmp_path / "p"


ini_pieces = st.sampled_from(
    [
        "[Profile0]",
        "[Profile1]",
        "[Install4F96]",
        "[General]",
        "Name=x",
        "Path=p1",
        "Path=",
        "IsRelative=",
        "IsRelative=1",
        "IsRelative=maybe",
        "Default=1",
        "Default=",
        "Default=Profiles/p",
        "=",
        "x",
        "[",
        "]",
        ";c",
        "#c",
        " ",
        "﻿",
    ]
)


@settings(max_examples=500, deadline=None)
@given(lines=st.lists(ini_pieces, max_size=14), sep=st.sampled_from(["\n", "\r\n", "\n\n"]))
def test_any_profiles_ini_gives_profiles_or_a_coded_error_and_nothing_else(
    tmp_path_factory, lines, sep
):
    """The fuzz that found PF-06, kept: no profiles.ini may end in a plain exception."""
    root = tmp_path_factory.mktemp("ini")
    (root / "profiles.ini").write_text(sep.join(lines), encoding="utf-8")
    try:
        found = read_profiles(root)
    except PeekError as error:
        assert isinstance(error, DiscoveryError) and error.code.code.startswith("PAF-1")
    else:
        assert found


def test_random_bytes_as_profiles_ini_are_a_coded_error(tmp_path: Path):
    (tmp_path / "profiles.ini").write_bytes(b"\xff\xfe\x00[Profile0]\x00\xc3\x28")
    with pytest.raises(DiscoveryError) as caught:
        read_profiles(tmp_path)
    assert caught.value.code is errors.PROFILES_UNREADABLE


def test_the_text_that_an_error_quotes_is_cut_short(tmp_path: Path):
    (tmp_path / "profiles.ini").write_text("a" * 300_000)
    with pytest.raises(DiscoveryError) as caught:
        read_profiles(tmp_path)
    assert len(caught.value.detail) < 1_000 and "more characters" in caught.value.detail


def test_clip_leaves_short_text_alone_and_says_how_much_was_cut():
    assert errors.clip("short") == "short"
    cut = errors.clip("x" * 1_000, 10)
    assert cut.startswith("x" * 10) and "990 more characters" in cut


# --- no home folder is a situation to explain, not a bug (review 3, F-M3) ------------------------


@pytest.fixture
def without_a_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Path.home()`` raises, as for a service account or a container with no passwd entry."""

    def cannot(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(cannot))


@pytest.mark.parametrize("args", [["install", "--skip-loader"], ["uninstall"]])
def test_without_a_home_folder_the_commands_ask_for_a_profile_instead_of_crashing(
    without_a_home, args: list[str]
):
    result = runner.invoke(app, [*args, "--yes"])
    assert result.exit_code == errors.EXIT_FAILURE, result.output
    assert errors.NO_PROFILES_INI.code in result.output and "--profile" in result.output
    assert errors.UNEXPECTED.code not in result.output and "Traceback" not in result.output


def test_without_a_home_folder_a_profile_given_by_hand_still_works(without_a_home, profile: Path):
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 0, result.output
    assert (profile / "chrome" / "autohide.css").is_file()


@pytest.mark.parametrize("args", [["doctor", "--json"], ["logs"], ["doctor", "--markdown"]])
def test_without_a_home_folder_doctor_and_logs_still_answer(without_a_home, args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code in (0, errors.EXIT_FAILURE), result.output
    assert errors.UNEXPECTED.code not in result.output


def test_shell_completion_without_a_home_folder_offers_nothing_and_does_not_fail(without_a_home):
    from peek_a_foxy import cli

    assert cli._complete_profile("") == []


# --- a NUL byte in profiles.ini is a damaged file, not a bug (review 3, F-M4) -------------------


def firefox_folder(tmp_path: Path, monkeypatch, ini: bytes) -> Path:
    home = tmp_path / "home"
    folder = home / ".mozilla" / "firefox"
    folder.mkdir(parents=True)
    (folder / "profiles.ini").write_bytes(ini)
    monkeypatch.setenv("HOME", str(home))
    # Where this system's Firefox keeps profiles.ini differs (macOS, Windows): name this folder.
    monkeypatch.setattr(platform, "profiles_root", lambda: folder)
    return folder


@pytest.mark.parametrize(
    "ini",
    [
        b"[Profile0]\nName=x\nPath=ab\x00cd\nDefault=1\n",
        b"[Profile0]\nName=x\nPath=\x00\nIsRelative=0\n",
        b"[Profile0]\nName=x\nPath=/tmp/\x00/../etc\nIsRelative=0\n",
        b"[Profile0]\nName=ok\nPath=fine\n[Profile1]\nName=bad\nPath=a\x00b\n",
    ],
)
def test_a_nul_byte_in_a_profile_path_is_a_coded_error_for_every_command(
    tmp_path: Path, monkeypatch, ini: bytes
):
    firefox_folder(tmp_path, monkeypatch, ini)
    with pytest.raises(DiscoveryError) as caught:
        read_profiles(tmp_path / "home" / ".mozilla" / "firefox")
    assert caught.value.code is errors.PROFILES_UNREADABLE
    for args in (
        ["install", "--yes", "--skip-loader"],
        ["install", "--yes", "--skip-loader", "--dry-run"],
        ["uninstall", "--yes"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == errors.EXIT_FAILURE, (args, result.output)
        assert errors.PROFILES_UNREADABLE.code in result.output
        assert errors.UNEXPECTED.code not in result.output and "Traceback" not in result.output


path_texts = st.lists(
    st.sampled_from(
        ["a", "b", "/", "\\", ".", "..", " ", "\x00", "\u202e", "\u200f", "~", "%", "é", "-", ":"]
    ),
    max_size=12,
).map("".join)


@settings(max_examples=250, deadline=None)
@given(
    path=path_texts,
    relative=st.sampled_from(["0", "1", ""]),
    crlf=st.booleans(),
)
def test_whatever_a_profile_path_holds_install_ends_in_success_or_a_coded_error(
    tmp_path_factory, path, relative, crlf
):
    """End to end, not just ``read_profiles``: the fuzz of this file stopped there once, and a NUL
    went through it to the file system. Exit 70 (a bug) is the one answer that must not happen."""
    home = tmp_path_factory.mktemp("home")
    root = home / ".mozilla" / "firefox"
    root.mkdir(parents=True)
    newline = "\r\n" if crlf else "\n"
    ini = newline.join(
        ["[Profile0]", "Name=fuzz", f"Path={path}", f"IsRelative={relative}", "Default=1", ""]
    )
    (root / "profiles.ini").write_bytes(ini.encode("utf-8"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(home))
        # Never touch the real file system outside the throwaway home: an absolute fuzzed path is
        # a plan only.
        for args in (["install", "--skip-loader"], ["uninstall"]):
            result = runner.invoke(app, [*args, "--yes", "--dry-run"])
            assert result.exit_code in (0, 1, 2), (ini, args, result.output)
            assert errors.UNEXPECTED.code not in result.output, (ini, args, result.output)


# --- PF-21: Ctrl-C says what was done -------------------------------------------------------------


def test_an_interrupt_in_the_middle_of_a_plan_says_how_far_it_got(profile: Path, monkeypatch):
    real = installer._edit
    calls = []

    def interrupted(path, transform):
        calls.append(path)
        raise KeyboardInterrupt

    monkeypatch.setattr(installer, "_edit", interrupted)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    monkeypatch.setattr(installer, "_edit", real)
    assert calls, "the step that is interrupted did run"
    assert "1 of 3 steps finished" in result.output  # the old code printed nothing of the kind
    assert "safe" in result.output
    assert "The step that was running was interrupted" in result.output
    assert "failed step" not in result.output  # a Ctrl-C is not a failure
    assert (profile / "chrome" / "autohide.css").is_file()  # what the first step did stays done


# --- PF-27.11: --save takes a path that starts with "-" -------------------------------------------


def machine_free(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.mark.parametrize("name", ["-report.json", "-", "--", "-x"])
def test_save_takes_the_next_word_even_when_it_starts_with_a_dash(
    tmp_path: Path, monkeypatch, name: str
):
    machine_free(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor", "--json", "--save", name])
    assert "no such option" not in result.output.lower(), result.output
    assert result.exit_code in (0, 1)
    if name not in ("--",):
        assert (tmp_path / name).is_file() or "saved" in result.output


def test_save_followed_by_an_option_still_means_the_default_place(tmp_path: Path, monkeypatch):
    machine_free(monkeypatch, tmp_path)
    for following in ("--json", "-v", "--markdown"):
        result = runner.invoke(app, ["doctor", "--save", following])
        assert "The report was saved to" in result.output, (following, result.output)


def test_save_at_the_end_means_the_default_place(tmp_path: Path, monkeypatch):
    machine_free(monkeypatch, tmp_path)
    result = runner.invoke(app, ["doctor", "--json", "--save"])
    assert "The report was saved to" in result.output


# --- PF-20: messages that read as sentences and name the right file -------------------------------


def test_the_loader_missing_message_is_two_sentences(tmp_path: Path):
    """The report said ``Firefox cannot run the script without them.run the script.``"""
    firefox = tmp_path / "firefox"
    firefox.mkdir()
    (firefox / "omni.ja").touch()
    (firefox / "firefox").touch()
    result = runner.invoke(
        app, ["doctor", "--json", "--firefox-dir", str(firefox), "--profile", str(tmp_path)]
    )
    messages = [
        check["message"]
        for section in json.loads(result.output)["sections"]
        for check in section["checks"]
    ]
    missing = [message for message in messages if "loader files are missing" in message]
    assert missing and missing[0].endswith("without them.")
    assert "them.run" not in " ".join(messages)


def test_no_two_string_literals_of_the_source_run_a_sentence_into_the_next_word():
    """Python joins neighbouring literals as they are: a missing space shows up in a message.

    ``"...without them." "run the script."`` is the case that reached a report (PF-20); this reads
    every module and looks at each pair of neighbouring plain literals.
    """
    source = Path(__file__).resolve().parents[1] / "src" / "peek_a_foxy"
    found = []
    for path in sorted(source.glob("*.py")):
        tokens = [
            token
            for token in tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline)
            if token.type
            not in (
                tokenize.NL,
                tokenize.COMMENT,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
            )
        ]
        for first, second in zip(tokens, tokens[1:], strict=False):
            if first.type != tokenize.STRING or second.type != tokenize.STRING:
                continue
            try:
                before, after = ast.literal_eval(first.string), ast.literal_eval(second.string)
            except (ValueError, SyntaxError):
                continue
            glued = re.search(r"[A-Za-z0-9.,;:]$", before) and re.match(r"[A-Za-z]", after)
            if isinstance(before, str) and isinstance(after, str) and glued:
                found.append(f"{path.name}:{first.start[0]}: {before[-15:]!r} {after[:15]!r}")
    assert found == []


@needs_symlinks
def test_the_error_for_a_broken_link_names_the_file_the_person_knows(tmp_path: Path):
    """The message named ``userChrome.css.2576944.9d68cd16.peek-a-foxy.tmp``."""
    chrome = tmp_path / "profile" / "chrome"
    chrome.mkdir(parents=True)
    (chrome / "userChrome.css").symlink_to(tmp_path / "nowhere" / "dotfiles" / "x.css")
    result = runner.invoke(
        app, ["install", "--profile", str(tmp_path / "profile"), "--skip-loader", "--yes"]
    )
    assert result.exit_code == 1 and errors.FILE_IO.code in result.output
    assert ".peek-a-foxy.tmp" not in result.output
    assert "userChrome.css" in result.output or "x.css" in result.output


def test_the_progress_text_does_not_promise_what_atomic_edits_make_untrue():
    text = installer_progress()
    assert "may have changed part of its files" not in text
    assert "never left half written" in text


def installer_progress() -> str:
    from peek_a_foxy import cli

    plan = installer.Plan()
    plan.add("one", lambda: None)
    return cli._progress(plan)


# --- PF-27.6: the invisible direction marks are neutralised ---------------------------------------


@pytest.mark.parametrize("mark", ["‎", "‏", "؜", "‮", "⁧"])
def test_every_direction_mark_is_replaced_in_a_report(mark: str):
    assert mark not in report.clean(f"a{mark}b")
    assert report.clean(f"a{mark}b") == "a�b"


def test_right_to_left_letters_themselves_are_kept():
    assert report.clean("שלום") == "שלום"


# --- PF-27.7: platform odds and ends --------------------------------------------------------------


@pytest.mark.parametrize("path", ["/home/me/flatpak/projects/firefox", "/home/me/snapshots/ff"])
def test_a_folder_that_is_only_called_flatpak_is_not_a_flatpak_install(path: str):
    from peek_a_foxy import platform

    assert platform.sandbox_kind(Path(path)) is None


def test_fedora_and_suse_keep_firefox_in_lib64():
    from peek_a_foxy import platform

    assert "/usr/lib64/firefox" in platform.LINUX_INSTALL_DIRS


def test_the_program_says_it_runs_on_macos_too():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "Operating System :: MacOS" in text


def test_the_doctor_docstring_does_not_claim_it_writes_nothing():
    assert "Read-only: nothing here writes" not in (doctor.__doc__ or "")


# --- a folder argument that loops, or is a file, is a usage error on every Python -------


@needs_symlinks
@pytest.mark.parametrize("option", ["--profile", "--firefox-dir"])
@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_a_looping_link_as_a_folder_option_is_a_usage_error_never_a_bug(
    tmp_path: Path, option: str, command: str
):
    """``Path.resolve()`` raises ``RuntimeError`` for a loop before Python 3.13 (exit 70)."""
    if command == "uninstall" and option == "--firefox-dir":
        pytest.skip("uninstall has no --firefox-dir")
    loop = tmp_path / "loop"
    loop.symlink_to("loop")
    result = runner.invoke(app, [command, option, str(loop), "--yes"])
    assert result.exit_code == errors.EXIT_USAGE, result.output
    assert errors.UNEXPECTED.code not in result.output and "Traceback" not in result.output


@pytest.mark.parametrize("option", ["--profile", "--firefox-dir"])
def test_a_file_where_a_folder_is_wanted_is_a_usage_error(tmp_path: Path, option: str):
    plain = tmp_path / "plain"
    plain.write_text("x")
    for arguments in (["install", "--dry-run"], ["doctor"]):
        result = runner.invoke(app, [*arguments, option, str(plain)])
        assert result.exit_code == errors.EXIT_USAGE, result.output
        assert squeezed("is a file") in squeezed(result.output)


def test_a_folder_that_does_not_exist_is_still_a_usage_error_for_install(tmp_path: Path):
    result = runner.invoke(app, ["install", "--profile", str(tmp_path / "nowhere"), "--yes"])
    assert result.exit_code == errors.EXIT_USAGE
    assert squeezed("does not exist") in squeezed(result.output)
    assert not (tmp_path / "nowhere").exists()  # nothing was created for a typo


def test_a_failure_still_says_the_step_failed_not_that_it_was_interrupted():
    text = installer_progress()
    assert "If the failed step was copying files" in text and "interrupted" not in text


# --- PF-27.8: a symlinked chrome/utils is refused, before anything is copied ----------------------


@needs_symlinks
@pytest.mark.parametrize("target", ["elsewhere", "loop", "dangling"])
def test_a_symlinked_utils_folder_is_refused_and_nothing_is_written_through_it(
    tmp_path: Path, target: str
):
    from peek_a_foxy import loader

    checkout = tmp_path / "checkout"
    (checkout / "profile" / "chrome" / "utils").mkdir(parents=True)
    (checkout / "profile" / "chrome" / "utils" / "boot.sys.mjs").write_text("x")
    chrome = tmp_path / "chrome"
    chrome.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = chrome / "utils"
    link.symlink_to({"elsewhere": elsewhere, "loop": link, "dangling": tmp_path / "gone"}[target])

    with pytest.raises(errors.UserFileError) as raised:
        loader.install_utils(checkout, chrome)

    assert raised.value.code is errors.UTILS_IS_A_LINK and raised.value.code.code == "PAF-404"
    assert list(elsewhere.iterdir()) == []  # nothing went through the link
    assert link.is_symlink()
