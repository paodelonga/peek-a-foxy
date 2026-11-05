"""Command line interface: ``peek-a-foxy install`` / ``uninstall``."""

from __future__ import annotations

import errno
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.panel import Panel
from typer.core import TyperGroup

from peek_a_foxy import __version__, errors, logs, platform, ui
from peek_a_foxy.errors import DiscoveryError, PeekError, PlatformError
from peek_a_foxy.installer import Plan, Step, plan_install, plan_uninstall
from peek_a_foxy.profiles import Profile, default_profile, read_profiles

log = logging.getLogger(__name__)

# Shown to the user as the way to toggle each bar; they must match the script's TARGETS.
TABS_SHORTCUT = "Ctrl+Alt+T"
URLBAR_SHORTCUT = "Ctrl+Alt+U"

# The arguments of this run, as given (the log records them, redacted).
_argv: list[str] = sys.argv[1:]


class _Group(TyperGroup):
    """The top-level command: every failure ends up as a message, a log entry and an exit code.

    An expected failure (:class:`PeekError`, or a file system error) exits with 1 and a short
    message; anything else is a bug: it exits with 70 and the unexpected-error code. Both are
    logged with their traceback. Typer's own handling would print a stack trace instead.
    """

    def main(self, args: Sequence[str] | None = None, *rest: Any, **extra: Any) -> Any:
        global _argv
        _argv = list(sys.argv[1:] if args is None else args)
        return super().main(args, *rest, **extra)

    def invoke(self, ctx: Any) -> Any:
        code = errors.EXIT_OK
        try:
            return super().invoke(ctx)
        except KeyboardInterrupt:
            code = 130
            raise
        except Exception as error:
            if _is_click_signal(error):
                code = getattr(error, "exit_code", errors.EXIT_FAILURE)
                raise
            code = _handle_failure(error)
            raise typer.Exit(code) from None
        finally:
            logs.stop(code)


def _is_click_signal(error: Exception) -> bool:
    """Exit, Abort and the usage errors: Click prints and exits for these itself.

    Typer bundles its own copy of Click in recent versions and relies on the real one in older
    ones, so they are recognised by what they are rather than by their class.
    """
    if isinstance(error, (typer.Exit, typer.Abort)):
        return True
    return callable(getattr(error, "show", None)) and hasattr(error, "exit_code")


def _handle_failure(error: Exception) -> int:
    """Log and print a failure; return the exit code."""
    if isinstance(error, OSError) and error.errno == errno.EPIPE:
        raise error  # the reader of our output went away: not ours to explain
    if isinstance(error, OSError):
        error = errors.from_oserror(error)
    verbose, path = logs.is_verbose(), logs.active_path()
    if isinstance(error, PeekError):
        log.error("failed [%s] %s", error.code.code, error.message, exc_info=error)
        if error.detail:
            log.error("detail: %s", error.detail)
        ui.report(error, verbose=verbose, log_path=path)
        return errors.EXIT_FAILURE
    log.error("unexpected error [%s]", errors.UNEXPECTED.code, exc_info=error)
    ui.report_unexpected(error, verbose=verbose, log_path=path)
    return errors.EXIT_UNEXPECTED


