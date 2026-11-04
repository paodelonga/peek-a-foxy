from pathlib import Path

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
    first = {p: p.read_text() for p in profile.rglob("*") if p.is_file()}
    install(profile)
    assert {p: p.read_text() for p in profile.rglob("*") if p.is_file()} == first


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
