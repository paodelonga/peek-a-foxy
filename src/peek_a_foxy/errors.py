"""The errors this program expects, each with a stable code, a message and a "what to do" hint.

A code is ``PAF-<area><nn>``: ``1`` profiles and Firefox discovery, ``2`` the loader (git, network),
``3`` elevation and permissions, ``4`` the user's files, ``5`` platform and environment, ``6``
what ``peek-a-foxy doctor`` reports about an installation, ``9`` unexpected. Codes never change
meaning and are never reused, so people can search for them.

Every code is registered here and only here (:data:`CODES`); a test fails if one is duplicated or
used without being registered. The wording of ``meaning`` and ``hint`` is written for someone who
has never opened a terminal; technical detail goes in ``detail`` and is shown with ``--verbose``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ISSUES_URL = "https://github.com/paodelonga/peek-a-foxy/issues"

# Exit codes of the command line program.
EXIT_OK = 0
EXIT_FAILURE = 1  # an expected failure (a PeekError), or the user said no
EXIT_USAGE = 2  # wrong arguments (Click's own code)
EXIT_UNEXPECTED = 70  # a bug: EX_SOFTWARE of sysexits.h

CODE_PATTERN = re.compile(r"PAF-([1-9])(\d\d)")


@dataclass(frozen=True)
class ErrorCode:
    code: str  # "PAF-301"
    slug: str  # internal, for grep: "uac-cancelled"
    meaning: str  # what it means, one sentence (the README table)
    hint: str  # what to do next, written for a lay user

    @property
    def area(self) -> int:
        return int(self.code[4])


CODES: dict[str, ErrorCode] = {}


def _register(code: str, slug: str, meaning: str, hint: str) -> ErrorCode:
    if not CODE_PATTERN.fullmatch(code):
        raise ValueError(f"{code!r} is not a PAF-<area><nn> code")
    if code in CODES or any(entry.slug == slug for entry in CODES.values()):
        raise ValueError(f"error code {code} or slug {slug!r} is registered twice")
    entry = ErrorCode(code, slug, meaning, hint)
    CODES[code] = entry
    return entry


# --- 1xx: profiles and Firefox discovery --------------------------------------------------------

NO_PROFILES_INI = _register(
    "PAF-101",
    "no-profiles-ini",
    "Firefox's list of profiles (profiles.ini) was not found.",
    "Start Firefox once so it creates a profile, then run the command again. "
    "Or give the profile folder yourself with --profile.",
)
PROFILES_UNREADABLE = _register(
    "PAF-102",
    "profiles-unreadable",
    "Firefox's list of profiles (profiles.ini) could not be read.",
    "Give the profile folder yourself with --profile.",
)
NO_PROFILE_LISTED = _register(
    "PAF-103",
    "no-profile-listed",
    "Firefox's list of profiles has no profile in it.",
    "Start Firefox once so it creates a profile, then run the command again. "
    "Or give the profile folder yourself with --profile.",
)
AMBIGUOUS_PROFILE = _register(
    "PAF-104",
    "ambiguous-profile",
    "There is more than one default profile, so the right one is unclear.",
    "Run the command without --yes to pick one from a list, or give the folder with --profile.",
)
FIREFOX_NOT_FOUND = _register(
    "PAF-105",
    "firefox-not-found",
    "The Firefox install folder was not found.",
    "Give the folder that contains omni.ja with --firefox-dir. "
    "If fx-autoconfig is already set up in your Firefox, use --skip-loader instead.",
)
SEVERAL_FIREFOXES = _register(
    "PAF-106",
    "several-firefoxes",
    "More than one Firefox install was found and the choice cannot be asked.",
    "Give the one you want with --firefox-dir, or run the command without --yes to pick one.",
)
FIREFOX_SANDBOXED = _register(
    "PAF-107",
    "firefox-sandboxed",
    "This Firefox is a Snap, Flatpak or Microsoft Store build, which cannot be changed.",
    "Install Firefox from mozilla.org or from your system's regular package instead. "
    "If fx-autoconfig is already set up in it, use --skip-loader.",
)
INVALID_CHOICE = _register(
    "PAF-108",
    "invalid-choice",
    "The number typed is not one of the numbers in the list.",
    "Run the command again and type one of the numbers shown.",
)
NOT_A_FIREFOX_FOLDER = _register(
    "PAF-109",
    "not-a-firefox-folder",
    "The folder given with --firefox-dir does not look like the install folder of Firefox.",
    "Give the folder that contains omni.ja, for example /usr/lib/firefox on Linux or "
    "/Applications/Firefox.app/Contents/Resources on macOS. "
    "If fx-autoconfig is already set up in your Firefox, use --skip-loader instead.",
)

# --- 2xx: the loader (git, network) -------------------------------------------------------------

GIT_MISSING = _register(
    "PAF-201",
    "git-missing",
    "git is not installed, and it is needed to download the loader.",
    "Install git and run the command again. If fx-autoconfig is already set up in your Firefox, "
    "use --skip-loader.",
)
GIT_FAILED = _register(
    "PAF-202",
    "git-failed",
    "git could not download the loader.",
    "Check your internet connection (and any proxy or firewall) and run the command again. "
    "Running it with --verbose shows git's own output.",
)
BAD_PINNED_COMMIT = _register(
    "PAF-203",
    "bad-pinned-commit",
    "The FXAC_COMMIT environment variable is not a full commit hash.",
    "Remove FXAC_COMMIT, or set it to a full 40-digit commit hash.",
)
CHECKOUT_MISMATCH = _register(
    "PAF-204",
    "checkout-mismatch",
    "The downloaded loader is not the version this program expects.",
    "Run the command again. If it keeps happening, please report it: it should not happen.",
)
SUDO_FAILED = _register(
    "PAF-205",
    "sudo-failed",
    "sudo could not copy the loader into the Firefox folder.",
    "Run the command in a terminal where sudo can ask for your password, "
    "or make the Firefox folder writable for your user.",
)
ADMIN_CANNOT_WRITE = _register(
    "PAF-206",
    "admin-cannot-write",
    "The Firefox folder cannot be written, even as administrator.",
    "Check that Firefox is not a Microsoft Store build and that no antivirus is blocking "
    "writes to the Firefox folder, then run the command again.",
)
LOADER_UNVERIFIED = _register(
    "PAF-207",
    "loader-unverified",
    "The loader to copy as administrator is not the pinned one, so it was not copied.",
    "Remove FXAC_REPO and FXAC_COMMIT from the environment and run the command again. "
    "Only if you wrote that loader yourself or trust its source, add "
    "--allow-unverified-loader to copy it without checking it.",
)

# --- 3xx: elevation and permissions -------------------------------------------------------------

UAC_CANCELLED = _register(
    "PAF-301",
    "uac-cancelled",
    "The administrator prompt was cancelled.",
    "Run the command again and answer Yes to the prompt. It is only used to copy two small "
    "files into the Firefox folder.",
)
UAC_TIMEOUT = _register(
    "PAF-302",
    "uac-timeout",
    "The administrator prompt was not answered in time.",
    "Run the command again and answer the prompt within three minutes.",
)
UAC_UNAVAILABLE = _register(
    "PAF-303",
    "uac-unavailable",
    "Windows would not show the administrator prompt.",
    "Run the command from a normal terminal in your own desktop session, "
    "or open the terminal as administrator and run it again.",
)
UAC_HELPER_FAILED = _register(
    "PAF-304",
    "uac-helper-failed",
    "The administrator step started but could not finish.",
    "Run the command again. If it keeps happening, run it with --verbose and report the details.",
)
UAC_ENV_OVERRIDE = _register(
    "PAF-305",
    "uac-env-override",
    "FXAC_REPO or FXAC_COMMIT is set, and the administrator copy refuses a loader that is not "
    "the pinned one.",
    "Remove FXAC_REPO and FXAC_COMMIT from the environment and run the command again.",
)

COMMAND_TOO_LONG = _register(
    "PAF-306",
    "uac-command-too-long",
    "The command for the administrator step is longer than Windows allows, so it was not started.",
    "This should not happen with the files that Peek-a-Foxy installs. Please report it at "
    f"{ISSUES_URL} with the result of `peek-a-foxy doctor --copy`.",
)

# --- 4xx: the user's files ----------------------------------------------------------------------

FILE_NOT_UTF8 = _register(
    "PAF-401",
    "file-not-utf8",
    "One of your Firefox files is not valid UTF-8 text, so it cannot be edited safely.",
    "Open the file in a text editor and save it as UTF-8, or move it aside, "
    "then run the command again.",
)
FILE_IO = _register(
    "PAF-402",
    "file-io",
    "A file or folder could not be read or changed.",
    "Check that it exists, that you may change it, and that no other program (an editor, an "
    "antivirus) has it open. Then run the command again: it is safe to repeat.",
)
FILE_EXISTS = _register(
    "PAF-403",
    "file-exists",
    "A file with that name already exists, so nothing was saved.",
    "Choose another name with --save PATH, or move the old file away first.",
)
UTILS_IS_A_LINK = _register(
    "PAF-404",
    "utils-is-a-link",
    "The chrome/utils folder in your profile is a link, so nothing was copied into it.",
    "Replace the link with a real folder, or remove it, then run `peek-a-foxy install` again. "
    "Peek-a-Foxy never writes through a link, because the files would end up somewhere else.",
)

# --- 5xx: platform and environment --------------------------------------------------------------

UNSUPPORTED_OS = _register(
    "PAF-501",
    "unsupported-os",
    "This operating system is not supported.",
    "Peek-a-Foxy works on Linux, macOS and Windows. On another system, --profile with "
    "--skip-loader skips the automatic search.",
)
NO_TERMINAL = _register(
    "PAF-502",
    "no-terminal",
    "There is no terminal to ask for confirmation.",
    "Add --yes to apply the changes without asking.",
)
FILES_MISSING = _register(
    "PAF-503",
    "files-missing",
    "The Peek-a-Foxy files to install were not found next to the program.",
    "Reinstall Peek-a-Foxy (for example: pipx reinstall peek-a-foxy) and run the command again.",
)

# --- 6xx: what `peek-a-foxy doctor` reports (findings, not failures of the command) ------------

LOADER_MISSING = _register(
    "PAF-601",
    "loader-missing",
    "This Firefox does not have the loader (fx-autoconfig), so it cannot run the "
    "Peek-a-Foxy script.",
    "Run `peek-a-foxy install` and allow the request for administrator rights; it only "
    "copies two small files into the Firefox folder.",
)
LOADER_DIFFERENT = _register(
    "PAF-602",
    "loader-different",
    "The loader in this Firefox is not exactly the version that Peek-a-Foxy installs.",
    "If Peek-a-Foxy works for you, leave it as it is; if it does not, remove config.js and "
    "defaults/pref/config-prefs.js from the Firefox folder and run `peek-a-foxy install` "
    "again.",
)
AUTOCONFIG_FOREIGN = _register(
    "PAF-603",
    "autoconfig-foreign",
    "Another autoconfig setup is present in the Firefox folder and may prevent the loader "
    "from starting.",
    "The report names the files involved. If you do not need the other setup, remove it; "
    "otherwise make sure that it also loads fx-autoconfig's config.js.",
)
FIREFOX_INFO_UNREADABLE = _register(
    "PAF-604",
    "firefox-info-unreadable",
    "Firefox's application.ini file could not be read, so the version of this Firefox is unknown.",
    "Nothing needs to be done unless something else fails; if it does, mention which "
    "Firefox you use, which about:support shows.",
)
PROFILE_FOLDER_MISSING = _register(
    "PAF-605",
    "profile-folder-missing",
    "The profile folder does not exist.",
    "Choose an existing profile with --profile, or start Firefox once so that it creates one.",
)
PROFILE_FILES_MISSING = _register(
    "PAF-606",
    "profile-files-missing",
    "Some of the Peek-a-Foxy files are missing from the profile.",
    "Run `peek-a-foxy install` again.",
)
PROFILE_FILES_DIFFERENT = _register(
    "PAF-607",
    "profile-files-different",
    "Some of the Peek-a-Foxy files in the profile are not the ones that came with this version.",
    "Run `peek-a-foxy install` to update them; any change you made to those files will be "
    "replaced.",
)
UTILS_MISSING = _register(
    "PAF-608",
    "utils-missing",
    "The loader's utils folder is missing from the profile's chrome folder.",
    "Run `peek-a-foxy install` again.",
)
CSS_IMPORT_MISSING = _register(
    "PAF-609",
    "css-import-missing",
    "The file userChrome.css does not load the Peek-a-Foxy stylesheet.",
    "Run `peek-a-foxy install` again; it adds the missing line and keeps the rest of your file.",
)
CSS_IMPORT_LATE = _register(
    "PAF-610",
    "css-import-late",
    "The line that loads the Peek-a-Foxy stylesheet is placed below other rules, so "
    "Firefox ignores it.",
    "Run `peek-a-foxy install`; it moves the line to the top and keeps the rest of your file.",
)
PREFS_MISSING = _register(
    "PAF-611",
    "prefs-missing",
    "A setting that Firefox needs in order to run the script is missing or turned off.",
    "Run `peek-a-foxy install` again; it adds the settings to your user.js file.",
)
STARTUP_CACHE = _register(
    "PAF-612",
    "startup-cache",
    "Firefox may still be using a copy of its files from before Peek-a-Foxy was installed.",
    "Close all Firefox windows, start Firefox, open about:support, press the 'Clear "
    "startup cache' button and let Firefox restart.",
)
STATUS_MISSING = _register(
    "PAF-613",
    "status-missing",
    "Firefox has not run the script yet, so it has not reported anything.",
    "Close all Firefox windows and start Firefox again; if this message stays, the loader "
    "is not working, so look at the Firefox checks above it.",
)
STATUS_UNUSABLE = _register(
    "PAF-614",
    "status-unusable",
    "The status file written by Firefox could not be read, has an impossible date, or is "
    "older than the installed files.",
    "Close all Firefox windows, start Firefox again, and then run `peek-a-foxy doctor` once more.",
)
FIREFOX_REPORTS_PROBLEM = _register(
    "PAF-615",
    "firefox-reports-problem",
    "The script found something in this Firefox that it cannot work with.",
    "Update Peek-a-Foxy and Firefox; if the message stays, include this report when you "
    "ask for help, because Firefox may have changed something.",
)
FIREFOX_SCRIPT_ERRORS = _register(
    "PAF-616",
    "firefox-script-errors",
    "The script recorded errors while it was running in Firefox.",
    "Include this report when you ask for help, because the errors are listed in it.",
)
CONSOLE_ENCODING = _register(
    "PAF-617",
    "console-encoding",
    "This terminal cannot show every character, so some of the text may look wrong.",
    "This is harmless; for clean output use a terminal that is set to UTF-8, as Windows "
    "Terminal is.",
)

# --- 9xx: unexpected ----------------------------------------------------------------------------

UNEXPECTED = _register(
    "PAF-900",
    "unexpected",
    "Something unexpected went wrong; this is a bug in Peek-a-Foxy.",
    f"Please report it at {ISSUES_URL}: run `peek-a-foxy doctor --copy`, paste the result into "
    "your report and attach the log file, whose location `peek-a-foxy logs` shows.",
)


class PeekError(Exception):
    """An expected failure. ``str(error)`` is the message; the code and hint travel with it."""

    area: int | None = None  # set by the subclasses: the code must belong to that area

    def __init__(
        self, code: ErrorCode, message: str, *, hint: str | None = None, detail: str = ""
    ) -> None:
        if CODES.get(code.code) is not code:
            raise ValueError(f"{code.code} is not a registered error code")
        if self.area is not None and code.area != self.area:
            raise ValueError(f"{code.code} does not belong to {type(self).__name__}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = code.hint if hint is None else hint
        self.detail = detail  # technical, for --verbose and the log


class DiscoveryError(PeekError):
    """Profiles and Firefox installations: finding them, or choosing between them."""

    area = 1


class LoaderError(PeekError):
    area = 2


class ElevationError(PeekError):
    area = 3


class UserFileError(PeekError):
    area = 4


class PlatformError(PeekError):
    area = 5


class UnexpectedError(PeekError):
    area = 9


def set_context(error: BaseException, text: str) -> None:
    """Attach what already happened ("2 of 5 steps finished...") to any error, shown after it."""
    error.paf_context = text  # type: ignore[attr-defined]


def get_context(error: BaseException) -> str:
    context: object = getattr(error, "paf_context", "")
    return context if isinstance(context, str) else ""


def from_oserror(error: OSError) -> UserFileError:
    """A file system failure, as an error with a code (the original stays as ``__cause__``)."""
    where = f": {error.filename}" if error.filename else ""
    reason = error.strerror or str(error) or type(error).__name__
    wrapped = UserFileError(FILE_IO, f"{reason}{where}", detail=repr(error))
    wrapped.__cause__ = error
    set_context(wrapped, get_context(error))  # keep what a plan runner said about it
    return wrapped
