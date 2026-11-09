"""Terminal output.

Everything shown to the user that is not a fixed string of ours (paths, profile names, git's own
messages) goes through here as :class:`~rich.text.Text`, never as a markup string: a directory
called ``[/x]`` must be printed as typed, not crash Rich or be mistaken for a style. Only strings
written in this package's source may contain markup, and they must not contain user data.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import IO, Any

from rich.console import Console, RenderableType
from rich.table import Table
from rich.text import Text

from peek_a_foxy import errors as paf
from peek_a_foxy.errors import PeekError

_output_lost = False  # set when a write to stdout or stderr failed for good (no reader, no space)


def output_lost() -> bool:
    """Whether some output could not be written (the reader closed the pipe: ``... | head -c1``)."""
    return _output_lost


def reset_output_state() -> None:
    """Forget an earlier loss of output: each run of the program starts clean."""
    global _output_lost
    _output_lost = False


def silence(stream: IO[str] | None) -> None:
    """Point the file descriptor of ``stream`` at nowhere.

    After a broken pipe every later write, and the interpreter's own flush at exit, would fail
    again and print a traceback; with the descriptor going nowhere they succeed and say nothing.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        if stream is not None:
            os.dup2(devnull, stream.fileno())
    except (OSError, ValueError, AttributeError):  # no real descriptor (a test, a closed stream)
        pass
    finally:
        os.close(devnull)


def lost_output(stream: IO[str] | None) -> None:
    """Remember that ``stream`` cannot be written to, and make every later write harmless."""
    global _output_lost
    _output_lost = True
    silence(stream)


class _Console(Console):
    """A Rich console that does not end the program when its reader goes away.

    Rich's own reaction to a broken pipe is ``raise SystemExit(1)`` from inside ``print``. That
    would stop an installation half way through just because its output was piped into ``head``.
    """

    def on_broken_pipe(self) -> None:
        self.quiet = True  # nothing more to render for a reader that is gone
        lost_output(self.file)


console = _Console()
errors = _Console(stderr=True)


def _print(target: Console, *args: Any, **kwargs: Any) -> None:
    """``target.print`` that treats output which cannot be written as lost output, not a crash.

    A command that is half way through changing files must still finish them when the person
    pipes its output into ``head`` (a broken pipe), or sends it to a full disk (``> /dev/full``)
    or a closed stream. Only the text is lost; the first failure is logged.
    """
    try:
        target.print(*args, **kwargs)
    except (OSError, ValueError) as error:  # ValueError: "I/O operation on closed file"
        if not _output_lost:
            logging.getLogger(__name__).info("output to %s was lost: %r", target.file, error)
        lost_output(target.file)


class QuietStreamHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """The verbose console log, which also gives up quietly on a broken pipe."""

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (OSError, ValueError)):
            lost_output(self.stream)
            return
        super().handleError(record)


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
    _print(console, Text(message, style=style), soft_wrap=True)


def note(message: str) -> None:
    """A remark for the person, on stderr so that a report on stdout stays clean."""
    _print(errors, Text(message, style="dim"), soft_wrap=True)


def warn(message: str) -> None:
    """A warning, on stderr: stdout is for the product (a plan, a report that a program reads)."""
    _print(errors, Text.assemble(("warning: ", "yellow"), message), soft_wrap=True)


def step_line(number: int, total: int, description: str) -> None:
    _print(console, Text.assemble((f"({number}/{total}) ", "cyan"), description), soft_wrap=True)


def _error_line(text: Text | str) -> None:
    # soft_wrap: a path must not be broken across lines, people copy it from the message.
    _print(errors, text if isinstance(text, Text) else Text(text), soft_wrap=True)


def report(error: PeekError, *, verbose: bool, log_path: Path | None) -> None:
    """Print an expected failure: the code and message, what to do, then the extras."""
    _error_line(Text.assemble((f"error [{error.code.code}]: ", "bold red"), error.message))
    if error.hint:
        _error_line(Text.assemble(("What to do: ", "bold"), error.hint))
    context = paf.get_context(error)
    if context:
        _error_line(context)
    if verbose:
        _verbose_details(error, error.detail)
    _log_line(log_path)


def report_unexpected(error: BaseException, *, verbose: bool, log_path: Path | None) -> None:
    """Print a bug: the unexpected-error code and hint, and (verbose) the traceback."""
    code = paf.UNEXPECTED
    _error_line(Text.assemble((f"error [{code.code}]: ", "bold red"), code.meaning))
    _error_line(Text.assemble(("What to do: ", "bold"), code.hint))
    context = paf.get_context(error)
    if context:
        _error_line(context)
    if verbose:
        _error_line("".join(traceback.format_exception(error)).rstrip())
    _log_line(log_path)


def _verbose_details(error: BaseException, detail: str) -> None:
    if detail:
        _error_line(Text.assemble(("Details: ", "bold"), detail))
    cause = error.__cause__
    if cause is not None:
        _error_line(Text.assemble(("Caused by: ", "bold"), f"{type(cause).__name__}: {cause}"))


def _log_line(log_path: Path | None) -> None:
    if log_path is not None:
        _error_line(f"Details were saved to {log_path}")


def new_table(title: str, *, header: bool = True) -> Table:
    """A table whose title is plain text; fill it with :func:`row` so the cells are too."""
    return Table(title=Text(title), title_justify="left", show_header=header)


def row(table: Table, *cells: str) -> None:
    table.add_row(*[Text(cell) for cell in cells])


def show(renderable: RenderableType) -> None:
    _print(console, renderable)
