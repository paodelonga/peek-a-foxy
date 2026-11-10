"""The shortcuts as a keyboard delivers them: Firefox's own key handling, not a ``dispatchEvent``.

The other tests send a synthetic ``keydown`` straight to the window, which skips what makes the
handler in autohide.uc.js work: it listens in the capture phase (so that nothing in the window can
stop the event first), it calls ``preventDefault`` (so that the page does not also get the key) and
it belongs to one window. A chain of Marionette key actions (``Browser.real_keys``) goes through all
of that, so these tests can fail when those lines go. Keys that do or do not reach a web page are
read back from the page's title, which the page sets itself.
"""

# ruff: noqa: E501  (the long lines are JavaScript snippets)

from __future__ import annotations

import time
from urllib.parse import quote

import pytest
from marionette_driver.keys import Keys

pytestmark = pytest.mark.browser

HAS = "document.documentElement.hasAttribute(arguments[0])"
SHORTCUTS = [("t", "autohide-tabs"), ("u", "autohide-urlbar")]
# A page that writes every key event it sees into its own title. "swallow" makes it a page that stops
# every keydown at the window, the strongest thing a page can do.
PAGE = """
<title>-</title><input id="f" autofocus><script>
  const log = [];
  const swallow = location.hash === '#swallow';
  for (const type of ['keydown', 'keypress', 'keyup']) {
    window.addEventListener(type, (event) => {
      log.push(type + ':' + event.code);
      document.title = log.join(' ');
      if (swallow) { event.stopPropagation(); event.stopImmediatePropagation(); }
    }, true);
  }
</script>
"""
PAGE_URL = "data:text/html," + quote(PAGE)


@pytest.fixture(autouse=True)
def clean(browser):
    yield
    for handle in browser.client.chrome_window_handles:
        if handle != browser.first_window:
            browser.switch_to(handle)
            browser.js("window.close();")
    browser.switch_to(browser.first_window)
    browser.js(
        "for (const attr of ['autohide-tabs', 'autohide-urlbar'])"
        " document.documentElement.removeAttribute(attr);"
    )


def shortcut(browser, letter: str) -> None:
    """The default shortcut of the bar whose letter is ``t`` or ``u`` (Shift depends on the system)."""
    browser.real_shortcut({"t": "tabs", "u": "urlbar"}[letter])


def is_on(browser, attr: str) -> bool:
    return browser.js(f"return {HAS};", attr)


def page_keys(browser) -> list[str]:
    """What the page in the selected tab has seen so far, as ``type:code`` entries."""
    title = browser.js("return gBrowser.selectedBrowser.contentTitle;")
    return [] if title in ("-", "") else title.split()


def open_page(browser, swallow: bool = False) -> None:
    """Load the key-logging page in the selected tab of this window and give it the focus."""
    url = PAGE_URL + ("#swallow" if swallow else "")
    browser.js(
        """gBrowser.selectedBrowser.loadURI(Services.io.newURI(arguments[0]),
             {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});""",
        url,
    )
    browser.wait(
        "gBrowser.selectedBrowser.contentTitle === '-'", 10, "the key-logging page did not load"
    )
    browser.js("gBrowser.selectedBrowser.focus();")
    browser.wait("document.activeElement === gBrowser.selectedBrowser", 5, "the page has no focus")


