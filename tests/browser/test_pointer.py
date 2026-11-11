"""The pointer: a bar collapses to a strip and opens when the pointer is on it, as for a person.

Every other test reaches a revealed bar by an attribute, focus, a popup or a drag marker, never by
:hover, which is the way a bar is normally revealed. Here the pointer is real (Marionette actions,
see ``Browser.move_pointer``): Firefox updates :hover only for such a move. Each test runs twice,
with a native title bar and with ``customtitlebar`` (forced on Linux, as in test_customtitlebar.py).

The waits poll for a condition. "Stays open" is the one thing that needs a stretch of time; it is
looked at for a second, with the hide delay set to 0 so that a bar that is going to collapse does so
well inside it.
"""

# ruff: noqa: E501  (the long lines are JavaScript snippets)

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.browser

ROOT = "document.documentElement"
BUTTON_HEIGHT = 30
HIDE_DELAY = "peekafoxy.hide.delay.ms"
OUTSIDE = (450, 450)  # the web page, far from every bar
CENTER = """
  const r = document.getElementById(arguments[0]).getBoundingClientRect();
  return [r.left + r.width / 2, r.top + r.height / 2];
"""
# A stand-in for Firefox's window buttons (three 46 px wide ones), as in test_customtitlebar.py.
CUSTOM_TITLE_BAR = f"""
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
"""
CLEAN_UP = """
  for (const name of ['customtitlebar', 'autohide-tabs', 'autohide-urlbar']) {
    document.documentElement.removeAttribute(name);
  }
  document.getElementById('peekafoxy-test-buttons')?.remove();
  Services.prefs.clearUserPref(arguments[0]);
  for (const pref of ['easing', 'bookmarks', 'show.delay.ms', 'tabs.strip.px', 'urlbar.strip.px', 'hide.ms', 'strip.px']) Services.prefs.clearUserPref('peekafoxy.' + pref);
  for (const v of ['show-delay', 'tabs-strip', 'nav-strip', 'hide-duration', 'strip']) document.documentElement.style.removeProperty('--autohide-' + v);
  CustomizableUI.setToolbarVisibility('PersonalToolbar', false);
"""
NAV_HEIGHT = "Math.round(document.getElementById('nav-bar').getBoundingClientRect().height)"
BOOKMARKS_HEIGHT = (
    "Math.round(document.getElementById('PersonalToolbar').getBoundingClientRect().height)"
)

variants = pytest.mark.parametrize(
    "customtitlebar", [False, True], ids=["native-title-bar", "customtitlebar"]
)


@pytest.fixture(autouse=True)
def first_window_again(browser):
    yield
    for handle in browser.client.chrome_window_handles:
        if handle != browser.first_window:
            browser.switch_to(handle)
            browser.js("window.close();")
    browser.switch_to(browser.first_window)


@contextmanager
def collapsed_window(browser, customtitlebar: bool, bookmarks: bool = False) -> Iterator[dict]:
    """A new window with both bars autohidden and the pointer on the page; yields the natural heights."""
    browser.new_window()
    browser.js("window.resizeTo(900, 600);")
    browser.wait("window.innerHeight >= 500", 5, "the window did not get its size")
    try:
        if customtitlebar:
            browser.js(CUSTOM_TITLE_BAR)
        if bookmarks:
            browser.js("CustomizableUI.setToolbarVisibility('PersonalToolbar', true);")
            browser.wait(f"{BOOKMARKS_HEIGHT} > 0", 5, "the bookmarks bar did not show")
        browser.move_pointer(*OUTSIDE)
        natural = browser.settled_heights()
        browser.js(
            f"{ROOT}.setAttribute('autohide-tabs', ''); {ROOT}.setAttribute('autohide-urlbar', '');"
        )
        wait_collapsed(browser)
        yield natural
    finally:
        browser.move_pointer(*OUTSIDE)
        browser.js(CLEAN_UP, HIDE_DELAY)


def wait_collapsed(browser, timeout: float = 8.0) -> None:
    browser.wait(
        f"{browser.TABS_HEIGHT} <= 8 && {NAV_HEIGHT} <= 8 && {BOOKMARKS_HEIGHT} === 0",
        timeout,
        "the bars did not collapse",
    )


def hover(browser, element_id: str) -> None:
    """Put the pointer in the middle of an element, where it is now, and wait for Firefox to say so."""
    browser.move_pointer(*browser.js(CENTER, element_id))
    browser.wait(f"{element(element_id)}.matches(':hover')", 5, f"{element_id} never got the hover")


