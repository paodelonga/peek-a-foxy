"""Command line interface: ``peek-a-foxy install`` / ``uninstall``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.panel import Panel
from rich.text import Text

from peek_a_foxy import __version__, platform, ui
from peek_a_foxy.installer import (
    Plan,
    Step,
    UserFileError,
    plan_install,
    plan_uninstall,
)
from peek_a_foxy.loader import LoaderError
from peek_a_foxy.profiles import NoProfilesError, Profile, default_profile, read_profiles

# Shown to the user as the way to toggle each bar; they must match the script's TARGETS.
TABS_SHORTCUT = "Ctrl+Alt+T"
URLBAR_SHORTCUT = "Ctrl+Alt+U"

app = typer.Typer(
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
        "--yes",
        "-y",
        help="Don't ask anything: apply without confirming, and don't prompt for the profile or "
        "the Firefox installation (an unclear choice is an error instead).",
    ),
]


def _version(value: bool) -> None:
    if value:
        ui.console.print(f"peek-a-foxy {__version__}")
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


def _interactive(yes: bool) -> bool:
    return not yes and sys.stdin.isatty() and sys.stdout.isatty()


def _choose_profile(profile: Path | None, yes: bool) -> Path:
    if profile is not None:
        return profile
    try:
        profiles = read_profiles(platform.profiles_root())
    except (NoProfilesError, platform.UnsupportedPlatformError) as error:
        ui.fail(str(error))

    if len(profiles) == 1:
        return profiles[0].path
    preferred = default_profile(profiles)
    if _interactive(yes):
        return _prompt_profile(profiles, preferred)
    if preferred is None:
        # Several installations (release, developer edition...) each have their own default.
        ui.fail("cannot tell which profile to use; pass --profile (or run without --yes to choose)")
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
        ui.fail(f"choose a number between 1 and {len(profiles)}")
    return profiles[choice - 1].path


def _resolve_firefox_dir(firefox_dir: Path | None, skip_loader: bool, yes: bool) -> Path | None:
    if skip_loader:
        return None
    if firefox_dir is None:
        firefox_dir = _choose_firefox_dir(yes)
    kind = platform.sandbox_kind(firefox_dir)
    if kind:
        ui.fail(f"{kind} builds of Firefox are read-only and not supported ({firefox_dir})")
    return firefox_dir


def _choose_firefox_dir(yes: bool) -> Path:
    try:
        candidates = platform.firefox_dir_candidates()
    except platform.UnsupportedPlatformError as error:
        ui.fail(str(error))
    if not candidates:
        ui.fail("could not find the Firefox install directory; pass --firefox-dir")
    if len(candidates) == 1:
        return candidates[0]
    if not _interactive(yes):
        found = ", ".join(str(path) for path in candidates)
        ui.fail(f"several Firefox installations found ({found}); pass --firefox-dir")

    table = ui.new_table("Firefox installations")
    table.add_column("#", justify="right")
    table.add_column("Path", overflow="fold")
    for number, candidate in enumerate(candidates, start=1):
        ui.row(table, str(number), str(candidate))
    ui.show(table)
    choice: int = typer.prompt("Install the loader into number", type=int)
    if not 1 <= choice <= len(candidates):
        ui.fail(f"choose a number between 1 and {len(candidates)}")
    return candidates[choice - 1]


def _build(make_plan: Callable[[], Plan]) -> Plan:
    """Build a plan, turning unreadable user files into a clean error instead of a traceback."""
    try:
        return make_plan()
    except (UserFileError, LoaderError, OSError) as error:
        ui.fail(str(error))


def _show_plan(plan: Plan, title: str) -> None:
    table = ui.new_table(title, header=False)
    table.add_column(justify="right", style="dim")
    table.add_column(overflow="fold")
    for number, step in enumerate(plan.steps, start=1):
        ui.row(table, str(number), step.description)
    ui.show(table)


def _confirm() -> None:
    """Ask before changing anything; with nobody to ask (no terminal) refuse instead of assuming."""
    if not _interactive(False):
        ui.fail("no terminal to ask for confirmation; pass --yes to apply the changes anyway")
    if not typer.confirm("Apply these changes?", default=True):
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
    except (LoaderError, UserFileError, OSError) as error:
        _fail_partway(plan, error)


def _fail_partway(plan: Plan, error: Exception) -> NoReturn:
    """Report a failed step together with what the earlier steps already changed."""
    finished = len(plan.completed)
    if finished:
        done = "; ".join(step.description for step in plan.completed)
        progress = f"{finished} of {len(plan.steps)} steps finished: {done}."
    else:
        progress = "No step had finished."
    ui.errors.print(Text.assemble(("error: ", "bold red"), str(error)), soft_wrap=True)
    ui.say(
        f"{progress} The failed step may have changed part of its files. "
        "Running the same command again is safe: every step can be repeated."
    )
    raise typer.Exit(1)


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
        "[bold magenta]PEEK-A-BOO![/] \U0001f98a  https://youtu.be/6uJf2IT2Zh8?t=59"
    )


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
        ui.warn(warning)
    title, body = done_summary(skip_loader, plan.loader_conflict)
    color = "green" if title == "Done" else "yellow"
    ui.show(Panel(body, title=f"[{color}]{title}[/]", title_align="left"))


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
    ui.console.print(
        "[green]Done.[/] Left in place: chrome/utils and the loader in the Firefox install "
        "directory, since other scripts may use them."
    )
