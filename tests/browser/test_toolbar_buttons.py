"""The two toolbar buttons are toggles: each shows, in its own window, whether its bar is hidden."""

# ruff: noqa: E501  (the long lines are JavaScript snippets)

from __future__ import annotations

import pytest
from conftest import launched

pytestmark = pytest.mark.browser

TABS = ("tabs-autohide-button", "autohide-tabs")
URLBAR = ("urlbar-autohide-button", "autohide-urlbar")
NODE = "CustomizableUI.getWidget(arguments[0]).forWindow(window).node"


@pytest.fixture(autouse=True)
def clean(browser):
    browser.switch_to(browser.first_window)
    browser.js(
        "for (const attr of ['autohide-tabs', 'autohide-urlbar'])"
        " document.documentElement.removeAttribute(attr);"
    )
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


def pressed(browser, button: tuple[str, str]) -> str | None:
    """The ``checked`` attribute of this window's button."""
    return browser.js(f"return {NODE}.getAttribute('checked');", button[0])


def wait_pressed(browser, button: tuple[str, str], value: str | None) -> None:
    browser.wait(
        f"{NODE.replace('arguments[0]', repr(button[0]))}.getAttribute('checked') === "
        f"{'null' if value is None else repr(value)}",
        5,
        f"{button[0]} should be {'not pressed' if value is None else 'pressed'}",
    )


def test_a_button_is_pressed_while_its_bar_is_hidden_and_not_otherwise(browser):
    assert pressed(browser, TABS) is None and pressed(browser, URLBAR) is None
    browser.js("document.getElementById(arguments[0]).click();", TABS[0])
    wait_pressed(browser, TABS, "true")
    assert pressed(browser, URLBAR) is None  # the other button is not affected
    browser.js("document.getElementById(arguments[0]).click();", TABS[0])
    wait_pressed(browser, TABS, None)


def test_the_two_windows_have_their_own_state_on_their_own_buttons(browser):
    """The widget is shared by all windows; what the buttons show is not."""
    first = browser.first_window
    second = browser.new_window()
    browser.js("document.getElementById(arguments[0]).click();", TABS[0])  # in the second window
    wait_pressed(browser, TABS, "true")
    browser.keydown("KeyU")  # and its other bar, by the shortcut
    wait_pressed(browser, URLBAR, "true")

    browser.switch_to(first)
    assert pressed(browser, TABS) is None and pressed(browser, URLBAR) is None
    browser.keydown("KeyU")
    wait_pressed(browser, URLBAR, "true")

    browser.switch_to(second)
    browser.js("document.getElementById(arguments[0]).click();", TABS[0])
    wait_pressed(browser, TABS, None)
    assert pressed(browser, URLBAR) == "true"  # still its own
    browser.switch_to(first)
    assert pressed(browser, TABS) is None and pressed(browser, URLBAR) == "true"


def test_the_state_is_the_attribute_of_the_window_however_it_changed(browser):
    """Adversarial: the shortcut, a restored session or anything else that sets the attribute."""
    browser.js("document.documentElement.setAttribute('autohide-urlbar', '');")
    wait_pressed(browser, URLBAR, "true")
    browser.js("document.documentElement.removeAttribute('autohide-urlbar');")
    wait_pressed(browser, URLBAR, None)


def test_a_restored_window_state_presses_the_button(browser):
    """What SessionStore does after a restore: it saves the values, then announces the state."""
    browser.new_window()
    browser.js(
        "SessionStore.setCustomWindowValue(window, 'autohideTabs', '1');"
        "window.dispatchEvent(new Event('SSWindowStateReady'));"
    )
    wait_pressed(browser, TABS, "true")
    browser.js(
        "SessionStore.setCustomWindowValue(window, 'autohideTabs', '0');"
        "window.dispatchEvent(new Event('SSWindowStateReady'));"
    )
    wait_pressed(browser, TABS, None)


def test_the_attribute_is_removed_not_set_to_false(browser):
    """Adversarial: Firefox draws any ``checked`` attribute as pressed, even ``checked="false"``."""
    browser.js("document.documentElement.setAttribute('autohide-tabs', '');")
    wait_pressed(browser, TABS, "true")
    browser.js("document.documentElement.removeAttribute('autohide-tabs');")
    wait_pressed(browser, TABS, None)
    assert not browser.js(f"return {NODE}.hasAttribute('checked');", TABS[0])


