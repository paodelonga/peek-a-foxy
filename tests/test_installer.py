import errno
import os
from pathlib import Path

import pytest
from support import needs_permissions, needs_symlinks

from peek_a_foxy import installer
from peek_a_foxy import userfiles as uf
from peek_a_foxy.assets import FILES
from peek_a_foxy.installer import plan_install, plan_uninstall


def install(profile: Path, firefox_dir: Path | None = None) -> list[str]:
    return plan_install(profile, firefox_dir).execute()


def test_fresh_install_without_loader(profile: Path):
    install(profile)
    assert (profile / "chrome" / "autohide.css").is_file()
    for name in FILES:
        assert (profile / "chrome" / name).is_file(), name
    assert (profile / "chrome" / "userChrome.css").read_text() == uf.CSS_IMPORT + "\n"
    # Only the prefs Firefox itself needs. The autohide prefs stay out of user.js, which is
    # re-applied on every start and would undo changes made in about:config.
    assert (profile / "user.js").read_text() == (
        'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
        'user_pref("userChromeJS.persistent_domcontent_callback", true);\n'
    )


def test_install_with_loader(profile: Path, firefox_dir: Path, fxac_repo: Path):
    assert install(profile, firefox_dir) == []
    assert (profile / "chrome" / "utils" / "boot.sys.mjs").is_file()
    assert (firefox_dir / "config.js").read_text() == "// loader\n"
    assert (firefox_dir / "defaults" / "pref" / "config-prefs.js").is_file()


def test_install_is_idempotent(profile: Path):
    install(profile)
    first = {p: p.read_bytes() for p in profile.rglob("*") if p.is_file()}
    install(profile)
    assert {p: p.read_bytes() for p in profile.rglob("*") if p.is_file()} == first


def test_user_content_and_changed_prefs_are_preserved(profile: Path):
    (profile / "chrome" / "userChrome.css").write_text("body { color: red; }\n")
    (profile / "user.js").write_text('user_pref("peekafoxy.tabs.autohide", true);\n')
    install(profile)
    css = (profile / "chrome" / "userChrome.css").read_text().splitlines()
    assert css == [uf.CSS_IMPORT, "body { color: red; }"]
    assert 'user_pref("peekafoxy.tabs.autohide", true);' in (profile / "user.js").read_text()


def test_migrates_from_the_old_project_name(profile: Path):
    chrome = profile / "chrome"
    (chrome / "JS").mkdir()
    (chrome / "tabs-autohide.css").touch()
    (chrome / "JS" / "tabs_autohide.uc.js").touch()
    (chrome / "userChrome.css").write_text(f"{uf.LEGACY_CSS_IMPORT}\nbody{{}}\n")
    install(profile)
    assert not (chrome / "tabs-autohide.css").exists()
    assert not (chrome / "JS" / "tabs_autohide.uc.js").exists()
    assert (chrome / "userChrome.css").read_text() == f"{uf.CSS_IMPORT}\nbody{{}}\n"


def test_a_different_existing_loader_is_not_overwritten(
    profile: Path, firefox_dir: Path, fxac_repo: Path
):
    (firefox_dir / "config.js").write_text("// someone else's\n")
    warnings = install(profile, firefox_dir)
    assert len(warnings) == 1 and "not overwriting" in warnings[0]
    assert (firefox_dir / "config.js").read_text() == "// someone else's\n"
    assert not (firefox_dir / "defaults").exists()
    assert (profile / "chrome" / "autohide.css").is_file()  # the profile part still installs


def test_the_pinned_commit_is_verified(
    profile: Path, firefox_dir: Path, fxac_repo: Path, monkeypatch
):
    import pytest

    from peek_a_foxy.loader import LoaderError

    monkeypatch.setenv("FXAC_COMMIT", "0" * 40)
    with pytest.raises(LoaderError):
        install(profile, firefox_dir)
    assert not (firefox_dir / "config.js").exists()


