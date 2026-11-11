"""Building and running the list of changes that install or remove peek-a-foxy.

A *plan* is a list of steps that have not run yet. The CLI can show it (``--dry-run``), ask for
confirmation and then execute it, and the tests can run it against throwaway profiles.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import secrets
import shutil
import stat
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from peek_a_foxy import errors, fileio, loader, platform, userfiles
from peek_a_foxy.assets import FILES, assets_dir
from peek_a_foxy.errors import UserFileError
from peek_a_foxy.status import STATUS_FILE

T = TypeVar("T")
log = logging.getLogger(__name__)

LEGACY_FILES = (
    "tabs-autohide.css",
    "JS/tabs_autohide.uc.js",
)  # names before the project was renamed

EMPTIED_FOLDERS = ("JS", "resources")  # in chrome/: removed on uninstall, only if left empty


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
                log.info("step %d/%d: %s", number, len(self.steps), step.description)
                started = time.monotonic()
                try:
                    warning = step.run()
                except BaseException as error:
                    log.error(
                        "step %d/%d failed after %.2f s: %s: %s",
                        number,
                        len(self.steps),
                        time.monotonic() - started,
                        type(error).__name__,
                        error,
                    )
                    raise
                log.info(
                    "step %d/%d done in %.2f s", number, len(self.steps), time.monotonic() - started
                )
                self.completed.append(step)
                if warning:
                    log.warning("step %d/%d: %s", number, len(self.steps), warning)
                    warnings.append(warning)
        finally:
            self._cleanup.close()
        return warnings


UTF8_BOM = b"\xef\xbb\xbf"
BACKUP_SUFFIX = ".peek-a-foxy.bak"  # a copy of a user's file as it was before our first edit
TEMP_SUFFIX = ".peek-a-foxy.tmp"  # where an edit is written before it replaces the file
MAX_USER_FILE_BYTES = 64 * 1024 * 1024  # a userChrome.css or user.js is kilobytes; this is absurd
EDIT_ATTEMPTS = 3  # how often an edit starts over when the file changes while it is being edited


def backup_path(path: Path) -> Path:
    """Where the one-time copy of the user's ``path`` is kept: next to it."""
    return path.with_name(path.name + BACKUP_SUFFIX)


def _resolve(path: Path) -> Path:
    """The file that really holds ``path``'s bytes: the end of a chain of symbolic links.

    Replacing ``path`` itself would replace the link with a plain file (userChrome.css is often a
    link into a dotfiles folder), so an edit replaces the file the chain ends at, and the link
    stays. A dangling link resolves to the missing file it points at; a loop has no end.
    """
    real = Path(os.path.realpath(path))
    if real.is_symlink():  # realpath() gives up at a loop and returns the link it stopped at
        raise UserFileError(
            errors.FILE_IO,
            f"{path} is a chain of symbolic links that never ends",
            detail=f"stopped at {real}",
        )
    return real


def _read_raw(real: Path) -> bytes | None:
    """The bytes of a regular file, or ``None`` when there is no such file.

    Anything else behind the name (a folder, a named pipe, a device) is refused: an edit replaces
    the file by renaming a new one over it, which would silently swap that thing for a plain file.
    """
    log.debug("reading %s", real)
    try:
        # Windows refuses the file for a moment while another program (a second install, a virus
        # scanner) has it open or is renaming a new one over it.
        raw = platform.retry_if_denied(lambda: fileio.read_regular(real, MAX_USER_FILE_BYTES))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (fileio.NotARegularFileError, IsADirectoryError) as error:
        raise UserFileError(
            errors.FILE_IO,
            f"{real} is not a regular file ({error.strerror}), so it is not edited",
            hint="Peek-a-Foxy only edits ordinary files. Move that item aside, or point the name "
            "at a regular file, then run the command again.",
            detail=repr(error),
        ) from error
    if len(raw) > MAX_USER_FILE_BYTES:
        raise UserFileError(
            errors.FILE_IO,
            f"{real} is larger than {MAX_USER_FILE_BYTES // (1024 * 1024)} MiB, so it is not "
            "edited",
            hint="A Firefox settings file this large is almost certainly not what it should be: "
            "check it, move it aside if it is not needed, then run the command again.",
        )
    return raw


