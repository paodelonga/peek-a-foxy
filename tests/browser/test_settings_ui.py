"""The settings page as a person uses it: recording a shortcut, the keyboard, the language, announcements.

Kept apart from test_settings.py, which checks what the page writes. Here the keys are real where it
matters: ``real_keys`` goes through Firefox's own key handling (a chain of Marionette actions), the
path a person's keyboard takes, which a ``dispatchEvent`` on the window or on the field skips.
"""

# ruff: noqa: E501  (the long lines are JavaScript snippets)

from __future__ import annotations

import time

import pytest
from marionette_driver.keys import Keys

pytestmark = pytest.mark.browser

TABS_FIELD = "peekafoxy-peekafoxy.tabs.shortcut"
URLBAR_FIELD = "peekafoxy-peekafoxy.urlbar.shortcut"
STRIP_FIELD = "peekafoxy-peekafoxy.strip.px"
PROMPT = "Click here, then press the new shortcut"
HAS = "document.documentElement.hasAttribute(arguments[0])"
PEEK = "ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs')"
FOCUS = "doc.getElementById(arguments[0]).focus();"
PROBLEM = """
  const input = doc.getElementById(arguments[0]);
  return input.closest('div').parentNode.querySelector('.pf-problem').textContent;
"""
SYNTHETIC_KEY = """
  const input = doc.getElementById(arguments[0]);
  input.focus();
  input.dispatchEvent(new win.KeyboardEvent('keydown', {
    key: arguments[1], code: arguments[2], ctrlKey: arguments[3].includes('c'),
    altKey: arguments[3].includes('a'), shiftKey: arguments[3].includes('s'),
    metaKey: false, bubbles: true, cancelable: true,
  }));
"""


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
               Services.prefs.clearUserPref('intl.uidirection');
               Services.prefs.clearUserPref('intl.l10n.pseudo');
               for (const attr of ['autohide-tabs', 'autohide-urlbar'])
                 document.documentElement.removeAttribute(attr);"""
        )

    reset()
    yield
    reset()


def real_keys(browser, key: str, *modifiers: str) -> None:
    """Press ``key`` with ``modifiers`` the way a keyboard does: through Firefox's key handling."""
    browser.real_keys(key, *modifiers)


def problem_under(browser, field_id: str, settle: float = 0.6) -> str:
    """The message under a field, which is announced a moment after the change (see ``announce``)."""
    deadline = time.monotonic() + settle
    while True:
        text = browser.settings(PROBLEM, field_id)
        if text or time.monotonic() >= deadline:
            return text
        time.sleep(0.05)


def pref_has_value(browser, name: str) -> bool:
    return browser.js("return Services.prefs.prefHasUserValue(arguments[0]);", name)


def tabs_bar_hidden(browser) -> bool:
    return browser.js(f"return {HAS};", "autohide-tabs")


# --- the recorder and the shortcut handler of the window ----------------------------------------


def test_a_real_shortcut_pressed_while_recording_does_not_toggle_the_bar(browser):
    """Default path, real keys: choosing its own shortcut in its field must not hide the tab bar."""
    browser.open_settings("#peekafoxy")
    browser.settings(FOCUS, TABS_FIELD)
    browser.real_shortcut("tabs")
    assert not tabs_bar_hidden(browser)
    assert problem_under(browser, TABS_FIELD, settle=0.2) == ""  # recorded, as far as it can be


def test_the_other_bars_shortcut_pressed_while_recording_toggles_neither(browser):
    """Adversarial: the refused shortcut is refused by the field and used by nobody."""
    browser.open_settings("#peekafoxy")
    browser.settings(FOCUS, TABS_FIELD)
    browser.real_shortcut("urlbar")
    assert problem_under(browser, TABS_FIELD) == "The other bar already uses this shortcut."
    assert not tabs_bar_hidden(browser)
    assert not browser.js(f"return {HAS};", "autohide-urlbar")


def test_the_shortcut_works_again_once_the_field_is_left(browser):
    """The control for the test above: the same keys toggle the bar when no field is recording."""
    browser.open_settings("#peekafoxy")
    browser.settings(FOCUS, TABS_FIELD)
    browser.real_shortcut("tabs")
    assert not tabs_bar_hidden(browser)
    browser.settings("doc.getElementById(arguments[0]).blur();", TABS_FIELD)
    browser.real_shortcut("tabs")
    assert tabs_bar_hidden(browser)


