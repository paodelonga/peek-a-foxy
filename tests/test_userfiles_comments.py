"""Edits and ``doctor`` read the user's files as Firefox does: no comments (PF-07, PF-26).

Mostly adversarial: a pref or an ``@import`` inside a block comment, a ``/*`` inside a string,
unclosed comments, mixed line endings, and a second, independent reader of ``user.js`` that the
property tests compare the editor with.
"""

from __future__ import annotations

import re
import time

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from peek_a_foxy import doctor, errors
from peek_a_foxy import userfiles as uf
from peek_a_foxy.errors import UserFileError

PREF = uf.STYLESHEETS_PREF
IMPORT = uf.CSS_IMPORT


# --- an independent reader of prefs files (slow and simple on purpose) ------------------------


def blank_comments(text: str) -> str:
    """The text with comments replaced by spaces, as a state machine over single characters.

    It does not share a line of code with ``userfiles`` so that the property tests compare two
    readers, not one with itself.
    """
    out: list[str] = []
    i = 0
    quote = ""
    while i < len(text):
        c = text[i]
        pair = text[i : i + 2]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif c == quote or c == "\n":
                quote = ""
        elif c in "\"'":
            quote = c
            out.append(c)
        elif pair == "/*":
            end = text.find("*/", i + 2)
            end = len(text) if end < 0 else end + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:end]))
            i = end - 1
        elif pair == "//":
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            out.append(" " * (end - i))
            i = end - 1
        else:
            out.append(c)
        i += 1
    return "".join(out)


