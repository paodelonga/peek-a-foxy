"""The state of each bar is saved with its window and comes back with a restored session.

SessionStore does not know a window while it starts ("Window is not tracked"), and a window that is
restored only gets its saved values later, when its state has been restored. These tests run a real
Firefox through a quit and a restart, and also feed the script a SessionStore that misbehaves.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import launched

pytestmark = pytest.mark.browser

HAS = "return document.documentElement.hasAttribute(arguments[0]);"
SAVED = "return SessionStore.getCustomWindowValue(window, arguments[0]);"
RESTORE_SESSION = 'user_pref("browser.startup.page", 3);\n'  # "open previous windows and tabs"


def toggle(browser, which: str) -> None:
    browser.js(f"document.getElementById('{which}-autohide-button').click();")


def states(browser) -> set[tuple[bool, bool]]:
    """(tab bar hidden, navigation bar hidden) of every window that is open."""
    found = set()
    for handle in browser.client.chrome_window_handles:
        browser.switch_to(handle)
        found.add(
            (
                browser.js(HAS, "autohide-tabs"),
                browser.js(HAS, "autohide-urlbar"),
            )
        )
    return found


def wait_for_states(browser, expected: set[tuple[bool, bool]], windows: int, timeout=40.0) -> None:
    deadline = time.monotonic() + timeout
    last: set[tuple[bool, bool]] = set()
    while time.monotonic() < deadline:
        if len(browser.client.chrome_window_handles) == windows:
            last = states(browser)
            if last == expected:
                return
        time.sleep(0.3)
    raise AssertionError(
        f"windows={len(browser.client.chrome_window_handles)} states={last}, wanted {expected}"
    )


def events(browser) -> list[dict]:
    browser.flush()
    return json.loads(browser.wait_for_status_file().read_text(encoding="utf-8"))["errors"]


def tracking_noise(found: list[dict]) -> list[dict]:
    return [e for e in found if e["where"] in ("autohide:state", "autohide:session")]


def quit_with_saved_session(browser) -> Path:
    """Wait until both values are saved with the window, then quit the way a person does."""
    profile = browser.profile
    browser.quit_gracefully()
    return profile


# --- a restored session brings the states back -------------------------------------------------


def test_a_restored_window_gets_its_saved_state_and_a_second_one_its_own(firefox_install, tmp_path):
    with launched(firefox_install, tmp_path, RESTORE_SESSION) as browser:
        toggle(browser, "tabs")  # the first window: tab bar hidden
        browser.new_window()
        toggle(browser, "urlbar")  # the second: navigation bar hidden
        for handle in browser.client.chrome_window_handles:
            browser.switch_to(handle)
            browser.wait(
                "SessionStore.getCustomWindowValue(window, 'autohideTabs') !== '' && "
                "SessionStore.getCustomWindowValue(window, 'autohideUrlbar') !== ''"
            )
        profile = quit_with_saved_session(browser)

    with launched(firefox_install, tmp_path, existing_profile=profile) as again:
        wait_for_states(again, {(True, False), (False, True)}, windows=2)
        # The window with the hidden tab bar really is collapsed, not just flagged.
        for handle in again.client.chrome_window_handles:
            again.switch_to(handle)
            if again.js(HAS, "autohide-tabs"):
                again.wait(f"{again.TABS_HEIGHT} <= 8", 15, "the restored tab bar did not collapse")
        assert tracking_noise(events(again)) == []


def test_a_saved_off_beats_a_default_that_is_on(firefox_install, tmp_path):
    """A bar turned off in a window stays off after a restart, whatever the pref says."""
    on = RESTORE_SESSION + 'user_pref("peekafoxy.tabs.autohide", true);\n'
    with launched(firefox_install, tmp_path, on) as browser:
        browser.wait(f"{browser.TABS_HEIGHT} <= 8", 10, "the default (on) did not apply")
        toggle(browser, "tabs")  # off, saved as "0"
        browser.wait("SessionStore.getCustomWindowValue(window, 'autohideTabs') === '0'")
        profile = quit_with_saved_session(browser)

    with launched(firefox_install, tmp_path, existing_profile=profile) as again:
        wait_for_states(again, {(False, False)}, windows=1)
        time.sleep(1.5)  # and it stays that way once everything has settled
        assert states(again) == {(False, False)}


def test_a_saved_on_beats_a_default_that_is_off(firefox_install, tmp_path):
    with launched(firefox_install, tmp_path, RESTORE_SESSION) as browser:
        toggle(browser, "urlbar")
        browser.wait("SessionStore.getCustomWindowValue(window, 'autohideUrlbar') === '1'")
        profile = quit_with_saved_session(browser)
    with launched(firefox_install, tmp_path, existing_profile=profile) as again:
        wait_for_states(again, {(False, True)}, windows=1)


def test_a_restored_window_that_has_no_saved_state_uses_the_default_and_saves_it(
    firefox_install, tmp_path
):
    """A session written before this script existed (or by another tool): no values at all."""
    on = RESTORE_SESSION + 'user_pref("peekafoxy.urlbar.autohide", true);\n'
    with launched(firefox_install, tmp_path, on) as browser:
        browser.js(
            "SessionStore.deleteCustomWindowValue(window, 'autohideTabs');"
            "SessionStore.deleteCustomWindowValue(window, 'autohideUrlbar');"
        )
        profile = quit_with_saved_session(browser)
    with launched(firefox_install, tmp_path, existing_profile=profile) as again:
        wait_for_states(again, {(False, True)}, windows=1)
        again.wait(
            "SessionStore.getCustomWindowValue(window, 'autohideUrlbar') === '1' && "
            "SessionStore.getCustomWindowValue(window, 'autohideTabs') === '0'",
            10,
            "the defaults were not saved with the restored window",
        )


# --- a new window saves its state from the start -----------------------------------------------


def test_a_new_window_saves_its_state_without_any_toggle_and_logs_nothing_about_it(
    firefox_install, tmp_path
):
    on = 'user_pref("peekafoxy.tabs.autohide", true);\n'
    with launched(firefox_install, tmp_path, on) as browser:
        browser.wait(
            "SessionStore.getCustomWindowValue(window, 'autohideTabs') === '1'",
            10,
            "the first window did not save its state",
        )
        assert browser.js(SAVED, "autohideUrlbar") == "0"
        browser.new_window()
        browser.wait("SessionStore.getCustomWindowValue(window, 'autohideTabs') === '1'", 10)
        assert browser.js(SAVED, "autohideUrlbar") == "0"
        assert tracking_noise(events(browser)) == []  # nothing is "expected to fail" any more


def test_a_toggle_in_the_first_moments_is_not_lost(firefox_install, tmp_path):
    """A shortcut can arrive while the window is still starting: it is saved like any other."""
    with launched(firefox_install, tmp_path) as browser:
        handle = browser.new_window()
        toggle(browser, "tabs")
        browser.wait("SessionStore.getCustomWindowValue(window, 'autohideTabs') === '1'", 10)
        time.sleep(1)
        assert browser.js(HAS, "autohide-tabs") and browser.js(SAVED, "autohideTabs") == "1"
        assert handle in browser.client.chrome_window_handles


# --- the script meets a SessionStore that misbehaves -------------------------------------------

# The script's own SessionStore is replaced by a local one (the real one is frozen in Firefox ESR,
# and Firefox itself needs it to start), so only this script sees it.
FAKE = """
    Peek.registerDefaults();
    window.__calls = {get: 0, set: 0};
    const SessionStore = {
      getCustomWindowValue: () => { window.__calls.get++; throw new Error(%(error)s); },
      setCustomWindowValue: () => { window.__calls.set++; throw new Error(%(error)s); },
    };