def test_moving_from_one_field_to_the_other_keeps_recording_and_then_stops(browser):
    browser.open_settings("#peekafoxy")
    browser.settings(FOCUS, TABS_FIELD)
    browser.settings(FOCUS, URLBAR_FIELD)
    browser.real_shortcut("tabs")
    assert not tabs_bar_hidden(browser)
    browser.settings("doc.activeElement.blur();")
    browser.real_shortcut("tabs")
    assert tabs_bar_hidden(browser)


def test_closing_the_settings_tab_while_recording_gives_the_shortcut_back(browser):
    """Adversarial: no blur is ever delivered to a page that is closed with the focus in it."""
    browser.open_settings("#peekafoxy")
    browser.settings(FOCUS, TABS_FIELD)
    browser.close_settings_tabs()
    browser.real_shortcut("tabs")
    assert tabs_bar_hidden(browser)


def test_leaving_the_settings_tab_while_recording_gives_the_shortcut_back(browser):
    """Adversarial: the field is still the focused element of a page that is in the background."""
    browser.open_settings("#peekafoxy")
    browser.settings(FOCUS, TABS_FIELD)
    browser.js("gBrowser.selectedTab = gBrowser.tabs[0];")
    browser.real_shortcut("tabs")
    assert tabs_bar_hidden(browser)


def test_a_field_that_is_gone_or_not_focused_is_not_recording(browser):
    """Adversarial, on the module itself: a field counts only while it is in its page and focused."""
    browser.open_settings("#peekafoxy")
    answers = browser.diag(
        """const doc = gBrowser.selectedBrowser.contentDocument;
           const field = doc.getElementById(arguments[0]), other = doc.getElementById(arguments[1]);
           const out = {};
           Peek.Recorder.blurred(document.createElement('input'));   // a blur that never had a focus
           out.nobody = Peek.Recorder.isRecording();
           Peek.Recorder.focused(document.createElement('input'));   // never in a page
           out.detached = Peek.Recorder.isRecording();
           Peek.Recorder.focused(other);                              // told so, but it is not the focus
           out.not_focused = Peek.Recorder.isRecording();
           field.focus();                                             // the page tells the module itself
           out.focused = Peek.Recorder.isRecording();
           field.remove();                                            // gone from its page, no blur
           out.removed = Peek.Recorder.isRecording();
           return out;""",
        TABS_FIELD,
        URLBAR_FIELD,
    )
    assert answers == {
        "nobody": False,
        "detached": False,
        "not_focused": False,
        "focused": True,
        "removed": False,
    }


# --- what Firefox already uses -------------------------------------------------------------------


def lookup(browser, text: str, os: str = "Linux"):
    return browser.diag(
        "return Peek.firefoxShortcut(window, arguments[0], arguments[1]);", text, os
    )


@pytest.mark.parametrize(
    ("text", "key_id", "label"),
    [
        ("Ctrl+W", "key_close", "Close Tab"),
        ("Ctrl+T", "key_newNavigatorTab", "New Tab"),
        ("Ctrl+Shift+W", "key_closeWindow", None),
    ],
)
def test_firefoxs_own_shortcut_is_found_with_its_name(browser, text, key_id, label):
    found = lookup(browser, text)
    assert found is not None and found["id"] == key_id
    if label is not None:
        assert found["label"] == label


def test_a_shortcut_that_firefox_does_not_use_is_not_reported(browser):
    assert lookup(browser, "Ctrl+Alt+Shift+F11") is None


@pytest.mark.parametrize(
    "text", ["", "Ctrl", "Ctrl+", "+W", "Ctrl+Ctrl+W", "W", "Shift+W", "Ctrl+Nonsense"]
)
def test_a_text_that_is_not_a_shortcut_is_not_reported_and_does_not_throw(browser, text):
    """Adversarial."""
    assert lookup(browser, text) is None


FAKE_FIREFOX = """
  // A window with the keys that are given: [{id, key, keycode, modifiers, disabled, command}] and the
  // items that show them: [{key: id, label}] and the commands: {id: label}.
  const fake = (keys, items = [], commands = {}) => {
    const element = (attrs, name) => ({
      id: attrs.id ?? '', localName: name, getAttribute: (n) => attrs[n] ?? null,
    });
    const keyElements = keys.map((k) => element(k, 'key'));
    const itemElements = items.map((i) => element({key: i.key, label: i.label}, 'menuitem'));
    return {document: {
      getElementById: (id) => id === 'mainKeyset' ? {querySelectorAll: () => keyElements}
        : (id in commands ? element({label: commands[id]}, 'command') : null),
      querySelectorAll: () => [...keyElements, ...itemElements],
    }};
  };
"""