def prefs_as_firefox_reads_them(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in blank_comments(text).split("\n"):
        match = re.match(r'\s*user_pref\(\s*"([^"]*)"\s*,\s*(.*?)\s*\)\s*;', line)
        if match:
            found[match.group(1)] = match.group(2)  # the last one wins
    return found


# --- the evidence from the review ---------------------------------------------------------------


def test_a_pref_inside_a_block_comment_is_not_set_and_not_edited():
    text = f'/*\nuser_pref("{PREF}", false);\n*/\n'
    result = uf.set_pref(text, PREF, True)
    assert result == text + f'user_pref("{PREF}", true);\n'  # added after the comment, intact
    assert doctor.parse_prefs(result)[PREF] == "true"


def test_doctor_does_not_see_a_pref_that_is_only_in_a_comment():
    assert doctor.parse_prefs(f'/* user_pref("{PREF}", true); */\n') == {}
    assert doctor.parse_prefs(f'/*\nuser_pref("{PREF}", true);\n*/\n') == {}
    assert doctor.parse_prefs(f'// user_pref("{PREF}", true);\n') == {}
    assert doctor.parse_prefs(f'/* a */ user_pref("{PREF}", true);\n') == {PREF: "true"}


def test_get_has_and_remove_skip_comments_but_keep_them():
    text = f'/*\nuser_pref("{PREF}", true);\n*/\n'
    assert uf.has_pref(text, PREF) is False
    assert uf.get_bool_pref(text, PREF) is None
    assert uf.remove_pref(text, PREF) == text


def test_a_slash_star_inside_a_string_does_not_start_a_comment():
    text = f'user_pref("a.note", "/* not a comment");\nuser_pref("{PREF}", false);\n'
    assert uf.get_bool_pref(text, PREF) is False
    assert uf.set_pref(text, PREF, True) == (
        f'user_pref("a.note", "/* not a comment");\nuser_pref("{PREF}", true);\n'
    )


def test_the_last_line_that_sets_a_pref_decides_as_in_firefox():
    text = f'user_pref("{PREF}", true);\nuser_pref("{PREF}", false);\n'
    assert uf.get_bool_pref(text, PREF) is False
    assert uf.set_pref(text, PREF, True) == f'user_pref("{PREF}", true);\n'  # the copies collapse


def test_a_pref_after_a_comment_on_the_same_line_is_read_but_its_comment_is_kept():
    text = f'/* mine */ user_pref("{PREF}", false);\n'
    assert uf.get_bool_pref(text, PREF) is False
    result = uf.set_pref(text, PREF, True)
    assert result.startswith("/* mine */ ")  # the person's comment is not taken away
    assert uf.get_bool_pref(result, PREF) is True


def test_an_import_inside_a_comment_stays_where_it_is():
    text = f"/*\n{IMPORT}\n*/\nbody{{}}\n"
    assert uf.with_css_import(text) == f"{IMPORT}\n{text}"
    assert uf.without_css_import(text) == text
    assert uf.without_css_import(uf.with_css_import(text)) == text


def test_an_import_after_a_comment_on_its_line_is_not_taken_for_ours():
    text = f"/* mine */ {IMPORT}\nbody{{}}\n"
    assert uf.without_css_import(text) == text  # the person's comment is not deleted with it


def test_the_import_goes_after_charset_and_after_the_comment_that_charset_opens():
    assert uf.with_css_import('@charset "x"; /* a\nb */\nbody{}') == (
        f'@charset "x"; /* a\nb */\n{IMPORT}\nbody{{}}'
    )
    # A comment that never ends swallows what is put after it: the import goes first instead.
    assert uf.with_css_import('@charset "x"; /* a\nb') == f'{IMPORT}\n@charset "x"; /* a\nb'


# --- line endings (PF-26) -----------------------------------------------------------------------


def test_mixed_line_endings_are_kept_line_by_line():
    assert uf.with_css_import("a{}\nb{}\r\nc{}\n") == f"{IMPORT}\na{{}}\nb{{}}\r\nc{{}}\n"
    assert uf.with_css_import("a{}\r\nb{}\nc{}\r\n") == f"{IMPORT}\r\na{{}}\r\nb{{}}\nc{{}}\r\n"
    text = 'user_pref("x", 1);\nuser_pref("y", 2);\r\n'
    result = uf.set_pref(text, "z", True)
    assert result == text + 'user_pref("z", true);\n'.replace("\n", "\n")  # LF is the majority tie


def test_a_crlf_file_stays_crlf_and_the_added_line_is_crlf():
    assert uf.set_pref("a\r\nb", "z", True) == 'a\r\nb\r\nuser_pref("z", true);'
    assert uf.set_pref("a\r\nb\r\n", "z", True) == 'a\r\nb\r\nuser_pref("z", true);\r\n'


tokens = st.sampled_from(
    ["a{}", " ", "\n", "\r\n", "/*", "*/", '"', "'", "\\", '@charset "x";', "//", "\u2028", "\x0b"]
)


# The falsifying example that the property found once, by chance, on a CI run: kept so that every
# run checks it. A CRLF-majority file with no final line break, whose only lines after @charset are
# inside the comment that @charset opens, so the import goes at the very end.
@example(parts=['@charset "x";', "/*", "\n", "\r\n", "\r\n", "*/"])
@settings(max_examples=300, deadline=None)
@given(parts=st.lists(tokens, max_size=30))
def test_adding_and_removing_the_import_gives_the_original_back(parts):
    text = "".join(parts)
    added = uf.with_css_import(text)
    assert uf.with_css_import(added) == added  # idempotent
    assert uf.without_css_import(added) == text  # and every other byte is where it was


@settings(max_examples=300, deadline=None)
@given(parts=st.lists(tokens, max_size=30))
def test_the_added_import_is_never_inside_a_comment(parts):
    result = uf.with_css_import("".join(parts))
    assert IMPORT in uf.mask_comments(result)  # still there once comments are taken away
    lines = uf.mask_comments(result).split("\n")
    assert any(line.strip() == IMPORT for line in lines)


LONE_CR = re.compile(r"\r(?!\n)")


@pytest.mark.parametrize(
    "text",
    [
        '@charset "x";/*\n\r\n\r\n*/',  # the example that the property found
        '@charset "UTF-8"; /* notes\r\nmore */',  # CRLF, comment to the end, no final break
        '@charset "x";/*\nmore\n*/',  # the same in a file that is LF
        '@charset "x"; /*\r\n\r\n*/',  # CRLF with nothing but blank comment lines
    ],
)
def test_an_import_added_as_the_last_line_leaves_no_lone_cr_and_is_stable(text: str):
    """The import goes after the comment that @charset opens; that can be the end of a file that
    has no final line break. The old last line then needs no ``\r`` of its own."""
    added = uf.with_css_import(text)
    assert IMPORT in uf.mask_comments(added)
    assert not LONE_CR.search(added), repr(added)  # the text has none, so the result has none
    assert uf.with_css_import(added) == added  # a second run changes nothing
    assert uf.without_css_import(added) == text  # and taking it out gives the original back


def test_the_import_at_the_end_of_a_file_that_ends_in_a_line_break_keeps_the_file_style():
    text = '@charset "x"; /* a\r\nb */\r\n'
    assert uf.with_css_import(text) == f'@charset "x"; /* a\r\nb */\r\n{IMPORT}\r\n'
    assert uf.with_css_import(text.replace("\r\n", "\n")) == (
        f'@charset "x"; /* a\nb */\n{IMPORT}\n'
    )


# --- two readers of user.js must agree -----------------------------------------------------------

pref_tokens = st.sampled_from(
    [
        f'user_pref("{PREF}", false);',
        f'user_pref("{PREF}", true);',
        'user_pref("other", 1);',
        "/*",
        "*/",
        "//",
        "\n",
        "\r\n",
        " ",
        '"',
        "'",
        "\u2028",
        "\x0b",
    ]
)


@settings(max_examples=400, deadline=None)
@given(parts=st.lists(pref_tokens, max_size=24), value=st.booleans())
def test_after_set_pref_a_comment_aware_reader_finds_the_value(parts, value):
    text = "".join(parts)
    try:
        result = uf.set_pref(text, PREF, value)
    except UserFileError:  # the one case that cannot be done safely, and is refused
        assume(prefs_as_firefox_reads_them(text).get(PREF) != ("true" if value else "false"))
        assert "/*" in text
        return
    assert prefs_as_firefox_reads_them(result)[PREF] == ("true" if value else "false")
    assert doctor.parse_prefs(result).get(PREF) == ("true" if value else "false")


@settings(max_examples=400, deadline=None)
@given(parts=st.lists(pref_tokens, max_size=24))
def test_doctor_and_the_independent_reader_agree_on_every_pref(parts):
    text = "".join(parts)
    assert doctor.parse_prefs(text) == prefs_as_firefox_reads_them(text)


@settings(max_examples=400, deadline=None)
@given(parts=st.lists(pref_tokens, max_size=24))
def test_get_bool_pref_agrees_with_the_independent_reader(parts):
    text = "".join(parts)
    seen = prefs_as_firefox_reads_them(text).get(PREF)
    assert uf.get_bool_pref(text, PREF) == {"true": True, "false": False}.get(seen or "")


@settings(max_examples=300, deadline=None)
@given(parts=st.lists(pref_tokens, max_size=24))
def test_removing_a_pref_never_changes_another_one(parts):
    text = "".join(parts)
    before = prefs_as_firefox_reads_them(text)
    after = prefs_as_firefox_reads_them(uf.remove_pref(text, PREF))
    assert {k: v for k, v in before.items() if k != PREF} == {
        k: v for k, v in after.items() if k != PREF
    }


def test_doctor_splits_lines_like_the_editor_does():
    """``splitlines()`` also breaks at U+2028 and \\x0b: a pref after one looked like a start."""
    text = f'x\u2028user_pref("{PREF}", true);\n'
    assert doctor.parse_prefs(text) == {}
    assert uf.has_pref(text, PREF) is False


# --- hostile sizes -------------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["/*", "/*/*", '"', "'\\", "//", "/* */ "])
def test_masking_comments_takes_time_in_proportion_to_the_size(unit):
    """A ratio of two sizes, not a clock limit: four times the text, at most about eight times."""

    def best_of(repeats: int, size: int) -> float:
        text = unit * size
        times = []
        for _ in range(3):
            started = time.perf_counter()
            uf.mask_comments(text, line_comments=True)
            uf.mask_comments(text)
            times.append(time.perf_counter() - started)
        return min(times)

    small, large = best_of(1, 50_000), best_of(1, 200_000)
    assert large < 8 * small + 0.05


def test_a_huge_file_of_unclosed_comments_is_masked():
    text = "/*\n" * 500_000
    assert set(uf.mask_comments(text)) <= {" ", "\n"}
    assert uf.with_css_import(text).startswith(IMPORT + "\n")


def test_a_comment_that_never_closes_and_starts_inside_two_earlier_ones_is_found():
    """Three comments chained over lines 0 to 3: each starts on the line where the one before it
    ends. The last never closes, so a new line may only go in front of the line where the whole
    chain begins; one step back from the last start would still be inside a comment."""
    text = "/* a\nb */ /* b2\nc */ /* c2\nd"
    assert uf._scan(text, line_comments=True)[2] == 0
    assert uf._scan(text, line_comments=False)[2] == 0
    result = uf.set_pref(text, PREF, True)
    assert result == f'user_pref("{PREF}", true);\n{text}'
    assert uf.get_bool_pref(result, PREF) is True
    assert doctor.parse_prefs(result)[PREF] == "true"


@pytest.mark.parametrize("depth", [1, 2, 3, 10, 200])
def test_a_chain_of_comments_of_any_length_leaves_the_new_line_in_front_of_all_of_them(depth: int):
    text = "/* a\n" + "".join(f"b{n} */ /* c{n}\n" for n in range(depth)) + "end"
    result = uf.set_pref(text, PREF, True)
    assert result.startswith(f'user_pref("{PREF}", true);\n/* a\n')
    assert uf.get_bool_pref(result, PREF) is True


def test_a_pref_that_cannot_be_changed_without_editing_a_comment_is_a_coded_error():
    """``/**/user_pref(..., false);/*``: the pref and a comment that never ends share a line."""
    text = f'/**/user_pref("{PREF}", false);/*'
    with pytest.raises(UserFileError) as caught:
        uf.set_pref(text, PREF, True)
    assert caught.value.code is errors.FILE_IO and "never closed" in caught.value.message
    assert uf.set_pref(text, PREF, False) == text  # already what is wanted: nothing to do