app = typer.Typer(
    cls=_Group,
    pretty_exceptions_show_locals=False,  # a traceback must never print the user's variables
    help="Peek-a-boo for Foxys: autohide the tab bar and navigation bar per window.",
    no_args_is_help=True,
    add_completion=True,  # adds --install-completion / --show-completion for bash, zsh, fish
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _complete_profile(incomplete: str) -> list[tuple[str, str]]:
    """Shell completion for --profile: the profiles listed in profiles.ini."""
    try:
        profiles = read_profiles(platform.profiles_root())
    except (DiscoveryError, PlatformError):
        return []
    return [
        (str(profile.path), profile.name)
        for profile in profiles
        if str(profile.path).startswith(incomplete)
    ]


def _complete_firefox_dir(incomplete: str) -> list[str]:
    """Shell completion for --firefox-dir: the Firefox installations that were detected."""
    try:
        candidates = platform.firefox_dir_candidates()
    except PlatformError:
        return []
    return [str(path) for path in candidates if str(path).startswith(incomplete)]


ProfileOption = Annotated[
    Path | None,
    typer.Option(
        "--profile",
        help="Firefox profile directory. Default: the default profile from profiles.ini.",
        autocompletion=_complete_profile,
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
]
FirefoxDirOption = Annotated[
    Path | None,
    typer.Option(
        "--firefox-dir",
        help="Firefox install directory for the loader. Default: auto-detected.",
        autocompletion=_complete_firefox_dir,
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
]
SkipLoaderOption = Annotated[
    bool,
    typer.Option(
        "--skip-loader",
        help="Only install the profile files; leave the Firefox install directory alone.",
    ),
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Show what would be done without changing anything.")
]
YesOption = Annotated[
    bool,
    typer.Option(
        "--yes",
        "-y",
        help="Don't ask anything: apply without confirming, and don't prompt for the profile or "
        "the Firefox installation (an unclear choice is an error instead).",
    ),
]


VerboseOption = Annotated[
    bool,
    typer.Option(
        "--verbose", "-v", help="Also print the technical details of each step, and of an error."
    ),
]
LogFileOption = Annotated[
    Path | None,
    typer.Option(
        "--log-file",
        help="Write the log to this file instead of the default one (see: peek-a-foxy logs).",
        dir_okay=False,
    ),
]
NoLogOption = Annotated[
    bool, typer.Option("--no-log", help="Do not write a log file for this run.")
]


@dataclass
class _LogOptions:
    """The logging flags given before the command name, which every command also accepts."""

    verbose: bool = False
    log_file: Path | None = None
    no_log: bool = False


def _begin(
    ctx: typer.Context,
    verbose: bool,
    log_file: Path | None,
    no_log: bool,
    *,
    write_file: bool = True,
) -> None:
    """Start logging for this run, from the flags before and after the command name."""
    given = ctx.obj if isinstance(ctx.obj, _LogOptions) else _LogOptions()
    target = logs.resolve_target(
        log_file=str(log_file or given.log_file or "") or None,
        no_log=no_log or given.no_log or not write_file,
        env_value=os.environ.get(logs.ENV_VAR),
    )
    logs.start(
        target=target.path,
        verbose=verbose or given.verbose,
        argv=_argv,
        version=__version__,
        warn=ui.warn,
    )


def _version(value: bool) -> None:
    if value:
        ui.console.print(f"peek-a-foxy {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
    verbose: VerboseOption = False,
    log_file: LogFileOption = None,
    no_log: NoLogOption = False,
) -> None:
    """Peek-a-boo for Foxys: autohide the tab bar and navigation bar per window."""
    ui.setup_streams()
    ctx.obj = _LogOptions(verbose, log_file, no_log)


def _interactive(yes: bool) -> bool:
    return not yes and sys.stdin.isatty() and sys.stdout.isatty()


def _choose_profile(profile: Path | None, yes: bool) -> Path:
    if profile is not None:
        return profile
    profiles = read_profiles(platform.profiles_root())
    if len(profiles) == 1:
        return profiles[0].path
    preferred = default_profile(profiles)
    if _interactive(yes):
        return _prompt_profile(profiles, preferred)
    if preferred is None:
        # Several installations (release, developer edition...) each have their own default.
        raise DiscoveryError(errors.AMBIGUOUS_PROFILE, "cannot tell which profile to use")
    return preferred.path


def _prompt_profile(profiles: list[Profile], preferred: Profile | None) -> Path:
    table = ui.new_table("Firefox profiles")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Path", overflow="fold")
    table.add_column("Default for an install")
    for number, entry in enumerate(profiles, start=1):
        ui.row(table, str(number), entry.name, str(entry.path), "yes" if entry.is_default else "")
    ui.show(table)
    default_number = profiles.index(preferred) + 1 if preferred else None
    choice: int = typer.prompt("Install into profile number", default=default_number, type=int)
    if not 1 <= choice <= len(profiles):
        raise DiscoveryError(
            errors.INVALID_CHOICE, f"choose a number between 1 and {len(profiles)}"
        )
    return profiles[choice - 1].path


def _resolve_firefox_dir(firefox_dir: Path | None, skip_loader: bool, yes: bool) -> Path | None:
    if skip_loader:
        return None
    if firefox_dir is None:
        firefox_dir = _choose_firefox_dir(yes)
    kind = platform.sandbox_kind(firefox_dir)
    if kind:
        raise DiscoveryError(
            errors.FIREFOX_SANDBOXED,
            f"{kind} builds of Firefox are read-only and not supported ({firefox_dir})",
        )
    return firefox_dir


def _choose_firefox_dir(yes: bool) -> Path:
    candidates = platform.firefox_dir_candidates()
    if not candidates:
        raise DiscoveryError(
            errors.FIREFOX_NOT_FOUND, "could not find the Firefox install directory"
        )
    if len(candidates) == 1:
        return candidates[0]
    if not _interactive(yes):
        found = ", ".join(str(path) for path in candidates)
        raise DiscoveryError(
            errors.SEVERAL_FIREFOXES, f"several Firefox installations found ({found})"
        )

    table = ui.new_table("Firefox installations")
    table.add_column("#", justify="right")
    table.add_column("Path", overflow="fold")
    for number, candidate in enumerate(candidates, start=1):
        ui.row(table, str(number), str(candidate))
    ui.show(table)
    choice: int = typer.prompt("Install the loader into number", type=int)
    if not 1 <= choice <= len(candidates):
        raise DiscoveryError(
            errors.INVALID_CHOICE, f"choose a number between 1 and {len(candidates)}"
        )
    return candidates[choice - 1]


def _show_plan(plan: Plan, title: str) -> None:
    table = ui.new_table(title, header=False)
    table.add_column(justify="right", style="dim")
    table.add_column(overflow="fold")
    for number, step in enumerate(plan.steps, start=1):
        ui.row(table, str(number), step.description)
    ui.show(table)


def _confirm(question: str = "Apply these changes?", *, default: bool = True) -> None:
    """Ask before changing anything; with nobody to ask (no terminal) refuse instead of assuming."""
    if not _interactive(False):
        hint = None
        if platform.is_windows():
            hint = (
                "Add --yes to apply the changes without asking. (Git Bash does not look like a "
                "terminal to Python: use --yes, or run the command through winpty.)"
            )
        raise PlatformError(
            errors.NO_TERMINAL,
            "no terminal to ask for confirmation; pass --yes to apply the changes anyway",
            hint=hint,
        )
    if not typer.confirm(question, default=default):
        raise typer.Exit(1)


def _apply(plan: Plan, title: str, dry_run: bool, yes: bool) -> list[str]:
    """Show the plan, ask for confirmation when interactive, then run it."""
    _show_plan(plan, title)
    if dry_run:
        ui.console.print("[dim]Dry run: nothing was changed.[/]")
        raise typer.Exit()
    if not yes:
        _confirm()

    def announce(number: int, total: int, step: Step) -> None:
        ui.step_line(number, total, step.description)

    try:
        return plan.execute(announce)
    except Exception as error:
        # Whatever went wrong, the person should know what the earlier steps already changed.
        errors.set_context(error, _progress(plan))
        raise


def _progress(plan: Plan) -> str:
    """What a failed plan already changed, and that running it again is safe."""
    finished = len(plan.completed)
    if finished:
        done = "; ".join(step.description for step in plan.completed)
        progress = f"{finished} of {len(plan.steps)} steps finished: {done}."
    else:
        progress = "No step had finished."
    return (
        f"{progress} The failed step may have changed part of its files. "
        "Running the same command again is safe: every step can be repeated."
    )


def done_summary(skipped_loader: bool, loader_conflict: bool) -> tuple[str, str]:
    """Title and body (Rich markup, fixed text only) of the panel closing a successful install."""
    cautions = []
    if skipped_loader:
        cautions.append(
            "[bold]--skip-loader[/]: the fx-autoconfig loader was not installed. The script only "
            "runs if fx-autoconfig is already set up in your Firefox; otherwise run "
            "[bold]peek-a-foxy install[/] again without it."
        )
    if loader_conflict:
        cautions.append(
            "Another autoconfig setup was found in the Firefox install directory and left "
            "untouched (see the warning above). The script only runs if that setup is a "
            "compatible fx-autoconfig."
        )
    if cautions:
        cautions.append(
            "Once the loader is in place, close [bold]all[/] Firefox windows and start it again."
        )
        return "Installed, with a caveat", "\n\n".join(cautions)
    return "Done", (
        "Close [bold]all[/] Firefox windows and start it again.\n\n"
        f"Both autohides start [bold]off[/]. Turn them on with [bold]{TABS_SHORTCUT}[/] (tabs) and "
        f"[bold]{URLBAR_SHORTCUT}[/] (urlbar), or add the buttons from Customize Toolbar. "
        "The shortcuts, sizes and timings can be changed in Firefox's settings, under "
        "[bold]Peek-a-Foxy[/].\n\n"
        "No button or shortcut? Clear the startup cache in [bold]about:support[/]. "
        "A Firefox update can remove the loader: run [bold]peek-a-foxy install[/] again.\n\n"
        f"[bold magenta]PEEK-A-BOO![/] {ui.fox()}https://youtu.be/6uJf2IT2Zh8?t=59"
    )


@app.command()
def install(
    ctx: typer.Context,
    profile: ProfileOption = None,
    firefox_dir: FirefoxDirOption = None,
    skip_loader: SkipLoaderOption = False,
    dry_run: DryRunOption = False,
    yes: YesOption = False,
    verbose: VerboseOption = False,
    log_file: LogFileOption = None,
    no_log: NoLogOption = False,
) -> None:
    """Install the autohide stylesheet and script, and the fx-autoconfig loader they need."""
    _begin(ctx, verbose, log_file, no_log)
    profile_path = _choose_profile(profile, yes)
    loader_dir = _resolve_firefox_dir(firefox_dir, skip_loader, yes)
    plan = plan_install(profile_path, loader_dir)
    warnings = _apply(plan, f"Install into {profile_path}", dry_run, yes)

    for warning in warnings:
        ui.warn(warning)
    title, body = done_summary(skip_loader, plan.loader_conflict)
    color = "green" if title == "Done" else "yellow"
    ui.show(Panel(body, title=f"[{color}]{title}[/]", title_align="left"))


@app.command()
def uninstall(
    ctx: typer.Context,
    profile: ProfileOption = None,
    dry_run: DryRunOption = False,
    yes: YesOption = False,
    verbose: VerboseOption = False,
    log_file: LogFileOption = None,
    no_log: NoLogOption = False,
) -> None:
    """Remove this project's files and prefs from a profile (the loader is left in place)."""
    _begin(ctx, verbose, log_file, no_log)
    profile_path = _choose_profile(profile, yes)
    plan = plan_uninstall(profile_path)
    _apply(plan, f"Uninstall from {profile_path}", dry_run, yes)
    ui.console.print(
        "[green]Done.[/] Left in place: chrome/utils and the loader in the Firefox install "
        "directory, since other scripts may use them."
    )


def _size(files: list[Path]) -> str:
    total = sum(path.stat().st_size for path in files)
    return f"{total / 1024:.1f} KB" if total < 1024 * 1024 else f"{total / 1024 / 1024:.1f} MB"


MAX_SHOWN = 30  # lines of the last run that `logs` prints before it folds the middle


@app.command("logs")
def logs_command(
    ctx: typer.Context,
    open_folder: Annotated[
        bool, typer.Option("--open", help="Open the folder that holds the log.")
    ] = False,
    clear: Annotated[bool, typer.Option("--clear", help="Delete the log files.")] = False,
    yes: YesOption = False,
    log_file: LogFileOption = None,
) -> None:
    """Show where the log is and what the last run did; open its folder or delete it."""
    if open_folder and clear:
        raise typer.BadParameter("use --open or --clear, not both")
    _begin(ctx, False, None, False, write_file=False)  # reading the log must not write to it
    given = ctx.obj if isinstance(ctx.obj, _LogOptions) else _LogOptions()
    target = logs.resolve_target(
        log_file=str(log_file or given.log_file or "") or None,
        env_value=os.environ.get(logs.ENV_VAR),
    )
    path = target.path
    if path is None:  # logging is off, but the default place is still where a log would be
        path = logs.resolve_target(env_value="").path
        assert path is not None
        ui.say("Logging is turned off here (PEEK_A_FOXY_LOG=off); this is where the log would be.")
    files = logs.log_files(path)
    ui.say(f"Log file: {path}")

    if open_folder:
        if not path.parent.is_dir():
            ui.say("There is no log folder yet: it is created the first time you run a command.")
        elif not logs.open_folder(path.parent):
            ui.warn(f"could not open the folder; open it yourself: {path.parent}")
        return
    if clear:
        _clear(path, files, yes)
        return
    if not files:
        ui.say("No log yet. It is created the first time you run install or uninstall.")
        return
    ui.say(f"Size: {_size(files)} in {len(files)} file(s), at most 5 MB each.")
    lines = logs.last_run(path)
    if lines:
        ui.say("Last run:")
        shown = lines
        if len(lines) > MAX_SHOWN:
            hidden = len(lines) - MAX_SHOWN
            shown = [
                lines[0],
                f"... {hidden} lines not shown; open the file to read them ...",
                *lines[-(MAX_SHOWN - 1) :],
            ]
        for line in shown:
            ui.say(f"  {line}")
    ui.say("Nothing is ever sent anywhere. If you share the log, read it first.", style="dim")


def _clear(path: Path, files: list[Path], yes: bool) -> None:
    if not files:
        ui.say("Nothing to delete: there is no log yet.")
        return
    if not yes:
        _confirm(f"Delete {len(files)} log file(s) ({_size(files)})?", default=False)
    removed = logs.clear(path)
    ui.say(f"Deleted {removed} log file(s).")