@pytest.mark.parametrize(
    ("keys", "text", "os", "expected"),
    [
        (
            [{"id": "a", "key": "w", "modifiers": "accel"}],
            "Ctrl+W",
            "Linux",
            "a",
        ),  # a lower-case key
        (
            [{"id": "a", "key": "W", "modifiers": "accel"}],
            "Meta+W",
            "Darwin",
            "a",
        ),  # accel is Cmd there
        ([{"id": "a", "key": "W", "modifiers": "accel"}], "Ctrl+W", "Darwin", None),
        ([{"id": "a", "key": "W", "modifiers": "accel"}], "Meta+W", "Linux", None),
        (
            [{"id": "a", "key": "W", "modifiers": "control alt"}],
            "Ctrl+Alt+W",
            "Linux",
            "a",
        ),  # spaces
        (
            [{"id": "a", "key": "W", "modifiers": "alt,control"}],
            "Ctrl+Alt+W",
            "Linux",
            "a",
        ),  # any order
        (
            [{"id": "a", "key": "W", "modifiers": "accel,shift"}],
            "Ctrl+W",
            "Linux",
            None,
        ),  # not a subset
        ([{"id": "a", "key": "W", "modifiers": "accel"}], "Ctrl+Shift+W", "Linux", None),
        (
            [{"id": "a", "key": "W", "modifiers": "accel", "disabled": "true"}],
            "Ctrl+W",
            "Linux",
            None,
        ),
        ([{"id": "a", "keycode": "VK_F5", "modifiers": "accel"}], "Ctrl+F5", "Linux", "a"),
        ([{"id": "a", "keycode": "VK_F5", "modifiers": "accel"}], "Ctrl+F6", "Linux", None),
        ([{"id": "a", "keycode": "VK_RETURN", "modifiers": "accel"}], "Ctrl+W", "Linux", None),
        (
            [{"id": "a", "key": "", "modifiers": "accel"}],
            "Ctrl+W",
            "Linux",
            None,
        ),  # an empty alternative
        ([{"id": "a", "key": "WW", "modifiers": "accel"}], "Ctrl+W", "Linux", None),
        ([{"id": "a", "key": "W"}], "Ctrl+W", "Linux", None),  # no modifiers: a bare W
        ([{"id": "a", "key": "W", "modifiers": "os"}], "Meta+W", "Linux", "a"),
        ([{"id": "a", "key": "W", "modifiers": "ACCEL"}], "Ctrl+W", "Linux", "a"),
        (
            [{"id": "", "key": "W", "modifiers": "accel", "command": "cmd_x"}],
            "Ctrl+W",
            "Linux",
            "cmd_x",
        ),
    ],
)
def test_the_lookup_reads_firefoxs_key_elements_the_way_firefox_does(
    browser, keys, text, os, expected
):
    found = browser.diag(
        FAKE_FIREFOX
        + "return Peek.firefoxShortcut(fake(arguments[0]), arguments[1], arguments[2]);",
        keys,
        text,
        os,
    )
    assert (found["id"] if found else None) == expected


def test_the_name_comes_from_the_menu_item_then_from_the_command_and_may_be_missing(browser):
    keys = [{"id": "k", "key": "W", "modifiers": "accel", "command": "cmd_k"}]
    call = FAKE_FIREFOX + "return Peek.firefoxShortcut(fake(...arguments[0]), 'Ctrl+W', 'Linux');"
    both = browser.diag(
        call, [keys, [{"key": "k", "label": " Close Tab "}], {"cmd_k": "From the command"}]
    )
    command_only = browser.diag(call, [keys, [], {"cmd_k": "From the command"}])
    neither = browser.diag(call, [keys, [{"key": "other", "label": "Not this one"}], {}])
    blank = browser.diag(call, [keys, [{"key": "k", "label": "  "}], {}])
    assert [both["label"], command_only["label"], neither["label"], blank["label"]] == [
        "Close Tab",
        "From the command",
        None,
        None,
    ]


@pytest.mark.parametrize(
    "window", ["null", "undefined", "{}", "{document: {getElementById: () => null}}"]
)
def test_a_window_without_firefoxs_keys_gives_no_answer_and_no_error(browser, window):
    """Adversarial: Firefox may rename #mainKeyset, or the page may have no owner window."""
    assert browser.diag(f"return Peek.firefoxShortcut({window}, 'Ctrl+W', 'Linux');") is None