def _decode(path: Path, raw: bytes | None) -> tuple[str, bool]:
    if raw is None:
        return "", False
    try:
        return raw.decode("utf-8-sig"), raw.startswith(UTF8_BOM)
    except UnicodeDecodeError as error:
        raise UserFileError(
            errors.FILE_NOT_UTF8, f"{path} is not valid UTF-8", detail=repr(error)
        ) from error


def _read(path: Path) -> tuple[str, bool]:
    """Return the text of ``path`` (empty if missing) and whether it starts with a UTF-8 BOM."""
    return _decode(path, _read_raw(_resolve(path)))


def _new_file(directory: Path, name: str, data: bytes, template: os.stat_result | None) -> Path:
    """Write ``data`` to a new, uniquely named file in ``directory`` and return its path.

    The name cannot clash with another run (two installs at once) and is never an existing file or
    link (``O_EXCL``). With a ``template`` the file gets that file's permissions and, when we may,
    its owner: an edit by root must not turn a person's file into root's.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    temporary = directory / f"{name}.{os.getpid()}.{secrets.token_hex(4)}{TEMP_SUFFIX}"
    descriptor = os.open(temporary, flags, 0o666)  # the umask trims it for a new file
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())  # the data is on disk before the rename makes it the file
        if template is not None:
            os.chmod(temporary, stat.S_IMODE(template.st_mode))
            if hasattr(os, "chown"):
                with contextlib.suppress(OSError):  # only root may; anyone else keeps their own
                    os.chown(temporary, template.st_uid, template.st_gid)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    return temporary


def _keep_backup(path: Path, original: bytes, template: os.stat_result) -> None:
    """Keep a copy of the file as the user had it, once: never replaced, never for a new file.

    The copy appears whole or not at all (it is written aside and then linked into place), so a
    crash cannot leave a half copy that later runs would trust, and two runs cannot overwrite each
    other: the first one wins.
    """
    backup = backup_path(path)
    if os.path.lexists(backup):
        return
    temporary = _new_file(backup.parent, backup.name, original, template)
    try:
        try:
            os.link(temporary, backup)  # fails if it exists, even as a dangling link
        except FileExistsError:
            return
        except OSError:  # a file system without hard links
            if not os.path.lexists(backup):
                platform.retry_if_denied(lambda: os.replace(temporary, backup))
                return
        log.info("kept a copy of %s as %s", path, backup)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def _write(path: Path, real: Path, text: str, bom: bool, original: bytes | None) -> bool:
    """Replace ``real`` with ``text`` in one step; ``False`` if it changed since it was read.

    ``original`` is what was read (``None`` for a file that did not exist). The new content is
    written next to the file and renamed over it, so the file is always either all old or all new.
    """
    log.info("writing %s", path)
    if not path.is_symlink():
        path.parent.mkdir(parents=True, exist_ok=True)
    template: os.stat_result | None = None
    if original is not None:
        try:
            template = real.stat()
        except FileNotFoundError:  # removed while we were working: that is a change as well
            return False
        if not os.access(real, os.W_OK):  # a read-only file is the owner's way of saying "not me"
            raise PermissionError(errno.EACCES, "the file is read-only", str(real))
    data = (UTF8_BOM if bom else b"") + text.encode("utf-8")
    temporary = _new_file(real.parent, real.name, data, template)
    try:
        if _read_raw(real) != original:  # someone else wrote it while we were working
            return False
        if original is not None and template is not None:
            _keep_backup(path, original, template)
        # The same folder, so this is a rename and never a copy. Windows refuses it while another
        # program has the file open, which lasts a moment.
        platform.retry_if_denied(lambda: os.replace(temporary, real))
        return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)  # gone after a successful rename; otherwise remove the leftover


def _named_after(error: OSError, path: Path) -> OSError:
    """The same error, naming the file the person knows and not the temporary one beside it."""
    if not str(error.filename).endswith(TEMP_SUFFIX):
        return error
    return type(error)(error.errno, error.strerror, str(path))


def _edit(path: Path, transform: Callable[[str], str]) -> None:
    """Apply ``transform`` to a text file, creating it when missing and skipping no-op rewrites.

    The file is replaced atomically (through its symbolic link, if it is one) after a copy of the
    original was kept; if it changes while the edit is being prepared, the edit starts over from
    the new content, so another program's change is never overwritten.
    """
    for _ in range(EDIT_ATTEMPTS):
        real = _resolve(path)  # again each time: a link may have been moved while we worked
        raw = _read_raw(real)
        before, bom = _decode(path, raw)
        after = transform(before)
        if after == before and (raw is not None or real.exists()):
            return
        try:
            written = _write(path, real, after, bom, raw)
        except OSError as error:
            raise _named_after(error, path) from error
        if written:
            return
        log.warning("%s changed while it was being edited; starting again", path)
    raise UserFileError(
        errors.FILE_IO,
        f"{path} keeps changing while it is being edited, so it was left as it is",
        hint="Close the program that keeps saving that file (an editor, a sync tool) and run "
        "the command again: it is safe to repeat.",
    )


def _remove(path: Path) -> None:
    log.debug("removing %s if present", path)
    path.unlink(missing_ok=True)


def _is_link(path: Path) -> bool:
    """A symbolic link or, on Windows, any reparse point (a junction counts; Python < 3.12 cannot
    tell), looked at without following it."""
    if path.is_symlink():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _remove_if_empty(folder: Path) -> None:
    """Remove ``folder`` when nothing is in it; in every other case leave it, quietly.

    One ``rmdir`` does the whole job: the system itself refuses a folder that holds anything, so
    a file somebody adds between a check and the removal is never lost, and nothing is deleted
    recursively. A link (or, on Windows, a junction) is not ours and is never removed or followed.
    Whatever stops the removal (a folder with files, a missing one, no permission, a program that
    has it open) only leaves an empty folder behind, which is not worth failing an uninstall for.
    """
    log.debug("removing %s if it is empty", folder)
    if _is_link(folder):
        log.info("%s is a link, not a folder of ours, so it was kept", folder)
        return
    try:
        os.rmdir(folder)
    except OSError as error:  # missing, not empty, not a folder, no permission, in use
        log.info("%s was kept: %s", folder, error.strerror or type(error).__name__)


def _remove_leftover(path: Path) -> str | None:
    """Remove a file that only holds diagnostics; if that is not possible, a warning, not a failure.

    A link is removed itself and never followed. A folder is not ours to delete.
    """
    log.debug("removing %s if present", path)
    try:
        if path.is_dir() and not path.is_symlink():
            return f"{path} is a folder, not the status file that Firefox writes, so it was kept."
        path.unlink(missing_ok=True)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        return (
            f"{path} could not be removed ({reason}); it only holds diagnostic data, so it can be "
            "deleted by hand."
        )
    return None


def plan_install(
    profile: Path, firefox_dir: Path | None, *, allow_unverified: bool = False
) -> Plan:
    """Changes needed to install into ``profile``; ``firefox_dir=None`` skips the loader.

    ``allow_unverified`` lets sudo copy a loader that is not the pinned one (``FXAC_REPO``).
    """
    chrome = profile / "chrome"
    source = assets_dir()
    plan = Plan()

    # Fail before anything changes: unreadable user files, then (first step) the network fetch.
    _read(chrome / "userChrome.css")
    _read(profile / "user.js")
    checkout: list[Path] = []
    if firefox_dir is not None:
        commit = loader.pinned_commit()  # refuses anything but a full hash, before any change
        label = (
            f"Fetch fx-autoconfig ({commit[:10]}, with git)"
            if loader.overridden()
            else f"Check the fx-autoconfig files that come with Peek-a-Foxy ({commit[:10]})"
        )
        plan.add(label, lambda: checkout.append(plan.enter(loader.loader_files())))

    def copy_files() -> None:
        for name in FILES:
            shutil.copyfile(source / name, _ensure(chrome / name))
        for legacy in LEGACY_FILES:
            _remove(chrome / legacy)

    plan.add(f"Copy {_names(FILES)} into {chrome}", copy_files)
    css = chrome / "userChrome.css"
    plan.add(
        f"Add the @import line to {css} ({_backup_note(css, installing=True)})",
        lambda: _edit(css, userfiles.with_css_import),
    )

    def set_prefs(text: str) -> str:
        # The only prefs Firefox itself needs from user.js. The autohide prefs are deliberately NOT
        # written here: user.js is re-applied on every start, which would undo changes made in
        # about:config.
        # The script registers them itself, both off, on Firefox's default branch, so a pref that
        # nobody has set just has that default.
        text = userfiles.set_pref(text, userfiles.STYLESHEETS_PREF, True)
        text = userfiles.set_pref(text, userfiles.SUBDOCUMENTS_PREF, True)
        # Old pref names: keep a deliberate "on" under the new name, drop the old lines. An old
        # "false" was only the default this tool used to write, so it is not carried over.
        for old, new in userfiles.LEGACY_PREFS.items():
            if userfiles.get_bool_pref(text, old) is True:
                text = userfiles.set_pref(text, new, True, keep_existing=True)
            text = userfiles.remove_pref(text, old)
        return text

    user_js = profile / "user.js"
    plan.add(
        f"Enable userChrome.css loading and the settings page in {user_js} "
        f"({_backup_note(user_js, installing=True)})",
        lambda: _edit(user_js, set_prefs),
    )

    if firefox_dir is not None:
        _add_loader_steps(plan, checkout, chrome, firefox_dir, allow_unverified)
    return plan


def _backup_note(path: Path, *, installing: bool) -> str:
    """Said in the step: the user's file is copied once before it is edited, and the copy stays."""
    name = backup_path(path).name
    if installing:
        return f"an existing file is first copied to {name}, once"
    return f"if there is no {name} yet, the file is first copied to it; an existing copy is kept"