"""
KEYDOWN = """
  window.dispatchEvent(new KeyboardEvent('keydown',
    {code: arguments[0], ctrlKey: true, altKey: true, bubbles: true, cancelable: true}));
"""


def with_fake_store(error: str):
    def edit(source: str) -> str:
        if "@include        main" not in source:
            return source
        assert source.count("Peek.registerDefaults();") == 1
        return source.replace("Peek.registerDefaults();", FAKE % {"error": json.dumps(error)})

    return edit


def test_a_window_that_is_never_tracked_is_retried_a_bounded_number_of_times(
    firefox_install, tmp_path
):
    with launched(
        firefox_install,
        tmp_path,
        'user_pref("peekafoxy.tabs.autohide", true);\n',
        edit_script=with_fake_store("Window is not tracked"),
    ) as browser:
        time.sleep(3.5)  # the retries last about two seconds
        calls = browser.js("return {...window.__calls};")
        time.sleep(1.5)
        assert browser.js("return {...window.__calls};") == calls  # it gave up
        assert 1 <= calls["get"] <= 100 and calls["set"] == 0
        assert browser.js(HAS, "autohide-tabs")  # the pref default stands
        assert tracking_noise(events(browser)) == []  # being untracked is not worth a mention
        # The shortcut still works; the failure to save is reported once and is not fatal.
        browser.js(KEYDOWN, "KeyT")
        assert not browser.js(HAS, "autohide-tabs")
        warned = [e["where"] for e in events(browser) if e["level"] == "warn"]
        assert warned.count("autohide:session") == 1


def test_any_other_failure_of_the_session_store_is_reported_and_does_not_retry(
    firefox_install, tmp_path
):
    with launched(
        firefox_install, tmp_path, edit_script=with_fake_store("something else broke")
    ) as browser:
        time.sleep(3)
        calls = browser.js("return {...window.__calls};")
        assert calls["get"] == 2  # once per bar, no retry loop for an unrelated error
        warned = [e for e in events(browser) if e["where"] == "autohide:state"]
        assert warned and warned[0]["level"] == "warn"
        assert not browser.js(HAS, "autohide-tabs")  # the window is fine, on its defaults
        assert browser.js("return document.getElementById('tabs-autohide-button') !== null")


def test_a_saved_value_that_is_not_one_of_ours_is_ignored(browser):
    browser.new_window()
    browser.js("SessionStore.setCustomWindowValue(window, 'autohideTabs', 'banana');")
    browser.js("window.dispatchEvent(new Event('SSWindowStateReady'));")
    assert not browser.js(HAS, "autohide-tabs")
    assert browser.js(SAVED, "autohideTabs") == "banana"  # not ours to overwrite either


def test_every_restored_window_state_is_applied_again(browser):
    """Undo close window, restore previous session: the event arrives again and again."""
    browser.new_window()
    for value, expected in (("1", True), ("0", False), ("1", True)):
        browser.js(
            "SessionStore.setCustomWindowValue(window, 'autohideTabs', arguments[0]);", value
        )
        browser.js("window.dispatchEvent(new Event('SSWindowStateReady'));")
        assert browser.js(HAS, "autohide-tabs") is expected
    browser.js("document.getElementById('tabs-autohide-button').click();")  # back to off
    assert browser.js(SAVED, "autohideTabs") == "0"


def test_a_window_closed_while_it_is_starting_leaves_no_error_behind(browser):
    before = len(browser.client.chrome_window_handles)
    handle = browser.new_window()
    browser.js("window.close();")
    time.sleep(1.5)  # long enough for every retry of the closed window to have come and gone
    browser.switch_to(browser.first_window)
    assert len(browser.client.chrome_window_handles) == before
    assert handle not in browser.client.chrome_window_handles
    assert [
        e for e in events(browser) if e["level"] == "error" and e["where"].startswith("autohide")
    ] == []
