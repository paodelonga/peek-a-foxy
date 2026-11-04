"""The tab bar when Firefox draws the title bar itself (``customtitlebar`` on the root).

Then #TabsToolbar also holds the window buttons and is the drag area, so hiding the tab bar must
hide only the tabs (``#TabsToolbar .toolbar-items``) and leave the toolbar, and with it the buttons,
alone. Firefox on Linux (headless) has no ``customtitlebar`` and no window buttons, so these tests
force the attribute and add a stand-in for the buttons' container; the real thing is checked by
the Windows-only test at the end.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.browser

BUTTON_HEIGHT = 30
ROOT = "document.documentElement"
NOT_CLIPPED = (
    "const t = document.getElementById('TabsToolbar'); return t.scrollHeight <= t.clientHeight;"
)

# A stand-in for Firefox's window buttons (three 46 px wide ones), as real as it gets on Linux.
STAND_IN = f"""
  const box = document.createXULElement('hbox');
  box.className = 'titlebar-buttonbox-container';
  box.id = 'peekafoxy-test-buttons';
  for (let i = 0; i < 3; i++) {{
    const button = document.createXULElement('hbox');
    button.className = 'titlebar-button';
    button.style.cssText = 'width: 46px; align-self: flex-start;'
      + 'min-height: {BUTTON_HEIGHT}px; height: {BUTTON_HEIGHT}px;';
    box.append(button);
  }}
  document.getElementById('TabsToolbar').append(box);
  document.documentElement.setAttribute('customtitlebar', '');
  document.documentElement.setAttribute('autohide-tabs', '');
"""
CLEAN_UP = """
  for (const name of ['customtitlebar', 'autohide-tabs', 'tabs-flash', 'peekafoxy-dragging']) {
    document.documentElement.removeAttribute(name);
  }
  document.getElementById('peekafoxy-test-buttons')?.remove();
  document.querySelector('#tabbrowser-tabs')?.removeAttribute('movingtab');
"""
STATE = """
  const rect = el => { const r = el.getBoundingClientRect();
    return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
            height: Math.round(r.height)}; };
  const toolbar = document.getElementById('TabsToolbar');
  const items = toolbar.querySelector('.toolbar-items');
  const buttons = document.getElementById('peekafoxy-test-buttons');
  return {
    toolbar: rect(toolbar), items: rect(items),
    buttons: rect(buttons.querySelector('.titlebar-button')),
    toolbarMaxHeight: getComputedStyle(toolbar).maxHeight,
    itemsOpacity: getComputedStyle(items).opacity,
    buttonsDisplay: getComputedStyle(buttons).display,
  };