def test_a_keyset_that_throws_gives_no_answer_and_the_error_is_recorded(browser):
    found = browser.diag(
        """const win = {document: {getElementById: () => ({querySelectorAll: () => { throw new Error('keyset-broke'); }})}};
           const answer = Peek.firefoxShortcut(win, 'Ctrl+W', 'Linux');
           return [answer, Diag.events().some(e => e.message.includes('keyset-broke'))];"""
    )
    assert found == [None, True]


def record_with_synthetic_key(browser, field_id: str, key: str, code: str, mods: str) -> str:
    browser.settings(SYNTHETIC_KEY, field_id, key, code, mods)
    return problem_under(browser, field_id)


def test_recording_a_shortcut_that_firefox_uses_warns_with_its_name_and_keeps_it(browser):
    browser.open_settings("#peekafoxy")
    message = record_with_synthetic_key(browser, TABS_FIELD, "w", "KeyW", "c")
    assert message == "Firefox already uses this shortcut for “Close Tab”, which will stop working."
    assert browser.js("return Services.prefs.getStringPref('peekafoxy.tabs.shortcut');") == "Ctrl+W"


def test_the_warning_for_a_shortcut_without_a_name_uses_its_own_text(browser):
    try:
        browser.open_settings("#peekafoxy")
        browser.js(
            "document.getElementById('mainKeyset').querySelector('key#key_close')"
            ".setAttribute('command', 'no-such-command');"
            "for (const item of document.querySelectorAll('[key=key_close]'))"
            " item.setAttribute('label', ' ');"
        )
        message = record_with_synthetic_key(browser, TABS_FIELD, "w", "KeyW", "c")
    finally:
        browser.js(
            "for (const item of document.querySelectorAll('[key=key_close]'))"
            " item.setAttribute('label', 'Close Tab');"
        )
    assert message == "Firefox already uses this shortcut, which will stop working."


def test_a_shortcut_that_firefox_does_not_use_has_no_warning(browser):
    browser.open_settings("#peekafoxy")
    assert record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "ca") == ""


def test_the_warnings_exist_in_both_languages_and_keep_the_name_placeholder(browser):
    texts = browser.diag(
        """return ["en", "pt"].map((lang) => {
             const p = Peek.STRINGS[lang].settings.problems;
             return [p.firefoxUses, p.firefoxUsesUnnamed];
           });"""
    )
    assert texts == [
        [
            "Firefox already uses this shortcut for “{name}”, which will stop working.",
            "Firefox already uses this shortcut, which will stop working.",
        ],
        [
            "O Firefox já usa esse atalho para “{name}”, que vai deixar de funcionar.",
            "O Firefox já usa esse atalho, que vai deixar de funcionar.",
        ],
    ]


def test_the_warning_is_in_portuguese_for_a_portuguese_firefox(browser_in_portuguese):
    browser = browser_in_portuguese
    browser.open_settings("#peekafoxy")
    try:
        message = record_with_synthetic_key(browser, TABS_FIELD, "w", "KeyW", "c")
    finally:
        browser.js("Services.prefs.clearUserPref('peekafoxy.tabs.shortcut');")  # a shared Firefox
        browser.close_settings_tabs()
    assert message == "O Firefox já usa esse atalho para “Close Tab”, que vai deixar de funcionar."


# --- the recorder's keys and its visible instruction ---------------------------------------------


@pytest.mark.parametrize("field", [TABS_FIELD, URLBAR_FIELD])
def test_each_shortcut_field_shows_its_instruction_under_it_and_is_described_by_it(browser, field):
    browser.open_settings("#peekafoxy")
    shown = browser.settings(
        """const input = doc.getElementById(arguments[0]);
           const prompt = doc.getElementById(input.getAttribute('aria-describedby'));
           const a = input.getBoundingClientRect(), b = prompt?.getBoundingClientRect();
           return {text: prompt?.textContent, below: b && b.top >= a.bottom - 1,
                   visible: !!b && b.height > 0 && win.getComputedStyle(prompt).visibility === 'visible',
                   placeholder: input.getAttribute('placeholder')};""",
        field,
    )
    assert shown == {"text": PROMPT, "below": True, "visible": True, "placeholder": None}


@pytest.mark.parametrize("key", ["Backspace", "Delete"])
def test_backspace_and_delete_bring_the_default_back(browser, key):
    browser.open_settings("#peekafoxy")
    assert record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "ca") == ""
    assert pref_has_value(browser, "peekafoxy.tabs.shortcut")
    assert record_with_synthetic_key(browser, TABS_FIELD, key, key, "") == ""
    browser.wait("!Services.prefs.prefHasUserValue('peekafoxy.tabs.shortcut')")
    assert browser.settings(
        "return doc.getElementById(arguments[0]).value;", TABS_FIELD
    ) == browser.default_shortcut("tabs")


