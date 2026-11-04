from pathlib import Path

from peek_a_foxy import userfiles as uf
from peek_a_foxy.installer import plan_install, plan_uninstall


def install(profile: Path, firefox_dir: Path | None = None) -> list[str]:
    return plan_install(profile, firefox_dir).execute()


def test_fresh_install_without_loader(profile: Path):
    install(profile)
    assert (profile / "chrome" / "autohide.css").is_file()
    assert (profile / "chrome" / "JS" / "autohide.uc.js").is_file()
    assert (profile / "chrome" / "userChrome.css").read_text() == uf.CSS_IMPORT + "\n"
    # Only the pref Firefox needs. The autohide prefs stay out of user.js, which is re-applied on
    # every start and would undo changes made in about:config; a missing pref means "off".
    assert (profile / "user.js").read_text() == (
        'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
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
    assert not (chrome / "JS" / "autohide.uc.js").exists()
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