def wait_for_page_key(browser, entry: str) -> list[str]:
    """Wait until the page has seen ``entry``: keys reach it in order, so what came before is in."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        keys = page_keys(browser)
        if entry in keys:
            return keys
        time.sleep(0.1)
    raise AssertionError(f"the page never saw {entry}: {page_keys(browser)}")


# --- one window --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("letter", "attr"), SHORTCUTS, ids=["tabs", "urlbar"])
def test_a_real_shortcut_toggles_the_bar_of_the_window_that_has_the_keyboard_only(
    browser, letter, attr
):
    """Default path, real keys: the second window gets the key, the first one is not touched."""
    first = browser.first_window
    second = browser.new_window()
    shortcut(browser, letter)
    assert is_on(browser, attr)
    browser.switch_to(first)
    assert not is_on(browser, attr), "the shortcut reached a window that did not have the keyboard"
    browser.switch_to(second)
    shortcut(browser, letter)
    assert not is_on(browser, attr)


def test_a_shortcut_with_Shift_added_or_missing_does_nothing(browser):
    """Adversarial: the default tab bar shortcut with Shift flipped (Ctrl+Alt+T where the default is
    Ctrl+Alt+Shift+T, or the other way round) is another shortcut. The real one right after proves
    the keys work."""
    browser.new_window()
    has_shift = "Shift" in browser.default_shortcut("tabs")
    other = (Keys.CONTROL, Keys.ALT) if has_shift else (Keys.CONTROL, Keys.ALT, Keys.SHIFT)
    browser.real_keys("t", *other)
    assert not is_on(browser, "autohide-tabs")
    shortcut(browser, "t")
    assert is_on(browser, "autohide-tabs")  # once: the first press did not toggle it twice


def test_the_old_urlbar_default_is_not_a_shortcut_any_more(browser):
    """Adversarial: Ctrl+Alt+U belongs to Firefox (the tabs sidebar) and not to the navigation bar."""
    browser.new_window()
    browser.real_keys("u", Keys.CONTROL, Keys.ALT)
    assert not is_on(browser, "autohide-urlbar")
    shortcut(browser, "u")
    assert is_on(browser, "autohide-urlbar")


# --- the page does not get the key ---------------------------------------------------------------------


@pytest.mark.parametrize(("letter", "attr"), SHORTCUTS, ids=["tabs", "urlbar"])
def test_the_page_does_not_get_the_shortcut_key(browser, letter, attr):
    """Adversarial: without ``preventDefault`` the page sees the shortcut's key as well.

    A key that is not a shortcut comes first, to show that this page does see the keys it is given;
    the one after proves the shortcut is over, because keys reach the page in the order they were sent.
    """
    browser.new_window()
    open_page(browser)
    browser.real_keys("a")
    wait_for_page_key(browser, "keydown:KeyA")
    shortcut(browser, letter)
    browser.real_keys("z")
    keys = wait_for_page_key(browser, "keydown:KeyZ")
    assert is_on(browser, attr)
    # The keyup may still arrive: preventDefault on the keydown covers the keydown and the keypress.
    assert not [
        k for k in keys if k in (f"keydown:Key{letter.upper()}", f"keypress:Key{letter.upper()}")
    ], keys


def test_a_page_that_stops_every_key_cannot_stop_the_shortcut(browser):
    """Adversarial: the handler is in the window and sees the key before any page does."""
    browser.new_window()
    open_page(browser, swallow=True)
    shortcut(browser, "t")
    assert is_on(browser, "autohide-tabs")


# --- nothing in the window gets in the way -------------------------------------------------------------

STOPS_KEYS_AT = {
    "the address field": "gURLBar.inputField",
    "the page": "gBrowser.selectedBrowser",
}


@pytest.mark.parametrize("where", STOPS_KEYS_AT)
def test_an_element_that_stops_keydown_propagation_cannot_stop_the_shortcut(browser, where):
    """Adversarial: the focused element stops the event for everything above it (a listener in the
    bubble phase, on the target). The handler is in the capture phase, so it has run before that."""
    browser.new_window()
    target = STOPS_KEYS_AT[where]
    browser.js(
        f"""window.__peekStopper = (event) => event.stopPropagation();
            {target}.addEventListener('keydown', window.__peekStopper);"""
    )
    try:
        if target == "gURLBar.inputField":
            browser.js("gURLBar.focus();")
            browser.wait("gURLBar.focused", 5, "the address field did not get the focus")
        else:
            browser.js("gBrowser.selectedBrowser.focus();")
        shortcut(browser, "t")
        assert is_on(browser, "autohide-tabs")
    finally:
        browser.js(f"{target}.removeEventListener('keydown', window.__peekStopper);")


def test_the_shortcut_is_consumed_and_other_keys_are_not(browser):
    """What a listener further down the path sees: ``defaultPrevented`` for the shortcut and only it."""
    browser.new_window()
    browser.js(
        """window.__peekSeen = [];
           window.__peekWatcher = (event) => window.__peekSeen.push([event.code, event.defaultPrevented]);
           window.addEventListener('keydown', window.__peekWatcher);  // bubble phase: after the handler
           gURLBar.focus();"""
    )
    try:
        browser.wait("gURLBar.focused", 5, "the address field did not get the focus")
        browser.real_keys("x", Keys.CONTROL, Keys.ALT)  # Ctrl+Alt+X belongs to nobody
        shortcut(browser, "t")
        seen = dict(
            browser.js(
                "return window.__peekSeen.filter(([code]) => code === 'KeyX' || code === 'KeyT');"
            )
        )
        assert seen == {"KeyX": False, "KeyT": True}
    finally:
        browser.js("window.removeEventListener('keydown', window.__peekWatcher);")
