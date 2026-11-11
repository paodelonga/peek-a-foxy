"""Edits to the user's own files: ``chrome/userChrome.css`` and ``user.js``.

Everything here works on text and is idempotent, so callers can read, transform and write back
without ever touching lines that belong to the user. Every line keeps its own ending (LF or CRLF),
the presence of a final newline is preserved, and a transform that changes nothing returns its
input unchanged.

A line that lies inside a ``/* ... */`` comment (or, in ``user.js``, after ``//``) does not exist as
far as Firefox is concerned, so it does not exist here either: it is never read as a setting, never
moved and never removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from peek_a_foxy import errors
from peek_a_foxy.errors import UserFileError

CSS_IMPORT = '@import url("autohide.css");'
LEGACY_CSS_IMPORT = '@import url("tabs-autohide.css");'  # name before the project was renamed
OWN_IMPORTS = (CSS_IMPORT, LEGACY_CSS_IMPORT)

STYLESHEETS_PREF = "toolkit.legacyUserProfileCustomizations.stylesheets"
# fx-autoconfig only runs scripts in the browser window unless this is set; the settings page is a
# script for about:preferences, which is a document inside a tab. Read once, at startup.
SUBDOCUMENTS_PREF = "userChromeJS.persistent_domcontent_callback"
TABS_PREF = "peekafoxy.tabs.autohide"
URLBAR_PREF = "peekafoxy.urlbar.autohide"
# Every pref the script registers (chrome/resources/peekafoxy.sys.mjs); uninstall removes them
# from user.js, where people may have put them.
OWN_PREFS = (
    TABS_PREF,
    URLBAR_PREF,
    "peekafoxy.strip.px",
    "peekafoxy.show.ms",
    "peekafoxy.show.delay.ms",
    "peekafoxy.hide.delay.ms",
    "peekafoxy.tabs.flash.ms",
    "peekafoxy.tabs.reveal.switch",
    "peekafoxy.tabs.reveal.new",
    "peekafoxy.tabs.reveal.link",
    "peekafoxy.tabs.shortcut",
    "peekafoxy.urlbar.shortcut",
    "peekafoxy.welcomed",
)
# Names used before the prefs moved under the project's own prefix, mapped to their replacements.
LEGACY_PREFS = {
    "userchrome.tabs.autohide": TABS_PREF,
    "userchrome.urlbar.autohide": URLBAR_PREF,
}


# A quoted string, then a block comment (an unclosed one runs to the end), then (user.js only) a
# line comment. Strings are matched so that a ``/*`` inside one does not start a comment. Every
# part is written so that the regular expression engine cannot backtrack without end.
_STRING = r"""(?P<string>"[^"\\\n]*(?:\\.[^"\\\n]*)*"?|'[^'\\\n]*(?:\\.[^'\\\n]*)*'?)"""
_BLOCK = r"(?P<block>/\*.*?(?:\*/|\Z))"
_CSS_TOKENS = re.compile(f"{_STRING}|{_BLOCK}", re.DOTALL)
_JS_TOKENS = re.compile(f"{_STRING}|{_BLOCK}|(?P<line>//[^\n]*)", re.DOTALL)
_NOT_NEWLINE = re.compile(r"[^\n]")


def _scan(text: str, *, line_comments: bool) -> tuple[str, frozenset[int], int | None]:
    """``text`` with every comment blanked out, the lines that start inside a block comment, and
    the first line that a block comment that is never closed can be put in front of (``None`` if
    there is no such comment).

    The result has the same length and the same line breaks as ``text``, so line ``n`` of one is
    line ``n`` of the other. The work is linear in the size of the text.
    """
    tokens = _JS_TOKENS if line_comments else _CSS_TOKENS
    parts: list[str] = []
    inside: set[int] = set()
    unclosed: int | None = None
    position = 0  # how far the text was copied into ``parts``
    line = 0  # the line that ``position`` is on
    for found in tokens.finditer(text):
        kind = found.lastgroup
        if kind == "string":
            continue
        start, end = found.span()
        line += text.count("\n", position, start)
        body = found.group()
        breaks = body.count("\n")
        if kind == "block":
            inside.update(range(line + 1, line + breaks + 1))
            unclosed = line if len(body) < 4 or not body.endswith("*/") else None
        parts += (text[position:start], _NOT_NEWLINE.sub(" ", body))
        line += breaks
        position = end
    parts.append(text[position:])
    while unclosed is not None and unclosed in inside:
        unclosed -= 1  # that line starts inside another comment: go back to one that does not
    return "".join(parts), frozenset(inside), unclosed


def mask_comments(text: str, *, line_comments: bool = False) -> str:
    """``text`` with the comments replaced by spaces (line breaks kept), as Firefox would skip them.

    ``line_comments`` also blanks ``//`` to the end of the line, which is how ``user.js`` and
    ``prefs.js`` work; a stylesheet has only ``/* ... */``.
    """
    return _scan(text, line_comments=line_comments)[0]


@dataclass(frozen=True)
class _Document:
    """A text file split into lines, remembering how to put it back together.

    Each line keeps its own ending inside it: a trailing ``\\r`` of a CRLF line stays part of the
    line, so a line that is not touched is written back byte for byte, whatever the others use.
    ``crlf`` tells which ending a line that is added gets: the one most lines of the file use.
    """

    lines: list[str]
    crlf: bool
    trailing_newline: bool

    @classmethod
    def parse(cls, text: str) -> _Document:
        # Split on "\n" only: str.splitlines() would also break on U+2028, \x0b, \x1c... and
        # silently rewrite lines that merely contain those characters.
        if not text:
            return cls([], False, True)
        trailing = text.endswith("\n")
        body = text[:-1] if trailing else text
        lines = body.split("\n")
        both = text.count("\r\n")
        only_lf = text.count("\n") - both
        crlf = both > only_lf or (both == only_lf and lines[0].endswith("\r"))
        return cls(lines, crlf, trailing)

    def render(self) -> str:
        if not self.lines:
            return ""
        text = "\n".join(self.lines)
        return text + "\n" if self.trailing_newline else text

    def with_lines(self, lines: list[str]) -> _Document:
        return _Document(lines, self.crlf, self.trailing_newline)

    def new_line(self, content: str) -> str:
        """``content`` as a line of this file that is followed by another line."""
        return content + "\r" if self.crlf else content

    def appended(self, content: str, before: int | None = None) -> list[str]:
        """The lines with ``content`` added at the end, in the style of the file.

        With ``before``, the new line goes in front of that line instead (a comment that is never
        closed would swallow it at the end).
        """
        lines = list(self.lines)
        if before is not None:
            return [*lines[:before], self.new_line(content), *lines[before:]]
        if lines and self.crlf and not self.trailing_newline and not lines[-1].endswith("\r"):
            lines[-1] += "\r"  # the old last line gets the ending that it never needed
        last = content + "\r" if self.crlf and self.trailing_newline else content
        return [*lines, last]


def _is_charset(line: str) -> bool:
    return line.lstrip().startswith("@charset")


def _is_own_import(line: str, masked: str) -> bool:
    """An autohide ``@import`` that stands alone on a line and is not inside a comment."""
    stripped = line.strip()
    return stripped in OWN_IMPORTS and masked.strip() == stripped


def with_css_import(text: str) -> str:
    """Make the autohide ``@import`` the first rule of a stylesheet.

    An ``@import`` is only valid before other rules, but a leading ``@charset`` must stay first. A
    comment that happens to contain an ``@import`` line is left as it is.
    """
    document = _Document.parse(text)
    masked_text, inside, unclosed = _scan(text, line_comments=False)
    masked = _Document.parse(masked_text).lines
    # (line, masked line, whether the line starts inside a comment), without our own import lines.
    rest = [
        (line, blanked, number in inside)
        for number, (line, blanked) in enumerate(zip(document.lines, masked, strict=True))
        if not _is_own_import(line, blanked)
    ]
    position = 0
    if rest and _is_charset(rest[0][0]) and _is_charset(rest[0][1]):
        # After the @charset, and after the comment that it may open: never inside one.
        position = next(
            (n for n in range(1, len(rest)) if not rest[n][2]),
            0 if unclosed is not None else len(rest),
        )
    lines = [line for line, _, _ in rest]
    if position == len(lines) and not document.trailing_newline:
        # The import becomes the last line of a file that has no final line break. The line above
        # it keeps its own ending (as written) and gets a plain "\n": a "\r" at the end of the
        # file would be a line ending that nothing follows, and the next run, which reads the file
        # differently, would move it.
        lines.append(CSS_IMPORT)
    else:
        lines.insert(position, document.new_line(CSS_IMPORT))
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()


def without_css_import(text: str) -> str:
    document = _Document.parse(text)
    masked = _Document.parse(mask_comments(text)).lines
    lines = [
        line
        for line, blanked in zip(document.lines, masked, strict=True)
        if not _is_own_import(line, blanked)
    ]
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()


def _pref_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf'^\s*user_pref\(\s*"{re.escape(name)}"\s*,')


def _pref_lines(text: str, name: str) -> tuple[_Document, list[str], set[int], set[int]]:
    """The document, its lines without comments, and the numbers of the lines that set ``name``.

    Of the two sets, the first holds the lines that Firefox would read as setting the pref and the
    second those among them that we may edit.

    A line sets the pref when it does so with the comments taken away, so a pref that only appears
    in a comment is not there. A line may be edited only if the pref is also the start of the line
    as written: ``/* old */ user_pref(...)`` sets the pref, but rewriting that line would take the
    person's comment with it.
    """
    pattern = _pref_pattern(name)
    document = _Document.parse(text)
    masked = _Document.parse(mask_comments(text, line_comments=True)).lines
    setting = {n for n, line in enumerate(masked) if pattern.match(line)}
    editable = {
        n
        for n in setting
        # The line must also start with the pref, and open no comment that it does not close:
        # removing or rewriting a line that opens one would change what the lines below it mean.
        if pattern.match(document.lines[n])
        and _scan(document.lines[n], line_comments=True)[2] is None
    }
    return document, masked, setting, editable


def has_pref(text: str, name: str) -> bool:
    return bool(_pref_lines(text, name)[2])


def get_bool_pref(text: str, name: str) -> bool | None:
    """The boolean value of ``user_pref(name, ...)``, or ``None`` if absent or not a boolean.

    As in Firefox, the last line that sets the pref decides.
    """
    _, masked, setting, _ = _pref_lines(text, name)
    if not setting:
        return None
    pattern = re.compile(rf'^\s*user_pref\(\s*"{re.escape(name)}"\s*,\s*(true|false)\s*\)')
    match = pattern.match(masked[max(setting)])
    return match.group(1) == "true" if match else None


def remove_pref(text: str, name: str) -> str:
    document, _, _, editable = _pref_lines(text, name)
    lines = [line for number, line in enumerate(document.lines) if number not in editable]
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()


def _with_entry(document: _Document, entry: str) -> _Document:
    """The document with ``entry`` added as the last line that Firefox will read.

    A block comment that is never closed would swallow a line put after it, so the line goes in
    front of the one where that comment starts.
    """
    unclosed = _scan(document.render(), line_comments=True)[2]
    new_file = not document.lines
    return _Document(
        document.appended(entry, before=unclosed),
        document.crlf,
        document.trailing_newline or new_file,  # a new file ends with a newline
    )


def set_pref(text: str, name: str, value: bool, *, keep_existing: bool = False) -> str:
    """Set ``user_pref(name, value)``, in place when it already exists and appended otherwise.

    With ``keep_existing``, a value that is already present is left alone. Duplicate entries
    collapse into the first one. A line that Firefox would read but that cannot be edited without
    touching a comment is left as it is, and the entry is added after it instead, where it wins.
    """
    entry = f'user_pref("{name}", {"true" if value else "false"});'
    document, _, setting, editable = _pref_lines(text, name)

    if not setting:
        return _with_entry(document, entry).render()
    if keep_existing:
        return text

    lines: list[str] = []
    seen = False
    for number, line in enumerate(document.lines):
        if number not in editable:
            lines.append(line)
        elif not seen:
            lines.append(entry + ("\r" if line.endswith("\r") else ""))
            seen = True
    result = document.with_lines(lines)
    if get_bool_pref(result.render(), name) is not value:
        result = _with_entry(result, entry)
    rendered = result.render()
    if get_bool_pref(rendered, name) is not value:
        # A line that sets the pref ends in a comment that is never closed, and a new line can only
        # go in front of that line, where the old one would still win: nothing safe is left to do.
        raise UserFileError(
            errors.FILE_IO,
            f"{name} is set on a line that ends in a comment that is never closed, so it cannot be "
            "changed without editing that line",
            hint="Close the comment with */ or move that line, then run the command again.",
        )
    return text if result.lines == document.lines else rendered
