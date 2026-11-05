"""The report of ``peek-a-foxy doctor``: its model, its three renderings, saving and copying.

A :class:`Report` is a list of :class:`Section` objects, each a list of :class:`Check` objects.
A check has a status (``ok``, ``warn`` or ``fail``); one that is not ``ok`` also has a plain
``message``, a ``hint`` ("What to do") and a ``code`` from the registry in
:mod:`peek_a_foxy.errors`.

Everything that leaves the program (terminal, clipboard, file) goes through :meth:`Report.redacted`
first, so the home folder, the user name and the Firefox profile folder names are hidden in all of
it, whatever the format. Nothing is ever sent anywhere.

The JSON form is a contract (``"schema": 1``): keys are only ever added, never renamed or removed,
and a change of meaning bumps ``schema``. The keys are::

    schema, tool, version, generated, ok, counts{ok,warn,fail},
    sections[{id, title, checks[{id, title, status, value, message, hint, code, detail}]}],
    notice, issues_url
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from peek_a_foxy import errors
from peek_a_foxy.errors import UserFileError

SCHEMA = 1
OK, WARN, FAIL = "ok", "warn", "fail"
STATUSES = (OK, WARN, FAIL)
NOTICE = "Nothing was sent anywhere. Review it, then paste it into your issue."
ISSUES_NEW_URL = "https://github.com/paodelonga/peek-a-foxy/issues/new/choose"
CLIPBOARD_TIMEOUT = 10  # seconds a clipboard tool gets before it is given up on
MAX_DETAIL = 400  # characters kept of one technical detail (a report must stay pasteable)

_STYLES = {OK: "green", WARN: "yellow", FAIL: "bold red"}


@dataclass(frozen=True)
class Check:
    id: str  # stable, dotted: "profile.import"
    title: str
    status: str
    value: str = ""  # the fact found, as text
    message: str = ""  # when not OK: what is wrong, in one plain sentence
    hint: str = ""  # when not OK: what to do
    code: str = ""  # when not OK: PAF-xxx
    detail: str = ""  # technical extra (hashes, raw errors); shown with --verbose in the table

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.status != OK and not (self.message and self.hint and self.code):
            raise ValueError(
                f"{self.id}: a check that is not OK needs a message, a hint and a code"
            )
        if self.code and self.code not in errors.CODES:
            raise ValueError(f"{self.code} is not a registered error code")

    def mapped(self, change: Callable[[str], str]) -> Check:
        return Check(
            self.id,
            self.title,
            self.status,
            change(self.value),
            change(self.message),
            change(self.hint),
            self.code,
            change(self.detail),
        )


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    checks: tuple[Check, ...]


@dataclass(frozen=True)
class Report:
    version: str
    generated: str  # ISO 8601, UTC
    sections: tuple[Section, ...]
    # The profile names found in profiles.ini, in order. They are never part of the output: the
    # redactor needs them to hide a name wherever it turns up in a text (see Redactor).
    profile_names: tuple[str, ...] = ()

    def all_checks(self) -> list[Check]:
        return [check for section in self.sections for check in section.checks]

    @property
    def counts(self) -> dict[str, int]:
        found = [check.status for check in self.all_checks()]
        return {status: found.count(status) for status in STATUSES}

    @property
    def ok(self) -> bool:
        """No FAIL (warnings are fine): this decides the exit code."""
        return self.counts[FAIL] == 0

    def redacted(self, change: Callable[[str], str]) -> Report:
        """The same report with ``change`` (a redactor) applied to every text in it.

        Afterwards every text is also cleaned of control and direction-changing characters, which
        a file name or a file's content could use to mislead a terminal or a reader.
        """

        def both(text: str) -> str:
            return clean(change(text))

        sections = tuple(
            Section(s.id, both(s.title), tuple(c.mapped(both) for c in s.checks))
            for s in self.sections
        )
        return Report(self.version, both(self.generated), sections)


def clean(text: str) -> str:
    """Replace what could mislead a terminal or a reader: line breaks and tabs become spaces,
    other control characters (escape sequences) and invisible direction overrides become U+FFFD.
    Right-to-left letters themselves are kept."""
    out = []
    for char in text:
        if char in "\r\n\t\v\f\x85\u2028\u2029":
            out.append(" ")
        elif unicodedata.category(char) == "Cc" or char in _DIRECTION_CONTROLS:
            out.append("\ufffd")
        else:
            out.append(char)
    return "".join(out)


_DIRECTION_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 3] + "..."


# --- JSON ---------------------------------------------------------------------------------------


def to_dict(report: Report) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "tool": "peek-a-foxy",
        "version": report.version,
        "generated": report.generated,
        "ok": report.ok,
        "counts": report.counts,
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "checks": [
                    {
                        "id": check.id,
                        "title": check.title,
                        "status": check.status,
                        "value": check.value,
                        "message": check.message,
                        "hint": check.hint,
                        "code": check.code,
                        "detail": _clip(check.detail),
                    }
                    for check in section.checks
                ],
            }
            for section in report.sections
        ],
        "notice": NOTICE,
        "issues_url": ISSUES_NEW_URL,
    }


def to_json(report: Report) -> str:
    return json.dumps(to_dict(report), indent=2, ensure_ascii=False) + "\n"


# --- Markdown -----------------------------------------------------------------------------------


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell (and that cannot open a code fence)."""
    # "<" is escaped because Markdown would take <user> or <profile 1> for an HTML tag and hide it.
    return " ".join(text.split()).replace("|", "\\|").replace("<", "\\<")