@pytest.mark.parametrize("key", ["Backspace", "Delete"])
def test_backspace_with_nothing_to_restore_does_nothing_and_does_not_complain(browser, key):
    browser.open_settings("#peekafoxy")
    assert record_with_synthetic_key(browser, TABS_FIELD, key, key, "") == ""
    assert not pref_has_value(browser, "peekafoxy.tabs.shortcut")


@pytest.mark.parametrize("mods", ["c", "a", "ca"])
def test_backspace_with_ctrl_or_alt_is_not_a_clear_it_is_an_unusable_key(browser, mods):
    """Adversarial: Ctrl+Backspace must not silently wipe a shortcut the person chose."""
    browser.open_settings("#peekafoxy")
    assert record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "ca") == ""
    assert (
        record_with_synthetic_key(browser, TABS_FIELD, "Backspace", "Backspace", mods)
        == "That key can't be used."
    )
    assert (
        browser.js("return Services.prefs.getStringPref('peekafoxy.tabs.shortcut');")
        == "Ctrl+Alt+G"
    )


@pytest.mark.parametrize(
    ("key", "code", "mods"),
    [("Enter", "Enter", ""), (" ", "Space", ""), ("Enter", "Enter", "ca"), (" ", "Space", "cas")],
)
def test_enter_and_space_do_nothing_and_say_nothing(browser, key, code, mods):
    browser.open_settings("#peekafoxy")
    assert record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "ca") == ""
    assert record_with_synthetic_key(browser, TABS_FIELD, key, code, mods) == ""
    assert (
        browser.js("return Services.prefs.getStringPref('peekafoxy.tabs.shortcut');")
        == "Ctrl+Alt+G"
    )


def test_enter_and_space_clear_a_message_that_is_showing(browser):
    browser.open_settings("#peekafoxy")
    assert (
        record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "") == "Add Ctrl, Alt or Meta."
    )
    assert record_with_synthetic_key(browser, TABS_FIELD, "Enter", "Enter", "") == ""


# --- the reset buttons ---------------------------------------------------------------------------

RESET_OF = "doc.getElementById(arguments[0]).closest('.pf-row').querySelector('button')"


def change_strip(browser) -> None:
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 20);")
    browser.wait(
        f"!gBrowser.selectedBrowser.contentDocument.getElementById('{STRIP_FIELD}')"
        ".closest('.pf-row').querySelector('button').disabled"
    )


def test_after_a_reset_the_focus_is_on_the_field_not_on_the_button_that_just_disabled_itself(
    browser,
):
    browser.open_settings("#peekafoxy")
    change_strip(browser)
    browser.settings(f"{RESET_OF}.click();", STRIP_FIELD)
    browser.wait(f"gBrowser.selectedBrowser.contentDocument.activeElement.id === '{STRIP_FIELD}'")
    assert not pref_has_value(browser, "peekafoxy.strip.px")
    assert browser.settings(f"return {RESET_OF}.disabled;", STRIP_FIELD) is True


def test_the_reset_button_works_from_the_keyboard_with_a_real_enter(browser):
    browser.open_settings("#peekafoxy")
    change_strip(browser)
    browser.settings(f"{RESET_OF}.focus();", STRIP_FIELD)
    real_keys(browser, Keys.ENTER)
    browser.wait(f"gBrowser.selectedBrowser.contentDocument.activeElement.id === '{STRIP_FIELD}'")
    assert not pref_has_value(browser, "peekafoxy.strip.px")


def test_after_a_reset_of_a_shortcut_the_field_has_the_focus_and_is_recording(browser):
    browser.open_settings("#peekafoxy")
    assert record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "ca") == ""
    browser.wait(
        f"!gBrowser.selectedBrowser.contentDocument.getElementById('{TABS_FIELD}')"
        ".closest('.pf-row').querySelector('button').disabled"
    )
    browser.settings(f"{RESET_OF}.click();", TABS_FIELD)
    browser.wait(f"gBrowser.selectedBrowser.contentDocument.activeElement.id === '{TABS_FIELD}'")
    browser.real_shortcut("tabs")  # the field has the focus again: recording
    assert not tabs_bar_hidden(browser)


def test_each_reset_button_is_named_after_its_field(browser):
    browser.open_settings("#peekafoxy")
    names = browser.settings(
        """return [...doc.querySelectorAll('#peekafoxy-pane .pf-reset')].map(b => b.getAttribute('aria-label'));"""
    )
    assert len(names) == 7 and len(set(names)) == 7, names
    assert all(name.startswith("Restore default: ") for name in names), names
    assert "Restore default: Hover strip thickness (px)" in names
    assert "Restore default: Toggle tab bar visibility" in names


