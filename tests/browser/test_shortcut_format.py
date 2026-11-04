"""The shortcut format shared by the script and the settings page, tried on the real module."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

MODULE = 'const P = ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs");'


def parse(browser, texts: list):
    return browser.js(
        MODULE
        + """return arguments[0].map(t => {
               const r = P.parseShortcut(t);
               return r.ok ? r.text : r.reason;
             });""",
        texts,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ctrl+Alt+T", "Ctrl+Alt+T"),
        ("ctrl+alt+t", "Ctrl+Alt+T"),  # case does not matter, the result is canonical
        ("Alt+Ctrl+T", "Ctrl+Alt+T"),  # so does the order of modifiers
        (" Ctrl + Alt + T ", "Ctrl+Alt+T"),
        ("Control+Option+9", "Ctrl+Alt+9"),
        ("Cmd+Shift+K", "Shift+Meta+K"),
        ("Alt+F12", "Alt+F12"),
        ("Ctrl+f1", "Ctrl+F1"),
        ("Meta+Z", "Meta+Z"),
        ("Alt+Shift+Q", "Alt+Shift+Q"),
        ("Ctrl+Alt+Shift+Meta+A", "Ctrl+Alt+Shift+Meta+A"),
    ],
)
def test_valid_shortcuts_are_normalised(browser, text, expected):
    assert parse(browser, [text]) == [expected]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "format"),
        ("+", "format"),
        ("Ctrl+", "format"),
        ("+T", "format"),
        ("Ctrl++T", "format"),
        ("Ctrl+Ctrl+T", "format"),  # a modifier twice
        ("Hyper+T", "format"),
        ("Ctrl+Alt+Nonsense", "key"),
        ("Ctrl+Alt+F13", "key"),
        ("Ctrl+Alt+F0", "key"),
        ("Ctrl+Alt+TT", "key"),
        ("Ctrl+Alt+Enter", "key"),
        ("Ctrl+Alt+ñ", "key"),
        ("T", "modifier"),
        ("Shift+T", "modifier"),  # Shift alone would swallow typing
        ("F5", "modifier"),
        ("Ctrl+Alt+Shift+Meta", "key"),
    ],
)
def test_invalid_shortcuts_say_why(browser, text, reason):
    assert parse(browser, [text]) == [reason]


def test_odd_values_never_throw(browser):
    result = browser.js(
        MODULE
        + """return [null, undefined, 5, {}, [], "\\u0000", "Ctrl+\\u202eT", "𝕋"].map(
             v => { try { return P.parseShortcut(v).ok; } catch (e) { return "threw " + e; } });"""
    )
    assert result == [False] * 8


def test_what_a_key_press_produces_parses_back_and_matches_itself(browser):
    result = browser.js(
        MODULE
        + """
        const codes = ["KeyA", "KeyZ", "Digit0", "Digit9", "F1", "F12"];
        const failures = [];
        for (const code of codes) for (let m = 0; m < 16; m++) {
          const event = {code, ctrlKey: !!(m & 1), altKey: !!(m & 2),
                         shiftKey: !!(m & 4), metaKey: !!(m & 8)};
          const text = P.shortcutFromEvent(event);
          const parsed = P.parseShortcut(text);
          if (!(m & 11)) { if (parsed.ok) failures.push(["shift-only accepted", text]); continue; }
          if (!parsed.ok || parsed.text !== text) {
            failures.push(["round trip", text, parsed]);
            continue;
          }
          if (!P.matches(parsed, event)) failures.push(["no match", text]);
          if (P.matches(parsed, {...event, shiftKey: !event.shiftKey}))
            failures.push(["loose", text]);
          if (P.matches(parsed, {...event, code: "KeyQ"})) failures.push(["wrong key", text]);
        }
        return failures;"""
    )
    assert result == []


def test_keys_that_are_not_shortcut_material_are_ignored(browser):
    result = browser.js(
        MODULE
        + """return ["ControlLeft", "AltRight", "Enter", "Tab", "Escape", "ArrowUp", "Space",
                     "Minus", ""]
             .map(code => P.shortcutFromEvent({code, ctrlKey: true, altKey: true}));"""
    )
    assert result == [None] * 9


def test_the_shortcut_problem_checks_the_other_bar(browser):
    # `other` is the other bar's pref (here the tab bar's, Ctrl+Alt+T): we choose for the urlbar.
    result = browser.js(
        MODULE
        + """const other = P.PREFS.tabsShortcut;
           return ["Ctrl+Alt+T", "ctrl+alt+t", "Ctrl+Alt+U", "Ctrl+Alt+G", "G", "Ctrl+Alt+Enter"]
             .map(t => P.shortcutProblem(t, other));"""
    )
    assert result == ["duplicate", "duplicate", None, None, "modifier", "key"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-5, 1), (0, 1), (1, 1), (40, 40), (41, 40), (10**9, 40), (12.7, 12.7)],
)
def test_numbers_are_clamped_to_the_pref_limits(browser, value, expected):
    assert (
        browser.js(
            MODULE + "return P.clamp(P.PREFS.stripPx, arguments[0]);",
            value,
        )
        == expected
    )


def test_every_pref_has_a_default_inside_its_limits_and_texts_in_both_languages(browser):
    problems = browser.js(
        MODULE
        + """
        const out = [];
        for (const [key, pref] of Object.entries(P.PREFS)) {
          if (pref.type === "int" && !(pref.default >= pref.min && pref.default <= pref.max))
            out.push(`${key}: default outside its limits`);
          if (pref.type === "string" && !P.parseShortcut(pref.default).ok)
            out.push(`${key}: default shortcut is invalid`);
          if (!pref.name.startsWith(P.PREF_BRANCH)) out.push(`${key}: outside the branch`);
        }
        const keysOf = (o) => Object.keys(o).sort().join();
        const en = P.STRINGS.en, pt = P.STRINGS.pt;
        if (keysOf(en) !== keysOf(pt)) out.push("top-level texts differ");
        if (keysOf(en.settings) !== keysOf(pt.settings)) out.push("settings texts differ");
        if (keysOf(en.settings.problems) !== keysOf(pt.settings.problems))
          out.push("problems differ");
        for (const t of ["tabs", "urlbar"]) {
          for (const lang of [en, pt])
            if (!lang[t].tooltip.includes("{key}")) out.push(`${t} tooltip has no {key}`);
        }
        for (const lang of [en, pt])
          if (!/[{]min[}].*[{]max[}]/.test(lang.settings.problems.range))
            out.push("range text lacks its numbers");
        return out;"""
    )
    assert problems == []


@pytest.mark.parametrize(
    ("locale", "greeting"),
    [
        ("en-US", "Instaalleeeeed PEEK A BOO!!! >.<"),
        ("pt-BR", "Instaalaadoooo PEEK A BOO!!! >.<"),
        ("pt_PT", "Instaalaadoooo PEEK A BOO!!! >.<"),
        ("PT", "Instaalaadoooo PEEK A BOO!!! >.<"),
        ("de", "Instaalleeeeed PEEK A BOO!!! >.<"),
        ("", "Instaalleeeeed PEEK A BOO!!! >.<"),
        (None, "Instaalleeeeed PEEK A BOO!!! >.<"),
    ],
)
def test_the_language_picks_the_texts_and_falls_back_to_english(browser, locale, greeting):
    assert browser.js(MODULE + "return P.textFor(arguments[0]).greeting;", locale) == greeting


def test_altgr_presses_are_never_shortcuts(browser):
    result = browser.js(
        MODULE
        + """
        const altgr = {code: "KeyT", ctrlKey: true, altKey: true, shiftKey: false, metaKey: false,
                       getModifierState: (name) => name === "AltGraph"};
        const plain = {...altgr, getModifierState: () => false};
        const binding = P.parseShortcut("Ctrl+Alt+T");
        return [P.shortcutFromEvent(altgr), P.shortcutFromEvent(plain),
                P.matches(binding, altgr), P.matches(binding, plain)];"""
    )
    assert result == [None, "Ctrl+Alt+T", False, True]


def test_the_hint_is_the_same_everywhere_plus_what_is_true_on_this_system(browser):
    hints = browser.js(
        MODULE
        + """const s = P.STRINGS.en.settings;
           return ["Linux", "WINNT", "Darwin"].map(os => P.shortcutHint(s, os));"""
    )
    base = browser.js(MODULE + "return P.STRINGS.en.settings.shortcutHint;")
    assert all(hint.startswith(base) for hint in hints)
    assert "GNOME" in hints[0] and "GNOME" not in base
    assert "AltGr" in hints[1] and "GNOME" not in hints[1]
    assert hints[2] == base  # nothing special to say on macOS


def test_the_hint_texts_exist_in_both_languages_and_name_no_system_in_the_neutral_part(browser):
    problems = browser.js(
        MODULE
        + """
        const out = [];
        for (const lang of ["en", "pt"]) {
          const s = P.STRINGS[lang].settings;
          for (const key of ["shortcutHint", "shortcutHintLinux", "shortcutHintWindows"])
            if (!s[key]) out.push(`${lang}.${key} missing`);
          if (/GNOME|Ubuntu|Windows/.test(s.shortcutHint))
            out.push(`${lang}: neutral hint names a system`);
        }
        return out;"""
    )
    assert problems == []
