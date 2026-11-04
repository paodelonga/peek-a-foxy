"""Behavior checks in a real Firefox: what the CSS and the script actually do to the window."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

KEYDOWN = """
  window.dispatchEvent(new KeyboardEvent('keydown',
    {code: arguments[0], ctrlKey: true, altKey: true, bubbles: true, cancelable: true}));
"""
HAS = "document.documentElement.hasAttribute(arguments[0])"


def press(browser, code: str) -> None:
    browser.js(KEYDOWN, code)


# --- loading -----------------------------------------------------------------------------------


def test_the_loader_runs_the_script_and_registers_both_buttons(browser):
    assert browser.js("return typeof UC_API;") == "object"
    for button in ("tabs-autohide-button", "urlbar-autohide-button"):
        assert browser.js("return !!document.getElementById(arguments[0]);", button)


def test_everything_starts_off(browser):
    assert browser.initial["attrs"] == []


# --- the greeting ------------------------------------------------------------------------------


def test_the_greeting_is_shown_once_in_the_firefox_language(browser):
    # fx-autoconfig shows a notification of its own the first time it loads; only ours counts here.
    notes = [n for n in browser.initial["notifications"] if n["value"] == "peekafoxy-welcome"]
    assert len(notes) == 1
    assert notes[0]["text"] == "Instaalleeeeed PEEK A BOO!!! >.<"
    assert notes[0]["buttons"] == ["Peek-a-boo!"]
    assert browser.js("return Services.prefs.getBoolPref('peekafoxy.welcomed', false);")


def test_the_greeting_button_opens_the_song_without_errors(browser):
    browser.switch_to(browser.first_window)
    before = browser.js("return gBrowser.tabs.length;")
    browser.js(
        "document.querySelector('notification-message[value=peekafoxy-welcome] "
        "button.notification-button').click();"
    )
    browser.wait(f"gBrowser.tabs.length === {before + 1}", message="the button opened no tab")
    browser.wait(
        "[...gBrowser.tabs].some(t => t.linkedBrowser.currentURI.spec.includes('6uJf2IT2Zh8'))",
        message="the new tab did not go to the song",
    )
    errors = browser.js(
        """return Services.console.getMessageArray().map(m => String(m.message))
             .filter(m => /openWebLinkIn|autohide\\.uc\\.js/.test(m));"""
    )
    assert errors == []


def test_a_second_window_does_not_greet_again(browser):
    browser.new_window()
    ours = browser.js(
        "return [...window.gNotificationBox.allNotifications]"
        ".filter(n => n.getAttribute('value') === 'peekafoxy-welcome').length;"
    )
    assert ours == 0


# --- toggles are per window ---------------------------------------------------------------------


def test_shortcuts_toggle_only_their_own_window(browser):
    first = browser.first_window
    second = browser.new_window()
    browser.switch_to(first)
    press(browser, "KeyT")
    assert browser.js(f"return {HAS};", "autohide-tabs")
    browser.switch_to(second)
    assert not browser.js(f"return {HAS};", "autohide-tabs")
    browser.switch_to(first)
    press(browser, "KeyT")  # leave it as we found it
    assert not browser.js(f"return {HAS};", "autohide-tabs")


def test_the_state_is_saved_with_the_window(browser):
    browser.new_window()
    press(browser, "KeyU")
    assert browser.js("return SessionStore.getCustomWindowValue(window, 'autohideUrlbar');") == "1"
    press(browser, "KeyU")
    assert browser.js("return SessionStore.getCustomWindowValue(window, 'autohideUrlbar');") == "0"


def test_the_toolbar_button_toggles_its_window(browser):
    browser.new_window()
    browser.js("document.getElementById('tabs-autohide-button').click();")
    assert browser.js(f"return {HAS};", "autohide-tabs")
    browser.js("document.getElementById('tabs-autohide-button').click();")
    assert not browser.js(f"return {HAS};", "autohide-tabs")


# --- the tab bar -------------------------------------------------------------------------------


def test_tab_bar_collapses_to_the_strip_and_opens_to_its_full_height(browser):
    browser.new_window()
    natural = browser.settled_heights()["tabs"]
    press(browser, "KeyT")
    browser.wait("document.getElementById('TabsToolbar').getBoundingClientRect().height <= 8", 5)
    browser.js("document.documentElement.setAttribute('tabs-flash', '');")
    browser.wait(
        f"Math.round(document.getElementById('TabsToolbar').getBoundingClientRect().height)"
        f" === {natural}",
        5,
        "the tab bar did not open to its natural height",
    )
    # Nothing is clipped: the toolbar shows all of its content.
    assert browser.js(
        "const t = document.getElementById('TabsToolbar'); return t.scrollHeight <= t.clientHeight;"
    )
    browser.js("document.documentElement.removeAttribute('tabs-flash');")


def test_opening_a_tab_reveals_the_tab_bar_briefly(browser):
    browser.new_window()
    press(browser, "KeyT")
    browser.js(
        "gBrowser.addTab('about:blank', {triggeringPrincipal: "
        "Services.scriptSecurityManager.getSystemPrincipal()});"
    )
    browser.wait(f"{HAS.replace('arguments[0]', repr('tabs-flash'))}", 3, "no flash on tab open")
    browser.wait(f"!{HAS.replace('arguments[0]', repr('tabs-flash'))}", 5, "the flash never ended")
    press(browser, "KeyT")


# --- the navigation bar and the bookmarks bar ---------------------------------------------------


def test_navbar_and_bookmarks_bar_hide_and_show_together(browser):
    browser.new_window()
    browser.js("CustomizableUI.setToolbarVisibility('PersonalToolbar', true);")
    browser.wait("document.getElementById('PersonalToolbar').getBoundingClientRect().height > 0", 5)
    normal = browser.settled_heights()

    press(browser, "KeyU")
    browser.wait(
        "document.getElementById('nav-bar').getBoundingClientRect().height <= 8"
        " && document.getElementById('PersonalToolbar').getBoundingClientRect().height === 0",
        8,
        "the navigation bar and the bookmarks bar did not both collapse",
    )

    browser.js("gURLBar.focus();")  # Ctrl+L and friends focus the urlbar
    browser.wait(
        f"Math.round(document.getElementById('nav-bar').getBoundingClientRect().height)"
        f" === {normal['nav']}",
        5,
        "the navigation bar did not open on focus",
    )
    browser.wait(
        f"Math.round(document.getElementById('PersonalToolbar').getBoundingClientRect().height) "
        f"=== {normal['bookmarks']}",
        5,
        "the bookmarks bar did not open with the navigation bar",
    )

    browser.js("gBrowser.selectedBrowser.focus();")
    browser.wait(
        "document.getElementById('PersonalToolbar').getBoundingClientRect().height === 0", 8
    )
    press(browser, "KeyU")
    browser.wait(
        f"Math.round(document.getElementById('PersonalToolbar').getBoundingClientRect().height) "
        f"=== {normal['bookmarks']}",
        5,
        "turning autohide off did not restore the bookmarks bar",
    )
    browser.js("CustomizableUI.setToolbarVisibility('PersonalToolbar', false);")


def test_a_bookmarks_bar_the_user_turned_off_stays_off(browser):
    browser.new_window()
    browser.js("CustomizableUI.setToolbarVisibility('PersonalToolbar', false);")
    press(browser, "KeyU")
    browser.js("gURLBar.focus();")
    browser.wait(
        "Math.round(document.getElementById('nav-bar').getBoundingClientRect().height) >= 30", 5
    )
    assert browser.js(
        "const bar = document.getElementById('PersonalToolbar');"
        " return bar.getBoundingClientRect().height === 0"
        " || getComputedStyle(bar).visibility === 'collapse';"
    )
    press(browser, "KeyU")


# --- modes where the bars must stay out of the way ---------------------------------------------


def test_customize_toolbar_shows_the_bars_in_full(browser):
    browser.new_window()
    natural = browser.settled_heights()
    press(browser, "KeyT")
    press(browser, "KeyU")
    browser.wait("document.getElementById('nav-bar').getBoundingClientRect().height <= 8", 8)
    browser.js("gCustomizeMode.enter();")
    try:
        browser.wait("document.documentElement.hasAttribute('customizing')", 15, "never entered")
        browser.wait(
            f"Math.round(document.getElementById('nav-bar').getBoundingClientRect().height)"
            f" === {natural['nav']}",
            8,
            "the navigation bar stayed collapsed in Customize Toolbar",
        )
    finally:
        browser.js("gCustomizeMode.exit();")
        browser.wait("!document.documentElement.hasAttribute('customizing')", 15)
    press(browser, "KeyT")
    press(browser, "KeyU")


def test_full_screen_is_left_to_firefox(browser):
    browser.new_window()
    natural = browser.settled_heights()
    press(browser, "KeyU")
    browser.wait("document.getElementById('nav-bar').getBoundingClientRect().height <= 8", 8)
    browser.js("window.fullScreen = true;")
    try:
        browser.wait(
            "document.documentElement.hasAttribute('inFullscreen')", 15, "never went full screen"
        )
        browser.wait(
            f"Math.round(document.getElementById('nav-bar').getBoundingClientRect().height)"
            f" === {natural['nav']}",
            8,
            "our rules still applied in full screen",
        )
    finally:
        browser.js("window.fullScreen = false;")
        browser.wait("!document.documentElement.hasAttribute('inFullscreen')", 15)
    press(browser, "KeyU")


# --- the prefs ------------------------------------------------------------------------------------


def test_prefs_are_listed_as_booleans_without_being_written_anywhere(browser):
    for name in ("peekafoxy.tabs.autohide", "peekafoxy.urlbar.autohide"):
        info = browser.js(
            """const p = Services.prefs;
               return {type: p.getPrefType(arguments[0]) === p.PREF_BOOL,
                       userValue: p.prefHasUserValue(arguments[0]),
                       value: p.getBoolPref(arguments[0])};""",
            name,
        )
        assert info == {"type": True, "userValue": False, "value": False}, name


def test_a_pref_with_the_wrong_type_does_not_break_the_script(browser_with_a_bad_pref):
    b = browser_with_a_bad_pref
    assert b.js("return !!document.getElementById('urlbar-autohide-button');")
    assert b.initial["attrs"] == []  # fell back to "off"
    b.new_window()
    press(b, "KeyU")
    assert b.js(f"return {HAS};", "autohide-urlbar")  # still fully functional
    press(b, "KeyU")
