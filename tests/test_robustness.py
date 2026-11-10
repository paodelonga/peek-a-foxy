"""Failure modes and unusual-but-plausible setups; none may corrupt user files or crash."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from support import fake_sudo, needs_permissions, needs_posix_shell, needs_symlinks
from typer.testing import CliRunner

from peek_a_foxy import cli, errors, loader
from peek_a_foxy import userfiles as uf
from peek_a_foxy.cli import app
from peek_a_foxy.installer import UserFileError, plan_install, plan_uninstall

runner = CliRunner()
SRC = str(Path(__file__).resolve().parents[1] / "src")


def tree(*roots: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file()}


# --- the user's files ------------------------------------------------------------------------


@needs_symlinks
def test_a_symlinked_userchrome_css_stays_a_symlink(profile: Path, tmp_path: Path):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    target = dotfiles / "userChrome.css"
    target.write_text("body{}\n")
    (profile / "chrome" / "userChrome.css").symlink_to(target)
    plan_install(profile, None).execute()
    link = profile / "chrome" / "userChrome.css"
    assert link.is_symlink()
    assert target.read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n"


def test_crlf_and_bom_survive_an_install_and_an_uninstall(profile: Path):
    user_js = profile / "user.js"
    original = b"\xef\xbb\xbf" + b'user_pref("my.own", 1);\r\n'
    user_js.write_bytes(original)
    plan_install(profile, None).execute()
    installed = user_js.read_bytes()
    assert installed.startswith(b"\xef\xbb\xbf") and b"\r\n" in installed
    assert b"\n" not in installed.replace(b"\r\n", b"")
    plan_uninstall(profile).execute()
    after = user_js.read_bytes()
    assert after.startswith(original)  # BOM, CRLF and the user's own line are untouched
    assert b"peekafoxy." not in after
    # The stylesheets pref stays on purpose: the user's other styles may depend on it.
    assert b"toolkit.legacyUserProfileCustomizations.stylesheets" in after


def test_invalid_utf8_stops_everything_before_any_change(profile: Path):
    (profile / "user.js").write_bytes(b'user_pref("x", "\xff\xfe");\n')
    before = tree(profile)
    with pytest.raises(UserFileError, match="not valid UTF-8"):
        plan_install(profile, None)
    assert tree(profile) == before


def test_cli_reports_unreadable_user_files_cleanly(profile: Path):
    (profile / "chrome" / "userChrome.css").write_bytes(b"\xff\xfe\x00")
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output and "Traceback" not in result.output
    assert not (profile / "chrome" / "autohide.css").exists()


def test_existing_utils_keep_the_users_extra_files(
    profile: Path, firefox_dir: Path, fxac_repo: Path
):
    extra = profile / "chrome" / "utils" / "my_module.sys.mjs"
    extra.parent.mkdir(parents=True)
    extra.write_text("mine\n")
    plan_install(profile, firefox_dir).execute()
    assert extra.read_text() == "mine\n"
    assert (profile / "chrome" / "utils" / "boot.sys.mjs").is_file()


def test_paths_with_spaces_and_unicode(tmp_path: Path):
    profile = tmp_path / "meu perfil ñ ü" / "abc.default"
    (profile / "chrome").mkdir(parents=True)
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 0, result.output
    assert (profile / "chrome" / "autohide.css").is_file()


# --- failures: nothing half-installed --------------------------------------------------------


def test_a_failed_fetch_changes_nothing(profile: Path, firefox_dir: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("FXAC_REPO", str(tmp_path / "does-not-exist"))
    before = tree(profile, firefox_dir)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert tree(profile, firefox_dir) == before  # the fetch is the first step


def test_missing_git_is_explained(profile: Path, firefox_dir: Path, monkeypatch):
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--firefox-dir", str(firefox_dir), "--yes"]
    )
    assert result.exit_code == 1 and "git is required" in result.output
    assert not (profile / "chrome" / "autohide.css").exists()


def test_chrome_being_a_file_is_a_clean_error(tmp_path: Path):
    profile = tmp_path / "p"
    profile.mkdir()
    (profile / "chrome").write_text("i am a file\n")
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 1 and "Traceback" not in result.output


@needs_permissions
def test_a_read_only_profile_is_a_clean_error(profile: Path):
    profile.chmod(0o555)
    (profile / "chrome").chmod(0o555)
    try:
        result = runner.invoke(
            app, ["install", "--profile", str(profile), "--skip-loader", "--yes"]
        )
    finally:
        profile.chmod(0o755)
        (profile / "chrome").chmod(0o755)
    assert result.exit_code == 1 and "Traceback" not in result.output


# --- the privileged copy ---------------------------------------------------------------------


def test_a_read_only_firefox_dir_falls_back_to_sudo(monkeypatch, tmp_path):
    calls: list[tuple[tuple[str, ...], bytes | None]] = []
    monkeypatch.setattr(loader, "_sudo", lambda *command, data=None: calls.append((command, data)))

    def denied(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(loader, "_copy_direct", denied)
    monkeypatch.setenv("FXAC_REPO", "x")  # not the pinned loader, so it has to be allowed
    source = tmp_path / "config.js"
    source.write_text("x")
    destination = tmp_path / "usr" / "lib" / "firefox" / "defaults" / "config.js"
    loader._copy(source, destination, "config.js", allow_unverified=True)
    assert calls == [
        (("mkdir", "-p", str(destination.parent)), None),
        (("install", "-m", "644", "/dev/stdin", str(destination)), b"x"),
    ]


def test_on_macos_the_verified_bytes_go_through_tee_and_chmod(monkeypatch, tmp_path):
    """BSD ``install`` may refuse /dev/stdin, so macOS uses ``tee`` then ``chmod``."""
    calls: list[tuple[tuple[str, ...], bytes | None]] = []
    monkeypatch.setattr(loader, "_sudo", lambda *command, data=None: calls.append((command, data)))
    monkeypatch.setattr(loader.platform, "system", lambda: "macos")

    def denied(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(loader, "_copy_direct", denied)
    monkeypatch.setenv("FXAC_REPO", "x")
    source = tmp_path / "config.js"
    source.write_text("x")
    destination = tmp_path / "Resources" / "config.js"
    loader._copy(source, destination, "config.js", allow_unverified=True)
    assert calls == [
        (("mkdir", "-p", str(destination.parent)), None),
        (("tee", str(destination)), b"x"),
        (("chmod", "644", str(destination)), None),
    ]


@needs_permissions
@needs_posix_shell
@pytest.mark.parametrize("sudo", ["refuses", "missing"])
def test_a_failing_sudo_is_a_clean_error(
    profile: Path, firefox_dir: Path, fxac_repo, monkeypatch, tmp_path, sudo: str
):
    """The real ``_sudo`` runs against a ``sudo`` that exits 1, or against no ``sudo`` at all.

    The old test made ``subprocess.run`` itself raise, so ``check=True`` was never exercised: a
    ``check=False`` mutant of ``_sudo`` survived and a refused sudo would have counted as success.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sudo == "refuses":
        fake_sudo(bin_dir, tmp_path / "calls", exit_code=1)
    git_path = shutil.which("git")
    assert git_path is not None
    (bin_dir / "git").symlink_to(git_path)  # git still has to work
    monkeypatch.setenv("PATH", str(bin_dir))
    firefox_dir.chmod(0o555)  # not writable: the loader has to ask for sudo
    try:
        result = runner.invoke(
            app,
            [
                "install",
                "--profile",
                str(profile),
                "--firefox-dir",
                str(firefox_dir),
                "--allow-unverified-loader",
                "--yes",
            ],
        )
    finally:
        firefox_dir.chmod(0o755)
    assert result.exit_code == 1 and "PAF-205" in result.output and "Traceback" not in result.output
    assert not (firefox_dir / "config.js").exists()
    assert (profile / "chrome" / "autohide.css").is_file()  # the earlier steps did run
    assert "Running the same command again is safe" in result.output
    assert "Done" not in result.output  # a refused sudo is never reported as a success