def test_the_reset_buttons_are_named_in_portuguese_for_a_portuguese_firefox(browser_in_portuguese):
    browser = browser_in_portuguese
    browser.open_settings("#peekafoxy")
    names = browser.settings(
        "return [...doc.querySelectorAll('#peekafoxy-pane .pf-reset')].map(b => b.getAttribute('aria-label'));"
    )
    browser.close_settings_tabs()
    assert len(set(names)) == 7 and all(n.startswith("Restaurar padrão: ") for n in names), names
    assert "Restaurar padrão: Alternar a exibição da barra de abas" in names


# --- the note about vertical tabs ----------------------------------------------------------------

VERTICAL_NOTE = "doc.getElementById('peekafoxy-vertical-tabs-note')"
VERTICAL_TEXT = "Vertical tabs are on, so Firefox already hides the tab bar and the tab bar options have no effect."


def note_shown(browser) -> bool:
    return browser.settings(
        f"const note = {VERTICAL_NOTE}; return !!note && !note.hidden && note.getBoundingClientRect().height > 0;"
    )


def wait_for_note(browser, shown: bool) -> None:
    browser.wait(
        f"(() => {{ const doc = gBrowser.selectedBrowser.contentDocument;"
        f" const note = {VERTICAL_NOTE}; return !!note && (!note.hidden) === {str(shown).lower()}; }})()",
        5,
        f"the note about vertical tabs did not become {'visible' if shown else 'hidden'}",
    )


@pytest.fixture
def vertical_tabs_off(browser):
    browser.js("Services.prefs.clearUserPref('sidebar.verticalTabs');")
    yield
    browser.js("Services.prefs.clearUserPref('sidebar.verticalTabs');")


def test_the_vertical_tabs_note_is_not_shown_while_vertical_tabs_are_off(
    browser, vertical_tabs_off
):
    browser.open_settings("#peekafoxy")
    assert not note_shown(browser)
    assert browser.settings(f"return {VERTICAL_NOTE}.textContent;") == VERTICAL_TEXT


def test_the_vertical_tabs_note_follows_the_pref_while_the_page_is_open(browser, vertical_tabs_off):
    browser.open_settings("#peekafoxy")
    browser.js("Services.prefs.setBoolPref('sidebar.verticalTabs', true);")
    wait_for_note(browser, True)
    assert note_shown(browser)
    browser.js("Services.prefs.setBoolPref('sidebar.verticalTabs', false);")
    wait_for_note(browser, False)
    browser.js("Services.prefs.setBoolPref('sidebar.verticalTabs', true);")  # and again
    wait_for_note(browser, True)
    browser.js("Services.prefs.clearUserPref('sidebar.verticalTabs');")
    wait_for_note(browser, False)


def test_the_vertical_tabs_note_is_shown_at_once_when_the_page_opens_with_them_on(
    browser, vertical_tabs_off
):
    browser.js("Services.prefs.setBoolPref('sidebar.verticalTabs', true);")
    browser.open_settings("#peekafoxy")
    assert note_shown(browser)
    browser.close_settings_tabs()


def test_the_vertical_tabs_note_is_in_portuguese_for_a_portuguese_firefox(
    browser_in_portuguese,
):
    browser = browser_in_portuguese
    browser.js("Services.prefs.setBoolPref('sidebar.verticalTabs', true);")
    try:
        browser.open_settings("#peekafoxy")
        shown = note_shown(browser)
        text = browser.settings(f"return {VERTICAL_NOTE}.textContent;")
    finally:
        browser.js("Services.prefs.clearUserPref('sidebar.verticalTabs');")
        browser.close_settings_tabs()
    assert shown
    assert text == (
        "As abas verticais estão ativadas, então o Firefox já oculta a barra de abas e as opções "
        "da barra de abas não têm efeito."
    )


def test_the_vertical_tabs_note_stops_listening_when_the_page_is_closed(browser, vertical_tabs_off):
    """Cleaning up on unload: changing the pref after the page is gone records no error."""
    browser.open_settings("#peekafoxy")
    browser.close_settings_tabs()
    problems = "return Diag.events().filter((e) => e.level !== 'info').length;"
    before = browser.diag(problems)
    browser.js("Services.prefs.setBoolPref('sidebar.verticalTabs', true);")
    time.sleep(0.3)
    browser.js("Services.prefs.clearUserPref('sidebar.verticalTabs');")
    assert browser.diag(problems) == before