def test_a_button_that_is_moved_in_customize_toolbar_stays_pressed(browser):
    """Adversarial: the button is taken out of its bar and put back (Customize Toolbar does that)."""
    browser.js("document.documentElement.setAttribute('autohide-tabs', '');")
    wait_pressed(browser, TABS, "true")
    where = browser.js("return CustomizableUI.getPlacementOfWidget(arguments[0]);", TABS[0])
    try:
        browser.js("CustomizableUI.removeWidgetFromArea(arguments[0]);", TABS[0])
        browser.wait(f"!{NODE.replace('arguments[0]', repr(TABS[0]))}.parentNode", 5)
        browser.js(
            "CustomizableUI.addWidgetToArea(arguments[0], arguments[1], arguments[2]);",
            TABS[0],
            where["area"],
            where["position"],
        )
        browser.wait(
            f"document.getElementById({TABS[0]!r})", 5, "the button did not come back to its bar"
        )
        wait_pressed(browser, TABS, "true")
    finally:
        browser.js("document.documentElement.removeAttribute('autohide-tabs');")


def test_a_pressed_button_looks_pressed(browser):
    look = """
      const icon = document.getElementById(arguments[0]).querySelector('.toolbarbutton-icon');
      return getComputedStyle(icon).backgroundColor;"""
    plain = browser.js(look, TABS[0])
    browser.js("document.documentElement.setAttribute('autohide-tabs', '');")
    wait_pressed(browser, TABS, "true")
    assert browser.js(look, TABS[0]) != plain
    assert browser.js(look, URLBAR[0]) == plain  # and only that button


# --- a window that starts with its bar hidden ---------------------------------------------------


@pytest.fixture(scope="module")
def browser_that_starts_hidden(firefox_install, tmp_path_factory):
    """The setting "hide the tab bar in new windows" is on before the first window opens."""
    start = 'user_pref("peekafoxy.tabs.autohide", true);\n'
    with launched(firefox_install, tmp_path_factory.mktemp("hidden"), start) as helper:
        yield helper


def test_the_buttons_of_a_window_that_starts_hidden_start_pressed(browser_that_starts_hidden):
    """The first window applies the state before it has made the buttons, the next ones after."""
    browser = browser_that_starts_hidden
    assert browser.js("return document.documentElement.hasAttribute('autohide-tabs');")
    wait_pressed(browser, TABS, "true")
    assert pressed(browser, URLBAR) is None
    browser.new_window()
    wait_pressed(browser, TABS, "true")
    assert pressed(browser, URLBAR) is None


# --- what assistive technology is told ----------------------------------------------------------


@pytest.fixture(scope="module")
def browser_with_accessibility(firefox_install, tmp_path_factory):
    """A Firefox of its own: once the accessibility service starts it stays on until Firefox quits."""
    with launched(firefox_install, tmp_path_factory.mktemp("accessibility")) as helper:
        yield helper


ACCESSIBLE_STATE = """
  const service = Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService);
  const node = CustomizableUI.getWidget(arguments[0]).forWindow(window).node;
  const accessible = service.getAccessibleFor(node);
  if (!accessible) return null;
  const state = {}, extra = {};
  accessible.getState(state, extra);
  return {pressed: Boolean(state.value & Ci.nsIAccessibleStates.STATE_PRESSED), name: accessible.name};
"""


def test_a_screen_reader_is_told_that_the_button_is_pressed(browser_with_accessibility):
    browser = browser_with_accessibility
    browser.js("Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService);")
    # The accessibility tree is built a moment after the service starts.
    browser.wait(
        f"(() => {{ {ACCESSIBLE_STATE.replace('arguments[0]', repr(TABS[0]))} }})() !== null",
        15,
        "no accessible for the toolbar button",
    )
    off = browser.js(ACCESSIBLE_STATE, TABS[0])
    browser.js("document.documentElement.setAttribute('autohide-tabs', '');")
    browser.wait(
        f"(() => {{ {ACCESSIBLE_STATE.replace('arguments[0]', repr(TABS[0]))} }})().pressed", 5
    )
    on = browser.js(ACCESSIBLE_STATE, TABS[0])
    assert (off["pressed"], on["pressed"]) == (False, True)
    assert on["name"] == off["name"] == "Auto-hide the tab bar"
