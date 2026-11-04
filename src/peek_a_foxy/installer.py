"""Building and running the list of changes that install or remove peek-a-foxy.

A *plan* is a list of steps that have not run yet. The CLI can show it (``--dry-run``), ask for
confirmation and then execute it, and the tests can run it against throwaway profiles.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from peek_a_foxy import loader, userfiles
from peek_a_foxy.assets import CSS_NAME, SCRIPT_NAME, assets_dir

T = TypeVar("T")

LEGACY_FILES = (
    "tabs-autohide.css",
    "JS/tabs_autohide.uc.js",
)  # names before the project was renamed


@dataclass
class Step:
    description: str
    run: Callable[[], str | None]  # may return a warning to show to the user


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    completed: list[Step] = field(default_factory=list)  # the steps that ran to the end
    loader_conflict: bool = False  # another loader was found in Firefox's directory and kept
    _cleanup: ExitStack = field(default_factory=ExitStack, repr=False)

    def add(self, description: str, run: Callable[[], str | None]) -> None:
        self.steps.append(Step(description, run))

    def enter(self, context: AbstractContextManager[T]) -> T:
        """Keep ``context`` open until the plan has finished (e.g. a temporary checkout)."""
        return self._cleanup.enter_context(context)

    def execute(self, on_step: Callable[[int, int, Step], None] | None = None) -> list[str]:
        """Run the steps in order and return the warnings they produced.

        ``on_step(number, total, step)`` is called just before each step runs.
        """
        warnings: list[str] = []
        try:
            for number, step in enumerate(self.steps, start=1):
                if on_step:
                    on_step(number, len(self.steps), step)
                warning = step.run()
                self.completed.append(step)
                if warning:
                    warnings.append(warning)
        finally:
            self._cleanup.close()
        return warnings


UTF8_BOM = b"\xef\xbb\xbf"


class UserFileError(RuntimeError):
    """One of the user's own files can't be edited safely."""


def _read(path: Path) -> tuple[str, bool]:
    """Return the text of ``path`` (empty if missing) and whether it starts with a UTF-8 BOM."""
    if not path.is_file():
        return "", False
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig"), raw.startswith(UTF8_BOM)
    except UnicodeDecodeError as error:
        raise UserFileError(
            f"{path} is not valid UTF-8, so it can't be edited safely; fix or remove it and retry"
        ) from error


def _write(path: Path, text: str, bom: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes() writes through a symlink instead of replacing it (userChrome.css is often one).
    path.write_bytes((UTF8_BOM if bom else b"") + text.encode("utf-8"))


def _edit(path: Path, transform: Callable[[str], str]) -> None:
    """Apply ``transform`` to a text file, creating it when missing and skipping no-op rewrites."""
    before, bom = _read(path)
    after = transform(before)
    if after != before or not path.exists():
        _write(path, after, bom)


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


def plan_install(profile: Path, firefox_dir: Path | None) -> Plan:
    """Changes needed to install into ``profile``; ``firefox_dir=None`` skips the loader."""
    chrome = profile / "chrome"
    source = assets_dir()
    plan = Plan()

    # Fail before anything changes: unreadable user files, then (first step) the network fetch.
    _read(chrome / "userChrome.css")
    _read(profile / "user.js")
    checkout: list[Path] = []
    if firefox_dir is not None:
        commit = loader.pinned_commit()  # refuses anything but a full hash, before any change
        plan.add(
            f"Fetch fx-autoconfig ({commit[:10]}, verified)",
            lambda: checkout.append(plan.enter(loader.fetch_loader())),
        )

    def copy_files() -> None:
        shutil.copyfile(source / CSS_NAME, _ensure(chrome / CSS_NAME))
        shutil.copyfile(source / "JS" / SCRIPT_NAME, _ensure(chrome / "JS" / SCRIPT_NAME))
        for legacy in LEGACY_FILES:
            _remove(chrome / legacy)

    plan.add(f"Copy {CSS_NAME} and {SCRIPT_NAME} into {chrome}", copy_files)
    plan.add(
        f"Add the @import line to {chrome / 'userChrome.css'}",
        lambda: _edit(chrome / "userChrome.css", userfiles.with_css_import),
    )

    def set_prefs(text: str) -> str:
        # The only pref Firefox needs from user.js. The autohide prefs are deliberately NOT written
        # here: user.js is re-applied on every start, which would undo changes made in about:config.
        # The script registers them itself, both off, on Firefox's default branch, so a pref that
        # nobody has set just has that default.
        text = userfiles.set_pref(text, userfiles.STYLESHEETS_PREF, True)
        # Old pref names: keep a deliberate "on" under the new name, drop the old lines. An old
        # "false" was only the default this tool used to write, so it is not carried over.
        for old, new in userfiles.LEGACY_PREFS.items():
            if userfiles.get_bool_pref(text, old) is True:
                text = userfiles.set_pref(text, new, True, keep_existing=True)
            text = userfiles.remove_pref(text, old)
        return text

    plan.add(
        f"Enable userChrome.css loading in {profile / 'user.js'}",
        lambda: _edit(profile / "user.js", set_prefs),
    )

    if firefox_dir is not None:
        _add_loader_steps(plan, checkout, chrome, firefox_dir)
    return plan


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _add_loader_steps(plan: Plan, checkout: list[Path], chrome: Path, firefox_dir: Path) -> None:
    def install_utils() -> None:
        loader.install_utils(checkout[0], chrome)

    def install_loader() -> str | None:
        existing = loader.conflicts(checkout[0], firefox_dir)
        if existing:
            plan.loader_conflict = True
            names = ", ".join(str(path) for path in existing)
            return (
                f"{names} already exists and differs from the one this tool provides; "
                "not overwriting another autoconfig setup "
                "(update it by hand if it is an older fx-autoconfig)"
            )
        loader.install_loader(checkout[0], firefox_dir)
        return None

    plan.add(f"Copy fx-autoconfig's utils into {chrome / 'utils'}", install_utils)
    plan.add(f"Install the loader into {firefox_dir} (uses sudo if needed)", install_loader)


def plan_uninstall(profile: Path) -> Plan:
    """Changes needed to remove this project from ``profile``."""
    chrome = profile / "chrome"
    plan = Plan()
    _read(chrome / "userChrome.css")
    _read(profile / "user.js")

    def remove_files() -> None:
        for name in (CSS_NAME, f"JS/{SCRIPT_NAME}", *LEGACY_FILES):
            _remove(chrome / name)

    plan.add(f"Remove {CSS_NAME} and {SCRIPT_NAME} from {chrome}", remove_files)
    plan.add(
        f"Remove the @import line from {chrome / 'userChrome.css'}",
        lambda: _edit_if_exists(chrome / "userChrome.css", userfiles.without_css_import),
    )

    def drop_prefs(text: str) -> str:
        for name in (*userfiles.OWN_PREFS, *userfiles.LEGACY_PREFS):
            text = userfiles.remove_pref(text, name)
        return text

    plan.add(
        f"Remove the autohide prefs from {profile / 'user.js'}",
        lambda: _edit_if_exists(profile / "user.js", drop_prefs),
    )
    return plan


def _edit_if_exists(path: Path, transform: Callable[[str], str]) -> None:
    if path.is_file():
        _edit(path, transform)
