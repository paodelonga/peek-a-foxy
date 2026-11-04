"""Terminal output.

Everything shown to the user that is not a fixed string of ours (paths, profile names, git's own
messages) goes through here as :class:`~rich.text.Text`, never as a markup string: a directory
called ``[/x]`` must be printed as typed, not crash Rich or be mistaken for a style. Only strings
written in this package's source may contain markup, and they must not contain user data.
"""

from __future__ import annotations

import sys
from typing import NoReturn

import typer
from rich.console import Console, RenderableType
from rich.table import Table
from rich.text import Text

console = Console()
errors = Console(stderr=True)


def can_print(text: str) -> bool:
    """Whether the console's encoding can show ``text`` (a legacy code page cannot show emoji)."""
    try:
        text.encode(console.encoding or "utf-8")
    except UnicodeEncodeError:
        return False
    return True


def fox() -> str:
    """The fox, followed by spaces, or nothing where the console cannot show it."""
    return "\U0001f98a  " if can_print("\U0001f98a") else ""


def setup_streams() -> None:
    """Never crash on a character the console cannot show: print ``?`` instead."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def say(message: str, style: str = "") -> None:
    """Print ``message`` literally."""
    console.print(Text(message, style=style), soft_wrap=True)


def warn(message: str) -> None:
    console.print(Text.assemble(("warning: ", "yellow"), message), soft_wrap=True)


def step_line(number: int, total: int, description: str) -> None:
    console.print(Text.assemble((f"({number}/{total}) ", "cyan"), description), soft_wrap=True)


def fail(message: str) -> NoReturn:
    # soft_wrap: a path must not be broken across lines, people copy it from the message.
    errors.print(Text.assemble(("error: ", "bold red"), message), soft_wrap=True)
    raise typer.Exit(1)


def new_table(title: str, *, header: bool = True) -> Table:
    """A table whose title is plain text; fill it with :func:`row` so the cells are too."""
    return Table(title=Text(title), title_justify="left", show_header=header)


def row(table: Table, *cells: str) -> None:
    table.add_row(*[Text(cell) for cell in cells])


def show(renderable: RenderableType) -> None:
    console.print(renderable)
