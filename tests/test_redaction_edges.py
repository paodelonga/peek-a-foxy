"""Corner cases of the redaction: roots as homes, file names that look like profile folders, and
placeholders that must come out of the redactor exactly as they went in.

Windows-style strings are tested on every system: the redactor works on text, not on the disk.
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from peek_a_foxy import logs

# --- (a) a home folder that is a drive root or a filesystem root --------------------------------

ROOTS = [
    "/",
    "//",
    "///",
    "\\",
    "C:",
    "C:\\",
    "C:/",
    "c:\\",
    "c:/",
    "Z:\\",
    "C:\\\\",
    "\\\\?\\C:\\",
    "\\\\.\\D:",
    "",
    " ",
]
SAMPLE = r"C:\Windows\System32 and D:\data, c:/temp, /usr/lib/firefox, \\server\share and E:"


@pytest.mark.parametrize("root", ROOTS)
def test_a_root_as_the_home_folder_is_ignored_as_a_pattern(root: str):
    for ignore_case in (False, True):
        redact = logs.Redactor(home=root, user=None, ignore_case=ignore_case)
        assert redact(SAMPLE) == SAMPLE


@pytest.mark.parametrize("root", ROOTS)
def test_a_root_among_the_extra_homes_is_ignored_but_the_real_home_still_works(root: str):
    redact = logs.Redactor(
        home=r"C:\Users\Ana Maria", user=None, extra_homes=[root, "/home/ana"], ignore_case=True
    )
    assert redact(SAMPLE) == SAMPLE
    assert redact(r"C:\Users\Ana Maria\x and /home/ana/y") == "~\\x and ~/y"


def test_a_machine_whose_userprofile_is_a_drive_root_does_not_lose_its_c_colons(monkeypatch):
    monkeypatch.setattr(logs.getpass, "getuser", lambda: "carolina")
    redact = logs.Redactor.for_this_machine(
        {"USERPROFILE": "C:\\", "USERNAME": "carolina"}, None, "windows"
    )
    assert redact(SAMPLE) == SAMPLE
    assert redact("hello carolina") == "hello <user>"


@pytest.mark.parametrize("home", ["D:\\Users\\x", "/home/ana", "C:\\Users\\Ana", "/a/b", "C:/u/ab"])
def test_a_real_home_folder_is_still_hidden(home: str):
    assert logs.Redactor(home=home, user=None)(f"in {home}\\file") != f"in {home}\\file"


roots = st.builds(
    lambda prefix, drive, slashes: prefix + drive + slashes,
    st.sampled_from(["", "\\\\?\\", "\\\\.\\"]),
    st.one_of(st.just(""), st.from_regex(r"[A-Za-z]:", fullmatch=True)),
    st.text(alphabet="/\\", max_size=4),
)


@given(root=roots, text=st.text(max_size=60))
def test_whatever_root_the_home_is_the_text_comes_out_unchanged(root: str, text: str):
    # (the text may contain a placeholder-looking part only by chance: those stay as they are too)
    assert logs.Redactor(home=root, user=None)(text) == text
    assert logs.Redactor(home=root, user=None, ignore_case=True)(text) == text


# --- (b) file names of eight letters in a stack frame -------------------------------------------

FRAMES = [
    "autohide.uc.js",
    "peekafoxy.sys.mjs",
    "settings1.js",
    "abcdefgh.mjs",
    "abcdefgh.css",
    "abcdefgh.json",
    "abcdefgh.py",
    "abcdefgh.html",
    "abcdefgh.xhtml",
    "abcdefgh.ini",
    "ABCDEFGH.JS".lower() + "",
    "autohide.uc.js:12:5",
    "autohide.uc.js.bak",
]


@pytest.mark.parametrize("name", FRAMES)
@pytest.mark.parametrize("folder", ["chrome://userchrome/content/", "file:///x/chrome/JS/", "/p/"])
def test_a_script_file_name_of_eight_letters_is_not_taken_for_a_profile_folder(
    name: str, folder: str
):
    text = f"at run ({folder}{name}) here"
    assert logs.Redactor(home="/home/ana", user=None)(text) == text


def test_the_suffix_is_matched_whatever_its_case_and_only_as_a_whole_word():
    redact = logs.Redactor(home=None, user=None)
    assert redact("/x/autohide.UC.JS") == "/x/autohide.UC.JS"
    assert redact("/x/abcdefgh.jsx") == "/x/<profile>"  # "jsx" is not "js"
    assert redact("/x/abcdefgh.js-old") == "/x/<profile>"
    assert redact("/x/abcdefgh.json5") == "/x/<profile>"
    assert redact("/x/abcdefgh.pyc") == "/x/<profile>"


@pytest.mark.parametrize(
    "name",
    [
        "a1b2c3d4.default",
        "a1b2c3d4.default-release",
        "x9y8z7w6.dev-edition-default",
        "abcdefgh.my profile".replace(" ", "-"),
        "12345678.Work",
        "a1b2c3d4.default-esr",
        "a1b2c3d4.js-old",  # starts like a script suffix, is not one
        "a1b2c3d4.css-theme",
    ],
)
@pytest.mark.parametrize("separator", ["/", "\\"])
def test_a_real_profile_folder_is_still_hidden(name: str, separator: str):
    path = f"x{separator}Profiles{separator}{name}{separator}chrome{separator}user.js"
    shown = logs.Redactor(home=None, user=None)(path)
    assert name not in shown and "<profile>" in shown
    assert shown.endswith(f"{separator}chrome{separator}user.js")


def test_a_stack_frame_and_a_profile_folder_in_one_text_are_told_apart():
    text = (
        "Error: boom\n  at init (chrome://userchrome/content/autohide.uc.js:30:9)\n"
        "  from /home/ana/.mozilla/firefox/a1b2c3d4.default-release/chrome/x"
    )
    shown = logs.Redactor(home="/home/ana", user=None)(text)
    assert "autohide.uc.js:30:9" in shown and "a1b2c3d4" not in shown
    assert "~/.mozilla/firefox/<profile>/chrome/x" in shown


folder_letters = st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=8)
profile_words = st.text("abcdefghijklmnopqrstuvwxyz-", min_size=1, max_size=15).filter(
    lambda word: (
        not re.match(r"(?i:uc\.js|sys\.mjs|m?js|css|json|py|x?html|ini)(?![A-Za-z0-9_-])", word)
    )
)


@given(salt=folder_letters, word=profile_words)
def test_any_profile_folder_with_a_name_that_is_not_a_script_suffix_is_hidden(salt, word):
    shown = logs.Redactor(home=None, user=None)(f"/p/{salt}.{word}/chrome")
    assert salt not in shown and shown == "/p/<profile>/chrome"


@given(
    stem=folder_letters,
    suffix=st.sampled_from(["uc.js", "sys.mjs", "js", "mjs", "css", "json", "py", "html", "ini"]),
    tail=st.sampled_from(["", ":1:2", ")", "'"]),
)
def test_any_script_name_of_eight_characters_survives(stem, suffix, tail):
    text = f"at (/p/{stem}.{suffix}{tail}"
    assert logs.Redactor(home=None, user=None)(text) == text


# --- (c) placeholders are never redacted again --------------------------------------------------


def names_redactor(*profile_names: str, user: str | None = None) -> logs.Redactor:
    return logs.Redactor(home=None, user=user, profile_names=list(profile_names))


def test_a_profile_named_profile_does_not_turn_the_placeholder_into_nested_brackets():
    redact = names_redactor("profile")
    assert redact("see <profile> here") == "see <profile> here"
    assert redact("the profile is here") == "the <profile 1> is here"
    assert redact("/a1b2c3d4.default and profile") == "/<profile> and <profile 1>"


def test_a_user_named_like_a_placeholder_word_is_safe_too():
    redact = logs.Redactor(home=None, user="profile")
    assert redact("<profile> and profile") == "<profile> and <user>"
    assert logs.Redactor(home=None, user="user")("<user> and user") == "<user> and <user>"


def test_a_numbered_placeholder_is_kept_when_a_profile_is_named_profile():
    redact = names_redactor("profile", "work")
    assert (
        redact("<profile 1> <profile 2> profile work")
        == "<profile 1> <profile 2> <profile 1> <profile 2>"
    )


def test_a_name_inside_a_longer_word_or_a_different_bracket_is_not_protected():
    redact = names_redactor("profile")
    assert redact("<profiles>") == "<profiles>"  # a word of its own: nothing matched
    assert redact("<my profile>") == "<my <profile 1>>"  # not our placeholder: redacted as ever


def test_a_text_redacted_twice_comes_out_the_same():
    redact = logs.Redactor(
        home="/home/ana", user="ana-maria", profile_names=["profile", "user", "work"]
    )
    text = "/home/ana/.mozilla/firefox/a1b2c3d4.work/x profile user work ana-maria"
    once = redact(text)
    assert redact(once) == once


@given(
    names=st.lists(
        st.sampled_from(["profile", "user", "work", "default", "ab", "a b", "<profile>", "1"]),
        max_size=4,
    ),
    user=st.sampled_from([None, "user", "profile", "ana-maria"]),
    text=st.lists(
        st.sampled_from(
            [*"abc <>/\\.:1 ", "profile", "user", "work", "<profile>", "<user>", "<profile 1>"]
        ),
        max_size=14,
    ).map("".join),
)
def test_redacting_is_idempotent_whatever_the_names_and_the_text(names, user, text):
    redact = logs.Redactor(home="/home/ana", user=user, profile_names=names)
    once = redact(text)
    assert redact(once) == once


@given(
    names=st.lists(st.sampled_from(["profile", "user", "work", "profil"]), max_size=3),
    user=st.sampled_from([None, "user", "profile"]),
)
def test_redacted_text_has_no_doubled_brackets_unless_the_input_had_them(names, user):
    text = "a <profile> b <user> c <profile 1> d profile e user f work"
    shown = logs.Redactor(home=None, user=user, profile_names=names)(text)
    assert "<<" not in shown and ">>" not in shown


def test_the_status_file_text_from_firefox_survives_the_report_redaction():
    """Firefox writes ``<profile>``; the doctor redacts the same text again on this side."""
    written_by_the_script = "read <profile>/chrome/a.js for <user> in ~/x"
    redact = logs.Redactor(home="/home/ana", user="ana-maria", profile_names=["profile"])
    assert redact(written_by_the_script) == written_by_the_script