def _result(check: Check) -> str:
    parts = [part for part in (check.value, check.message) if part]
    return _cell(" - ".join(parts))


def to_markdown(report: Report) -> str:
    counts = report.counts
    lines = [
        "# Peek-a-Foxy doctor report",
        "",
        f"This report was generated by peek-a-foxy {_cell(report.version)} on "
        f"{report.generated} and uses report format {SCHEMA}.",
        "",
        f"**Result: {counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[OK]} OK**",
    ]
    for section in report.sections:
        lines += [
            "",
            f"## {_cell(section.title)}",
            "",
            "| Status | Check | Result |",
            "|---|---|---|",
        ]
        for check in section.checks:
            lines.append(f"| {check.status.upper()} | {_cell(check.title)} | {_result(check)} |")
        todo = [check for check in section.checks if check.status != OK]
        if todo:
            lines += ["", "What to do:"]
            lines += [
                f"- **{_cell(check.title)}** (`{check.code}`): {_cell(check.hint)}"
                for check in todo
            ]
        details = [check for check in section.checks if check.detail]
        if details:
            lines += ["", "Technical details:", "", "```text"]
            lines += [
                f"{check.id}: {_clip(check.detail).replace('`', chr(39))}" for check in details
            ]
            lines.append("```")
    lines += ["", NOTICE, ISSUES_NEW_URL, ""]
    return "\n".join(lines)


# --- the friendly table (terminal) --------------------------------------------------------------


def to_rich(report: Report, *, verbose: bool = False) -> list[RenderableType]:
    """Tables for a terminal: one per section, then what to do, then the closing lines."""
    out: list[RenderableType] = []
    for section in report.sections:
        table = Table(title=Text(section.title), title_justify="left", show_header=True)
        table.add_column("Status")
        table.add_column("Check")
        table.add_column("Result", overflow="fold")
        for check in section.checks:
            result = Text(" - ".join(part for part in (check.value, check.message) if part))
            if verbose and check.detail:
                result.append(f"\n{_clip(check.detail)}", style="dim")
            table.add_row(
                Text(check.status.upper(), style=_STYLES[check.status]), Text(check.title), result
            )
        out.append(table)
        for check in section.checks:
            if check.status != OK:
                out.append(
                    Text.assemble(
                        (f"{check.title} [{check.code}] ", _STYLES[check.status]),
                        ("What to do: ", "bold"),
                        check.hint,
                    )
                )
    counts = report.counts
    style = "bold red" if counts[FAIL] else "yellow" if counts[WARN] else "green"
    out.append(
        Text(f"Result: {counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[OK]} OK", style=style)
    )
    out.append(Text(f"{NOTICE}\n{ISSUES_NEW_URL}", style="dim"))
    return out


# --- saving -------------------------------------------------------------------------------------


def default_save_path(folder: Path, suffix: str, now: datetime) -> Path:
    """``doctor-YYYYmmdd-HHMMSS.<suffix>`` in ``folder``, numbered if it exists already."""
    stem = f"doctor-{now:%Y%m%d-%H%M%S}"
    candidate = folder / f"{stem}.{suffix}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{number}.{suffix}"
        number += 1
    return candidate


def save(text: str, path: Path) -> Path:
    """Write ``text`` to a file that must not exist yet: a report never replaces anything.

    The file is created exclusively (never through a symbolic link that is already there, never
    over another file, even when two runs race), and a write that fails halfway removes what it
    wrote, so no cut-off report is left behind.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "x", encoding="utf-8", newline="\n")  # noqa: SIM115 - closed below
    except FileExistsError as error:
        if path.parent.is_dir():  # the file is what exists
            raise UserFileError(
                errors.FILE_EXISTS, f"{path} already exists.", detail=repr(error)
            ) from error
        raise
    try:
        with handle:
            handle.write(text)
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    return path


def save_new(text: str, folder: Path, suffix: str, now: datetime) -> Path:
    """Save under the default name, taking the next free one if another run took it meanwhile."""
    for _ in range(1000):
        path = default_save_path(folder, suffix, now)
        try:
            return save(text, path)
        except UserFileError as error:
            if error.code is not errors.FILE_EXISTS:
                raise
    raise UserFileError(errors.FILE_EXISTS, f"no free name for a report in {folder}")


# --- the clipboard (best effort) ----------------------------------------------------------------

Runner = Callable[..., object]


def clipboard_commands(kind: str, environ: Mapping[str, str]) -> list[tuple[list[str], str]]:
    """Programs that put text on the clipboard, with the encoding each wants, best first."""
    if kind == "windows":
        return [(["clip"], "utf-16")]  # clip reads UTF-16 with a byte order mark
    if kind == "macos":
        return [(["pbcopy"], "utf-8")]
    commands: list[tuple[list[str], str]] = []
    if environ.get("WAYLAND_DISPLAY"):
        commands.append((["wl-copy"], "utf-8"))
    if environ.get("DISPLAY"):
        commands.append((["xclip", "-selection", "clipboard"], "utf-8"))
    return commands


def copy_to_clipboard(
    text: str,
    kind: str,
    environ: Mapping[str, str],
    *,
    which: Callable[[str], str | None],
    run: Runner = subprocess.run,
) -> str | None:
    """Copy ``text`` with the first tool that is installed and works; its name, or ``None``."""
    for command, encoding in clipboard_commands(kind, environ):
        if which(command[0]) is None:
            continue
        try:
            run(
                command,
                input=text.encode(encoding),
                check=True,
                timeout=CLIPBOARD_TIMEOUT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        return command[0]
    return None
