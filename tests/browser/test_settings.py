"""The Peek-a-Foxy category in about:preferences, and the live effect of its settings."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

PREF_PREFIX = "peekafoxy."
KEYDOWN_IN_PAGE = """
  const input = doc.getElementById(arguments[0]);
  input.focus();
  input.dispatchEvent(new win.KeyboardEvent('keydown', {
    key: arguments[1], code: arguments[2], ctrlKey: arguments[3].includes('c'),
    altKey: arguments[3].includes('a'), shiftKey: arguments[3].includes('s'),
    metaKey: arguments[3].includes('m'), bubbles: true, cancelable: true,
  }));
  return input.closest('div').parentNode.querySelector('.pf-problem').textContent;
"""
PANE = "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-pane')"
FIELD = "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-%s')"
KEYDOWN = """
  window.dispatchEvent(new KeyboardEvent('keydown',
    {code: arguments[0], ctrlKey: true, altKey: true, bubbles: true, cancelable: true}));
"""
OPEN_TAB = (
    "gBrowser.addTab('about:blank', "
    "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});"
)
HAS = "document.documentElement.hasAttribute(arguments[0])"


@pytest.fixture(autouse=True)
def clean(browser):
    """Every test starts and ends with no user values, no settings tab and the first window."""

    def reset() -> None:
        browser.switch_to(browser.first_window)
        browser.close_settings_tabs()
        browser.js(
            """for (const name of Services.prefs.getChildList('peekafoxy.')) {
                 if (name !== 'peekafoxy.welcomed') Services.prefs.clearUserPref(name);
               }
               for (const attr of ['autohide-tabs', 'autohide-urlbar'])
                 document.documentElement.removeAttribute(attr);"""
        )

    reset()
    yield
    reset()


def root_var(browser, name: str) -> str:
    return browser.js("return document.documentElement.style.getPropertyValue(arguments[0]);", name)


# --- the category -------------------------------------------------------------------------------


def test_the_category_is_listed_and_opens_its_pane_from_the_address(browser):
    browser.open_settings("#peekafoxy")
    browser.wait(
        f"{PANE}?.hidden === false",
        10,
        "the pane did not open at #peekafoxy",
    )
    shown = browser.settings(
        """return {
             current: doc.getElementById('categories').currentView,
             label: doc.getElementById('category-peekafoxy').textContent.trim(),
             hash: doc.location.hash,
             visible: [...doc.querySelectorAll('#mainPrefPane > [data-category]')]
               .filter(e => !e.hidden).map(e => e.getAttribute('data-category')),
           };"""
    )
    assert shown == {
        "current": "panePeekafoxy",
        "label": "Peek-a-Foxy",
        "hash": "#peekafoxy",
        "visible": ["panePeekafoxy"],
    }


def test_clicking_the_category_and_leaving_it_works_like_any_other(browser):
    browser.open_settings()
    browser.settings("doc.getElementById('category-peekafoxy').activate();")
    browser.wait(
        f"{PANE}.hidden === false",
        message="clicking the category did not show the pane",
    )
    assert browser.settings("return doc.location.hash;") == "#peekafoxy"

    browser.settings("doc.getElementById('category-downloads').activate();")
    browser.wait(
        f"{PANE}.hidden === true",
        message="our pane stayed open in another category",
    )
    assert browser.settings("return doc.location.hash;") == "#downloads"


def test_firefoxs_own_categories_are_untouched(browser):
    browser.open_settings("#downloads")
    count = browser.settings(
        "return doc.querySelectorAll('#categories moz-page-nav-button').length;"
    )
    assert browser.settings(
        "return doc.getElementById('category-downloads').getAttribute('view');"
    ) == ("paneDownloads")
    assert count > 5
    assert browser.settings("return doc.getElementById('peekafoxy-pane').hidden;") is True


def test_the_controls_show_the_current_prefs(browser):
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 20);")
    browser.open_settings("#peekafoxy")
    shown = browser.settings(
        """const v = (id) => doc.getElementById(id);
           return {strip: v('peekafoxy-peekafoxy.strip.px').value,
                   show: v('peekafoxy-peekafoxy.show.ms').value,
                   hide: v('peekafoxy-peekafoxy.hide.delay.ms').value,
                   flash: v('peekafoxy-peekafoxy.tabs.flash.ms').value,
                   tabs: v('peekafoxy-peekafoxy.tabs.shortcut').value,
                   urlbar: v('peekafoxy-peekafoxy.urlbar.shortcut').value,
                   startTabs: v('peekafoxy-peekafoxy.tabs.autohide').checked};"""
    )
    assert shown == {
        "strip": "20",
        "show": "120",
        "hide": "300",
        "flash": "1500",
        "tabs": "Ctrl+Alt+T",
        "urlbar": "Ctrl+Alt+U",
        "startTabs": False,
    }


def test_a_pref_changed_elsewhere_updates_the_open_page(browser):
    browser.open_settings("#peekafoxy")
    browser.js("Services.prefs.setIntPref('peekafoxy.show.ms', 400);")
    browser.wait(
        f"{FIELD % 'peekafoxy.show.ms'}.value === '400'",
        message="the page did not follow about:config",
    )


# --- editing a number ----------------------------------------------------------------------------


def set_number(browser, pref: str, value: str) -> str:
    return browser.settings(
        """const input = doc.getElementById('peekafoxy-' + arguments[0]);
           input.value = arguments[1];
           input.dispatchEvent(new win.Event('change', {bubbles: true}));
           return input.closest('div').parentNode.querySelector('.pf-problem').textContent;""",
        pref,
        value,
    )


def test_a_number_is_saved_as_a_real_pref(browser):
    browser.open_settings("#peekafoxy")
    assert set_number(browser, "peekafoxy.hide.delay.ms", "750") == ""
    assert browser.js("return Services.prefs.getIntPref('peekafoxy.hide.delay.ms');") == 750


@pytest.mark.parametrize("bad", ["", "abc", "-1", "41", "3.5", "1e2", "999999"])
def test_a_bad_number_is_refused_with_a_message_and_changes_nothing(browser, bad):
    browser.open_settings("#peekafoxy")
    message = set_number(browser, "peekafoxy.strip.px", bad)
    assert message == "Enter a number between 1 and 40."
    assert not browser.js("return Services.prefs.prefHasUserValue('peekafoxy.strip.px');")
    assert (
        browser.settings("return doc.getElementById('peekafoxy-peekafoxy.strip.px').value;") == "8"
    )


def test_reset_puts_the_default_back_and_is_disabled_without_a_user_value(browser):
    browser.open_settings("#peekafoxy")
    button = (
        "return doc.getElementById('peekafoxy-peekafoxy.strip.px').closest('.pf-row')"
        ".querySelector('button')"
    )
    assert browser.settings(button + ".disabled;") is True
    set_number(browser, "peekafoxy.strip.px", "20")
    browser.wait(
        "!gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-peekafoxy.strip.px')"
        ".closest('.pf-row').querySelector('button').disabled"
    )
    browser.settings(button + ".click();")
    assert not browser.js("return Services.prefs.prefHasUserValue('peekafoxy.strip.px');")


# --- applied live, in every window ---------------------------------------------------------------


def test_the_strip_height_applies_to_every_open_window_at_once(browser):
    first = browser.first_window
    second = browser.new_window()
    browser.switch_to(first)
    browser.open_settings("#peekafoxy")
    assert set_number(browser, "peekafoxy.strip.px", "20") == ""
    for window in (first, second):
        browser.switch_to(window)
        browser.wait(
            "document.documentElement.style.getPropertyValue('--autohide-strip') === '20px'",
            message=f"window {window} did not get the new strip height",
        )
    browser.switch_to(first)
    browser.close_settings_tabs()
    browser.switch_to(second)
    browser.js("window.close();")
    browser.switch_to(first)


def test_the_strip_height_really_changes_how_far_a_bar_collapses(browser):
    browser.js("document.documentElement.setAttribute('autohide-tabs', '');")
    browser.wait("document.getElementById('TabsToolbar').getBoundingClientRect().height <= 8")
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 20);")
    browser.wait(
        "Math.round(document.getElementById('TabsToolbar').getBoundingClientRect().height) === 20",
        8,
        "the tab bar did not collapse to the new strip height",
    )
    browser.js("Services.prefs.clearUserPref('peekafoxy.strip.px');")
    browser.wait("document.getElementById('TabsToolbar').getBoundingClientRect().height <= 8", 8)


def test_without_a_user_value_the_variable_is_left_to_the_stylesheet(browser):
    assert root_var(browser, "--autohide-strip") == ""
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 12);")
    browser.wait("document.documentElement.style.getPropertyValue('--autohide-strip') === '12px'")
    browser.js("Services.prefs.clearUserPref('peekafoxy.strip.px');")
    browser.wait("document.documentElement.style.getPropertyValue('--autohide-strip') === ''")


def test_the_timings_are_applied_as_css_variables(browser):
    browser.js(
        "Services.prefs.setIntPref('peekafoxy.show.ms', 250);"
        "Services.prefs.setIntPref('peekafoxy.hide.delay.ms', 900);"
    )
    browser.wait(
        "document.documentElement.style.getPropertyValue('--autohide-show-duration') === '250ms'"
    )
    assert root_var(browser, "--autohide-hide-delay") == "900ms"
    computed = browser.js(
        "return getComputedStyle(document.documentElement)"
        ".getPropertyValue('--autohide-hide').trim();"
    )
    assert computed == "0.2s ease-in 900ms"
    assert "250ms" in browser.js(
        "return getComputedStyle(document.documentElement).getPropertyValue('--autohide-show');"
    )


def test_a_garbage_value_in_a_number_pref_is_clamped_not_trusted(browser):
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 100000);")
    browser.wait("document.documentElement.style.getPropertyValue('--autohide-strip') === '40px'")
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', -5);")
    browser.wait("document.documentElement.style.getPropertyValue('--autohide-strip') === '1px'")


def test_the_flash_time_comes_from_the_pref(browser):
    browser.js("Services.prefs.setIntPref('peekafoxy.tabs.flash.ms', 0);")
    browser.js(OPEN_TAB)
    browser.wait("!document.documentElement.hasAttribute('tabs-flash')", 3)
    assert not browser.js("return document.documentElement.hasAttribute('tabs-flash');")
    browser.js("Services.prefs.setIntPref('peekafoxy.tabs.flash.ms', 4000);")
    browser.js(OPEN_TAB)
    assert browser.js("return document.documentElement.hasAttribute('tabs-flash');")
    browser.js(
        "for (const tab of [...gBrowser.tabs].slice(1)) gBrowser.removeTab(tab);"
        "document.documentElement.removeAttribute('tabs-flash');"
    )


def test_the_starting_state_of_new_windows_comes_from_the_checkboxes(browser):
    browser.open_settings("#peekafoxy")
    browser.settings(
        """const box = doc.getElementById('peekafoxy-peekafoxy.urlbar.autohide');
           box.checked = true; box.dispatchEvent(new win.Event('change', {bubbles: true}));"""
    )
    assert browser.js("return Services.prefs.getBoolPref('peekafoxy.urlbar.autohide');")
    browser.close_settings_tabs()
    second = browser.new_window()
    assert browser.js(f"return {HAS};", "autohide-urlbar")
    assert not browser.js(f"return {HAS};", "autohide-tabs")
    browser.js("window.close();")
    browser.switch_to(browser.first_window)
    assert second


# --- shortcuts -----------------------------------------------------------------------------------


def record(browser, field: str, key: str, code: str, mods: str) -> str:
    return browser.settings(
        KEYDOWN_IN_PAGE, f"peekafoxy-peekafoxy.{field}.shortcut", key, code, mods
    )


def test_a_recorded_shortcut_replaces_the_old_one_in_every_window(browser):
    browser.open_settings("#peekafoxy")
    assert record(browser, "tabs", "g", "KeyG", "ca") == ""
    assert (
        browser.js("return Services.prefs.getStringPref('peekafoxy.tabs.shortcut');")
        == "Ctrl+Alt+G"
    )
    browser.close_settings_tabs()

    browser.js(KEYDOWN, "KeyT")  # the old one does nothing now
    assert not browser.js(f"return {HAS};", "autohide-tabs")
    browser.js(KEYDOWN, "KeyG")
    assert browser.js(f"return {HAS};", "autohide-tabs")
    assert "Ctrl+Alt+G" in browser.js(
        "return CustomizableUI.getWidget('tabs-autohide-button').forWindow(window).node"
        ".getAttribute('tooltiptext');"
    )


@pytest.mark.parametrize(
    ("key", "code", "mods", "message"),
    [
        ("g", "KeyG", "", "Include Ctrl, Alt or Meta."),
        ("g", "KeyG", "s", "Include Ctrl, Alt or Meta."),
        ("Enter", "Enter", "ca", "That key cannot be used."),
        ("ArrowUp", "ArrowUp", "ca", "That key cannot be used."),
        ("u", "KeyU", "ca", "The other bar already uses this shortcut."),
    ],
)
def test_a_bad_shortcut_is_refused_with_a_message_and_changes_nothing(
    browser, key, code, mods, message
):
    browser.open_settings("#peekafoxy")
    assert record(browser, "tabs", key, code, mods) == message
    assert not browser.js("return Services.prefs.prefHasUserValue('peekafoxy.tabs.shortcut');")


def test_pressing_only_a_modifier_waits_and_tab_still_leaves_the_field(browser):
    browser.open_settings("#peekafoxy")
    assert record(browser, "tabs", "Control", "ControlLeft", "c") == ""
    assert record(browser, "tabs", "Tab", "Tab", "") == ""
    assert not browser.js("return Services.prefs.prefHasUserValue('peekafoxy.tabs.shortcut');")


def test_a_shortcut_that_is_garbage_in_the_pref_falls_back_to_the_default(browser):
    browser.js("Services.prefs.setStringPref('peekafoxy.tabs.shortcut', 'Ctrl+Nonsense+');")
    browser.wait("Services.prefs.getStringPref('peekafoxy.tabs.shortcut') === 'Ctrl+Nonsense+'")
    browser.js(KEYDOWN, "KeyT")
    assert browser.js(f"return {HAS};", "autohide-tabs")


def test_the_two_bars_can_swap_their_shortcuts(browser):
    browser.open_settings("#peekafoxy")
    assert record(browser, "tabs", "g", "KeyG", "ca") == ""
    assert record(browser, "urlbar", "t", "KeyT", "ca") == ""  # free now
    browser.close_settings_tabs()
    browser.js(KEYDOWN, "KeyT")
    assert browser.js(f"return {HAS};", "autohide-urlbar")
    assert not browser.js(f"return {HAS};", "autohide-tabs")


# --- the greeting --------------------------------------------------------------------------------


def test_show_the_greeting_again_resets_the_pref_for_the_next_window(browser):
    assert browser.js("return Services.prefs.getBoolPref('peekafoxy.welcomed');") is True
    browser.open_settings("#peekafoxy")
    browser.settings("doc.getElementById('peekafoxy-greeting').click();")
    assert browser.js("return Services.prefs.getBoolPref('peekafoxy.welcomed');") is False
    assert "next window" in browser.settings(
        "return doc.getElementById('peekafoxy-greeting').parentNode"
        ".querySelector('.pf-note').textContent;"
    )
    browser.close_settings_tabs()
    browser.new_window()
    browser.wait(
        "[...window.gNotificationBox.allNotifications]"
        ".some(n => n.getAttribute('value') === 'peekafoxy-welcome')",
        message="the greeting did not come back",
    )
    browser.js("window.close();")
    browser.switch_to(browser.first_window)


# --- languages and a Firefox that changed --------------------------------------------------------


def test_the_page_is_in_portuguese_for_a_portuguese_firefox(browser_in_portuguese):
    browser = browser_in_portuguese
    browser.open_settings("#peekafoxy")
    texts = browser.settings(
        """return {
             group: [...doc.querySelectorAll('#peekafoxy-pane h2')].map(h => h.textContent),
             start: doc.getElementById('peekafoxy-peekafoxy.tabs.autohide')
               .closest('label').textContent.trim(),
             reset: doc.querySelector('#peekafoxy-pane button').textContent,
           };"""
    )
    assert texts == {
        "group": [
            "Novas janelas",
            "Revelar a barra de abas quando",
            "Tamanho e tempos",
            "Atalhos",
            "Saudação",
        ],
        "start": "Ocultar a barra de abas automaticamente em novas janelas",
        "reset": "Restaurar",
    }
    message = browser.settings(
        """const input = doc.getElementById('peekafoxy-peekafoxy.strip.px');
           input.value = '99'; input.dispatchEvent(new win.Event('change', {bubbles: true}));
           return input.closest('div').parentNode.querySelector('.pf-problem').textContent;"""
    )
    assert message == "Digite um número entre 1 e 40."
    browser.close_settings_tabs()


def test_when_firefox_changes_the_page_nothing_breaks_and_the_console_says_why(
    browser_with_a_changed_settings_page,
):
    browser = browser_with_a_changed_settings_page
    browser.open_settings("#peekafoxy")
    browser.wait(
        "gBrowser.selectedBrowser.contentDocument.getElementById('category-downloads')", 10
    )
    assert browser.settings("return doc.getElementById('category-peekafoxy');") is None
    assert browser.settings("return doc.getElementById('peekafoxy-pane');") is None
    # Firefox's own page still works, and the toolbar part of Peek-a-Foxy is unaffected.
    browser.settings("doc.getElementById('category-downloads').activate();")
    browser.wait("gBrowser.selectedBrowser.contentDocument.location.hash === '#downloads'")
    messages = browser.js(
        """const storage = Cc["@mozilla.org/consoleAPI-storage;1"]
             .getService(Ci.nsIConsoleAPIStorage);
           return storage.getEvents().filter(e => e.level === "warn")
             .map(e => e.arguments.map(String).join(" "))
             .filter(m => m.includes("peekafoxy settings"));"""
    )
    # The warning names what was missing, so a bug report says what Firefox changed.
    assert any("#mainPrefPane-renamed" not in m and "#mainPrefPane" in m for m in messages), (
        messages
    )
    assert browser.js("return !!document.getElementById('tabs-autohide-button');") is True
    browser.close_settings_tabs()


def test_prefs_are_real_and_listed_with_their_types(browser):
    types = browser.js(
        """const out = {};
           for (const name of Services.prefs.getChildList('peekafoxy.'))
             out[name] = Services.prefs.getPrefType(name);
           return out;"""
    )
    kinds = {128: "bool", 64: "int", 32: "string"}
    assert {name: kinds[kind] for name, kind in types.items()} == {
        "peekafoxy.tabs.autohide": "bool",
        "peekafoxy.urlbar.autohide": "bool",
        "peekafoxy.strip.px": "int",
        "peekafoxy.show.ms": "int",
        "peekafoxy.hide.delay.ms": "int",
        "peekafoxy.tabs.flash.ms": "int",
        "peekafoxy.tabs.reveal.switch": "bool",
        "peekafoxy.tabs.reveal.new": "bool",
        "peekafoxy.tabs.reveal.link": "bool",
        "peekafoxy.tabs.shortcut": "string",
        "peekafoxy.urlbar.shortcut": "string",
        "peekafoxy.welcomed": "bool",
    }


def test_reduced_motion_still_wins_over_the_timing_settings(browser):
    browser.js(
        "Services.prefs.setIntPref('ui.prefersReducedMotion', 1);"
        "Services.prefs.setIntPref('peekafoxy.show.ms', 900);"
        "Services.prefs.setIntPref('peekafoxy.hide.delay.ms', 700);"
    )
    try:
        browser.wait(
            "document.documentElement.style.getPropertyValue("
            "'--autohide-show-duration') === '900ms'"
        )
        computed = browser.js(
            "const s = getComputedStyle(document.documentElement);"
            "return [s.getPropertyValue('--autohide-show').trim(),"
            " s.getPropertyValue('--autohide-hide').trim()];"
        )
        assert computed == ["0s", "0s 700ms"]  # instant to open, only the closing delay is kept
    finally:
        browser.js("Services.prefs.clearUserPref('ui.prefersReducedMotion');")


@pytest.mark.parametrize("name", ["switch", "new", "link"])
def test_the_reveal_checkboxes_start_on_and_write_real_prefs(browser, name):
    pref = f"peekafoxy.tabs.reveal.{name}"
    browser.open_settings("#peekafoxy")
    box = f"doc.getElementById('peekafoxy-{pref}')"
    assert browser.settings(f"return {box}.checked;") is True
    browser.settings(f"{box}.checked = false; {box}.dispatchEvent(new win.Event('change'));")
    assert browser.js("return Services.prefs.getBoolPref(arguments[0]);", pref) is False
    browser.js("Services.prefs.setBoolPref(arguments[0], true);", pref)
    browser.wait(f"{FIELD % pref}.checked === true", message="the box did not follow the pref")
