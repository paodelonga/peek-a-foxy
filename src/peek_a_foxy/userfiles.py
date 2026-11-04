"""Edits to the user's own files: ``chrome/userChrome.css`` and ``user.js``.

Everything here works on text and is idempotent, so callers can read, transform and write back
without ever touching lines that belong to the user. Line endings (LF or CRLF) and the presence of a
final newline are preserved, and a transform that changes nothing returns its input unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CSS_IMPORT = '@import url("autohide.css");'
LEGACY_CSS_IMPORT = '@import url("tabs-autohide.css");'  # name before the project was renamed
OWN_IMPORTS = (CSS_IMPORT, LEGACY_CSS_IMPORT)

STYLESHEETS_PREF = "toolkit.legacyUserProfileCustomizations.stylesheets"
TABS_PREF = "userchrome.tabs.autohide"
URLBAR_PREF = "userchrome.urlbar.autohide"
OWN_PREFS = (TABS_PREF, URLBAR_PREF)


@dataclass(frozen=True)
class _Document:
    """A text file split into lines, remembering how to put it back together."""

    lines: list[str]
    newline: str
    trailing_newline: bool

    @classmethod
    def parse(cls, text: str) -> _Document:
        # Split on "\n" only: str.splitlines() would also break on U+2028, \x0b, \x1c... and
        # silently rewrite lines that merely contain those characters.
        newline = "\r\n" if "\r\n" in text else "\n"
        if not text:
            return cls([], newline, True)
        trailing = text.endswith("\n")
        body = text[:-1] if trailing else text
        lines = [line.removesuffix("\r") for line in body.split("\n")]
        return cls(lines, newline, trailing)

    def render(self) -> str:
        if not self.lines:
            return ""
        text = self.newline.join(self.lines)
        return text + self.newline if self.trailing_newline else text

    def with_lines(self, lines: list[str]) -> _Document:
        return _Document(lines, self.newline, self.trailing_newline)


def _is_charset(line: str) -> bool:
    return line.lstrip().startswith("@charset")


def with_css_import(text: str) -> str:
    """Make the autohide ``@import`` the first rule of a stylesheet.

    An ``@import`` is only valid before other rules, but a leading ``@charset`` must stay first.
    """
    document = _Document.parse(text)
    rest = [line for line in document.lines if line.strip() not in OWN_IMPORTS]
    position = 1 if rest and _is_charset(rest[0]) else 0
    lines = [*rest[:position], CSS_IMPORT, *rest[position:]]
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()


def without_css_import(text: str) -> str:
    document = _Document.parse(text)
    lines = [line for line in document.lines if line.strip() not in OWN_IMPORTS]
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()


def _pref_pattern(name: str) -> re.Pattern[str]:
    # Matches real pref lines only: a commented-out `// user_pref(...)` does not count.
    return re.compile(rf'^\s*user_pref\(\s*"{re.escape(name)}"\s*,')


def has_pref(text: str, name: str) -> bool:
    pattern = _pref_pattern(name)
    return any(pattern.match(line) for line in _Document.parse(text).lines)


def remove_pref(text: str, name: str) -> str:
    pattern = _pref_pattern(name)
    document = _Document.parse(text)
    lines = [line for line in document.lines if not pattern.match(line)]
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()


def set_pref(text: str, name: str, value: bool, *, keep_existing: bool = False) -> str:
    """Set ``user_pref(name, value)``, in place when it already exists and appended otherwise.

    With ``keep_existing``, a value that is already present is left alone. Duplicate entries
    collapse into the first one.
    """
    entry = f'user_pref("{name}", {"true" if value else "false"});'
    pattern = _pref_pattern(name)
    document = _Document.parse(text)

    if not any(pattern.match(line) for line in document.lines):
        appended = _Document(
            [*document.lines, entry],
            document.newline,
            document.trailing_newline or not text,  # a new file ends with a newline
        )
        return appended.render()
    if keep_existing:
        return text

    lines: list[str] = []
    seen = False
    for line in document.lines:
        if not pattern.match(line):
            lines.append(line)
        elif not seen:
            lines.append(entry)
            seen = True
    if lines == document.lines:
        return text
    return document.with_lines(lines).render()
