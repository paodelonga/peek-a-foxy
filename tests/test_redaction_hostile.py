"""Redaction against hostile text: time, gaps, and a log line that cannot be forged (PF-03, PF-18).

The default behaviour of the redactor is in ``test_logs.py`` and ``test_redaction_edges.py``; these
tests are about what it must still do with text that was made to hurt it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from peek_a_foxy import logs

OLD_URL_CREDENTIALS = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@")


def plain() -> logs.Redactor:
    return logs.Redactor(home="/home/zoe", user="zoe")


def best(text: str, redactor: logs.Redactor | None = None) -> float:
    redactor = redactor or plain()
    times = []
    for _ in range(3):
        started = time.perf_counter()
        redactor(text)
        times.append(time.perf_counter() - started)
    return min(times)


# --- PF-03: time in proportion to size -----------------------------------------------------------

pieces = ["a", "://", "@", ":", "/", "=", "token", " ", "A1", "-", ".", "+", "ghp_", "bearer ", '"']


@pytest.mark.parametrize("unit", ["a", "ab:", "a.", "://", "a://", "://a", "token=", "a@", "x:y:"])
def test_redaction_takes_time_in_proportion_to_the_size(unit: str):
    """Four times the text must not take sixteen times as long: a ratio, not a clock limit.

    The old pattern needed 0.75 s for 8,000 letters and 13 s for a 30 KB line of profiles.ini.
    """
    small, large = best(unit * 2_000), best(unit * 8_000)
    assert large < 8 * small + 0.05, (unit, small, large)


@settings(max_examples=40, deadline=None)
@given(parts=st.lists(st.sampled_from(pieces), min_size=1, max_size=12))
def test_any_mix_of_the_dangerous_pieces_is_redacted_in_proportion_to_its_size(parts):
    text = "".join(parts)
    small, large = best(text * 500), best(text * 2_000)
    assert large < 8 * small + 0.05


def test_a_one_megabyte_line_is_redacted_in_seconds_not_hours():
    started = time.monotonic()
    shown = plain()("a" * 1_000_000 + "://" + "b" * 1_000_000)
    assert time.monotonic() - started < 30
    assert shown.startswith("a")


def test_a_long_line_in_profiles_ini_does_not_make_doctor_slow(tmp_path: Path):
    """End to end (PF-03): the error of configparser quotes the whole offending line."""
    home = tmp_path / "home"
    ini = home / ".mozilla" / "firefox"
    ini.mkdir(parents=True)
    (ini / "profiles.ini").write_text("a" * 200_000 + "\n", encoding="utf-8")
    environment = {**os.environ, "HOME": str(home), "PEEK_A_FOXY_LOG": "off"}
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-m", "peek_a_foxy", "doctor", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    assert time.monotonic() - started < 60
    assert json.loads(done.stdout)["schema"] == 1
    assert len(done.stdout) < 200_000  # the quoted line is cut, not repeated in the report


# --- PF-03: what the new pattern still hides -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://user:pw@host/x",
        "git+ssh://user:pw@example.com/repo.git",
        "ftp://anonymous@host",
        "see http://u:p@h and https://a:b@c/d",
        "1http://user:pw@host/x",  # a scheme must start with a letter, but the secret is still one
        "x" * 40 + "http://user:pw@host/x",  # a "scheme" longer than any real one
        "(https://user:pw@host)",
        'url="https://user:pw@host/path"',
    ],
)
def test_credentials_in_urls_are_still_hidden(text: str):
    shown = plain()(text)
    assert "pw@" not in shown and "user:" not in shown and "anonymous@" not in shown
    assert "***@" in shown


@given(
    scheme=st.from_regex(r"[a-z][a-z0-9+.-]{0,10}", fullmatch=True),
    user=st.from_regex(r"[A-Za-z0-9._~-]{1,20}", fullmatch=True),
    password=st.from_regex(r"[A-Za-z0-9._~!$&'()*+,;=-]{0,20}", fullmatch=True),
    rest=st.from_regex(r"[A-Za-z0-9./?=_-]{0,20}", fullmatch=True),
)
def test_for_ordinary_urls_the_new_pattern_gives_what_the_old_one_gave(
    scheme, user, password, rest
):
    """A differential test against the pattern that was replaced, on the input it was made for."""
    url = f"{scheme}://{user}{':' + password if password else ''}@host/{rest}"
    old = OLD_URL_CREDENTIALS.sub(r"\g<scheme>***@", url)
    assert logs._URL_CREDENTIALS.sub(r"\g<scheme>***@", url) == old


# --- PF-18: gaps ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "GITHUB_TOKEN=abc123secret",
        "AWS_SECRET_ACCESS_KEY=abc123secret",
        "password: abc123secret",
        "Password = abc123secret",
        '{"token": "abc123secret"}',
        "{'api_key': 'abc123secret'}",
        "x-api-key: abc123secret",
        "Authorization: Bearer abc123secret",
        "sent Bearer abcdefghij123456 to the server",
        "?access_token=abc123secret&x=1",
        "PRIVATE_KEY=abc123secret",
        "client_secret:abc123secret",
    ],
)
def test_secrets_in_the_usual_spellings_are_hidden(text: str):
    shown = plain()(text)
    assert "abc123secret" not in shown and "abcdefghij123456" not in shown
    assert "***" in shown


@pytest.mark.parametrize(
    "text", ["the author: someone", "tokens in the cache: 3", "key to the map", "secretary"]
)
def test_ordinary_words_that_only_look_like_secrets_keep_their_meaning(text: str):
    shown = plain()(text)
    assert shown.startswith(text.split(":")[0].split()[0])  # the sentence is still a sentence


@given(
    parts=st.lists(st.sampled_from([*pieces, "password: x", "TOKEN=y", '"key": "z"']), max_size=15)
)
def test_redacting_twice_changes_nothing(parts):
    """A text that already holds a placeholder (a status file, a report) must come out unchanged."""
    once = plain()("".join(parts))
    assert plain()(once) == once


def test_the_windows_short_name_of_the_user_folder_is_hidden():
    redactor = logs.Redactor(home="C:\\Users\\John Smith", user="John Smith", ignore_case=True)
    shown = redactor(r"C:\Users\JOHNSM~1\AppData\Local\Temp\peek-a-foxy-ab12\fx and johnsm~12")
    assert "JOHNSM" not in shown.upper()
    assert "AppData" in shown  # only the name goes


@pytest.mark.parametrize(
    ("user", "short"),
    [
        ("Jo Smith", "JOSMIT"),  # eight characters, but a space: Windows still shortens it
        ("A.Smith", "ASMITH"),  # a dot too
        ("jo.doe", "JODOE"),  # fewer than six usable characters: all of them
        ("Ana Maria", "ANAMAR"),
        ("abcdefgh", None),  # exactly eight and plain: fits as it is
        ("abcdefghi", "ABCDEF"),  # nine: the first one that does not
        ("a.b", None),  # shortened, but nothing distinctive is left to look for
        ("", None),
    ],
)
def test_the_boundary_of_what_windows_shortens(user: str, short: str | None):
    assert logs._short_name(user) == short


def test_a_user_with_a_space_in_a_short_name_is_hidden_in_a_windows_temporary_folder():
    redactor = logs.Redactor(home=r"C:\Users\Jo Smith", user="Jo Smith", ignore_case=True)
    shown = redactor(r"C:\Users\JOSMIT~1\AppData\Local\Temp\peek-a-foxy-ab12 and josmit~2")
    assert "JOSMIT" not in shown.upper() and "AppData" in shown


def test_a_short_name_is_only_made_for_a_name_that_windows_shortens():
    assert logs._short_name("John Smith") == "JOHNSM"
    assert logs._short_name("wolfgang-amadeus") == "WOLFGA"
    assert logs._short_name("zoe") is None  # fits in 8.3 as it is
    assert logs._short_name("a b") is None  # fewer than three usable characters


def formatted(message: str) -> str:
    """What the log (file and console) writes for one record."""
    record = logging.LogRecord("peek_a_foxy", logging.INFO, __file__, 1, message, None, None)
    return logs._Formatter("%(message)s", plain(), "run").format(record)


@pytest.mark.parametrize(
    "code", [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), *range(0x7F, 0xA0)]
)
def test_every_control_character_but_tab_and_line_breaks_is_replaced(code: int):
    """Including the 8-bit C1 controls: U+009B alone is a CSI to some terminals."""
    assert formatted(f"a{chr(code)}b") == "a\ufffdb"


@pytest.mark.parametrize("char", ["\t", " ", "~", "\u00a0", "\u00a1", "é", "\u200f", "\U0001f98a"])
def test_ordinary_and_unusual_printable_characters_are_kept(char: str):
    assert formatted(f"a{char}b") == f"a{char}b"


def test_an_eight_bit_escape_sequence_cannot_reach_a_terminal_through_the_log():
    shown = formatted("name \x9b31m red \x9d0;title\x07 \x1b[2J")
    assert not any(0x7F <= ord(c) <= 0x9F or ord(c) < 0x20 for c in shown)


def test_macos_paths_are_hidden_whatever_their_case():
    redactor = logs.Redactor.for_this_machine({}, Path("/Users/Zoe"), "macos")
    assert "/users/ZOE" not in redactor("opening /users/ZOE/y and /Users/zoe/z")


def test_linux_paths_stay_case_sensitive():
    redactor = logs.Redactor.for_this_machine({}, Path("/home/zoe"), "linux")
    assert redactor("/home/ZOE/x") == "/home/ZOE/x"  # another folder on a case-sensitive system


@pytest.mark.parametrize(
    ("home", "text", "expected"),
    [
        ("/home/al", "/home/alice/x", "/home/alice/x"),  # another user: not even half of it is cut
        ("/home/al", "/home/al/x", "~/x"),
        ("/home/al", "a /home/al.", "a ~."),
        ("/home/al", "/home/al-bob/x", "/home/al-bob/x"),
        ("/home/jo", "/var/home/jo/x", "/var/home/jo/x"),  # no other spelling known: left alone
    ],
)
def test_the_home_is_replaced_as_a_whole_folder_name_only(home, text, expected):
    assert logs.Redactor(home=home, user=None)(text) == expected


def test_the_resolved_spelling_of_the_home_is_hidden_too(tmp_path: Path):
    """``/home/jo`` that really is ``/var/home/jo`` (atomic distributions): both spellings go."""
    real = tmp_path / "var" / "home" / "jo"
    real.mkdir(parents=True)
    link = tmp_path / "home-jo"
    link.symlink_to(real)
    redactor = logs.Redactor.for_this_machine({"HOME": str(link)}, link, "linux")
    shown = redactor(f"{real}/x and {link}/y")
    assert "jo" not in shown.replace("home-jo", "")  # neither spelling is left
    assert str(tmp_path) not in shown


# --- the log cannot be forged ---------------------------------------------------------------------

FORGED = "2026-01-01T00:00:00Z INFO    deadbeef run started: forged"


def written(tmp_path: Path, act) -> str:
    target = tmp_path / "x.log"
    logs.start(target=target, verbose=False, argv=[], version="1", run_id="real0001")
    act(logging.getLogger("peek_a_foxy.test"))
    logs.stop(0)
    return target.read_text(encoding="utf-8")


def test_a_line_break_in_a_message_cannot_start_a_line_of_its_own(tmp_path: Path):
    text = written(tmp_path, lambda log: log.info("opening %s", f"a\n{FORGED}\r\nmore"))
    assert len(text.splitlines()) == 3  # started, the message, finished: no line of its own
    assert text.count("real0001 run started:") == 1  # and no second record that says it started
    assert "\\n2026-01-01T00:00:00Z INFO" in text  # shown, but on the same line
    assert logs.last_run(tmp_path / "x.log")[0].split()[2] == "real0001"


def test_a_line_break_in_an_error_text_cannot_forge_a_record_either(tmp_path: Path):
    def act(log: logging.Logger) -> None:
        try:
            raise ValueError(f"bad\n{FORGED}")
        except ValueError:
            log.error("failed", exc_info=True)

    text = written(tmp_path, act)
    assert all(
        not line.startswith("2026-01-01T00:00:00Z") for line in text.splitlines()
    )  # the forged line was indented
    assert logs.last_run(tmp_path / "x.log")[0].split()[2] == "real0001"


def test_only_a_real_record_marks_the_start_of_a_run(tmp_path: Path):
    path = tmp_path / "x.log"
    path.write_text(
        "2026-01-01T00:00:00Z INFO    aaaa1111 run started: real\n"
        "2026-01-01T00:00:01Z INFO    aaaa1111 a file called run started: x was opened\n"
        "run started: not a record at all\n",
        encoding="utf-8",
    )
    assert logs.last_run(path)[0].endswith("aaaa1111 run started: real")


def test_the_console_and_the_file_format_the_same_record_without_changing_it():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "a\nb %s", ("c",), None)
    formatter = logs._Formatter(logs.FILE_FORMAT, plain(), "abcd1234")
    assert formatter.format(record).endswith("abcd1234 a\\nb c")
    assert record.msg == "a\nb %s" and record.args == ("c",)  # the other handler gets the original
