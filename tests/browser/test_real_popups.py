"""Real popups, real focus keys and the show delay: what the older tests set by hand.

The popup markers, the tab context menu and the show delay are tested elsewhere with attributes
written by the test. These open the real thing (the application menu, a permission notification,
the tab's context menu) and press the real keys, with the native title bar and with the one Firefox
draws itself.
"""

from __future__ import annotations

import pytest
from marionette_driver.keys import Keys
from test_pointer import (  # noqa: F401  (first_window_again is an autouse fixture there)
    NAV_HEIGHT,
    ROOT,
    collapsed_window,
    first_window_again,
    stays,
    variants,
)

pytestmark = pytest.mark.browser

LONG_DELAY = 3000  # ms: far longer than anything a reveal that skips the delay needs
WITHIN = 1.8  # s: a reveal that skips the delay is done long before this
SET_DELAY = f"Services.prefs.setIntPref('peekafoxy.show.delay.ms', {LONG_DELAY});"
MARKER = f"return {ROOT}.getAttribute('peekafoxy-popup-open');"

OPEN_APP_MENU = "PanelUI.show();"
CLOSE_APP_MENU = "PanelUI.hide();"
OPEN_NOTIFICATION = """
  PopupNotifications.show(
    gBrowser.selectedBrowser, 'peekafoxy-test', 'A message for the test', null,
    {label: 'OK', accessKey: 'O', callback() {}}, null, {persistent: true});
"""
CLOSE_NOTIFICATION = """
  const n = PopupNotifications.getNotification('peekafoxy-test', gBrowser.selectedBrowser);
  if (n) PopupNotifications.remove(n);
"""
OPEN_TAB_MENU = """
  const tab = gBrowser.selectedTab;
  const r = tab.getBoundingClientRect();
  const event = new MouseEvent('contextmenu', {
    bubbles: true, cancelable: true, button: 2,
    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
    screenX: window.screenX + r.left + r.width / 2, screenY: window.screenY + r.top + r.height / 2,
  });
  tab.dispatchEvent(event);
  document.getElementById('tabContextMenu')
    .openPopupAtScreen(event.screenX, event.screenY, true, event);
"""
CLOSE_TAB_MENU = "document.getElementById('tabContextMenu').hidePopup();"
TAB_MENU_OPEN = "['open', 'showing'].includes(document.getElementById('tabContextMenu').state)"


def delay_is_set(browser) -> None:
    browser.js(SET_DELAY)
    browser.wait(
        f"{ROOT}.style.getPropertyValue('--autohide-show-delay') === '{LONG_DELAY}ms'",
        5,
        "the pref did not reach the CSS variable",
    )


# --- the show delay is only for the pointer ------------------------------------------------------


@variants
@pytest.mark.parametrize(
    ("key", "modifiers"),
    [("l", (Keys.CONTROL,)), ("d", (Keys.ALT,)), (Keys.F6, ()), ("k", (Keys.CONTROL,))],
    ids=["ctrl-l", "alt-d", "f6", "ctrl-k"],
)
def test_the_real_focus_keys_do_not_wait_for_the_show_delay(
    browser, customtitlebar, key, modifiers
):
    """Adversarial: with a 3 s delay the pointer has to rest for 3 s, a focus key must not."""
    with collapsed_window(browser, customtitlebar) as natural:
        delay_is_set(browser)
        browser.js("window.focus(); gBrowser.selectedBrowser.focus();")
        browser.real_keys(key, *modifiers)
        browser.wait(
            f"{NAV_HEIGHT} === {natural['nav']}", WITHIN, "the focus key waited for the show delay"
        )


@variants
def test_a_tab_switch_flash_does_not_wait_for_the_show_delay(browser, customtitlebar):
    """Adversarial: the tab bar that opens for a moment after a switch is not a pointer."""
    with collapsed_window(browser, customtitlebar) as natural:
        delay_is_set(browser)
        browser.js(
            "gBrowser.addTab('about:blank', {inBackground: true,"
            " triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});"
            f"{ROOT}.removeAttribute('tabs-flash');"
            "gBrowser.selectedTab = gBrowser.tabs[1];"
        )
        browser.wait(
            f"{browser.TABS_HEIGHT} === {natural['tabs']}",
            WITHIN,
            "the flash waited for the show delay",
        )
        browser.js("gBrowser.removeTab(gBrowser.tabs[1]);")


