"""Command line interface: ``peek-a-foxy install`` / ``uninstall``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from peek_a_foxy import __version__, platform
from peek_a_foxy.installer import (
    Plan,
    Step,
    UserFileError,
    plan_install,
    plan_uninstall,
)
from peek_a_foxy.loader import LoaderError
from peek_a_foxy.profiles import NoProfilesError, Profile, default_profile, read_profiles

app = typer.Typer(
    help="Peek-a-boo for Foxys: autohide the tab bar and navigation bar per window.",
    no_args_is_help=True,
    add_completion=True,  # adds --install-completion / --show-completion for bash, zsh, fish
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
errors = Console(stderr=True)


def _complete_profile(incomplete: str) -> list[tuple[str, str]]:
    """Shell completion for --profile: the profiles listed in profiles.ini."""
    try:
        profiles = read_profiles(platform.profiles_root())
    except (NoProfilesError, platform.UnsupportedPlatformError):
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
    except platform.UnsupportedPlatformError:
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
        "--yes", "-y", help="Don't ask for confirmation or choose a profile interactively."
    ),
]


def _version(value: bool) -> None:
    if value:
        console.print(f"peek-a-foxy {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Peek-a-boo for Foxys: autohide the tab bar and navigation bar per window."""


def _fail(message: str) -> NoReturn:
    errors.print(f"[bold red]error:[/] {message}")
    raise typer.Exit(1)


def _interactive(yes: bool) -> bool:
    return not yes and sys.stdin.isatty() and sys.stdout.isatty()


def _choose_profile(profile: Path | None, yes: bool) -> Path:
    if profile is not None:
        return profile
    try:
        profiles = read_profiles(platform.profiles_root())
    except (NoProfilesError, platform.UnsupportedPlatformError) as error:
        _fail(str(error))

    if len(profiles) == 1:
        return profiles[0].path
    preferred = default_profile(profiles)
    if _interactive(yes):
        return _prompt_profile(profiles, preferred)
    if preferred is None:
        # Several installations (release, developer edition...) each have their own default.
        _fail("cannot tell which profile to use; pass --profile (or run without --yes to choose)")
    return preferred.path


def _prompt_profile(profiles: list[Profile], preferred: Profile | None) -> Path:
    table = Table(title="Firefox profiles", title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Path", overflow="fold")
    table.add_column("Default for an install")
    for number, entry in enumerate(profiles, start=1):
        table.add_row(str(number), entry.name, str(entry.path), "yes" if entry.is_default else "")
    console.print(table)
    default_number = profiles.index(preferred) + 1 if preferred else None
    choice = typer.prompt("Install into profile number", default=default_number, type=int)
    if not 1 <= choice <= len(profiles):
        _fail(f"choose a number between 1 and {len(profiles)}")
    return profiles[choice - 1].path


def _resolve_firefox_dir(firefox_dir: Path | None, skip_loader: bool, yes: bool) -> Path | None:
    if skip_loader:
        return None
    if firefox_dir is None:
        firefox_dir = _choose_firefox_dir(yes)
    if platform.is_sandboxed(firefox_dir):
        _fail(f"Snap and Flatpak builds of Firefox are read-only and not supported ({firefox_dir})")
    return firefox_dir


def _choose_firefox_dir(yes: bool) -> Path:
    try:
        candidates = platform.firefox_dir_candidates()
    except platform.UnsupportedPlatformError as error:
        _fail(str(error))
    if not candidates:
        _fail("could not find the Firefox install directory; pass --firefox-dir")
    if len(candidates) == 1:
        return candidates[0]
    if not _interactive(yes):
        found = ", ".join(str(path) for path in candidates)
        _fail(f"several Firefox installations found ({found}); pass --firefox-dir")

    table = Table(title="Firefox installations", title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("Path", overflow="fold")
    for number, candidate in enumerate(candidates, start=1):
        table.add_row(str(number), str(candidate))
    console.print(table)
    choice = typer.prompt("Install the loader into number", type=int)
    if not 1 <= choice <= len(candidates):
        _fail(f"choose a number between 1 and {len(candidates)}")
    return candidates[choice - 1]


def _build(make_plan: Callable[[], Plan]) -> Plan:
    """Build a plan, turning unreadable user files into a clean error instead of a traceback."""
    try:
        return make_plan()
    except (UserFileError, OSError) as error:
        _fail(str(error))


def _show_plan(plan: Plan, title: str) -> None:
    table = Table(title=title, title_justify="left", show_header=False)
    table.add_column(justify="right", style="dim")
    table.add_column(overflow="fold")
    for number, step in enumerate(plan.steps, start=1):
        table.add_row(str(number), step.description)
    console.print(table)


def _apply(plan: Plan, title: str, dry_run: bool, yes: bool) -> list[str]:
    """Show the plan, ask for confirmation when interactive, then run it."""
    _show_plan(plan, title)
    if dry_run:
        console.print("[dim]Dry run: nothing was changed.[/]")
        raise typer.Exit()
    if _interactive(yes) and not typer.confirm("Apply these changes?", default=True):
        raise typer.Exit(1)

    def announce(number: int, total: int, step: Step) -> None:
        console.print(f"[cyan]({number}/{total})[/] {step.description}")

    try:
        return plan.execute(announce)
    except (LoaderError, UserFileError, OSError) as error:
        _fail(str(error))


@app.command()
def install(
    profile: ProfileOption = None,
    firefox_dir: FirefoxDirOption = None,
    skip_loader: SkipLoaderOption = False,
    dry_run: DryRunOption = False,
    yes: YesOption = False,
) -> None:
    """Install the autohide stylesheet and script, and the fx-autoconfig loader they need."""
    profile_path = _choose_profile(profile, yes)
    loader_dir = _resolve_firefox_dir(firefox_dir, skip_loader, yes)
    plan = _build(lambda: plan_install(profile_path, loader_dir))
    warnings = _apply(plan, f"Install into {profile_path}", dry_run, yes)

    for warning in warnings:
        console.print(f"[yellow]warning:[/] {warning}")
    console.print(
        Panel(
            "Close [bold]all[/] Firefox windows and start it again.\n\n"
            "Both autohides start [bold]off[/]. Turn them on with [bold]Ctrl+Alt+T[/] (tabs) and "
            "[bold]Ctrl+Alt+U[/] (urlbar), or add the buttons from Customize Toolbar.\n\n"
            "No button or shortcut? Clear the startup cache in [bold]about:support[/]. "
            "A Firefox update can remove the loader: run [bold]peek-a-foxy install[/] again.\n\n"
            "[bold magenta]PEEK-A-BOO![/] \U0001f98a  https://youtu.be/6uJf2IT2Zh8?t=59",
            title="[green]Done[/]",
            title_align="left",
        )
    )


@app.command()
def uninstall(
    profile: ProfileOption = None,
    dry_run: DryRunOption = False,
    yes: YesOption = False,
) -> None:
    """Remove this project's files and prefs from a profile (the loader is left in place)."""
    profile_path = _choose_profile(profile, yes)
    plan = _build(lambda: plan_uninstall(profile_path))
    _apply(plan, f"Uninstall from {profile_path}", dry_run, yes)
    console.print(
        "[green]Done.[/] Left in place: chrome/utils and the loader in the Firefox install "
        "directory, since other scripts may use them."
    )
