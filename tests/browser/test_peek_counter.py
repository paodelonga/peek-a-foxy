"""The peek counter: a window counts the times the pointer enters a bar that is down to its strip.

Only the count exists (in memory, per window); nothing is shown or done with it. The pointer is real
(Marionette actions, as in test_pointer.py), and each test runs with the native title bar and with
the one Firefox draws itself.
"""

from __future__ import annotations

import pytest
from test_pointer import (  # noqa: F401  (first_window_again is an autouse fixture there)
    NAV_HEIGHT,
    OUTSIDE,
    ROOT,
    collapsed_window,
    first_window_again,
    hover,
    leave,
    variants,
)

pytestmark = pytest.mark.browser

PEEK = "const Peek = ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs');"
BARS = pytest.mark.parametrize("bar", ["TabsToolbar", "nav-bar"], ids=["tabs", "navbar"])


def count(browser) -> int:
    return browser.js(PEEK + "return Peek.Peeks.of(window);")


@pytest.fixture(autouse=True)
def no_handlers(browser):
    yield
    browser.js(PEEK + "Peek.Peeks.handlers.length = 0; delete window.__milestones;")


@variants
@BARS
def test_entering_a_collapsed_bar_counts_one_peek_and_each_new_entry_one_more(
    browser, customtitlebar, bar
):
    """Default path, real pointer: one entry is one peek, staying is not more, coming back is."""
    with collapsed_window(browser, customtitlebar):
        before = count(browser)
        hover(browser, bar)
        browser.wait(f"{PEEK_COUNT} === {before + 1}", 3, "the entry was not counted")
        browser.move_pointer(*browser.js(CENTER_PLUS, bar))  # moving inside the bar
        assert count(browser) == before + 1
        leave(browser)
        hover(browser, bar)
        browser.wait(f"{PEEK_COUNT} === {before + 2}", 3, "the second entry was not counted")


PEEK_COUNT = (
    "ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs').Peeks.of(window)"
)
CENTER_PLUS = """
  const r = document.getElementById(arguments[0]).getBoundingClientRect();
  return [r.left + r.width / 2 + 5, r.top + r.height / 2];
"""


@variants
def test_the_page_does_not_count(browser, customtitlebar):
    """Adversarial: the pointer moving over the page, far from the bars, is not a peek."""
    with collapsed_window(browser, customtitlebar):
        before = count(browser)
        browser.move_pointer(*OUTSIDE)
        browser.move_pointer(OUTSIDE[0] + 40, OUTSIDE[1] + 40)
        leave(browser)
        assert count(browser) == before


@variants
@BARS
def test_a_bar_that_is_already_open_does_not_count(browser, customtitlebar, bar):
    """Adversarial: the bar is open because of a flash or a popup, so entering it is no peek."""
    with collapsed_window(browser, customtitlebar):
        before = count(browser)
        browser.js(
            f"{ROOT}.setAttribute('tabs-flash', '');"
            f" {ROOT}.setAttribute('peekafoxy-popup-open', 'navbar');"
        )
        browser.wait(f"{NAV_HEIGHT} > 8", 5, "the navigation bar did not open")
        hover(browser, bar)
        assert count(browser) == before
        browser.js(
            f"{ROOT}.removeAttribute('tabs-flash'); {ROOT}.removeAttribute('peekafoxy-popup-open');"
        )


@variants
@BARS
def test_a_bar_with_the_autohide_off_does_not_count(browser, customtitlebar, bar):
    """Adversarial: nothing is hiding, so nothing peeks."""
    with collapsed_window(browser, customtitlebar):
        browser.js(
            f"{ROOT}.removeAttribute('autohide-tabs'); {ROOT}.removeAttribute('autohide-urlbar');"
        )
        before = count(browser)
        hover(browser, bar)
        browser.move_pointer(*OUTSIDE)  # not leave(): with the autohide off the bars never collapse
        assert count(browser) == before
        browser.js(
            f"{ROOT}.setAttribute('autohide-tabs', ''); {ROOT}.setAttribute('autohide-urlbar', '');"
        )


def synthetic_entries(browser, bar: str, times: int) -> None:
    """``times`` mouseenter events on a bar that is down to its strip (the pointer is elsewhere)."""
    browser.js(
        """const bar = document.getElementById(arguments[0]);
           const enter = () => bar.dispatchEvent(new MouseEvent('mouseenter'));
           for (let i = 0; i < arguments[1]; i++) enter();""",
        bar,
        times,
    )


@variants
def test_the_milestones_call_the_handlers_exactly_once_each(browser, customtitlebar):
    """Adversarial: 50, 100 and 200 reached by many entries call a handler once each, and nothing
    else does (not 49, 51, 99, 101...)."""
    with collapsed_window(browser, customtitlebar):
        browser.js(
            PEEK
            + """Peek.Peeks.set(window, 0);
               Peek.Peeks.handlers.push(({count}) => (window.__milestones ??= []).push(count));"""
        )
        synthetic_entries(browser, "nav-bar", 205)
        assert browser.js("return window.__milestones;") == [50, 100, 200]
        assert count(browser) == 205


@variants
def test_a_handler_that_throws_does_not_stop_the_others_or_the_count(browser, customtitlebar):
    with collapsed_window(browser, customtitlebar):
        browser.js(
            PEEK
            + """Peek.Peeks.set(window, 49);
               Peek.Peeks.handlers.push(() => { throw new Error('bad handler'); });
               Peek.Peeks.handlers.push(({count}) => (window.__milestones ??= []).push(count));"""
        )
        synthetic_entries(browser, "nav-bar", 2)
        assert browser.js("return window.__milestones;") == [50]
        assert count(browser) == 51


def test_there_are_no_handlers_and_nothing_is_shown_by_default(browser):
    """The count has no effect yet: no handler, no notification, no element, no pref."""
    assert browser.js(PEEK + "return Peek.Peeks.handlers.length;") == 0
    assert browser.js(PEEK + "return Peek.Peeks.milestones;") == [50, 100, 200]
    assert (
        browser.js(
            "return Services.prefs.getChildList('peekafoxy.').filter(n => /peek.*count/i.test(n));"
        )
        == []
    )


@variants
def test_each_window_counts_on_its_own_and_a_new_window_starts_at_zero(browser, customtitlebar):
    first = browser.first_window
    browser.switch_to(first)
    browser.js(PEEK + "Peek.Peeks.set(window, 7);")
    with collapsed_window(browser, customtitlebar):
        assert count(browser) == 0
        synthetic_entries(browser, "nav-bar", 3)
        assert count(browser) == 3
    browser.switch_to(first)
    assert count(browser) == 7
    browser.js(PEEK + "Peek.Peeks.set(window, 0);")