def element(element_id: str) -> str:
    return f"document.getElementById('{element_id}')"


def leave(browser) -> None:
    browser.move_pointer(*OUTSIDE)
    wait_collapsed(browser)


def leave_to_the_page(browser, element_id: str) -> None:
    """Move off the page's bars and wait until Firefox has taken the hover away from an element."""
    browser.move_pointer(*OUTSIDE)
    browser.wait(f"!{element(element_id)}.matches(':hover')", 5, f"{element_id} kept the hover")


def stays(browser, condition: str, message: str, seconds: float = 1.0) -> None:
    """The condition holds throughout a stretch of time (a bar that is about to collapse has by then)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert browser.js(f"return Boolean({condition});"), f"{message}: {browser.heights()}"
        time.sleep(0.1)


def no_delay(browser) -> None:
    browser.js("Services.prefs.setIntPref(arguments[0], 0);", HIDE_DELAY)


# --- the tab bar ----------------------------------------------------------------------------------


@variants
def test_the_pointer_on_the_tab_strip_opens_the_tab_bar_and_leaving_closes_it(
    browser, customtitlebar
):
    """Default path, real pointer."""
    with collapsed_window(browser, customtitlebar) as natural:
        hover(browser, "TabsToolbar")
        browser.wait(
            f"{browser.TABS_HEIGHT} === {natural['tabs']}", 5, "the tab bar did not open on hover"
        )
        assert browser.js(
            "const t = document.getElementById('TabsToolbar'); return t.scrollHeight <= t.clientHeight;"
        ), "the opened tab bar is clipped"
        browser.move_pointer(*OUTSIDE)
        browser.wait(
            f"{browser.TABS_HEIGHT} <= 8", 8, "the tab bar did not close after the pointer left"
        )


@variants
def test_the_pointer_on_the_tab_strip_does_not_open_the_navigation_bar(browser, customtitlebar):
    """Adversarial: one bar's strip is next to the other's; each opens only for its own pointer."""
    with collapsed_window(browser, customtitlebar):
        no_delay(browser)
        hover(browser, "TabsToolbar")
        browser.wait(f"{browser.TABS_HEIGHT} > 8", 5, "the tab bar did not open")
        stays(browser, f"{NAV_HEIGHT} <= 8", "the navigation bar opened for the tab strip", 0.6)


# --- the navigation bar -----------------------------------------------------------------------------


@variants
def test_the_pointer_on_the_navigation_strip_opens_the_navigation_bar_and_leaving_closes_it(
    browser, customtitlebar
):
    with collapsed_window(browser, customtitlebar) as natural:
        hover(browser, "nav-bar")
        browser.wait(f"{NAV_HEIGHT} === {natural['nav']}", 5, "the navigation bar did not open")
        browser.move_pointer(*OUTSIDE)
        browser.wait(
            f"{NAV_HEIGHT} <= 8", 8, "the navigation bar did not close after the pointer left"
        )


@variants
def test_the_pointer_on_the_navigation_strip_does_not_open_the_tab_bar(browser, customtitlebar):
    """Adversarial: the other way round."""
    with collapsed_window(browser, customtitlebar):
        no_delay(browser)
        hover(browser, "nav-bar")
        browser.wait(f"{NAV_HEIGHT} > 8", 5, "the navigation bar did not open")
        stays(
            browser,
            f"{browser.TABS_HEIGHT} <= 8",
            "the tab bar opened for the navigation strip",
            0.6,
        )


@variants
def test_moving_into_the_bookmarks_bar_keeps_the_navigation_group_open(browser, customtitlebar):
    """The bookmarks bar has no strip of its own: it opens with the navigation bar and, once the
    pointer is in it, keeps the pair open although the navigation bar has lost the hover."""
    with collapsed_window(browser, customtitlebar, bookmarks=True) as natural:
        no_delay(browser)
        hover(browser, "nav-bar")
        browser.wait(
            f"{NAV_HEIGHT} === {natural['nav']} && {BOOKMARKS_HEIGHT} === {natural['bookmarks']}",
            5,
            "the navigation group did not open on hover",
        )
        hover(browser, "PersonalToolbar")
        assert not browser.js(f"return {element('nav-bar')}.matches(':hover');"), (
            "the pointer is still over the navigation bar: the test proves nothing"
        )
        stays(
            browser,
            f"{NAV_HEIGHT} === {natural['nav']} && {BOOKMARKS_HEIGHT} === {natural['bookmarks']}",
            "the group closed under the pointer in the bookmarks bar",
        )
        browser.move_pointer(*OUTSIDE)
        wait_collapsed(browser)


# --- the hide delay ---------------------------------------------------------------------------------


@variants
@pytest.mark.parametrize(
    ("bar", "height"),
    [("TabsToolbar", "TABS_HEIGHT"), ("nav-bar", "NAV_HEIGHT")],
    ids=["tabs", "navbar"],
)
def test_drifting_off_a_bar_and_back_within_the_hide_delay_does_not_close_it(
    browser, customtitlebar, bar, height
):
    """Adversarial: the delay is what keeps a bar from flickering when the pointer leaves it briefly."""
    with collapsed_window(browser, customtitlebar) as natural:
        measure = browser.TABS_HEIGHT if height == "TABS_HEIGHT" else NAV_HEIGHT
        key = "tabs" if height == "TABS_HEIGHT" else "nav"
        browser.js("Services.prefs.setIntPref(arguments[0], 1500);", HIDE_DELAY)
        hover(browser, bar)
        browser.wait(f"{measure} === {natural[key]}", 5, "the bar did not open")
        leave_to_the_page(browser, bar)
        stays(browser, f"{measure} === {natural[key]}", "the bar closed before the hide delay", 0.4)
        hover(browser, bar)  # back before the delay is over
        # ... and past the moment the bar would have closed (the delay and the 0.2 s transition).
        stays(
            browser,
            f"{measure} === {natural[key]}",
            "the bar closed although the pointer came back",
            1.8,
        )
        browser.move_pointer(*OUTSIDE)
        browser.wait(f"{measure} <= 8", 8, "the bar never closed after the pointer left for good")


# --- the show delay -------------------------------------------------------------------------------


@variants
@pytest.mark.parametrize(
    ("bar", "height"),
    [("TabsToolbar", "TABS_HEIGHT"), ("nav-bar", "NAV_HEIGHT")],
    ids=["tabs", "nav"],
)
def test_the_pointer_must_rest_for_the_show_delay_before_a_bar_opens(
    browser, customtitlebar, bar, height
):
    """Adversarial: with a 1.2 s show delay the bar is still closed after 0.5 s of hover, opens after
    the delay, and a pointer that leaves earlier never opens it. The variable follows the pref."""
    with collapsed_window(browser, customtitlebar) as natural:
        measure = browser.TABS_HEIGHT if height == "TABS_HEIGHT" else NAV_HEIGHT
        key = "tabs" if height == "TABS_HEIGHT" else "nav"
        browser.js("Services.prefs.setIntPref('peekafoxy.show.delay.ms', 1200);")
        browser.wait(
            f"{ROOT}.style.getPropertyValue('--autohide-show-delay') === '1200ms'",
            5,
            "the pref did not reach the CSS variable",
        )
        hover(browser, bar)
        stays(browser, f"{measure} <= 8", "the bar opened before the show delay", 0.5)
        leave(browser)  # leaves early: it never opened
        stays(browser, f"{measure} <= 8", "the bar opened for a pointer that had left", 0.8)
        hover(browser, bar)
        browser.wait(f"{measure} === {natural[key]}", 6, "the bar never opened after the delay")


# --- the strip of each bar, and the closing animation --------------------


def test_each_bar_can_have_a_strip_of_its_own_and_zero_follows_the_shared_one(browser):
    """Adversarial: the shared strip moves both bars, a per-bar value moves only its bar, and 0
    (the default) hands the bar back to the shared strip. The tab bar has a strip only with the
    native title bar (a window that draws its own, as on Windows, has no strip for it)."""
    with collapsed_window(browser, False):
        native = browser.js(f"return !{ROOT}.hasAttribute('customtitlebar');")
        tabs = (
            (lambda value: f"{browser.TABS_HEIGHT} === {value}")
            if native
            else (lambda value: "true")
        )
        browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 14);")
        browser.wait(f"{tabs(14)} && {NAV_HEIGHT} === 14", 5, "the shared strip did not apply")
        browser.js("Services.prefs.setIntPref('peekafoxy.tabs.strip.px', 24);")
        browser.wait(
            f"{tabs(24)} && {NAV_HEIGHT} === 14", 5, "the tab bar's own strip did not apply"
        )
        browser.js("Services.prefs.setIntPref('peekafoxy.urlbar.strip.px', 6);")
        browser.wait(
            f"{tabs(24)} && {NAV_HEIGHT} === 6", 5, "the navigation bar's own strip did not apply"
        )
        browser.js("Services.prefs.setIntPref('peekafoxy.urlbar.strip.px', 0);")
        browser.wait(
            f"{NAV_HEIGHT} === 14", 5, "0 did not hand the navigation bar back to the shared strip"
        )


def test_the_closing_animation_duration_follows_its_pref(browser):
    """With reduced motion (which the Windows runner has on) the stylesheet drops the animation, so
    this test turns it off first."""
    browser.js("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
    try:
        _closing_duration(browser)
    finally:
        browser.js("Services.prefs.clearUserPref('ui.prefersReducedMotion');")


def _closing_duration(browser):
    with collapsed_window(browser, False):
        browser.js("Services.prefs.setIntPref('peekafoxy.hide.ms', 750);")
        browser.wait(
            "getComputedStyle(document.getElementById('nav-bar')).transitionDuration.includes('0.75s')",
            5,
            "the closing duration did not follow the pref",
        )


# --- the animation curve and the bookmarks bar ---------------------------------------------------


@pytest.mark.parametrize(
    ("value", "opening", "closing"),
    [
        ("linear", "linear", "linear"),
        ("snappy", "cubic-bezier(0.2, 0.9, 0.3, 1)", "cubic-bezier(0.4, 0, 1, 1)"),
        ("smooth", "ease-out", "ease-in"),
        ("nonsense", "ease-out", "ease-in"),  # not one of the choices: the default
        ("", "ease-out", "ease-in"),
        ("LINEAR", "ease-out", "ease-in"),  # exact keys only
    ],
)
def test_the_animation_curve_follows_its_pref_and_a_bad_value_gives_the_default(
    browser, value, opening, closing
):
    browser.js("Services.prefs.setStringPref('peekafoxy.easing', arguments[0]);", value)
    browser.wait(
        f"getComputedStyle({ROOT}).getPropertyValue('--autohide-show-easing').trim() === '{opening}'",
        5,
        "the opening curve did not follow the pref",
    )
    assert (
        browser.js(
            f"return getComputedStyle({ROOT}).getPropertyValue('--autohide-hide-easing').trim();"
        )
        == closing
    )


def test_the_bookmarks_bar_can_stay_visible_while_the_navigation_bar_hides(browser):
    """Adversarial: with `visible` the bookmarks bar keeps its height while the navigation bar is
    down to its strip, hovering it does not open the navigation bar, and `follow` (the default) puts
    it back to closing with the bar."""
    with collapsed_window(browser, False, bookmarks=True) as natural:
        browser.js("Services.prefs.setStringPref('peekafoxy.bookmarks', 'visible');")
        browser.wait(
            f"{ROOT}.getAttribute('peekafoxy-bookmarks') === 'visible'", 5, "the pref did not apply"
        )
        browser.wait(
            f"{BOOKMARKS_HEIGHT} === {natural['bookmarks']} && {NAV_HEIGHT} <= 8",
            5,
            "the bookmarks bar did not stay while the navigation bar hid",
        )
        hover(browser, "PersonalToolbar")
        stays(
            browser,
            f"{NAV_HEIGHT} <= 8",
            "hovering the visible bookmarks bar opened the navigation bar",
        )
        browser.move_pointer(*OUTSIDE)
        browser.js("Services.prefs.clearUserPref('peekafoxy.bookmarks');")
        browser.wait(
            f"{BOOKMARKS_HEIGHT} === 0", 8, "the bookmarks bar did not go back to following the bar"
        )


# --- the address bar of a collapsed navigation bar ----------------------------------------------

URLBAR_BELOW_THE_STRIP = """
  const urlbar = document.getElementById('urlbar'), nav = document.getElementById('nav-bar');
  const box = urlbar.getBoundingClientRect(), strip = nav.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, strip.bottom + 10);
  return {
    hitsTheUrlbar: !!hit?.closest('#urlbar'),
    opacity: getComputedStyle(urlbar).opacity,
    pointerEvents: getComputedStyle(urlbar).pointerEvents,
  };