"""


def hidden(browser) -> str:
    """Hidden for good: zero height, and the fade (which starts from nothing to animate) is over."""
    return f"{browser.TABS_HEIGHT} === 0 && getComputedStyle({browser.TABS_HOLDER}).opacity === '0'"


@pytest.fixture
def forced(browser):
    """A fresh window with autohide-tabs on, customtitlebar forced and the stand-in added."""
    browser.new_window()
    browser.js(STAND_IN)
    browser.wait(hidden(browser), 5, "the tabs did not collapse")
    yield browser
    browser.js(CLEAN_UP)


def reveal_with(browser, setup: str, undo: str) -> None:
    """The tabs come back to a real height with ``setup``, and go away again with ``undo``."""
    browser.js(setup)
    browser.wait(f"{browser.TABS_HEIGHT} >= 30", 5, f"this did not reveal the tabs: {setup}")
    browser.js(undo)
    browser.wait(hidden(browser), 5, f"this did not hide the tabs: {undo}")


def test_collapsing_hides_only_the_tabs_and_keeps_the_window_buttons(forced):
    state = forced.js(STATE)
    assert state["items"]["height"] == 0
    assert state["itemsOpacity"] == "0"
    # The toolbar is not the 8 px strip: it keeps the height of the window buttons, unclipped.
    assert state["toolbarMaxHeight"] != "8px"
    assert state["toolbar"]["height"] >= BUTTON_HEIGHT
    assert state["buttons"]["height"] == BUTTON_HEIGHT
    assert state["buttonsDisplay"] != "none"
    assert state["toolbar"]["top"] <= state["buttons"]["top"]
    assert state["buttons"]["bottom"] <= state["toolbar"]["bottom"]
    assert forced.js(NOT_CLIPPED)


def test_the_tabs_come_back_while_the_tab_bar_is_flashed(forced):
    reveal_with(
        forced,
        f"{ROOT}.setAttribute('tabs-flash', '');",
        f"{ROOT}.removeAttribute('tabs-flash');",
    )


def test_a_revealed_tab_bar_is_not_clipped_and_leaves_the_window_buttons_alone(forced):
    before = forced.js(STATE)["buttons"]["height"]
    forced.js(f"{ROOT}.setAttribute('tabs-flash', '');")
    forced.wait(f"{forced.TABS_HEIGHT} >= 30", 5)
    assert forced.js(NOT_CLIPPED)
    assert forced.js(STATE)["buttons"]["height"] == before
    forced.js(f"{ROOT}.removeAttribute('tabs-flash');")
    forced.wait(hidden(forced), 5)
    assert forced.js(STATE)["buttons"]["height"] == before


def test_the_tabs_come_back_while_a_tab_is_being_dragged_out_of_the_bar(forced):
    reveal_with(
        forced,
        f"{ROOT}.setAttribute('peekafoxy-dragging', 'tabs');",
        f"{ROOT}.removeAttribute('peekafoxy-dragging');",
    )
    reveal_with(
        forced,
        "document.getElementById('tabbrowser-tabs').setAttribute('movingtab', 'true');",
        "document.getElementById('tabbrowser-tabs').removeAttribute('movingtab');",
    )


def test_the_tabs_come_back_while_something_in_the_tab_bar_has_the_focus(forced):
    reveal_with(
        forced,
        "gBrowser.selectedTab.focus();",
        "gBrowser.selectedTab.blur(); gBrowser.selectedBrowser.focus();",
    )


def test_the_tabs_come_back_while_the_tab_context_menu_is_open(forced):
    reveal_with(
        forced,
        "document.getElementById('tabContextMenu').setAttribute('state', 'open');",
        "document.getElementById('tabContextMenu').removeAttribute('state');",
    )


def test_without_customtitlebar_the_whole_tab_bar_still_collapses_to_the_strip(browser):
    browser.new_window()
    browser.js(f"{ROOT}.setAttribute('autohide-tabs', '');")
    try:
        browser.wait(
            "document.getElementById('TabsToolbar').getBoundingClientRect().height <= 8",
            5,
            "the tab bar did not collapse to the strip",
        )
        assert (
            browser.js("return getComputedStyle(document.getElementById('TabsToolbar')).maxHeight;")
            == "8px"
        )
    finally:
        browser.js(f"{ROOT}.removeAttribute('autohide-tabs');")


WINDOWS_LAYOUT = """
  const toolbar = document.getElementById('TabsToolbar');
  const rect = el => { const r = el.getBoundingClientRect();
    return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
            width: r.width, height: r.height}; };
  const buttons = [...toolbar.querySelectorAll('.titlebar-button')]
    .map(b => ({name: b.className, ...rect(b)})).filter(b => b.width > 0 && b.height > 0);
  return {
    window: {width: window.innerWidth, height: window.innerHeight},
    toolbar: rect(toolbar), buttons,
    items: rect(toolbar.querySelector('.toolbar-items')),
    maxHeight: getComputedStyle(toolbar).maxHeight,
  };
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the real window buttons only exist on Windows")
def test_on_windows_the_window_buttons_stay_whole_while_the_tabs_are_hidden(browser):
    browser.new_window()
    browser.js(f"{ROOT}.setAttribute('autohide-tabs', '');")
    try:
        # Nothing is forced: Firefox itself sets customtitlebar on Windows.
        browser.wait(f"{ROOT}.hasAttribute('customtitlebar')", 5, "Firefox set no customtitlebar")
        browser.wait(hidden(browser), 8, "the tabs did not collapse")
        layout = browser.js(WINDOWS_LAYOUT)
    finally:
        browser.js(f"{ROOT}.removeAttribute('autohide-tabs');")

    assert layout["items"]["height"] == 0
    assert len(layout["buttons"]) == 3, layout["buttons"]  # minimize, restore, close
    toolbar, window = layout["toolbar"], layout["window"]
    for button in layout["buttons"]:
        assert button["width"] == pytest.approx(46, abs=1), button
        assert button["height"] > 8, button  # the strip is 8 px: it must not apply here
        # Whole: inside the toolbar and inside the window, so nothing clips it.
        assert toolbar["top"] <= button["top"] + 0.5, button
        assert button["bottom"] <= toolbar["bottom"] + 0.5, button
        assert button["left"] >= 0 and button["right"] <= window["width"] + 0.5, button
        assert button["bottom"] <= window["height"], button
    assert toolbar["height"] >= max(b["height"] for b in layout["buttons"]) - 0.5
    assert layout["maxHeight"] != "8px"
