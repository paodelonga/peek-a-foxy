"""Popups: windows that a page opens, and popups (panels, menus) that open from a bar.

Two different things share the word. A *popup window* is what ``window.open(url, name, "popup")``
makes: a browser window without toolbars, which the loader runs the script in twice, the first time
before the window has any browser UI. A *popup* is a panel or a menu anchored to a bar, such as the
list of all tabs: while it is open the bar must not collapse under it.
"""

# ruff: noqa: E501  (the long lines are JavaScript snippets)

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.browser

PEEK = "ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs')"
ROOT = "document.documentElement"
STARTED_EVENT = "the script started in a window"
OPEN_FROM_CONTENT = "window.open('about:blank', '_blank', arguments[0]);"
ALL_TABS_PANEL = "document.getElementById('allTabsMenu-allTabsView')?.closest('panel')"
# The popups of these tests are panels that stay open until hidden, so that two can be open at once.
OPEN_PANEL = """
  const panel = document.createXULElement('panel');
  panel.id = arguments[0];
  panel.setAttribute('noautohide', 'true');
  panel.style.minWidth = '120px';
  panel.style.minHeight = '40px';
  if (arguments[3] === 'cancel') panel.addEventListener('popupshowing', (e) => e.preventDefault());
  document.getElementById('mainPopupSet').append(panel);
  panel.openPopup(document.querySelector(arguments[1]), arguments[2]);
  return document.documentElement.getAttribute('peekafoxy-popup-open');
"""
POPUP_ATTR = f"return {ROOT}.getAttribute('peekafoxy-popup-open');"


def started_events(browser) -> int:
    return browser.js(
        f"return {PEEK}.Diag.events().filter(e => e.message === arguments[0]).length;",
        STARTED_EVENT,
    )


def error_events(browser) -> list[str]:
    return browser.js(
        f"return {PEEK}.Diag.events().filter(e => e.level === 'error')"
        ".map(e => e.where + ': ' + e.message);"
    )


def open_popup_window(browser, features: str = "popup,width=500,height=300") -> str:
    """Let the page in the selected tab open a popup window; switch to it once its script has run."""
    before = set(browser.client.chrome_window_handles)
    browser.client.set_context(browser.client.CONTEXT_CONTENT)
    browser.client.execute_script(OPEN_FROM_CONTENT, script_args=[features])
    browser.client.set_context(browser.client.CONTEXT_CHROME)
    deadline = time.monotonic() + 15
    new: list[str] = []
    while not new and time.monotonic() < deadline:
        new = [h for h in browser.client.chrome_window_handles if h not in before]
        time.sleep(0.1)
    assert new, "the page's popup window never opened"
    browser.switch_to(new[0])
    browser.wait(
        f"typeof gBrowser !== 'undefined' && gBrowserInit.delayedStartupFinished"
        f" && {PEEK}.Diag.hasStarted(window)",
        15,
        "the script never finished in the popup window",
    )
    return new[0]


def close_popup_window(browser) -> None:
    browser.js("window.close();")
    browser.switch_to(browser.first_window)


def settled(browser, expression: str, quiet: float = 0.6, timeout: float = 10.0):
    """The value of a JS expression once it has stopped changing (a bar or a panel still moving)."""
    deadline = time.monotonic() + timeout
    last, since = browser.js(f"return {expression};"), time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.1)
        current = browser.js(f"return {expression};")
        if current != last:
            last, since = current, time.monotonic()
        elif time.monotonic() - since >= quiet:
            return current
    raise AssertionError(f"never settled: {expression} = {last}")


def move_pointer(browser, x: float, y: float) -> None:
    """A real pointer move (Marionette actions), so that :hover is updated like for a person."""
    browser.move_pointer(x, y)