def test_sudo_runs_the_command_it_was_given(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        loader.subprocess, "run", lambda command, **kw: calls.append([*command, str(kw)])
    )
    loader._sudo("install", "-m", "644", "a", "b")
    assert calls == [["sudo", "install", "-m", "644", "a", "b", "{'check': True, 'input': None}"]]


def test_a_loader_identical_to_ours_is_not_a_conflict(profile, firefox_dir, fxac_repo):
    assert plan_install(profile, firefox_dir).execute() == []
    assert plan_install(profile, firefox_dir).execute() == []  # second run: same files, no warning


# --- interactive choices ---------------------------------------------------------------------


def _profiles_ini(root: Path) -> list[Path]:
    paths = [root / "Profiles" / name for name in ("one", "two")]
    for path in paths:
        path.mkdir(parents=True)
    (root / "profiles.ini").write_text(
        "[Profile0]\nName=one\nPath=Profiles/one\n\n[Profile1]\nName=two\nPath=Profiles/two\n"
    )
    return paths


def test_interactive_profile_choice(tmp_path: Path, monkeypatch):
    one, two = _profiles_ini(tmp_path)
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--skip-loader"], input="2\ny\n")
    assert result.exit_code == 0, result.output
    assert (two / "chrome" / "autohide.css").is_file()
    assert not (one / "chrome").exists()