def test_uninstall_removes_only_what_was_installed(profile: Path):
    (profile / "chrome" / "userChrome.css").write_text("body{}\n")
    (profile / "user.js").write_text('user_pref("my.own", 1);\n')
    install(profile)
    plan_uninstall(profile).execute()
    chrome = profile / "chrome"
    assert not (chrome / "autohide.css").exists()
    for name in FILES:
        assert not (chrome / name).exists(), name
    assert (chrome / "userChrome.css").read_text() == "body{}\n"
    user_js = (profile / "user.js").read_text()
    assert 'user_pref("my.own", 1);' in user_js
    assert "peekafoxy." not in user_js


def test_uninstall_on_a_clean_profile_does_nothing(profile: Path):
    plan_uninstall(profile).execute()
    assert not (profile / "user.js").exists()


# --- the folders that held only our files go with them ----------------------------------------


def test_uninstall_removes_the_folders_that_are_left_empty(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    (chrome / "utils").mkdir()
    (chrome / "utils" / "boot.sys.mjs").write_text("// the loader's, not ours\n")
    assert (chrome / "JS").is_dir() and (chrome / "resources").is_dir()
    assert plan_uninstall(profile).execute() == []
    assert not os.path.lexists(chrome / "JS") and not os.path.lexists(chrome / "resources")
    assert chrome.is_dir()  # the profile's own folder is never ours to remove
    assert (chrome / "utils" / "boot.sys.mjs").is_file()  # nor is the loader's folder
    assert plan_uninstall(profile).execute() == []  # and a second run has nothing to do


def test_the_plan_says_which_folders_it_removes_and_when(profile: Path):
    step = plan_uninstall(profile).steps[0].description
    assert "JS" in step and "resources" in step and "nothing else is in them" in step


def test_a_folder_that_holds_a_file_of_the_users_is_kept_with_that_file(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    (chrome / "JS" / "mine.uc.js").write_text("// mine\n")
    (chrome / "resources" / "mine.png").write_bytes(b"\x89PNG")
    assert plan_uninstall(profile).execute() == []
    assert (chrome / "JS" / "mine.uc.js").read_text() == "// mine\n"
    assert (chrome / "resources" / "mine.png").read_bytes() == b"\x89PNG"
    assert not (chrome / "JS" / "autohide.uc.js").exists()  # but ours still went


def test_only_one_of_the_two_folders_is_removed_when_the_other_is_in_use(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    (chrome / "JS" / "mine.uc.js").write_text("// mine\n")
    plan_uninstall(profile).execute()
    assert (chrome / "JS").is_dir() and not (chrome / "resources").exists()


def test_a_folder_with_only_an_empty_folder_inside_is_not_emptied_by_force(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    (chrome / "JS" / "mine").mkdir()  # an empty folder is still the user's something
    (chrome / "resources" / "a" / "b").mkdir(parents=True)
    plan_uninstall(profile).execute()
    assert (chrome / "JS" / "mine").is_dir() and (chrome / "resources" / "a" / "b").is_dir()


def test_a_hidden_or_oddly_named_file_keeps_its_folder(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    (chrome / "JS" / ".hidden").write_text("")
    (chrome / "resources" / "-rf").write_text("")  # looks like an option, is only a name
    plan_uninstall(profile).execute()
    assert (chrome / "JS" / ".hidden").is_file() and (chrome / "resources" / "-rf").is_file()


def test_an_empty_utils_folder_is_not_ours_to_remove(profile: Path):
    (profile / "chrome" / "utils").mkdir()  # the loader's folder, whatever it holds
    install(profile)
    plan_uninstall(profile).execute()
    assert (profile / "chrome" / "utils").is_dir()


def test_uninstall_without_those_folders_is_quiet(profile: Path):
    assert plan_uninstall(profile).execute() == []
    assert (profile / "chrome").is_dir()


@needs_symlinks
def test_a_link_to_an_empty_folder_is_neither_removed_nor_followed(profile: Path, tmp_path: Path):
    chrome = profile / "chrome"
    elsewhere = tmp_path / "dotfiles" / "scripts"
    elsewhere.mkdir(parents=True)
    (chrome / "JS").symlink_to(elsewhere, target_is_directory=True)
    (chrome / "resources").symlink_to(tmp_path / "nowhere", target_is_directory=True)  # dangling
    assert plan_uninstall(profile).execute() == []
    assert (chrome / "JS").is_symlink() and os.path.lexists(chrome / "resources")
    assert elsewhere.is_dir()


@needs_symlinks
def test_a_link_to_a_folder_with_our_file_loses_the_file_but_keeps_link_and_folder(
    profile: Path, tmp_path: Path
):
    chrome = profile / "chrome"
    elsewhere = tmp_path / "dotfiles" / "scripts"
    elsewhere.mkdir(parents=True)
    (chrome / "JS").symlink_to(elsewhere, target_is_directory=True)
    (elsewhere / "autohide.uc.js").write_text("// ours, installed through the link\n")
    plan_uninstall(profile).execute()
    assert not (elsewhere / "autohide.uc.js").exists()
    assert (chrome / "JS").is_symlink() and elsewhere.is_dir()


def test_a_junction_or_other_reparse_point_is_not_removed(profile: Path, monkeypatch):
    # Windows reports a junction as a reparse point that Python before 3.12 does not call a link;
    # simulated here so every system exercises the check.
    folder = profile / "chrome" / "JS"
    folder.mkdir()
    real_lstat = os.lstat

    class Reparse:
        def __init__(self, result: os.stat_result):
            self._result = result
            self.st_file_attributes = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT

        def __getattr__(self, name: str):
            return getattr(self._result, name)

    def lstat(path, *args, **kwargs):
        result = real_lstat(path, *args, **kwargs)
        return Reparse(result) if Path(path) == folder else result

    removed: list[object] = []
    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(installer.os, "rmdir", lambda path: removed.append(path))
    assert plan_uninstall(profile).execute() == []
    assert folder not in removed


@needs_permissions
def test_a_folder_that_the_system_refuses_to_remove_is_left_without_an_error(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    for name in ("userChrome.css", "autohide.css"):  # removing them needs a writable chrome
        (chrome / name).unlink()
    plan = plan_uninstall(profile)
    chrome.chmod(0o555)  # our files can still go (their folders are writable), the folders cannot
    try:
        assert plan.execute() == []
    finally:
        chrome.chmod(0o755)
    assert list((chrome / "JS").iterdir()) == [] and list((chrome / "resources").iterdir()) == []


@pytest.mark.parametrize(
    "code", [errno.EACCES, errno.EPERM, errno.EBUSY, errno.ENOTEMPTY, errno.EIO]
)
def test_whatever_stops_the_removal_only_leaves_the_folder_and_the_uninstall_goes_on(
    profile: Path, monkeypatch, code: int
):
    chrome = profile / "chrome"
    (chrome / "userChrome.css").write_text("body{}\n")
    install(profile)

    def refused(path):
        raise OSError(code, os.strerror(code), str(path))

    monkeypatch.setattr(installer.os, "rmdir", refused)
    assert plan_uninstall(profile).execute() == []
    assert (chrome / "JS").is_dir() and (chrome / "resources").is_dir()
    assert (chrome / "userChrome.css").read_text() == "body{}\n"  # later steps still ran
    assert "peekafoxy" not in (profile / "user.js").read_text()


def test_a_file_that_appears_just_before_the_removal_is_not_lost(profile: Path, monkeypatch):
    chrome = profile / "chrome"
    install(profile)
    real_rmdir = os.rmdir

    def writer_wins(path):
        if Path(path).name == "JS":  # a program saves a script right now
            (Path(path) / "late.uc.js").write_text("// late\n")
        real_rmdir(path)

    monkeypatch.setattr(installer.os, "rmdir", writer_wins)
    assert plan_uninstall(profile).execute() == []
    assert (chrome / "JS" / "late.uc.js").read_text() == "// late\n"
    assert not (chrome / "resources").exists()


def test_a_folder_that_vanishes_before_the_removal_is_not_an_error(profile: Path, monkeypatch):
    install(profile)
    real_rmdir = os.rmdir

    def somebody_else_was_first(path):
        real_rmdir(path)
        real_rmdir(path)  # the second one finds nothing

    monkeypatch.setattr(installer.os, "rmdir", somebody_else_was_first)
    assert plan_uninstall(profile).execute() == []


def test_the_status_file_is_still_removed_with_the_folders(profile: Path):
    chrome = profile / "chrome"
    install(profile)
    (chrome / "peekafoxy-status.json").write_text("{}")
    (chrome / "peekafoxy-status.json.tmp").write_text("{")
    assert plan_uninstall(profile).execute() == []
    assert not (chrome / "peekafoxy-status.json").exists()
    assert not (chrome / "peekafoxy-status.json.tmp").exists()
    assert not (chrome / "JS").exists() and not (chrome / "resources").exists()


# --- pref names moved from userchrome.* to peekafoxy.* ----------------------------------------


def test_an_old_on_is_carried_over_and_an_old_off_is_dropped(profile: Path):
    (profile / "user.js").write_text(
        'user_pref("userchrome.tabs.autohide", true);\n'
        'user_pref("userchrome.urlbar.autohide", false);\n'  # only ever the default we wrote
        'user_pref("my.own", 1);\n'
    )
    install(profile)
    user_js = (profile / "user.js").read_text()
    assert 'user_pref("peekafoxy.tabs.autohide", true);' in user_js  # the user's choice survives
    assert "peekafoxy.urlbar.autohide" not in user_js
    assert "userchrome." not in user_js
    assert 'user_pref("my.own", 1);' in user_js


def test_a_new_pref_already_set_wins_over_an_old_one(profile: Path):
    (profile / "user.js").write_text(
        'user_pref("peekafoxy.tabs.autohide", false);\n'
        'user_pref("userchrome.tabs.autohide", true);\n'
    )
    install(profile)
    user_js = (profile / "user.js").read_text()
    assert 'user_pref("peekafoxy.tabs.autohide", false);' in user_js
    assert "userchrome." not in user_js


def test_uninstall_also_removes_the_old_pref_names(profile: Path):
    (profile / "user.js").write_text('user_pref("userchrome.tabs.autohide", true);\n')
    plan_uninstall(profile).execute()
    assert "userchrome." not in (profile / "user.js").read_text()


# --- the settings page: more files, more prefs ------------------------------------------------


def test_uninstall_removes_every_pref_the_script_registers_and_keeps_firefoxs_own(profile: Path):
    lines = "".join(f'user_pref("{name}", 1);\n' for name in uf.OWN_PREFS)
    (profile / "user.js").write_text(lines + 'user_pref("my.own", 1);\n')
    install(profile)
    plan_uninstall(profile).execute()
    user_js = (profile / "user.js").read_text()
    assert "peekafoxy." not in user_js and 'user_pref("my.own", 1);' in user_js
    # Shared with other scripts and other tools, so it is left alone, like the stylesheets pref.
    assert uf.SUBDOCUMENTS_PREF in user_js and uf.STYLESHEETS_PREF in user_js


def test_the_settings_page_needs_scripts_in_subdocuments_and_install_turns_it_on(profile: Path):
    (profile / "user.js").write_text(f'user_pref("{uf.SUBDOCUMENTS_PREF}", false);\n')
    install(profile)
    assert f'user_pref("{uf.SUBDOCUMENTS_PREF}", true);' in (profile / "user.js").read_text()
    again = (profile / "user.js").read_bytes()
    install(profile)
    assert (profile / "user.js").read_bytes() == again  # idempotent


def test_an_install_that_predates_the_settings_page_is_completed_by_installing_again(
    profile: Path,
):
    install(profile)
    for name in ("JS/autohide-prefs.uc.js", "resources/peekafoxy.sys.mjs"):
        (profile / "chrome" / name).unlink()
    install(profile)
    assert (profile / "chrome" / "JS" / "autohide-prefs.uc.js").is_file()
    assert (profile / "chrome" / "resources" / "peekafoxy.sys.mjs").is_file()


def test_other_scripts_and_resources_in_the_profile_are_left_alone(profile: Path):
    (profile / "chrome" / "resources").mkdir()
    (profile / "chrome" / "resources" / "userChrome.au.css").write_text("/* theirs */\n")
    (profile / "chrome" / "JS").mkdir()
    (profile / "chrome" / "JS" / "other.uc.js").write_text("// theirs\n")
    install(profile)
    plan_uninstall(profile).execute()
    assert (profile / "chrome" / "resources" / "userChrome.au.css").read_text() == "/* theirs */\n"
    assert (profile / "chrome" / "JS" / "other.uc.js").read_text() == "// theirs\n"
