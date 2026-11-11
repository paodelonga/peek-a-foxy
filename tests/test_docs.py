"""The documents say what the program does: error table, default shortcuts, Windows notes, parity.

The READMEs are written by hand, so these tests only look at the facts that must not drift: every
error code of the registry is in both tables (English word for word), the default shortcuts are the
ones in the code, and the two READMEs have the same structure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from peek_a_foxy import cli, errors

ROOT = Path(__file__).resolve().parents[1]
READMES = ("README.md", "README.pt-BR.md")
ROW = re.compile(r"^\| `(PAF-\d{3})` \| (.+?) \| (.+) \|$", re.MULTILINE)


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _plain(text: str) -> str:
    """A table cell as the registry writes it: no code marks, no escaped pipes."""
    return text.replace("`", "").replace("\\|", "|")


HEADINGS = {
    "README.md": {"usage": "## Usage", "windows": "## Windows notes"},
    "README.pt-BR.md": {"usage": "## Como utilizar", "windows": "## Notas do Windows"},
}


def _section(name: str, which: str) -> str:
    """The text of one second-level section of a README."""
    text = _text(name)
    start = text.index(f"\n{HEADINGS[name][which]}\n")
    return text[start : text.index("\n## ", start + 4)]


def _rows(name: str) -> dict[str, tuple[str, str]]:
    return {code: (meaning, hint) for code, meaning, hint in ROW.findall(_text(name))}


@pytest.mark.parametrize("name", READMES)
def test_every_error_code_is_in_the_table_of_each_readme_exactly_once(name: str):
    found = ROW.findall(_text(name))
    assert sorted(code for code, _, _ in found) == sorted(errors.CODES)


def test_the_english_table_is_the_registry_word_for_word():
    rows = _rows("README.md")
    for code, entry in errors.CODES.items():
        meaning, hint = rows[code]
        assert _plain(meaning) == _plain(entry.meaning), code
        assert _plain(hint) == _plain(entry.hint), code


def test_the_portuguese_table_keeps_the_codes_commands_and_links_of_the_english_one():
    english, portuguese = _rows("README.md"), _rows("README.pt-BR.md")
    token = re.compile(r"`[^`]+`|https?://\S+")
    for code in errors.CODES:
        for en, pt in zip(english[code], portuguese[code], strict=True):
            assert pt.strip() and pt != en, code
            # Every command, option, file name and link of the English cell is in the Portuguese.
            assert sorted(token.findall(pt)) == sorted(token.findall(en)), code


@pytest.mark.parametrize("name", READMES)
def test_the_default_shortcuts_in_the_prefs_table_are_the_ones_of_the_code(name: str):
    text = _text(name)
    tabs = re.search(r"^\| `peekafoxy\.tabs\.shortcut` \| (.+?) \|", text, re.MULTILINE)
    urlbar = re.search(r"^\| `peekafoxy\.urlbar\.shortcut` \| (.+?) \|", text, re.MULTILINE)
    assert tabs and urlbar
    assert f"`{cli.TABS_SHORTCUT_LINUX}`" in tabs.group(1)
    assert f"`{cli.TABS_SHORTCUT}`" in tabs.group(1)
    assert urlbar.group(1) == f"`{cli.URLBAR_SHORTCUT}`"
    usage = _section(name, "usage")
    assert cli.TABS_SHORTCUT_LINUX in usage and cli.URLBAR_SHORTCUT in usage


@pytest.mark.parametrize("name", [*READMES, ".github/ISSUE_TEMPLATE/bug_report.yml"])
def test_no_text_teaches_the_old_navigation_bar_shortcut_as_a_default(name: str):
    text = _text(name)
    # The only place that may name it is the sentence that explains why it changed.
    for line in text.splitlines():
        if re.search(r"Ctrl\+Alt\+U\b", line):
            assert "Open Tabs" in line or "Abas abertas" in line, line


@pytest.mark.parametrize("name", READMES)
def test_the_windows_notes_describe_the_powershell_route_and_not_python_exe(name: str):
    notes = _section(name, "windows")
    assert "powershell.exe" in notes and "-EncodedCommand" in notes
    assert "python.exe" not in notes
    assert "gh attestation verify peek-a-foxy.exe -R paodelonga/peek-a-foxy" in notes


@pytest.mark.parametrize("name", READMES)
def test_the_readmes_say_that_powershell_completion_is_refused_and_how_to_get_it(name: str):
    text = _text(name)
    assert "--show-completion" in text and "Unrestricted" in text
    # The refusal must be said next to PowerShell, not only in the generic completion paragraph.
    refusal = next(line for line in text.splitlines() if "Unrestricted" in line)
    for needle in ("PowerShell", "--install-completion", "--show-completion"):
        assert needle in refusal, needle


@pytest.mark.parametrize("name", READMES)
def test_the_readmes_do_not_say_that_macos_is_supported_and_name_both_emptied_folders(name: str):
    text = _text(name)
    assert "Linux, macOS and Windows" not in text and "Linux, no macOS e no Windows" not in text
    heading = {"README.md": "## Uninstall", "README.pt-BR.md": "## Desinstalação"}[name]
    uninstall = text[text.index(f"\n{heading}\n") + 1 :].split("\n## ")[0]
    assert "`chrome/JS`" in uninstall and "`chrome/resources`" in uninstall


def _outline(name: str) -> list[str]:
    """The headings, the number of table rows and the code fences, in order, ignoring the words."""
    outline: list[str] = []
    fenced = False
    for line in _text(name).splitlines():
        if line.startswith("```"):
            fenced = not fenced
            outline.append("fence")
        elif not fenced and re.match(r"#{2,6} ", line):
            outline.append(line.split(" ")[0])
        elif not fenced and line.startswith("|"):
            outline.append("row")
    return outline


def test_the_two_readmes_have_the_same_structure():
    assert _outline("README.md") == _outline("README.pt-BR.md")