@pytest.fixture(autouse=True)
def clean(browser):
    def reset() -> None:
        first = browser.first_window
        for handle in browser.client.chrome_window_handles:
            if handle != first:
                browser.switch_to(handle)
                browser.js("window.close();")
        browser.switch_to(first)
        browser.js(
            f"""for (const name of ['peekafoxy.urlbar.autohide', 'peekafoxy.tabs.autohide'])
                 Services.prefs.clearUserPref(name);
               Services.prefs.clearUserPref('dom.disable_open_during_load');
               for (const panel of document.querySelectorAll('[id^=peekafoxy-test]')) panel.remove();
               {PEEK}.Diag.reset();"""
        )

    reset()
    browser.js("Services.prefs.setBoolPref('dom.disable_open_during_load', false);")
    yield
    reset()


# --- a popup window that a page opens ---------------------------------------------------------


@pytest.mark.parametrize(
    "features",
    [
        "popup,width=500,height=300",
        "popup",
        "width=400,height=300,toolbar=no,location=no,menubar=no,status=no",
    ],
)
def test_a_popup_window_opened_by_a_page_starts_cleanly_and_only_once(browser, features):
    """Adversarial: the loader runs the script before the window has gBrowser, then again."""
    open_popup_window(browser, features)
    try:
        assert browser.js("return window.toolbar.visible;") is False  # it really is a popup
        assert error_events(browser) == []
        assert browser.js(f"return {PEEK}.Diag.summary(window).state;") == "ok"
        assert started_events(browser) == 1  # one run that went through, not two
        # One handler for the shortcut: two would toggle twice and the bar would not change.
        assert not browser.js(f"return {ROOT}.hasAttribute('autohide-tabs');")
        browser.keydown("KeyT")
        assert browser.js(f"return {ROOT}.hasAttribute('autohide-tabs');")
    finally:
        close_popup_window(browser)


def test_running_the_script_again_in_a_started_window_does_nothing(browser):
    """Adversarial: a second run (the loader's persistent callback) must not register it all twice."""
    browser.new_window()
    browser.js(f"{PEEK}.Diag.reset();")
    browser.js(
        "Services.scriptloader.loadSubScript('chrome://userscripts/content/autohide.uc.js', window);"
    )
    time.sleep(0.5)
    assert started_events(browser) == 0
    assert error_events(browser) == []
    browser.keydown("KeyT")
    assert browser.js(f"return {ROOT}.hasAttribute('autohide-tabs');")  # toggled once, not twice
    browser.keydown("KeyT")
    assert not browser.js(f"return {ROOT}.hasAttribute('autohide-tabs');")


# --- the navigation bar of a popup window is never hidden ---------------------------------------


NAV_STATE = """
  const nav = document.getElementById('nav-bar');
  const style = getComputedStyle(nav);
  return {
    attr: document.documentElement.hasAttribute('autohide-urlbar'),
    height: Math.round(nav.getBoundingClientRect().height),
    maxHeight: style.maxHeight, opacity: style.opacity,
  };
"""


def test_a_popup_window_keeps_its_address_visible_even_when_new_windows_hide_the_navigation_bar(
    browser,
):
    browser.js("Services.prefs.setBoolPref('peekafoxy.urlbar.autohide', false);")
    open_popup_window(browser)
    natural = browser.js(NAV_STATE)
    close_popup_window(browser)
    assert natural["height"] > 8 and natural["opacity"] == "1"

    browser.js("Services.prefs.setBoolPref('peekafoxy.urlbar.autohide', true);")
    open_popup_window(browser)
    try:
        assert browser.js("return window.toolbar.visible;") is False
        assert browser.js(NAV_STATE) == natural  # not the 8 px strip, not transparent
        browser.keydown("KeyU")  # nor does the shortcut hide it
        assert browser.js(NAV_STATE) == natural
    finally:
        close_popup_window(browser)

    # The guard is for popup windows only: an ordinary new window still starts with the bar hidden.
    browser.new_window()
    assert browser.js(NAV_STATE)["attr"] is True
    browser.wait("document.getElementById('nav-bar').getBoundingClientRect().height <= 8", 8)


# --- a bar stays open while a popup that belongs to it is open ----------------------------------