# --- language and direction ----------------------------------------------------------------------


def test_the_pane_says_it_is_english_and_left_to_right_in_a_right_to_left_firefox(browser):
    """The strings are English whatever Firefox's language is, so the pane must not be mirrored."""
    # Both prefs: uidirection alone does not mirror the page, the pseudo-locale for right-to-left does.
    browser.js(
        "Services.prefs.setIntPref('intl.uidirection', 1);"
        "Services.prefs.setCharPref('intl.l10n.pseudo', 'bidi');"
    )
    browser.open_settings("#peekafoxy")
    shown = browser.settings(
        """const pane = doc.getElementById('peekafoxy-pane');
           const text = pane.querySelector('.pf-note');
           return {page: win.getComputedStyle(doc.documentElement).direction,
                   lang: pane.getAttribute('lang'), dir: pane.getAttribute('dir'),
                   text: win.getComputedStyle(text).direction, align: win.getComputedStyle(text).textAlign};"""
    )
    assert shown["page"] == "rtl", shown  # the page really is mirrored, or this proves nothing
    assert (shown["lang"], shown["dir"], shown["text"]) == ("en", "ltr", "ltr"), shown


def test_the_pane_says_it_is_portuguese_for_a_portuguese_firefox(browser_in_portuguese):
    browser = browser_in_portuguese
    browser.open_settings("#peekafoxy")
    shown = browser.settings(
        "const pane = doc.getElementById('peekafoxy-pane');"
        "return [pane.getAttribute('lang'), pane.getAttribute('dir')];"
    )
    browser.close_settings_tabs()
    assert shown == ["pt-BR", "ltr"]


@pytest.mark.parametrize(
    ("locale", "language", "direction"),
    [
        ("en-US", "en", "ltr"),
        ("pt-BR", "pt-BR", "ltr"),
        ("pt_PT", "pt-BR", "ltr"),  # Portuguese gets the Brazilian strings: the pane says so
        ("he-IL", "en", "ltr"),  # no Hebrew strings: English, and left to right
        ("ar", "en", "ltr"),
        ("fa-IR", "en", "ltr"),
        ("", "en", "ltr"),
        ("constructor", "en", "ltr"),  # adversarial: names that every object has
        ("__proto__-x", "en", "ltr"),
        ("toString", "en", "ltr"),
    ],
)
def test_the_language_and_direction_of_the_pane_follow_the_texts_not_firefox(
    browser, locale, language, direction
):
    assert browser.diag(
        "return [Peek.languageFor(arguments[0]), Peek.directionFor(arguments[0])];", locale
    ) == [language, direction]


@pytest.mark.parametrize("locale", ["constructor", "__proto__", "toString", "hasOwnProperty-US"])
def test_a_language_named_like_a_property_of_every_object_gets_english(browser, locale):
    """Adversarial: ``STRINGS[locale]`` used to answer with Object.prototype's own members."""
    assert (
        browser.diag("return Peek.textFor(arguments[0]).settings.supportGroup;", locale)
        == "Support"
    )


# --- announcements -------------------------------------------------------------------------------


def test_the_roles_of_the_live_regions(browser):
    browser.open_settings("#peekafoxy")
    roles = browser.settings(
        """const roles = (selector) => [...doc.querySelectorAll(selector)].map(n => n.getAttribute('role'));
           return {status: doc.getElementById('peekafoxy-status').getAttribute('role'),
                   problems: roles('#peekafoxy-pane .pf-problem'),
                   done: doc.getElementById('peekafoxy-copy-done').getAttribute('role')};"""
    )
    assert roles["status"] == "status"
    assert roles["done"] == "status"
    assert roles["problems"] == ["alert"] * len(roles["problems"]) and len(roles["problems"]) >= 7


WATCH_LINE = """
  const line = doc.getElementById(arguments[0]).closest('div').parentNode.querySelector('.pf-problem');
  win.__texts = [];
  win.__watch = new win.MutationObserver(() => win.__texts.push(line.textContent));
  win.__watch.observe(line, {childList: true, characterData: true, subtree: true});
"""
TEXTS = "return doc.defaultView.__texts;"


def enter_strip(browser, value: str) -> None:
    browser.settings(
        """const input = doc.getElementById(arguments[0]);
           input.value = arguments[1];
           input.dispatchEvent(new win.Event('change', {bubbles: true}));""",
        STRIP_FIELD,
        value,
    )


