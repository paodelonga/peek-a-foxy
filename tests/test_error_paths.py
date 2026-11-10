"""Error codes that only a test of the whole command can prove (review 3, F-L6).

The registry test only reads the source: it shows that a code is mentioned somewhere, not that the
command ends with it. Each test here runs the real command and looks at the code and the exit code
that the person gets: the mapping of the administrator prompt (301 to 305, 206), the choice that
cannot be asked (106), an answer outside the list (108), a malformed pin (203), and the program's
own files gone missing (503).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from peek_a_foxy import _winapi, assets, cli, elevate, errors, loader
from peek_a_foxy.cli import app

runner = CliRunner()

CONFIG = b"// a loader\n"
PREFS = b'pref("general.config.filename", "config.js");\n'


def install(profile: Path, *extra: str):
    return runner.invoke(app, ["install", "--profile", str(profile), "--yes", *extra])


def failed_with(result, code: errors.ErrorCode) -> None:
    assert result.exit_code == errors.EXIT_FAILURE, result.output
    assert f"error [{code.code}]" in result.output, result.output
    assert "What to do:" in result.output  # every one of these tells the person a way forward
    assert errors.UNEXPECTED.code not in result.output and "Traceback" not in result.output


# --- PAF-106: several Firefox installs and nobody to ask ----------------------------------------


@pytest.fixture
def two_firefoxes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    folders = [tmp_path / "ff1", tmp_path / "ff2"]
    for folder in folders:
        folder.mkdir()
        (folder / "omni.ja").touch()
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: folders)
    return folders


def test_two_firefoxes_without_a_terminal_is_paf_106_and_nothing_is_written(
    profile: Path, two_firefoxes: list[Path]
):
    failed_with(install(profile), errors.SEVERAL_FIREFOXES)
    assert not (profile / "chrome" / "autohide.css").exists()


# --- PAF-108: an answer that is not in the list --------------------------------------------------


@pytest.mark.parametrize("answer", ["0", "3", "-1", "99999999999999999999"])
def test_a_firefox_number_outside_the_list_is_paf_108_and_nothing_is_written(
    profile: Path, two_firefoxes: list[Path], monkeypatch, answer: str
):
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--profile", str(profile)], input=f"{answer}\ny\n")
    failed_with(result, errors.INVALID_CHOICE)
    assert "between 1 and 2" in result.output
    assert not (profile / "chrome" / "autohide.css").exists()
    assert not any((folder / "config.js").exists() for folder in two_firefoxes)


# --- PAF-203: FXAC_COMMIT is not a full hash -----------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",  # `export FXAC_COMMIT=` in a shell file
        "main",
        "abc123",
        "a" * 39,
        "a" * 41,
        "a" * 40 + "\n",  # fullmatch, not a pattern that lets a line end through
        "g" * 40,
        "０" * 40,  # full-width digits are not hexadecimal digits
        "--upload-pack=touch /tmp/pwned",
        "-" + "a" * 39,
    ],
)
def test_a_malformed_pin_is_paf_203_before_anything_is_fetched_or_written(
    profile: Path, firefox_dir: Path, monkeypatch, value: str
):
    monkeypatch.setenv("FXAC_COMMIT", value)
    monkeypatch.delenv("FXAC_REPO", raising=False)
    result = install(profile, "--firefox-dir", str(firefox_dir))
    failed_with(result, errors.BAD_PINNED_COMMIT)
    assert not (profile / "chrome" / "autohide.css").exists()
    assert not (firefox_dir / "config.js").exists()


def test_with_the_loader_skipped_the_pin_is_not_looked_at(
    profile: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("FXAC_COMMIT", "not a hash")
    assert install(profile, "--skip-loader").exit_code == 0


# --- PAF-503: the files to install are gone ------------------------------------------------------


def test_missing_program_files_are_paf_503_and_the_profile_is_left_alone(
    profile: Path, tmp_path: Path, monkeypatch
):
    empty = tmp_path / "empty-package"
    empty.mkdir()
    monkeypatch.setattr(assets.resources, "files", lambda name: empty)
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "a" / "b" / "assets.py"))
    failed_with(install(profile, "--skip-loader"), errors.FILES_MISSING)
    assert list((profile / "chrome").iterdir()) == []


# --- the administrator copy: 206 and 301 to 305 --------------------------------------------------


@pytest.fixture
def windows_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, firefox_dir: Path) -> Path:
    """A Windows-style install whose Firefox folder refuses the direct copy, so the prompt is next.

    Only the edges are replaced: the fetch (a prepared checkout), the refusal of the folder and the
    answer of ``run_elevated``. Everything between (the plan, the helper command, the mapping of
    what comes back, the report) is the real code.
    """
    checkout = tmp_path / "checkout"
    (checkout / "program" / "defaults" / "pref").mkdir(parents=True)
    (checkout / "program" / "config.js").write_bytes(CONFIG)
    (checkout / "program" / "defaults" / "pref" / "config-prefs.js").write_bytes(PREFS)
    (checkout / "profile" / "chrome" / "utils").mkdir(parents=True)
    (checkout / "profile" / "chrome" / "utils" / "boot.sys.mjs").write_text("boot\n")
    monkeypatch.setattr(
        elevate,
        "PINNED_SHA256",
        {
            "config.js": hashlib.sha256(CONFIG).hexdigest(),
            "defaults/pref/config-prefs.js": hashlib.sha256(PREFS).hexdigest(),
        },
    )

    @contextmanager
    def fetched() -> Iterator[Path]:
        yield checkout

    def refused(source: Path, destination: Path) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(loader, "fetch_loader", fetched)
    monkeypatch.setattr(loader, "_copy_direct", refused)
    monkeypatch.setattr(loader.platform, "is_windows", lambda: True)
    monkeypatch.setattr(elevate, "is_admin", lambda: False)
    monkeypatch.delenv("FXAC_REPO", raising=False)
    monkeypatch.delenv("FXAC_COMMIT", raising=False)
    return firefox_dir


def answer_of_the_prompt(monkeypatch: pytest.MonkeyPatch, outcome: object) -> list[str]:
    """Make ``run_elevated`` end with ``outcome`` (an exit code, or an exception to raise)."""
    seen: list[str] = []

    def run_elevated(executable: str, parameters: str, timeout_seconds: float) -> int:
        seen.append(executable)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, int)
        return outcome

    monkeypatch.setattr(_winapi, "run_elevated", run_elevated)
    # The prompt is replaced, not the check that its program exists, so say that it does.
    real_isfile = elevate.os.path.isfile
    monkeypatch.setattr(
        elevate.os.path,
        "isfile",
        lambda path: True if str(path).lower().endswith("powershell.exe") else real_isfile(path),
    )
    return seen


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (_winapi.ElevationFailed(_winapi.ERROR_CANCELLED, "cancelled"), errors.UAC_CANCELLED),
        (_winapi.ElevationFailed(_winapi.WAIT_TIMEOUT, "timed out"), errors.UAC_TIMEOUT),
        (_winapi.ElevationFailed(5, "access denied"), errors.UAC_UNAVAILABLE),
        (14, errors.UAC_HELPER_FAILED),  # the helper's own "writing failed"
        (12, errors.UAC_HELPER_FAILED),  # "not the pinned files"
        (10, errors.UAC_HELPER_FAILED),
        (15, errors.UAC_RESTRICTED_POWERSHELL),  # a policy keeps PowerShell out of FullLanguage
        (16, errors.UAC_HELPER_FAILED),  # the first code the helper does not use
        (255, errors.UAC_HELPER_FAILED),  # a code that the helper never uses
    ],
)
def test_the_end_of_the_administrator_prompt_is_a_coded_error_with_nothing_half_done(
    windows_install: Path, profile: Path, monkeypatch, outcome, code: errors.ErrorCode
):
    seen = answer_of_the_prompt(monkeypatch, outcome)
    result = install(profile, "--firefox-dir", str(windows_install))
    failed_with(result, code)
    assert len(seen) == 1  # asked once, never again in a loop
    assert "steps finished" in result.output  # the profile files before it are reported as done
    assert code.hint in " ".join(result.output.split())  # the way forward, however it is wrapped


def test_the_same_setup_succeeds_when_the_prompt_is_answered(
    windows_install: Path, profile: Path, monkeypatch
):
    """The control: without it, the failures above could be a broken fixture."""
    seen = answer_of_the_prompt(monkeypatch, 0)
    result = install(profile, "--firefox-dir", str(windows_install))
    assert result.exit_code == 0, result.output
    assert len(seen) == 1


@pytest.mark.parametrize("variable", ["FXAC_REPO", "FXAC_COMMIT"])
def test_a_pin_override_ends_the_administrator_step_as_paf_305_without_a_prompt(
    windows_install: Path, profile: Path, monkeypatch, variable: str
):
    seen = answer_of_the_prompt(monkeypatch, 0)
    monkeypatch.setenv(variable, "a" * 40 if variable == "FXAC_COMMIT" else "/some/repo")
    result = install(profile, "--firefox-dir", str(windows_install))
    failed_with(result, errors.UAC_ENV_OVERRIDE)
    assert seen == []


def test_an_administrator_who_cannot_write_either_is_paf_206_and_gets_no_second_prompt(
    windows_install: Path, profile: Path, monkeypatch
):
    seen = answer_of_the_prompt(monkeypatch, 0)
    monkeypatch.setattr(elevate, "is_admin", lambda: True)
    failed_with(install(profile, "--firefox-dir", str(windows_install)), errors.ADMIN_CANNOT_WRITE)
    assert seen == []