@pytest.mark.parametrize(
    "customtitlebar", [False, True], ids=["native-title-bar", "customtitlebar"]
)
def test_the_tab_bar_stays_open_when_the_pointer_moves_into_its_popup(browser, customtitlebar):
    """A real pointer: without the guard the bar collapsed and the list of tabs jumped up."""
    browser.new_window()
    browser.js("window.resizeTo(900, 600);")
    browser.js("gBrowser.addTrustedTab('about:blank'); gBrowser.addTrustedTab('about:blank');")
    if customtitlebar:
        browser.js(f"{ROOT}.setAttribute('customtitlebar', '');")
    try:
        browser.js("document.getElementById('tabs-autohide-button').click();")
        move_pointer(browser, 500, 400)  # far from every bar
        browser.wait(f"{browser.TABS_HEIGHT} <= 8", 8, "the tab bar did not collapse")

        browser.js("gTabsPanel.showAllTabsPanel();")
        browser.wait(f"{ALL_TABS_PANEL}?.state === 'open'", 8, "the list of all tabs did not open")
        assert browser.js(POPUP_ATTR) == "tabs"
        before = settled(
            browser,
            f"({{tabs: {browser.TABS_HEIGHT}, top: Math.round({ALL_TABS_PANEL}.getBoundingClientRect().top)}})",
        )
        assert before["tabs"] > 8, "the popup did not open the bar it belongs to"

        box = browser.js(
            f"const r = {ALL_TABS_PANEL}.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];"
        )
        move_pointer(browser, box[0] + box[2] / 2, box[1] + 60)  # into the popup
        assert not browser.js("return !!document.querySelector('#TabsToolbar:hover');"), (
            "the pointer is still over the bar: the test proves nothing"
        )
        after = settled(
            browser,
            f"({{tabs: {browser.TABS_HEIGHT}, top: Math.round({ALL_TABS_PANEL}.getBoundingClientRect().top)}})",
        )
        assert after == before, "the bar moved under its popup"

        browser.js("gTabsPanel.hideAllTabsPanel();")
        browser.wait(f"!{ROOT}.hasAttribute('peekafoxy-popup-open')", 5, "the attribute stayed")
        move_pointer(browser, 500, 404)  # hover is only recomputed when the pointer moves
        browser.wait(f"{browser.TABS_HEIGHT} <= 8", 8, "the tab bar did not collapse again")
    finally:
        browser.js(
            f"{ROOT}.removeAttribute('customtitlebar'); {ROOT}.removeAttribute('autohide-tabs');"
        )


@pytest.mark.parametrize("anchor", ["navbar", "bookmarks"])
def test_the_navigation_group_stays_open_for_a_popup_of_either_bar(browser, anchor):
    """The navigation bar and the bookmarks bar open and close together, whichever has the popup."""
    browser.new_window()
    browser.js("CustomizableUI.setToolbarVisibility('PersonalToolbar', true);")
    browser.wait("document.getElementById('PersonalToolbar').getBoundingClientRect().height > 0", 5)
    normal = browser.settled_heights()
    try:
        browser.js("document.getElementById('urlbar-autohide-button').click();")
        browser.wait(
            "document.getElementById('nav-bar').getBoundingClientRect().height <= 8"
            " && document.getElementById('PersonalToolbar').getBoundingClientRect().height === 0",
            8,
            "the navigation group did not collapse",
        )
        selector = "#urlbar-container" if anchor == "navbar" else "#PersonalToolbar"
        browser.js(OPEN_PANEL, "peekafoxy-test-a", selector, "after_start")
        browser.wait("document.getElementById('peekafoxy-test-a').state === 'open'", 5)
        assert browser.js(POPUP_ATTR) == anchor
        browser.wait(
            f"Math.round(document.getElementById('nav-bar').getBoundingClientRect().height) === {normal['nav']}"
            f" && Math.round(document.getElementById('PersonalToolbar').getBoundingClientRect().height) === {normal['bookmarks']}",
            5,
            "the navigation group did not open for its popup",
        )
        browser.js("document.getElementById('peekafoxy-test-a').hidePopup();")
        browser.wait(
            "document.getElementById('nav-bar').getBoundingClientRect().height <= 8"
            " && document.getElementById('PersonalToolbar').getBoundingClientRect().height === 0",
            8,
            "the navigation group stayed open after the popup closed",
        )
    finally:
        browser.js("CustomizableUI.setToolbarVisibility('PersonalToolbar', false);")


