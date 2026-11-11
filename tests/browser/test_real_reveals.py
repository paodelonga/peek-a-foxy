"""Reveals that the other tests set by hand: the real keys, and the modes that leave the bars alone.

They run with the native title bar and with the one Firefox draws itself (see test_pointer.py), on
the three bars where it matters. The focus keys are pressed through Firefox's own key handling
(``Browser.real_keys``), as a person would.
"""

from __future__ import annotations

import pytest
from marionette_driver.keys import Keys
from test_pointer import (  # noqa: F401  (first_window_again is an autouse fixture there)
    BOOKMARKS_HEIGHT,
    NAV_HEIGHT,
    ROOT,
    collapsed_window,
    first_window_again,
    variants,
)

pytestmark = pytest.mark.browser

FOCUS_KEYS = pytest.mark.parametrize(
    ("key", "modifiers"),
    [
        ("l", (Keys.CONTROL,)),
        ("d", (Keys.ALT,)),
        (Keys.F6, ()),
        ("k", (Keys.CONTROL,)),
    ],
    ids=["ctrl-l", "alt-d", "f6", "ctrl-k"],
)


@variants
@FOCUS_KEYS
def test_the_real_focus_keys_open_the_navigation_bar_and_it_closes_when_the_focus_leaves(
    browser, customtitlebar, key, modifiers
):
    """Default path, real keys: Ctrl+L, Alt+D, F6 and Ctrl+K put the focus in the address bar, which
    keeps the bar open; moving the focus back to the page lets it collapse."""
    with collapsed_window(browser, customtitlebar) as natural:
        browser.js("window.focus(); gBrowser.selectedBrowser.focus();")
        browser.real_keys(key, *modifiers)
        browser.wait(f"{NAV_HEIGHT} === {natural['nav']}", 5, "the key did not open the bar")
        assert browser.js(
            "return !!document.activeElement?.closest('#nav-bar') || gURLBar.focused;"
        ), "the focus is not in the navigation bar"
        browser.js("gBrowser.selectedBrowser.focus();")
        browser.wait(f"{NAV_HEIGHT} <= 8", 8, "the bar did not close after the focus left")


@variants
def test_customize_toolbar_shows_all_three_bars_in_full(browser, customtitlebar):
    """Adversarial: the older test only looks at the navigation bar. With everything hidden and the
    bookmarks bar on, Customize Toolbar shows the tab bar, the navigation bar and the bookmarks
    bar."""
    with collapsed_window(browser, customtitlebar, bookmarks=True) as natural:
        browser.js("gCustomizeMode.enter();")
        try:
            browser.wait(
                "document.documentElement.hasAttribute('customizing')", 15, "never entered"
            )
            browser.wait(
                f"{browser.TABS_HEIGHT} === {natural['tabs']} && {NAV_HEIGHT} === {natural['nav']}"
                f" && {BOOKMARKS_HEIGHT} === {natural['bookmarks']}",
                8,
                "a bar stayed collapsed in Customize Toolbar",
            )
        finally:
            browser.js("gCustomizeMode.exit();")
            browser.wait("!document.documentElement.hasAttribute('customizing')", 15)


@variants
def test_full_screen_leaves_all_three_bars_to_firefox(browser, customtitlebar):
    """Adversarial: our rules do not apply in full screen to any bar."""
    with collapsed_window(browser, customtitlebar, bookmarks=True):
        browser.js("window.fullScreen = true;")
        try:
            browser.wait(
                "document.documentElement.hasAttribute('inFullscreen')",
                15,
                "never went full screen",
            )
            # Firefox lays the bars out its own way in full screen (other heights, and it hides the
            # bookmarks bar itself), so compare with what our rules do, not with the usual heights.
            browser.wait(
                f"{browser.TABS_HEIGHT} > 30 && {NAV_HEIGHT} > 30 && "
                "getComputedStyle(document.getElementById('PersonalToolbar')).maxHeight !== '0px'",
                8,
                "our rules still applied in full screen",
            )
        finally:
            browser.js("window.fullScreen = false;")
            browser.wait("!document.documentElement.hasAttribute('inFullscreen')", 15)
        assert browser.js(f"return {ROOT}.hasAttribute('autohide-urlbar');")  # the state is kept
