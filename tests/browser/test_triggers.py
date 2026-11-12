"""What opens the tab bar for a moment: switching tabs, opening one, a link opening one."""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.browser

REVEALS = ("switch", "new", "link")
URL = "https://example.invalid/triggers"  # never loaded: only the address matters
HAS_FLASH = "return document.documentElement.hasAttribute('tabs-flash');"

# Each action, and the reveal pref that decides whether it opens the bar.
ACTIONS = {
    "switch": ("switch", "gBrowser.selectedTab = gBrowser.tabs[0];"),
    "new tab, selected": ("new", "BrowserCommands.openTab();"),
    "new tab, background": ("new", "gBrowser.addTrustedTab('about:newtab', {inBackground: true});"),
    "link, selected": ("link", f"openTrustedLinkIn('{URL}', 'tab', {{relatedToCurrent: true}});"),
    "link, background": (
        "link",
        f"openTrustedLinkIn('{URL}', 'tab', {{inBackground: true, relatedToCurrent: true}});",
    ),
}


def set_reveals(browser, **values: bool) -> None:
    for name, value in values.items():
        browser.js(
            "Services.prefs.setBoolPref('peekafoxy.tabs.reveal.' + arguments[0], arguments[1]);",
            name,
            value,
        )


@pytest.fixture(autouse=True)
def clean(browser):
    def reset() -> None:
        browser.switch_to(browser.first_window)
        browser.js(
            """for (const name of Services.prefs.getChildList('peekafoxy.tabs.')) {
                 Services.prefs.clearUserPref(name);
               }
               for (const tab of [...gBrowser.tabs].slice(1)) gBrowser.removeTab(tab);
               document.documentElement.removeAttribute('tabs-flash');"""
        )

    reset()
    browser.js("Services.prefs.setIntPref('peekafoxy.tabs.flash.ms', 4000);")
    yield
    reset()


def expect_flash(browser, expected: bool, what: str) -> None:
    if expected:
        browser.wait("document.documentElement.hasAttribute('tabs-flash')", 5, f"no flash: {what}")
    else:
        time.sleep(0.7)  # the decision is taken one tick after the tab opens
        assert not browser.js(HAS_FLASH), f"unexpected flash: {what}"


def run(browser, action: str, **reveals: bool) -> None:
    """Set the three reveal prefs, make sure there is a second tab to switch to, and act."""
    set_reveals(browser, switch=False, new=False, link=False)
    browser.js("gBrowser.addTrustedTab('about:blank');")  # a second tab, selected: no flash
    browser.js("gBrowser.selectedTab = gBrowser.tabs[gBrowser.tabs.length - 1];")
    time.sleep(0.3)
    set_reveals(browser, **reveals)
    browser.js("document.documentElement.removeAttribute('tabs-flash');")
    browser.js(ACTIONS[action][1])


@pytest.mark.parametrize("action", list(ACTIONS))
def test_every_trigger_opens_the_bar_by_default(browser, action):
    browser.js("gBrowser.addTrustedTab('about:blank');")
    browser.js("gBrowser.selectedTab = gBrowser.tabs[gBrowser.tabs.length - 1];")
    time.sleep(0.5)
    browser.js("document.documentElement.removeAttribute('tabs-flash');")
    browser.js(ACTIONS[action][1])
    expect_flash(browser, True, action)


@pytest.mark.parametrize("action", list(ACTIONS))
def test_a_trigger_that_is_off_does_not_open_the_bar_even_if_the_others_are_on(browser, action):
    own = ACTIONS[action][0]
    run(browser, action, **{name: name != own for name in REVEALS})
    expect_flash(browser, False, f"{action} with only '{own}' turned off")


@pytest.mark.parametrize("action", list(ACTIONS))
def test_a_trigger_that_is_on_opens_the_bar_even_if_the_others_are_off(browser, action):
    own = ACTIONS[action][0]
    run(browser, action, **{name: name == own for name in REVEALS})
    expect_flash(browser, True, f"{action} with only '{own}' turned on")


def test_with_everything_off_nothing_opens_the_bar(browser):
    for action in ACTIONS:
        run(browser, action, switch=False, new=False, link=False)
        expect_flash(browser, False, action)


def test_the_new_tab_page_and_the_home_page_count_as_a_tab_you_opened(browser):
    set_reveals(browser, switch=False, new=True, link=False)
    for address in ("about:newtab", "about:home", "about:blank"):
        browser.js("document.documentElement.removeAttribute('tabs-flash');")
        browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", address)
        expect_flash(browser, True, address)


def test_any_other_address_counts_as_a_link(browser):
    set_reveals(browser, switch=False, new=True, link=False)
    for address in (URL, "about:preferences", "file:///tmp/x.html", "data:text/plain,hi"):
        browser.js("document.documentElement.removeAttribute('tabs-flash');")
        browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", address)
        expect_flash(browser, False, address)