# --- how the popups are counted (adversarial) -----------------------------------------------------


def test_two_popups_of_one_bar_keep_it_open_until_the_second_one_closes(browser):
    browser.new_window()
    first = browser.js(OPEN_PANEL, "peekafoxy-test-a", "#alltabs-button", "after_start")
    second = browser.js(OPEN_PANEL, "peekafoxy-test-b", "#alltabs-button", "after_end")
    assert (first, second) == ("tabs", "tabs")
    browser.wait("document.getElementById('peekafoxy-test-b').state === 'open'", 5)
    browser.js("document.getElementById('peekafoxy-test-a').hidePopup();")
    browser.wait("document.getElementById('peekafoxy-test-a').state === 'closed'", 5)
    assert browser.js(POPUP_ATTR) == "tabs"  # a flag or a plain counter would have cleared it
    browser.js("document.getElementById('peekafoxy-test-b').hidePopup();")
    browser.wait(f"!{ROOT}.hasAttribute('peekafoxy-popup-open')", 5, "the attribute stayed")


def test_popups_of_two_bars_name_both_bars(browser):
    browser.new_window()
    browser.js(OPEN_PANEL, "peekafoxy-test-a", "#alltabs-button", "after_start")
    browser.js(OPEN_PANEL, "peekafoxy-test-b", "#urlbar-container", "after_start")
    browser.wait("document.getElementById('peekafoxy-test-b').state === 'open'", 5)
    assert set(browser.js(POPUP_ATTR).split()) == {"tabs", "navbar"}
    browser.js("document.getElementById('peekafoxy-test-b').hidePopup();")
    browser.wait(f"{ROOT}.getAttribute('peekafoxy-popup-open') === 'tabs'", 5)


def test_a_popup_that_is_removed_without_being_hidden_stops_counting_on_the_next_mouse_move(
    browser,
):
    browser.new_window()
    browser.js(OPEN_PANEL, "peekafoxy-test-a", "#alltabs-button", "after_start")
    browser.wait("document.getElementById('peekafoxy-test-a').state === 'open'", 5)
    browser.js("document.getElementById('peekafoxy-test-a').remove();")  # no popuphidden arrives
    browser.js("window.dispatchEvent(new MouseEvent('mousemove', {bubbles: true}));")
    assert browser.js(POPUP_ATTR) is None


def test_a_popup_whose_opening_is_cancelled_does_not_leave_the_bar_open(browser):
    browser.new_window()
    during = browser.js(OPEN_PANEL, "peekafoxy-test-a", "#alltabs-button", "after_start", "cancel")
    assert during == "tabs"  # the attribute is set while the event is being handled ...
    browser.wait(
        f"!{ROOT}.hasAttribute('peekafoxy-popup-open')", 5, "a cancelled popup kept the bar"
    )
    assert browser.js("return document.getElementById('peekafoxy-test-a').state;") == "closed"


def test_a_popup_that_belongs_to_no_bar_and_a_tooltip_do_not_open_one(browser):
    """Adversarial: the context menu of a web page must not drop the bars down."""
    browser.new_window()
    browser.js(OPEN_PANEL, "peekafoxy-test-a", "#appcontent", "after_start")
    browser.wait("document.getElementById('peekafoxy-test-a').state === 'open'", 5)
    assert browser.js(POPUP_ATTR) is None
    browser.js(
        """const tip = document.createXULElement('tooltip');
           tip.id = 'peekafoxy-test-tip';
           tip.append(document.createXULElement('label'));
           document.getElementById('mainPopupSet').append(tip);
           tip.openPopup(document.getElementById('alltabs-button'), 'after_start');"""
    )
    browser.wait("document.getElementById('peekafoxy-test-tip').state === 'open'", 5)
    assert browser.js(POPUP_ATTR) is None
    browser.js("document.getElementById('peekafoxy-test-tip').hidePopup();")