"""


@variants
@pytest.mark.parametrize("bookmarks", ["follow", "visible"])
def test_the_address_bar_of_a_collapsed_navigation_bar_is_invisible_and_takes_no_clicks(
    browser, customtitlebar, bookmarks
):
    """Adversarial: Firefox 153 keeps the address bar open in the top layer, outside the clipping of
    the bar, so it must be hidden by its own rule: transparent, and no pointer events below the strip."""
    with collapsed_window(browser, customtitlebar):
        browser.js("Services.prefs.setStringPref('peekafoxy.bookmarks', arguments[0]);", bookmarks)
        browser.move_pointer(*OUTSIDE)
        browser.wait(f"{NAV_HEIGHT} <= 8", 5, "the navigation bar did not collapse")
        browser.wait(
            "getComputedStyle(document.getElementById('urlbar')).opacity === '0'",
            5,
            "the address bar stayed visible",
        )
        state = browser.js(URLBAR_BELOW_THE_STRIP)
        assert state == {"hitsTheUrlbar": False, "opacity": "0", "pointerEvents": "none"}


@variants
def test_the_address_bar_is_back_when_the_navigation_bar_opens_and_takes_clicks(
    browser, customtitlebar
):
    """The way back: hovering the strip, or focusing the address bar, makes it opaque and clickable."""
    with collapsed_window(browser, customtitlebar) as natural:
        hover(browser, "nav-bar")
        browser.wait(f"{NAV_HEIGHT} === {natural['nav']}", 5, "the bar did not open on hover")
        browser.wait(
            "getComputedStyle(document.getElementById('urlbar')).opacity === '1'",
            5,
            "still transparent",
        )
        assert (
            browser.js("return getComputedStyle(document.getElementById('urlbar')).pointerEvents;")
            != "none"
        )
        leave(browser)
        browser.js("document.getElementById('urlbar').focus();")  # what Ctrl+L, Alt+D and F6 do
        browser.wait(
            f"{NAV_HEIGHT} === {natural['nav']}", 5, "focusing the address bar did not open it"
        )
        browser.wait(
            "getComputedStyle(document.getElementById('urlbar')).opacity === '1'",
            5,
            "still transparent",
        )
        browser.js("gBrowser.selectedBrowser.focus();")
        browser.wait(f"{NAV_HEIGHT} <= 8", 8, "the bar did not close after the focus left")


# --- the show delay and the always visible bookmarks bar ---------------------------------------


@variants
@pytest.mark.parametrize(
    ("marker", "strip", "other", "key"),
    [
        ("peekafoxy-popup-open", "nav-bar", "tabs", "nav"),
        ("peekafoxy-popup-open", "TabsToolbar", "navbar", "tabs"),
        ("peekafoxy-peek", "nav-bar", "tabs", "nav"),
    ],
    ids=["popup-on-tabs-nav-strip", "popup-on-nav-tabs-strip", "peek-of-tabs"],
)
def test_what_concerns_the_other_bar_does_not_cancel_the_show_delay(
    browser, customtitlebar, marker, strip, other, key
):
    """Adversarial: a popup or a peek of one bar must not make the other bar open at once; it still
    waits for the show delay (1.2 s here). A drag marker is not tried: the script ends a drag it did
    not see begin on the first mouse movement."""
    with collapsed_window(browser, customtitlebar) as natural:
        measure = browser.TABS_HEIGHT if key == "tabs" else NAV_HEIGHT
        browser.js("Services.prefs.setIntPref('peekafoxy.show.delay.ms', 1200);")
        browser.wait(
            f"{ROOT}.style.getPropertyValue('--autohide-show-delay') === '1200ms'",
            5,
            "delay not set",
        )
        browser.js(f"{ROOT}.setAttribute('{marker}', '{other}');")
        try:
            browser.settled_heights()  # the other bar opens and moves this strip: aim after that
            hover(browser, strip)
            stays(browser, f"{measure} <= 8", "the bar opened before the show delay", 0.6)
            browser.wait(f"{measure} === {natural[key]}", 6, "the bar never opened after the delay")
        finally:
            browser.js(f"{ROOT}.removeAttribute('{marker}');")


@variants
def test_a_bookmarks_bar_that_always_stays_visible_is_not_capped_when_the_group_opens(
    browser, customtitlebar
):
    """Adversarial: a bookmarks bar taller than the 40 px cap (90 px asked, about 70 shown) of the reveal rules keeps its height."""
    with collapsed_window(browser, customtitlebar, bookmarks=True) as natural:
        browser.js("Services.prefs.setStringPref('peekafoxy.bookmarks', 'visible');")
        browser.js("document.getElementById('PersonalToolbar').style.height = '90px';")
        try:
            browser.wait(
                f"{BOOKMARKS_HEIGHT} >= 50 && {NAV_HEIGHT} <= 8", 5, "not tall and visible"
            )
            hover(browser, "nav-bar")
            browser.wait(f"{NAV_HEIGHT} === {natural['nav']}", 5, "the group did not open")
            stays(browser, f"{BOOKMARKS_HEIGHT} >= 50", "the bookmarks bar was capped", 0.8)
        finally:
            browser.js("document.getElementById('PersonalToolbar').style.height = '';")