def test_declining_the_confirmation_changes_nothing(tmp_path: Path, monkeypatch, profile: Path):
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    before = tree(profile)
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--skip-loader"], input="n\n"
    )
    assert result.exit_code == 1
    assert tree(profile) == before


@pytest.mark.parametrize("answer", ["0", "3", "-1", "99999999999999999999", "2147483648"])
def test_a_number_outside_the_list_is_the_invalid_choice_error_and_nothing_changes(
    tmp_path: Path, monkeypatch, answer
):
    """The check itself must refuse it. (The first version of this test only looked at profile
    "one", and "0" passed with the check broken: index -1 picked the last profile, and the
    confirmation that followed then read "0" until the input ended.)"""
    one, two = _profiles_ini(tmp_path)
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--skip-loader"], input=f"{answer}\ny\n")
    assert result.exit_code == 1, result.output
    assert errors.INVALID_CHOICE.code in result.output and "between 1 and 2" in result.output
    assert not (one / "chrome").exists() and not (two / "chrome").exists()


@pytest.mark.parametrize("answer", ["x", "1.5", "", " "])
def test_an_answer_that_is_not_a_number_is_asked_again_and_nothing_changes(
    tmp_path: Path, monkeypatch, answer
):
    one, two = _profiles_ini(tmp_path)
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--skip-loader"], input=f"{answer}\n" * 3)
    assert result.exit_code != 0 and errors.UNEXPECTED.code not in result.output
    assert not (one / "chrome").exists() and not (two / "chrome").exists()


def test_interactive_firefox_choice(profile: Path, tmp_path: Path, monkeypatch, fxac_repo):
    dirs = []
    for name in ("ff1", "ff2"):
        directory = tmp_path / name
        directory.mkdir()
        dirs.append(directory)
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: dirs)
    monkeypatch.setattr(cli, "_interactive", lambda yes: True)
    result = runner.invoke(app, ["install", "--profile", str(profile)], input="2\ny\n")
    assert result.exit_code == 0, result.output
    assert (dirs[1] / "config.js").is_file() and not (dirs[0] / "config.js").exists()


def test_no_profiles_ini_and_no_profile_option_is_a_clean_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli.platform, "profiles_root", lambda: tmp_path)
    result = runner.invoke(app, ["install", "--skip-loader", "--yes"])
    assert result.exit_code == 1 and "profiles.ini" in result.output


def test_no_firefox_found_is_a_clean_error(profile: Path, monkeypatch):
    monkeypatch.setattr(cli.platform, "firefox_dir_candidates", lambda: [])
    result = runner.invoke(app, ["install", "--profile", str(profile), "--yes"])
    assert result.exit_code == 1 and "--firefox-dir" in result.output


def test_unsupported_platform_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(cli.platform.sys, "platform", "freebsd14")
    result = runner.invoke(app, ["install", "--yes"])
    assert result.exit_code == 1 and "Linux, macOS and Windows" in result.output