@variants
def test_a_real_popup_does_not_wait_for_the_show_delay(browser, customtitlebar):
    """Adversarial: the application menu belongs to the navigation bar and opens it at once."""
    with collapsed_window(browser, customtitlebar) as natural:
        delay_is_set(browser)
        browser.js(OPEN_APP_MENU)
        try:
            browser.wait(
                f"{NAV_HEIGHT} === {natural['nav']}",
                WITHIN,
                "the application menu waited for the show delay",
            )
        finally:
            browser.js(CLOSE_APP_MENU)


# --- the real popups keep their bar open ---------------------------------------------------------


@variants
def test_the_real_application_menu_keeps_the_navigation_bar_open_until_it_closes(
    browser, customtitlebar
):
    with collapsed_window(browser, customtitlebar) as natural:
        browser.js(OPEN_APP_MENU)
        try:
            browser.wait(f"{NAV_HEIGHT} === {natural['nav']}", 8, "the menu did not open the bar")
            assert "navbar" in (browser.js(MARKER) or "")
            stays(
                browser, f"{NAV_HEIGHT} === {natural['nav']}", "the bar closed under the menu", 1.2
            )
        finally:
            browser.js(CLOSE_APP_MENU)
        browser.wait(f"{NAV_HEIGHT} <= 8", 8, "the bar stayed open after the menu closed")
        assert not browser.js(MARKER)


@variants
def test_a_real_permission_notification_keeps_the_navigation_bar_open_until_it_goes(
    browser, customtitlebar
):
    with collapsed_window(browser, customtitlebar) as natural:
        browser.js(OPEN_NOTIFICATION)
        try:
            browser.wait(
                f"{NAV_HEIGHT} === {natural['nav']}", 8, "the notification did not open the bar"
            )
            stays(browser, f"{NAV_HEIGHT} === {natural['nav']}", "the bar closed under it", 1.2)
        finally:
            browser.js(CLOSE_NOTIFICATION)
        browser.wait(f"{NAV_HEIGHT} <= 8", 8, "the bar stayed open after the notification went")


# --- the tab's own context menu, as a person opens it --------------------------------------------


@variants
def test_the_real_tab_context_menu_keeps_the_tab_bar_open_until_it_closes(browser, customtitlebar):
    """The older test writes the menu's state attribute by hand; this one opens the menu."""
    with collapsed_window(browser, customtitlebar) as natural:
        browser.js(OPEN_TAB_MENU)
        try:
            browser.wait(TAB_MENU_OPEN, 8, "the tab context menu did not open")
            browser.wait(
                f"{browser.TABS_HEIGHT} === {natural['tabs']}",
                8,
                "the tab bar did not open for its menu",
            )
            stays(
                browser,
                f"{browser.TABS_HEIGHT} === {natural['tabs']}",
                "the tab bar closed under its menu",
                1.2,
            )
        finally:
            browser.js(CLOSE_TAB_MENU)
        browser.wait(f"{browser.TABS_HEIGHT} <= 8", 8, "the tab bar stayed open after the menu")


# --- a window that is not in front (decided in #88) ----------------------------------------------


@variants
def test_the_navigation_bar_of_a_window_that_is_not_in_front_stays_hidden(browser, customtitlebar):
    """The decision of #88: a window that is not in front gives its bar back, although its address
    bar still holds the focus, so that two windows side by side do not keep a bar open."""
    with collapsed_window(browser, customtitlebar) as natural:
        window_a = browser.client.current_chrome_window_handle
        browser.js("window.focus(); gURLBar.focus();")
        browser.wait(f"{NAV_HEIGHT} === {natural['nav']}", 5, "the focus did not open the bar")

        browser.new_window()  # takes the front
        browser.client.switch_to_window(window_a, focus=False)  # read A without bringing it back
        browser.wait(f"{NAV_HEIGHT} <= 8", 8, "the bar of the window behind stayed open")
        assert browser.js("return gURLBar.focused;"), "the address bar lost the focus: not the case"
        stays(browser, f"{NAV_HEIGHT} <= 8", "the bar of the window behind opened again", 1.0)