def test_the_same_mistake_twice_is_announced_twice(browser):
    """The line is emptied and filled again each time, which is what a live region needs to speak."""
    browser.open_settings("#peekafoxy")
    browser.settings(WATCH_LINE, STRIP_FIELD)
    for _ in range(2):
        enter_strip(browser, "999")
        assert problem_under(browser, STRIP_FIELD) == "Enter a number between 1 and 40."
        time.sleep(0.2)
    texts = browser.settings(TEXTS)
    message = "Enter a number between 1 and 40."
    assert texts.count(message) == 2, texts
    assert "" in texts[texts.index(message) :], texts  # emptied between the two


def test_a_message_that_is_replaced_before_it_is_announced_does_not_come_back(browser):
    """Adversarial: a mistake and its correction within the announcement delay leave a clean line."""
    browser.open_settings("#peekafoxy")
    browser.settings(
        """const input = doc.getElementById(arguments[0]);
           input.value = '999'; input.dispatchEvent(new win.Event('change', {bubbles: true}));
           input.value = '15'; input.dispatchEvent(new win.Event('change', {bubbles: true}));""",
        STRIP_FIELD,
    )
    time.sleep(0.5)  # ten times the delay of the announcement
    assert browser.settings(PROBLEM, STRIP_FIELD) == ""
    assert browser.js("return Services.prefs.getIntPref('peekafoxy.strip.px');") == 15


def test_a_shortcut_mistake_is_announced_through_the_same_mechanism(browser):
    browser.open_settings("#peekafoxy")
    browser.settings(WATCH_LINE, TABS_FIELD)
    for _ in range(2):
        assert (
            record_with_synthetic_key(browser, TABS_FIELD, "g", "KeyG", "")
            == "Add Ctrl, Alt or Meta."
        )
        time.sleep(0.2)
    texts = browser.settings(TEXTS)
    assert texts.count("Add Ctrl, Alt or Meta.") == 2, texts


# --- layout --------------------------------------------------------------------------------------

ROWS = """
  const rows = [...doc.querySelectorAll('#peekafoxy-pane .pf-row')].filter(r => r.querySelector('.pf-reset'));
  return rows.map((row) => {
    const input = row.querySelector('input').getBoundingClientRect();
    const button = row.querySelector('.pf-reset').getBoundingClientRect();
    return {field: row.querySelector('input').id, inputTop: input.top, buttonTop: button.top,
            rowHeight: row.getBoundingClientRect().height, pane: doc.getElementById('peekafoxy-pane').clientWidth};
  });
"""


def test_the_reset_button_is_on_the_same_row_as_its_field(browser):
    browser.open_settings("#peekafoxy")
    rows = browser.settings(ROWS)
    assert len(rows) == 7
    if rows[0]["pane"] < 520:
        pytest.skip(f"the window is too narrow for one row ({rows[0]['pane']}px)")
    for row in rows:
        assert abs(row["buttonTop"] - row["inputTop"]) < row["rowHeight"] / 2, row


def test_an_empty_message_line_takes_no_room(browser):
    browser.open_settings("#peekafoxy")
    heights = browser.settings(
        """return [...doc.querySelectorAll('#peekafoxy-pane .pf-problem')]
           .filter(p => !p.textContent).map(p => [p.getBoundingClientRect().height,
             win.getComputedStyle(p).marginTop, win.getComputedStyle(p).marginBottom]);"""
    )
    assert heights and all(h == [0, "0px", "0px"] for h in heights), heights


def test_a_message_line_with_a_message_has_room_again(browser):
    browser.open_settings("#peekafoxy")
    enter_strip(browser, "999")
    problem_under(browser, STRIP_FIELD)
    height = browser.settings(
        "return doc.getElementById(arguments[0]).closest('div').parentNode"
        ".querySelector('.pf-problem').getBoundingClientRect().height;",
        STRIP_FIELD,
    )
    assert height > 8


def test_the_reset_button_keeps_its_button_face_and_has_the_firefox_icon(browser):
    """Adversarial: the `background` shorthand once wiped the button face (and the icon was a file
    that does not exist); now both the face and the icon are there."""
    browser.open_settings("#peekafoxy")
    look = browser.settings(
        """const b = doc.querySelector('#peekafoxy-pane button.pf-reset');
           const s = getComputedStyle(b), probe = doc.createElement('button');
           doc.body.append(probe); const plain = getComputedStyle(probe);
           const out = {image: s.backgroundImage, face: s.backgroundColor === plain.backgroundColor,
                        border: s.borderTopWidth === plain.borderTopWidth};
           probe.remove(); return out;"""
    )
    assert "arrow-counterclockwise-16.svg" in look["image"], look
    assert look["face"] and look["border"], look