def test_uninstall_dry_run_changes_nothing(profile: Path):
    plan_install(profile, None).execute()
    before = tree(profile)
    result = runner.invoke(app, ["uninstall", "--profile", str(profile), "--dry-run"])
    assert result.exit_code == 0
    assert tree(profile) == before


def test_a_long_path_in_an_error_is_not_broken_across_lines(tmp_path: Path):
    """People copy the path out of an error message, so it must reach them in one piece."""
    profile = tmp_path / ("a-deliberately-long-directory-name-" * 3) / "profile"
    (profile / "chrome").mkdir(parents=True)
    css = profile / "chrome" / "userChrome.css"
    css.write_bytes(b"\xff\xfe\x00")
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 1
    assert str(css) in result.output  # more than 80 columns, still on one line


# --- no terminal and no --yes: nobody can confirm ---------------------------------------------


@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_without_a_terminal_and_without_yes_nothing_is_applied(
    command: str, profile: Path, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda yes: False)  # piped, cron, CI...
    plan_install(profile, None).execute()
    before = tree(profile)
    args = [command, "--profile", str(profile)]
    result = runner.invoke(app, args if command == "uninstall" else [*args, "--skip-loader"])
    assert result.exit_code == 1 and "--yes" in result.output
    assert "Traceback" not in result.output
    assert tree(profile) == before


class Stream:
    """A stand-in for a standard stream that only says whether it is a terminal."""

    def __init__(self, terminal: bool) -> None:
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal


@pytest.mark.parametrize(
    ("stdin", "stdout", "yes", "expected"),
    [
        (True, True, False, True),  # the only case in which anybody can answer
        (True, False, False, False),  # `peek-a-foxy install | tee out.txt`: the question would go
        (False, True, False, False),  # into the pipe, where nobody reads it
        (False, False, False, False),
        (True, True, True, False),  # --yes: nothing to ask
    ],
)
def test_the_person_is_only_asked_when_both_ends_are_a_terminal(
    monkeypatch, stdin: bool, stdout: bool, yes: bool, expected: bool
):
    monkeypatch.setattr(cli.sys, "stdin", Stream(stdin))
    monkeypatch.setattr(cli.sys, "stdout", Stream(stdout))
    assert cli._interactive(yes) is expected


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo-terminal")
def test_a_terminal_in_and_a_pipe_out_refuses_to_prompt_into_the_pipe(profile: Path):
    """The real thing, ``peek-a-foxy install | tee``: stdin is a terminal, stdout is a pipe.

    The terminal is kept open and holds an end-of-input (Ctrl-D), so a prompt that went ahead
    would read it and abort ("Aborted!", no code); only the refusal ends in PAF-502.
    """
    import os
    import pty

    master, slave = pty.openpty()
    try:
        os.write(master, b"\x04")  # Ctrl-D, waiting in the terminal for whoever reads it first
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "peek_a_foxy",
                "install",
                "--profile",
                str(profile),
                "--skip-loader",
            ],
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONPATH": SRC, "PEEK_A_FOXY_LOG": "off", "NO_COLOR": "1"},
        )
        stdout, stderr = process.communicate(timeout=120)
    finally:
        os.close(slave)
        os.close(master)
    assert process.returncode == errors.EXIT_FAILURE, (stdout, stderr)
    assert errors.NO_TERMINAL.code in stderr, stderr
    assert not (profile / "chrome" / "autohide.css").exists()


def test_a_dry_run_needs_no_terminal_and_no_yes(profile: Path):
    result = runner.invoke(
        app, ["install", "--profile", str(profile), "--skip-loader", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert not (profile / "chrome" / "autohide.css").exists()


def test_yes_applies_without_a_terminal(profile: Path):
    result = runner.invoke(app, ["install", "--profile", str(profile), "--skip-loader", "--yes"])
    assert result.exit_code == 0, result.output
    assert (profile / "chrome" / "autohide.css").is_file()


def test_the_real_cli_without_a_terminal_refuses_too(profile: Path):
    """End to end, with the real stdin/stdout (not a terminal under pytest) instead of a stub."""
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "peek_a_foxy",
            "install",
            "--profile",
            str(profile),
            "--skip-loader",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1 and "--yes" in result.stderr
    assert not (profile / "chrome" / "autohide.css").exists()