def _names(files: tuple[str, ...]) -> str:
    """File names for a step description: ``a, b and c``."""
    names = [Path(name).name for name in files]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _add_loader_steps(
    plan: Plan, checkout: list[Path], chrome: Path, firefox_dir: Path, allow_unverified: bool
) -> None:
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
        loader.install_loader(checkout[0], firefox_dir, allow_unverified=allow_unverified)
        return None

    plan.add(f"Copy fx-autoconfig's utils into {chrome / 'utils'}", install_utils)
    plan.add(f"Install the loader into {firefox_dir} ({loader.privilege_hint()})", install_loader)


def plan_uninstall(profile: Path) -> Plan:
    """Changes needed to remove this project from ``profile``."""
    chrome = profile / "chrome"
    plan = Plan()
    _read(chrome / "userChrome.css")
    _read(profile / "user.js")

    def remove_files() -> None:
        for name in (*FILES, *LEGACY_FILES):
            _remove(chrome / name)
        for folder in EMPTIED_FOLDERS:  # the files above were all that peek-a-foxy put in them
            _remove_if_empty(chrome / folder)

    plan.add(
        f"Remove {_names(FILES)} from {chrome}, then the {' and '.join(EMPTIED_FOLDERS)} "
        "folders there if nothing else is in them",
        remove_files,
    )

    def remove_status() -> str | None:
        problems = [
            problem
            for name in (STATUS_FILE, f"{STATUS_FILE}.tmp")
            if (problem := _remove_leftover(chrome / name))
        ]
        return " ".join(problems) or None

    plan.add(
        f"Remove {STATUS_FILE}, the status file that Firefox writes, and its .tmp leftover "
        f"from {chrome}",
        remove_status,
    )
    css = chrome / "userChrome.css"
    plan.add(
        f"Remove the @import line from {css} ({_backup_note(css, installing=False)})",
        lambda: _edit_if_exists(css, userfiles.without_css_import),
    )

    def drop_prefs(text: str) -> str:
        for name in (*userfiles.OWN_PREFS, *userfiles.LEGACY_PREFS):
            text = userfiles.remove_pref(text, name)
        return text

    user_js = profile / "user.js"
    plan.add(
        f"Remove the autohide prefs from {user_js} ({_backup_note(user_js, installing=False)})",
        lambda: _edit_if_exists(user_js, drop_prefs),
    )
    return plan


def _edit_if_exists(path: Path, transform: Callable[[str], str]) -> None:
    if path.is_file():
        _edit(path, transform)