def test_a_custom_home_page_is_still_a_tab_you_opened(browser):
    browser.js(
        "Services.prefs.setStringPref('browser.startup.homepage', 'https://example.invalid/home');"
    )
    try:
        set_reveals(browser, switch=False, new=True, link=False)
        browser.js("document.documentElement.removeAttribute('tabs-flash');")
        browser.js("gBrowser.addTrustedTab('https://example.invalid/home', {inBackground: true});")
        expect_flash(browser, True, "the custom home page")
    finally:
        browser.js("Services.prefs.clearUserPref('browser.startup.homepage');")


def test_changing_a_reveal_pref_applies_at_once_in_every_window(browser):
    second = browser.new_window()
    set_reveals(browser, switch=False, new=False, link=False)
    browser.js("gBrowser.addTrustedTab('about:blank', {inBackground: true});")
    time.sleep(0.5)
    browser.js("document.documentElement.removeAttribute('tabs-flash');")
    browser.js("gBrowser.selectedTab = gBrowser.tabs[1];")
    expect_flash(browser, False, "second window, switch off")
    set_reveals(browser, switch=True)
    browser.js("document.documentElement.removeAttribute('tabs-flash');")
    browser.js("gBrowser.selectedTab = gBrowser.tabs[0];")
    expect_flash(browser, True, "second window, switch on")
    browser.js("window.close();")
    browser.switch_to(browser.first_window)
    assert second


# --- what the new-tab check remembers, and what it must not --------------------------------------

HOME = "browser.startup.homepage"


def test_a_home_page_that_changes_while_firefox_runs_is_noticed_each_time(browser):
    """Only the fixed list and the imported modules are kept; the addresses are read every time."""
    first, second = "https://example.invalid/home-one", "https://example.invalid/home-two"
    set_reveals(browser, switch=False, new=True, link=False)
    try:
        for home, other in ((first, second), (second, first), (first, second)):
            browser.js("Services.prefs.setStringPref(arguments[0], arguments[1]);", HOME, home)
            browser.js("document.documentElement.removeAttribute('tabs-flash');")
            browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", home)
            expect_flash(browser, True, f"the home page {home}")
            browser.js("document.documentElement.removeAttribute('tabs-flash');")
            browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", other)
            expect_flash(browser, False, f"{other} is no longer the home page")
    finally:
        browser.js("Services.prefs.clearUserPref(arguments[0]);", HOME)


def test_a_home_page_with_several_addresses_is_compared_as_the_whole_text(browser):
    """What the check did before it kept anything: the value of the pref is one string."""
    both = "https://example.invalid/a|https://example.invalid/b"
    browser.js("Services.prefs.setStringPref(arguments[0], arguments[1]);", HOME, both)
    try:
        set_reveals(browser, switch=False, new=True, link=False)
        browser.js("document.documentElement.removeAttribute('tabs-flash');")
        browser.js("gBrowser.addTrustedTab('https://example.invalid/a', {inBackground: true});")
        expect_flash(browser, False, "one of the addresses, which is a link, as before")
    finally:
        browser.js("Services.prefs.clearUserPref(arguments[0]);", HOME)


IMPORTS = """
    const seen = [];
    const utils = window.ChromeUtils;  // the one the script of this window uses
    const real = utils.importESModule;
    utils.importESModule = function (url, ...rest) {
      if (/AboutNewTab|HomePage/.test(url)) seen.push(url);
      return real.call(this, url, ...rest);
    };
    window.__imports = { seen, restore: () => { utils.importESModule = real; } };
"""


def test_the_modules_are_imported_once_and_not_at_all_for_the_usual_addresses(browser):
    browser.new_window()  # a window whose script has not looked at any tab yet
    set_reveals(browser, switch=False, new=True, link=False)
    browser.js(IMPORTS)
    try:
        for _ in range(6):
            for address in ("about:newtab", "about:blank", "about:home", ""):
                browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", address)
        time.sleep(0.7)
        assert browser.js("return window.__imports.seen.length;") == 0  # the fixed list answers
        for _ in range(6):
            browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", URL)
        time.sleep(0.7)
        assert 1 <= browser.js("return window.__imports.seen.length;") <= 2  # once per module
        for _ in range(6):
            browser.js("gBrowser.addTrustedTab(arguments[0], {inBackground: true});", URL)
        time.sleep(0.7)
        assert browser.js("return window.__imports.seen.length;") <= 2  # and never again
    finally:
        browser.js("window.__imports.restore();")
        browser.js("for (const tab of [...gBrowser.tabs].slice(1)) gBrowser.removeTab(tab);")
