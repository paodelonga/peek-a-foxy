"""The Firefox side of the diagnostics: Diag, the health check, the status file, the Support group.

Mostly the unexpected: a flood of errors, hostile texts, a status file that cannot be written or that
is already there as garbage, several windows writing together, a pref of the wrong type, a Firefox
that renamed an element, a clipboard that does not work, a tiny window. The status file is always read
with the Python reader (``peek_a_foxy.status``) and checked against ``peek-a-foxy doctor``, so the two
sides are tested against each other and not each against its own idea of the format.
"""

# ruff: noqa: E501  (the long lines are JavaScript snippets and the texts they are checked against)

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import _speaking, launched

from peek_a_foxy import report
from peek_a_foxy.logs import Redactor
from peek_a_foxy.status import STATUS_FILE, Status, read_status

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "peekafoxy-status.json"
VERSION = next(
    line.split('"')[1]
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    if line.startswith("version = ")
)
HEALTH = [
    "navigator-toolbox",
    "tabs-toolbar",
    "nav-bar",
    "urlbar",
    "bookmarks-toolbar",
    "tabs-holder",
    "customtitlebar",
    "browser-apis",
    "toolbar-buttons",
    "prefs",
    "settings-values",
    "shortcuts",
    "shortcuts-distinct",
]
# What a hostile text can contain: none of this may reach the file or the clipboard text.
FORBIDDEN = (
    [chr(c) for c in range(0, 32) if chr(c) not in "\t\n\r"]
    + ["\x7f", "\x85"]
    + list("\u202e\u202a")
)
PANE = "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-pane')"
READ_CLIPBOARD = """
  const trans = Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);
  trans.init(null);
  trans.addDataFlavor("text/plain");
  Services.clipboard.getData(trans, Services.clipboard.kGlobalClipboard, null);
  const data = {};
  trans.getTransferData("text/plain", data);
  return data.value.QueryInterface(Ci.nsISupportsString).data;
"""
SUPPORT = """
  const status = doc.getElementById('peekafoxy-status');
  const heads = [...doc.querySelectorAll('#peekafoxy-pane h2')].map(h => h.textContent);
  return {
    heads, state: status.dataset.state, lines: [...status.querySelectorAll('p')].map(p => p.textContent),
    button: doc.getElementById('peekafoxy-copy').textContent,
    done: doc.getElementById('peekafoxy-copy-done').textContent,
    failed: doc.getElementById('peekafoxy-copy-failed').textContent,
  };
"""


# --- helpers ------------------------------------------------------------------------------------


def status_of(browser) -> Status:
    """What the file says right now (after Diag has written what it has)."""
    browser.flush()
    found = read_status(browser.chrome_dir)
    assert found is not None
    return found


def raw_status(browser) -> dict:
    """The file as JSON, whole: the Python reader keeps only the latest 20 errors."""
    browser.flush()
    return json.loads((browser.chrome_dir / STATUS_FILE).read_text(encoding="utf-8"))


def checked(browser) -> Status:
    browser.diag("Diag.check(window);")
    return status_of(browser)


def failed_health(status: Status) -> dict[str, str]:
    return dict(status.failed())


@contextmanager
def renamed(browser, element_id: str) -> Iterator[None]:
    """Firefox renamed an element: the window's element gets another id for a while."""
    browser.js("document.getElementById(arguments[0]).id = arguments[0] + '-gone';", element_id)
    try:
        yield
    finally:
        browser.js("document.getElementById(arguments[0] + '-gone').id = arguments[0];", element_id)


def run_doctor(browser_or_profile, install: Path) -> dict:
    profile = getattr(browser_or_profile, "profile", browser_or_profile)
    env = {**os.environ, "PEEK_A_FOXY_LOG": "off", "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "peek_a_foxy",
            "doctor",
            "--json",
            "--profile",
            str(profile),
            "--firefox-dir",
            str(install),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    return json.loads(result.stdout)


def checks_of(doctor: dict) -> dict[str, dict]:
    return {c["id"]: c for s in doctor["sections"] for c in s["checks"]}


def codes_of(doctor: dict) -> set[str]:
    return {c["code"] for c in checks_of(doctor).values() if c["code"]}


@pytest.fixture(autouse=True)
def clean(browser):
    """Every test starts and ends in the first window, with no user values and an empty buffer."""

    def reset() -> None:
        first = browser.first_window
        for handle in browser.client.chrome_window_handles:
            if handle != first:
                browser.switch_to(handle)
                browser.js("window.close();")
        browser.switch_to(first)
        browser.close_settings_tabs()
        browser.diag(
            """for (const name of Services.prefs.getChildList('peekafoxy.')) {
                 if (name !== 'peekafoxy.welcomed') Services.prefs.clearUserPref(name);
               }
               for (const id of ['navigator-toolbox', 'TabsToolbar', 'nav-bar', 'urlbar',
                                 'PersonalToolbar', 'tabbrowser-tabs'])
                 document.getElementById(id + '-gone')?.setAttribute('id', id);
               document.getElementById('peekafoxy-test-buttons')?.remove();
               document.documentElement.removeAttribute('customtitlebar');
               Services.prefs.clearUserPref('ui.systemUsesDarkTheme');
               Services.prefs.clearUserPref('browser.display.document_color_use');
               Services.prefs.clearUserPref('ui.useAccessibilityTheme');
               Diag.reset();
               Diag.setHealth('settings', []);  // the settings page reports itself when opened
               Diag.check(window);
               Cc["@mozilla.org/consoleAPI-storage;1"].getService(Ci.nsIConsoleAPIStorage).clearEvents();"""
        )

    reset()
    yield
    reset()


# --- the status file ----------------------------------------------------------------------------


def test_the_status_file_is_written_at_startup_and_the_python_reader_accepts_it(browser):
    path = browser.wait_for_status_file()
    # Earlier tests may have left windows that are still closing: wait until only this one is left.
    browser.wait("[...Services.wm.getEnumerator('navigator:browser')].length === 1", 10)
    status = status_of(browser)
    facts = browser.js(
        """const { AppConstants } = ChromeUtils.importESModule(
             'resource://gre/modules/AppConstants.sys.mjs');
           return [Services.appinfo.version, Services.appinfo.appBuildID, Services.appinfo.OS,
                   Services.locale.appLocaleAsBCP47, AppConstants.MOZ_UPDATE_CHANNEL];""",
    )
    assert (status.firefox_version, status.build_id, status.os, status.locale, status.channel) == (
        tuple(facts)
    )
    assert status.script_version == VERSION
    assert status.windows == 1
    assert list(status.health) == HEALTH
    assert status.failed() == []
    assert abs(time.time() - status.updated.timestamp()) < 3600
    assert not (path.parent / f"{STATUS_FILE}.tmp").exists()  # the temporary file was moved


def test_the_written_file_has_the_keys_of_the_documented_example(browser):
    browser.diag("Diag.info('test', 'an event, so that there is one to compare');")
    written = raw_status(browser)
    documented = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(written) == set(documented)
    assert set(written["errors"][0]) == set(documented["errors"][0])
    assert written["schema"] == documented["schema"] == 1
    # health is "ok" or "fail: <note>": strings, as status.py documents (an object would be read as
    # an unreadable value and reported as a failure).
    assert all(isinstance(v, str) for v in written["health"].values())


def test_the_file_stays_small_and_is_updated_not_just_created(browser):
    first = status_of(browser).updated
    time.sleep(0.05)
    assert status_of(browser).updated > first
    assert (browser.chrome_dir / STATUS_FILE).stat().st_size < 20_000


def test_events_are_written_in_the_order_they_happened(browser):
    browser.diag("Diag.warn('test:a', 'first'); Diag.error('test:b', 'second');")
    status = status_of(browser)
    assert [(e.level, e.where, e.message) for e in status.errors[-2:]] == [
        ("warn", "test:a", "first"),
        ("error", "test:b", "second"),
    ]


def test_the_new_code_takes_little_time_at_startup(browser):
    spent = browser.diag("return Diag.stats().syncMs;")
    assert spent < 250, f"Diag spent {spent} ms in the synchronous parts of startup"


# --- the ring buffer ----------------------------------------------------------------------------


def test_a_flood_of_different_errors_keeps_only_the_latest_fifty(browser):
    browser.diag("for (let i = 0; i < 1000; i++) Diag.error('flood', 'error ' + i);")
    written = raw_status(browser)["errors"]
    assert [e["message"] for e in written] == [f"error {i}" for i in range(950, 1000)]
    assert [e.message for e in status_of(browser).errors] == [
        f"error {i}" for i in range(980, 1000)
    ]
    assert (browser.chrome_dir / STATUS_FILE).stat().st_size < 20_000


def test_a_flood_of_the_same_error_is_one_event_with_a_count(browser):
    browser.diag("for (let i = 0; i < 5000; i++) Diag.error('loop', 'mousemove failed');")
    errors = raw_status(browser)["errors"]
    assert len(errors) == 1
    assert "mousemove failed" in errors[0]["message"] and "5000" in errors[0]["message"]


def test_harmless_events_never_push_out_errors_and_never_fill_the_buffer_alone(browser):
    browser.diag(
        """for (let i = 0; i < 10; i++) Diag.error('keep', 'error ' + i);
           for (let i = 0; i < 500; i++) Diag.info('noise', 'info ' + i);
           for (let i = 0; i < 500; i++) Diag.warn('noise', 'warn ' + i);"""
    )
    events = browser.diag("return Diag.events();")
    assert len(events) == 50
    assert [e["message"] for e in events if e["level"] == "error"] == [
        f"error {i}" for i in range(10)
    ]
    assert not any(e["level"] == "info" for e in events)  # the warnings took their place
    # And when only errors fill it, a new info is dropped instead of evicting one.
    browser.diag("Diag.reset(); for (let i = 0; i < 60; i++) Diag.error('e', 'e' + i);")
    browser.diag("Diag.info('late', 'harmless');")
    assert [e["where"] for e in browser.diag("return Diag.events();")].count("late") == 0


def test_the_buffer_is_shared_by_every_window(browser):
    browser.new_window()
    browser.diag("Diag.error('second-window', 'seen from everywhere');")
    browser.switch_to(browser.first_window)
    assert "second-window" in [e["where"] for e in browser.diag("return Diag.events();")]


# --- hostile texts ------------------------------------------------------------------------------

HOSTILE = {
    "nul": "before\\u0000after",
    "escape": "\\u001b[31mred\\u001b[0m and a bell \\u0007",
    "breaks": "one\\ntwo\\r\\nthree\\tfour\\u2028five\\u2029six\\u0085seven",
    "overrides": "\\u202eevil\\u202c and \\u202aembedded\\u2066 isolates\\u2069",
    "rtl": "\\u05e9\\u05dc\\u05d5\\u05dd \\u05e2\\u05d5\\u05dc\\u05dd \\u0645\\u0631\\u062d\\u0628\\u0627",
    "lone-surrogates": "high \\ud800 and low \\udc00 and \\udbff",
    "huge": "'x'.repeat(2_000_000)",
    "cut-inside-an-emoji": "'a'.repeat(298) + '\\ud83d\\ude00' + 'b'.repeat(50)",
    "many-emoji": "'\\ud83e\\udd8a'.repeat(5000)",
    "markdown": "'`'.repeat(3) + ' | cell | <b>x</b> ' + '`'.repeat(3)",
    "controls-only": "'\\u0001\\u0002\\u0003\\u007f\\u0080\\u009f'",
    "empty": "''",
}


def literal(expression: str) -> str:
    """The JS for a case: a plain string literal, or an expression such as 'x'.repeat(5)."""
    return expression if expression.startswith("'") else f'"{expression}"'


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_texts_are_cleaned_cut_and_still_valid_for_the_python_reader(browser, name):
    text = literal(HOSTILE[name])
    browser.diag(f"Diag.error({text}, {text});")
    event = browser.diag("return Diag.events().at(-1);")
    for part in (event["where"], event["message"]):
        assert not any(char in part for char in FORBIDDEN), repr(part)
        assert report.clean(part) == part  # the Python side finds nothing left to clean
        part.encode("utf-8")  # no lone surrogate survived
    assert len(event["where"]) <= 60 and len(event["message"]) <= 330
    # What the file holds is what the Python reader takes, and it needs no cleaning either.
    status = status_of(browser)
    assert status.errors[-1].message == event["message"]
    assert status.errors[-1].where == event["where"]
    raw = (browser.chrome_dir / STATUS_FILE).read_bytes()
    assert b"\x00" not in raw and len(raw) < 20_000
    json.loads(raw.decode("utf-8"))


def test_right_to_left_letters_are_kept_and_overrides_are_not(browser):
    browser.diag(f"Diag.error('rtl', {literal(HOSTILE['rtl'])} + {literal(HOSTILE['overrides'])});")
    message = browser.diag("return Diag.events().at(-1).message;")
    assert "\u05e9\u05dc\u05d5\u05dd" in message and "\u0645\u0631\u062d\u0628\u0627" in message
    assert "\u202e" not in message and "\ufffdevil\ufffd" in message


def test_something_that_is_not_text_does_not_break_recording(browser):
    browser.diag(
        """const hostile = { get message() { throw new Error('getter'); } };
           Diag.error('odd', hostile);
           Diag.error('odd', null);
           Diag.error('odd', undefined);
           Diag.error('odd', Symbol('s'));
           Diag.error('odd', { toString() { throw new Error('no text'); } });
           Diag.error('odd', Object.create(null));
           Diag.error({ toString() { throw new Error('where'); } }, 'x');"""
    )
    events = browser.diag("return Diag.events();")
    assert len(events) >= 4  # (identical neighbours are merged) none threw, none broke the buffer
    assert {"where": "(a text that could not be shown)", "message": "x"}.items() <= events[
        -1
    ].items()
    assert status_of(browser).errors  # and the file is still valid


# --- redaction ----------------------------------------------------------------------------------


def redact(browser, options: dict, text: str) -> str:
    return browser.diag("return Peek.makeRedactor(arguments[0])(arguments[1]);", options, text)


def test_the_home_folder_the_user_and_the_profile_are_hidden_in_every_spelling(browser):
    options = {
        "homes": ["/home/ana maria"],
        "user": "anamaria",
        "profileDir": "/data/My Profile",
        "profileName": "Work Stuff",
    }
    text = (
        "read /home/ana maria/x, file:///home/ana%20maria/y, in /data/My Profile/chrome/a.js "
        "and file:///data/My%20Profile/chrome/b.js for anamaria on Work Stuff"
    )
    assert redact(browser, options, text) == (
        "read ~/x, file://~/y, in <profile>/chrome/a.js and file://<profile>/chrome/b.js "
        "for <user> on <profile>"
    )


def test_windows_paths_match_in_any_case_and_with_either_slash_or_doubled_backslashes(browser):
    options = {"homes": ["C:\\Users\\Ana"], "user": "Ana Silva", "ignoreCase": True}
    text = "c:/users/ana/a, C:\\USERS\\ANA\\b, C:\\\\Users\\\\Ana\\\\c"
    assert redact(browser, options, text) == "~/a, ~\\b, ~\\\\c"


@pytest.mark.parametrize(
    ("options", "text"),
    [
        ({"homes": ["/"]}, "/usr/bin and /etc"),  # a home of "/" would blank every path
        ({"homes": ["C:\\"]}, "C:\\Windows"),
        ({"homes": ["/x"]}, "/xylophone is not /x"),
        ({"user": "al"}, "al is not hidden: too short to tell from a word"),
        ({"user": "pedro"}, "pedrolino and mpedro stay"),
        ({"profileName": "default-release"}, "the default-release profile is a standard name"),
        ({"profileName": "ab"}, "ab is too short"),
    ],
)
def test_what_could_blank_or_damage_ordinary_text_is_left_alone(browser, options, text):
    assert redact(browser, options, text) == text


def test_the_user_name_is_matched_as_a_whole_word_including_non_ascii_letters(browser):
    out = redact(browser, {"user": "José"}, "José and Joséphine and éJosé and José_ and José.")
    assert out == "<user> and Joséphine and éJosé and José_ and <user>."


def test_names_with_regular_expression_characters_are_taken_literally(browser):
    options = {"homes": ["/home/a(b)+[c]"], "user": "a.b*c?", "profileName": "(x|y)+$^"}
    text = "/home/a(b)+[c]/f for a.b*c? and aXb in (x|y)+$^ not x"
    assert redact(browser, options, text) == "~/f for <user> and aXb in <profile> not x"


def test_a_profile_folder_is_hidden_but_an_eight_letter_script_name_in_a_stack_is_not(browser):
    text = (
        "at f@chrome://userscripts/content/autohide.uc.js:12:3 and g@file:///x/conftest.py:8:1 "
        "and /x/abcd1234.default-release/prefs.js and /x/q1w2e3r4.dev-edition-default/y"
    )
    assert redact(browser, {}, text) == (
        "at f@chrome://userscripts/content/autohide.uc.js:12:3 and g@file:///x/conftest.py:8:1 "
        "and /x/<profile>/prefs.js and /x/<profile>/y"
    )


def test_secrets_in_urls_and_headers_are_hidden_like_the_python_side_does(browser):
    token = "ghp_" + "a1B2" * 6
    text = (
        f"https://bob:hunter2@host/x?token=abc123&k=1 Authorization: Bearer abc.def {token} "
        "password=swordfish /x/abcd1234.default-release/prefs.js"
    )
    out = redact(browser, {}, text)
    for secret in ("bob", "hunter2", "abc123", "abc.def", token, "swordfish", "abcd1234"):
        assert secret not in out, out
    assert out == (
        "https://***@host/x?token=***&k=1 Authorization: Bearer *** *** password=*** "
        "/x/<profile>/prefs.js"
    )


@pytest.mark.parametrize(
    ("home", "ignore_case", "text"),
    [
        ("/home/pedro", False, "/home/pedro/.mozilla/firefox/abcd1234.default/chrome/JS/a.js"),
        ("/home/pedro", False, "failed for pedro at https://pedro:pw@example.org/p?key=1&token=2"),
        ("/home/pedro", False, "the user pedro, again pedro, and pedrolino in /home/pedrolino"),
        ("C:\\Users\\Pedro", True, "c:/users/pedro/AppData and C:\\\\Users\\\\PEDRO\\x for Pedro"),
        # Adversarial: the home is a whole folder name, never the start, the end or the middle of
        # another one (a hyphen counts as part of a name, a dot or a slash ends it).
        (
            "/home/pedro",
            False,
            "/home/pedro-bob/x /home/pedro_x /home/pedro2 /home/pedro. /home/pedro,",
        ),
        (
            "/home/pedro",
            False,
            "/var/home/pedro/x /srv/home/pedro /xhome/pedro /home/pedro/home/pedro",
        ),
        ("/home/pedro", False, "/home/PEDRO/x on a case-sensitive system, /home/pedro/x"),
        (
            "/home/pedro",
            False,
            "/home/pedro\u0301x /home/pedro\U0001d400 /home/pedro\u00b2 /home/pedro\u0663",
        ),
        # ... with the trailing separators a home may come with.
        ("/home/pedro/", False, "/home/pedro/a /home/pedrolino/a /home/pedro"),
        ("/home/pedro//", False, "/home/pedro/a /home/pedro-x"),
        ("/home/pedro\\", False, "/home/pedro\\a /home/pedro/a /home/pedrolino"),
        # ... with letters that are not ASCII.
        (
            "/home/Jos\u00e9",
            False,
            "/home/Jos\u00e9/x /home/Jos\u00e9phine /home/\u00e9Jos\u00e9 /home/Jos\u00e9_",
        ),
        (
            "/home/\u05d3\u05e0\u05d9",
            False,
            "/home/\u05d3\u05e0\u05d9/x /home/\u05d3\u05e0\u05d9\u05d0 \u05d3\u05e0\u05d9",
        ),
        ("/home/a(b)+[c]", False, "/home/a(b)+[c]/x /home/a(b)+[c]x /home/a(b)+[c]-"),
        # ... on Windows, in either case and with either slash.
        ("C:\\Users\\x", True, "C:\\Users\\x\\a C:\\Users\\xavier\\a c:/users/X/a C:\\Users\\x-y"),
        ("C:\\Users\\Pedro\\", True, "C:\\Users\\Pedro\\a c:/users/pedrolino C:\\Users\\PedroX"),
        ("C:\\Users\\Jos\u00c9", True, "c:/users/jos\u00e9/a C:\\Users\\JOS\u00c9phine"),
    ],
)
def test_the_script_and_the_python_side_hide_the_same_things(browser, home, ignore_case, text):
    options = {"homes": [home], "user": "pedro", "ignoreCase": ignore_case}
    python = Redactor(home=home, user="pedro", ignore_case=ignore_case)
    assert redact(browser, options, text) == python(text)


@pytest.mark.parametrize(
    ("home", "text", "expected"),
    [
        # Adversarial: the same cases as in tests/test_redaction_hostile.py, with the answer spelled
        # out, so that both sides doing nothing (or both doing too much) cannot pass as "the same".
        ("/home/al", "/home/alice/x", "/home/alice/x"),
        ("/home/al", "/home/al/x", "~/x"),
        ("/home/al", "a /home/al.", "a ~."),
        ("/home/al", "/home/al-bob/x", "/home/al-bob/x"),
        ("/home/jo", "/var/home/jo/x", "/var/home/jo/x"),
        ("/home/pedro", "/home/pedrolino and /home/pedro", "/home/pedrolino and ~"),
        ("/home/pedro/", "/home/pedro/a /home/pedrolino/a", "~/a /home/pedrolino/a"),
        (
            "/home/Jos\u00e9",
            "/home/Jos\u00e9phine/a /home/Jos\u00e9/b",
            "/home/Jos\u00e9phine/a ~/b",
        ),
        # The script also knows the address spelling (percent-encoded), which Python does not print.
        (
            "/home/Jos\u00e9",
            "file:///home/Jos%C3%A9/x file:///home/Jos%C3%A9phine/x",
            "file://~/x file:///home/Jos%C3%A9phine/x",
        ),
        ("C:\\Users\\x", "C:\\Users\\xavier\\a C:\\Users\\x\\a", "C:\\Users\\xavier\\a ~\\a"),
    ],
)
def test_a_home_folder_is_hidden_only_as_a_whole_folder_name(browser, home, text, expected):
    assert redact(browser, {"homes": [home]}, text) == expected


# --- the health check ---------------------------------------------------------------------------

ELEMENTS = [
    ("navigator-toolbox", "navigator-toolbox", "#navigator-toolbox"),
    ("tabs-toolbar", "TabsToolbar", "#TabsToolbar"),
    ("nav-bar", "nav-bar", "#nav-bar"),
    ("urlbar", "urlbar", "#urlbar"),
    ("bookmarks-toolbar", "PersonalToolbar", "#PersonalToolbar"),
    ("tabs-holder", "tabbrowser-tabs", "#tabbrowser-tabs"),
]


@pytest.mark.parametrize(("check", "element", "selector"), ELEMENTS)
def test_a_renamed_element_fails_its_check_and_the_note_names_the_change(
    browser, check, element, selector
):
    with renamed(browser, element):
        status = checked(browser)
    failure = failed_health(status)
    assert list(failure) == [check]
    note = failure[check]
    assert selector in note and "Firefox may have renamed" in note
    assert checked(browser).failed() == []  # and it heals when the element is back


def test_several_failures_are_all_reported(browser):
    with renamed(browser, "nav-bar"), renamed(browser, "TabsToolbar"):
        assert set(failed_health(checked(browser))) == {"nav-bar", "tabs-toolbar"}


def test_window_buttons_without_the_customtitlebar_attribute_fail_that_check(browser):
    browser.js(STAND_IN_BUTTONS)
    failure = failed_health(checked(browser))
    assert list(failure) == ["customtitlebar"]
    assert "customtitlebar attribute" in failure["customtitlebar"]
    browser.js("document.documentElement.setAttribute('customtitlebar', '');")
    assert checked(browser).failed() == []  # with the attribute it is the other, supported variant


def test_customtitlebar_without_the_holder_of_the_tabs_fails_the_tabs_check(browser):
    browser.js("document.documentElement.setAttribute('customtitlebar', '');")
    browser.js(
        "document.querySelector('#TabsToolbar .toolbar-items').classList.replace("
        "'toolbar-items', 'toolbar-items-gone');"
    )
    try:
        failure = failed_health(checked(browser))
    finally:
        browser.js(
            "document.querySelector('#TabsToolbar .toolbar-items-gone').classList.replace("
            "'toolbar-items-gone', 'toolbar-items');"
        )
    assert "toolbar-items" in failure["tabs-holder"] and "customtitlebar" in failure["tabs-holder"]


STAND_IN_BUTTONS = """
  const box = document.createXULElement('hbox');
  box.className = 'titlebar-buttonbox-container';
  box.id = 'peekafoxy-test-buttons';
  box.style.display = 'flex';  // visible whatever Firefox's own rules say about the attribute
  const button = document.createXULElement('hbox');
  button.style.cssText = 'width: 46px; min-height: 30px; height: 30px;';
  box.append(button);
  document.getElementById('TabsToolbar').append(box);
"""


def test_a_missing_browser_api_fails_the_apis_check_and_names_it(browser):
    browser.js("window.SessionStore_kept = window.SessionStore; window.SessionStore = undefined;")
    try:
        failure = failed_health(checked(browser))
    finally:
        browser.js("window.SessionStore = window.SessionStore_kept;")
    assert "SessionStore.setCustomWindowValue" in failure["browser-apis"]


def test_a_pref_of_the_wrong_type_fails_the_prefs_check_and_the_default_is_still_used(
    browser_with_a_bad_pref,
):
    browser = browser_with_a_bad_pref
    browser.wait_for_status_file()
    failure = failed_health(checked(browser))
    assert list(failure) == ["prefs"]
    note = failure["prefs"]
    assert "peekafoxy.urlbar.autohide" in note and "a number instead of a true/false" in note
    assert "Reset it in about:config" in note
    assert not browser.js("return document.documentElement.hasAttribute('autohide-urlbar');")


def test_a_pref_that_is_not_registered_is_named(browser):
    browser.js(
        "Services.prefs.getDefaultBranch('').deleteBranch('peekafoxy.strip.px');"
        "Services.prefs.clearUserPref('peekafoxy.strip.px');"
    )
    try:
        note = failed_health(checked(browser))["prefs"]
    finally:
        browser.diag("Peek.registerDefaults();")
    assert "peekafoxy.strip.px is not registered" in note
    assert checked(browser).failed() == []


def test_values_outside_their_range_are_reported_with_the_value_actually_used(browser):
    browser.js("Services.prefs.setIntPref('peekafoxy.strip.px', 99999);")
    note = failed_health(checked(browser))["settings-values"]
    assert "peekafoxy.strip.px is 99999" in note and "1 to 40" in note and "uses 40" in note
    browser.js("Services.prefs.setIntPref('peekafoxy.show.ms', -5);")
    note = failed_health(checked(browser))["settings-values"]
    assert "1 more setting(s) are out of range" in note


def test_a_shortcut_that_does_not_parse_is_reported_with_the_default_in_use(browser):
    browser.js(
        "Services.prefs.setStringPref('peekafoxy.tabs.shortcut', 'Ctrl+Alt+Nonsense\\u0000');"
    )
    note = failed_health(checked(browser))["shortcuts"]
    assert "peekafoxy.tabs.shortcut" in note and "default Ctrl+Alt+T is used" in note
    assert "\x00" not in note


def test_two_bars_with_the_same_shortcut_are_reported(browser):
    browser.js(
        """Services.prefs.setStringPref('peekafoxy.tabs.shortcut', 'ctrl+alt+k');
           Services.prefs.setStringPref('peekafoxy.urlbar.shortcut', 'Alt+Ctrl+K');"""
    )
    note = failed_health(checked(browser))["shortcuts-distinct"]
    assert "Ctrl+Alt+K" in note and "only one of them reacts" in note


def test_changing_a_setting_rechecks_by_itself(browser):
    browser.js("Services.prefs.setStringPref('peekafoxy.tabs.shortcut', 'Ctrl+Alt+U');")
    browser.wait(
        "ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs')"
        ".Diag.health().some(r => r.name === 'shortcuts-distinct' && !r.ok)",
        5,
        "the check did not run again after a pref changed",
    )


def test_a_popup_window_without_toolbars_is_not_blamed_for_missing_bars(browser):
    before = set(browser.client.chrome_window_handles)
    browser.js(
        "window.openDialog('chrome://browser/content/browser.xhtml', '_blank', "
        "'chrome,dialog=no,toolbar=no,location=no,menubar=no,personalbar=no,width=500,height=400', "
        "'about:blank');"
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and set(browser.client.chrome_window_handles) == before:
        time.sleep(0.1)
    popup = next(iter(set(browser.client.chrome_window_handles) - before))
    browser.switch_to(popup)
    browser.wait("gBrowserInit.delayedStartupFinished", 15)
    browser.wait("document.getElementById('tabs-autohide-button')")
    time.sleep(1)  # the popup's own script runs and checks at idle
    browser.diag("Diag.check(window);")
    shown = browser.diag(
        "return {toolbars: window.toolbar.visible, failing: Diag.health().filter(r => !r.ok)"
        ".map(r => r.name)};"
    )
    browser.js("window.close();")
    browser.switch_to(browser.first_window)
    assert shown == {"toolbars": False, "failing": []}


def test_the_settings_page_check_is_reported_once_the_page_has_been_opened(browser):
    assert "settings-page" not in read_status(browser.chrome_dir).health  # not looked at yet
    browser.open_settings("#peekafoxy")
    browser.wait(f"{PANE}?.hidden === false")
    assert status_of(browser).health["settings-page"] == "ok"


# --- startup, with a Firefox that has changed ---------------------------------------------------


def _navbar_is_renamed_in_the_check(source: str) -> str:
    old = '["nav-bar", "nav-bar"],'
    assert source.count(old) == 1, "the nav-bar check moved: update this test"
    return source.replace(old, '["nav-bar", "nav-bar-renamed-by-firefox"],')


@pytest.fixture(scope="module")
def browser_with_a_broken_navbar(firefox_install, tmp_path_factory):
    """A Firefox in which, from the first moment, the navigation bar is not where it was."""
    root = tmp_path_factory.mktemp("broken-navbar")
    with launched(firefox_install, root, edit_module=_navbar_is_renamed_in_the_check) as helper:
        yield helper


def test_a_problem_present_at_startup_is_in_the_file_the_settings_page_and_the_doctor(
    browser_with_a_broken_navbar,
):
    browser = browser_with_a_broken_navbar
    browser.wait_for_status_file()
    failure = failed_health(status_of(browser))
    assert list(failure) == ["nav-bar"]
    assert "The element #nav-bar (the navigation bar) was not found" in failure["nav-bar"]
    # The script itself is not broken by it: the toolbar buttons are there, the bars work.
    assert browser.js("return !!document.getElementById('tabs-autohide-button');")

    browser.open_settings("#peekafoxy")
    browser.wait(f"{PANE}?.hidden === false")
    shown = browser.settings(SUPPORT)
    assert shown["state"] == "problem"
    assert shown["lines"][0].startswith("Problem found: The element #nav-bar (the navigation bar)")
    browser.close_settings_tabs()

    doctor = run_doctor(browser, browser.install_dir)
    health = checks_of(doctor)["status.health"]
    assert health["status"] == "warn" and health["code"] == "PAF-615"
    assert "nav-bar" in health["message"]
    assert "PAF-613" not in codes_of(doctor)


@pytest.fixture(scope="module")
def browser_for_doctor(firefox_install, tmp_path_factory):
    """Doctor runs before Firefox has ever started on the profile, and again after."""
    seen: dict = {}

    def before(profile: Path) -> None:
        seen["before"] = run_doctor(profile, firefox_install)

    with launched(firefox_install, tmp_path_factory.mktemp("doctor"), before_start=before) as h:
        h.doctor_before = seen["before"]
        yield h


def test_the_doctor_warns_before_the_script_has_run_and_is_content_after(browser_for_doctor):
    browser = browser_for_doctor
    assert "PAF-613" in codes_of(browser.doctor_before)  # "Firefox has not run the script yet"
    browser.wait_for_status_file()
    browser.flush()
    doctor = run_doctor(browser, browser.install_dir)
    found = checks_of(doctor)
    assert {"status.file", "status.script", "status.health", "status.errors"} <= set(found)
    assert found["status.file"]["status"] == "ok" and "1 window(s)" in found["status.file"]["value"]
    assert found["status.health"]["status"] == "ok"
    assert found["status.health"]["value"] == f"{len(HEALTH)} checks ok"
    assert found["status.errors"]["status"] == "ok"
    assert VERSION in found["status.script"]["value"]
    assert not codes_of(doctor) & {"PAF-613", "PAF-614", "PAF-615", "PAF-616"}


# --- a status file that cannot be written, or that is already there as garbage -------------------


def _a_folder_where_the_file_goes(profile: Path) -> None:
    folder = profile / "chrome" / STATUS_FILE
    folder.mkdir()
    (folder / "inside.txt").write_text("a folder holds the name of the status file")


@pytest.fixture(scope="module")
def browser_that_cannot_write_its_status(firefox_install, tmp_path_factory):
    root = tmp_path_factory.mktemp("cannot-write")
    with launched(firefox_install, root, before_start=_a_folder_where_the_file_goes) as helper:
        yield helper


def test_a_status_file_that_cannot_be_written_is_recorded_and_changes_nothing_else(
    browser_that_cannot_write_its_status,
):
    browser = browser_that_cannot_write_its_status
    browser.diag("Diag.check(window);")
    browser.flush()
    stats = browser.diag("return Diag.stats();")
    assert stats["writesFailed"] >= 1 and stats["writes"] == 0
    events = browser.diag("return Diag.events();")
    problem = [e for e in events if e["where"] == "status:write"]
    assert problem and problem[0]["level"] == "warn"
    assert "could not be written" in problem[0]["message"]
    # The script works as if nothing had happened.
    assert browser.js("return !!document.getElementById('tabs-autohide-button');")
    browser.js("document.documentElement.removeAttribute('autohide-tabs');")
    browser.js(
        "window.dispatchEvent(new KeyboardEvent('keydown', {code: 'KeyT', ctrlKey: true, altKey: true, bubbles: true, cancelable: true}));"
    )
    assert browser.js("return document.documentElement.hasAttribute('autohide-tabs');")
    browser.js("document.documentElement.removeAttribute('autohide-tabs');")
    # And it does not try again in a loop: the failure is recorded without queueing another write.
    before = browser.diag("return Diag.stats().writesFailed;")
    time.sleep(5)
    assert browser.diag("return Diag.stats().writesFailed;") == before
    assert (browser.chrome_dir / STATUS_FILE / "inside.txt").exists()  # nothing of ours deleted it


@pytest.fixture(scope="module")
def browser_with_a_read_only_chrome_folder(firefox_install, tmp_path_factory):
    if sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("a folder cannot be made read-only for this user here")
    holder: dict = {}

    def lock(profile: Path) -> None:
        holder["folder"] = profile / "chrome"
        holder["folder"].chmod(0o555)

    try:
        with launched(
            firefox_install, tmp_path_factory.mktemp("read-only"), before_start=lock
        ) as helper:
            yield helper
    finally:
        holder["folder"].chmod(0o755)


def test_a_read_only_profile_folder_is_silent_but_recorded(
    browser_with_a_read_only_chrome_folder,
):
    browser = browser_with_a_read_only_chrome_folder
    browser.diag("Diag.check(window);")
    browser.flush()
    assert browser.diag("return Diag.stats().writesFailed;") >= 1
    assert not (browser.chrome_dir / STATUS_FILE).exists()
    assert not (browser.chrome_dir / f"{STATUS_FILE}.tmp").exists()
    events = browser.diag("return Diag.events();")
    assert any(e["where"] == "status:write" for e in events)
    assert browser.js("return !!document.getElementById('urlbar-autohide-button');")


def _garbage_status(profile: Path) -> None:
    (profile / "chrome" / STATUS_FILE).write_bytes(
        b"\x00" * 3_000_000 + b'{"schema": 1, "updated": ' + b"\xff" * 1_000_000
    )


@pytest.fixture(scope="module")
def browser_with_a_huge_old_status(firefox_install, tmp_path_factory):
    with launched(
        firefox_install, tmp_path_factory.mktemp("huge-status"), before_start=_garbage_status
    ) as helper:
        yield helper


def test_a_huge_corrupt_status_file_is_replaced_by_a_small_valid_one(
    browser_with_a_huge_old_status,
):
    browser = browser_with_a_huge_old_status
    path = browser.chrome_dir / STATUS_FILE
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and path.stat().st_size > 1_000_000:
        time.sleep(0.2)
    assert path.stat().st_size < 20_000
    assert read_status(browser.chrome_dir) is not None
    assert not (browser.chrome_dir / f"{STATUS_FILE}.tmp").exists()


def _a_link_to_somebody_elses_file(profile: Path) -> None:
    precious = profile.parent / "precious.txt"
    precious.write_text("do not overwrite me")
    (profile / "chrome" / STATUS_FILE).symlink_to(precious)


@pytest.fixture(scope="module")
def browser_with_a_linked_status(firefox_install, tmp_path_factory):
    if sys.platform == "win32":
        pytest.skip("symbolic links need privileges on Windows")
    with launched(
        firefox_install,
        tmp_path_factory.mktemp("linked-status"),
        before_start=_a_link_to_somebody_elses_file,
    ) as helper:
        yield helper


def test_a_status_file_that_is_a_link_is_replaced_and_the_target_is_left_alone(
    browser_with_a_linked_status,
):
    browser = browser_with_a_linked_status
    path = browser.chrome_dir / STATUS_FILE
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and path.is_symlink():
        time.sleep(0.2)
    assert not path.is_symlink() and read_status(browser.chrome_dir) is not None
    assert (browser.profile.parent / "precious.txt").read_text() == "do not overwrite me"


# --- several windows ----------------------------------------------------------------------------


def test_the_window_count_follows_the_windows_that_are_open(browser):
    assert status_of(browser).windows == 1
    first = browser.first_window
    browser.new_window()
    browser.new_window()
    assert status_of(browser).windows == 3
    browser.js("window.close();")
    browser.switch_to(first)
    browser.wait(f"{WINDOWS_OPEN} === 2", 10, "the closed window was still counted")
    assert status_of(browser).windows == 2


WINDOWS_OPEN = (
    "ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs')"
    ".Diag.status().windows"
)


def test_windows_writing_at_once_never_leave_a_torn_file(browser):
    browser.new_window()
    browser.new_window()
    torn: list[str] = []
    reads = [0]
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                found = read_status(browser.chrome_dir)
            except Exception as error:  # a torn file is exactly what this looks for
                torn.append(repr(error))
            else:
                reads[0] += found is not None
            time.sleep(0.001)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for handle in browser.client.chrome_window_handles:
            browser.switch_to(handle)
            browser.client.set_context(browser.client.CONTEXT_CHROME)
            browser.client.execute_async_script(
                browser.DIAG
                + """const done = arguments[arguments.length - 1];
                     const writes = [];
                     for (let i = 0; i < 150; i++) {
                       Diag.error('window', 'error ' + i + ' ' + 'x'.repeat(200));
                       Diag.check(window);
                       writes.push(Diag.flush());
                     }
                     Promise.all(writes).then(() => done(true));"""
            )
    finally:
        stop.set()
        thread.join()
    assert torn == []
    assert reads[0] > 20
    browser.switch_to(browser.first_window)
    assert status_of(browser).windows == 3 and len(raw_status(browser)["errors"]) <= 50


# --- where Firefox says it was ------------------------------------------------------------------


def test_errors_from_our_files_are_recorded_and_other_scripts_errors_are_not(browser):
    browser.js(
        """const fire = (message, filename) => window.dispatchEvent(
          new ErrorEvent('error', {message, filename, lineno: 12}));
        fire('ours: boom', 'chrome://userscripts/content/autohide.uc.js');
        fire('ours too', 'chrome://userchrome/content/peekafoxy.sys.mjs');
        fire("firefox's own", 'chrome://browser/content/browser.js');
        fire('an extension', 'moz-extension://abc/background.js');
        fire('no file at all', undefined);"""
    )
    events = browser.diag("return Diag.events();")
    ours = [e for e in events if e["where"] == "autohide:uncaught"]
    assert [e["message"] for e in ours] == [
        "ours: boom (autohide.uc.js:12)",
        "ours too (peekafoxy.sys.mjs:12)",
    ]
    assert not any("firefox's own" in e["message"] or "extension" in e["message"] for e in events)


def test_a_rejection_from_firefox_itself_is_not_recorded_and_ours_is(browser):
    browser.js(
        """const reject = (reason) => {
             const promise = Promise.reject(reason); promise.catch(() => {});
             window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection', {promise, reason}));
           };
           reject(Object.assign(new Error('firefox rejected'), {stack: 'f@chrome://browser/content/x.js:1:1'}));
           reject(Object.assign(new Error('we rejected'), {stack: 'g@chrome://userscripts/content/autohide.uc.js:7:3'}));
           reject('a string');"""
    )
    messages = [e["message"] for e in browser.diag("return Diag.events();")]
    assert any("we rejected" in m for m in messages)
    assert not any("firefox rejected" in m or "a string" in m for m in messages)


def test_console_messages_keep_the_peekafoxy_prefix_and_infos_stay_out_of_the_console(browser):
    browser.diag("Diag.warn('test:where', 'hello warn'); Diag.info('test:where', 'quiet info');")
    messages = browser.js(
        """const storage = Cc["@mozilla.org/consoleAPI-storage;1"].getService(Ci.nsIConsoleAPIStorage);
           const text = (a) => { try { return String(a); } catch (e) { return '?'; } };
           return storage.getEvents().map(e => [e.level, e.arguments.map(text).join(' ')]);"""
    )
    assert ["warn", "[peekafoxy test:where] hello warn"] in messages
    assert not any("quiet info" in text for _, text in messages)


def test_a_repeated_warning_goes_to_the_console_once_not_a_thousand_times(browser):
    browser.diag("for (let i = 0; i < 1000; i++) Diag.warn('test:repeat', 'same thing');")
    count = browser.js(
        """const storage = Cc["@mozilla.org/consoleAPI-storage;1"].getService(Ci.nsIConsoleAPIStorage);
           const text = (a) => { try { return String(a); } catch (e) { return '?'; } };
           return storage.getEvents()
             .filter(e => e.arguments.map(text).join(' ').includes('test:repeat')).length;"""
    )
    assert count == 1


# --- redaction in the real file -----------------------------------------------------------------


@pytest.fixture(scope="module")
def browser_in_an_odd_folder(firefox_install, tmp_path_factory):
    root = tmp_path_factory.mktemp("odd") / "Ana María (work) é"
    root.mkdir()
    with launched(firefox_install, root) as helper:
        yield helper


def test_the_profile_folder_and_the_home_folder_never_reach_the_file(browser_in_an_odd_folder):
    browser = browser_in_an_odd_folder
    browser.wait_for_status_file()
    browser.diag(
        """const profile = PathUtils.profileDir;
           const home = Services.dirsvc.get('Home', Ci.nsIFile).path;
           Diag.error('where ' + profile, 'cannot load ' + PathUtils.toFileURI(profile) +
                      '/chrome/x.js and ' + profile + '/chrome/y.js');
           Diag.warn('test:home', 'read ' + home + '/.mozilla/firefox/abcd1234.default/prefs.js');"""
    )
    browser.flush()
    text = (browser.chrome_dir / STATUS_FILE).read_text(encoding="utf-8")
    profile = browser.profile
    home = str(Path.home())
    for hidden in (str(profile), "Ana%20Mar", "Mar\u00eda", str(profile.parent), home):
        assert hidden not in text, hidden
    assert "<profile>/chrome/y.js" in text and "~/.mozilla/firefox/<profile>/prefs.js" in text
    # Whatever the Python side would still redact, there is none left: it finds nothing to do.
    assert Redactor.for_this_machine(profile_names=["Ana Mar\u00eda (work) \u00e9"])(text) == text


def test_the_markdown_report_has_no_path_user_or_control_character(browser):
    browser.diag(
        """Diag.error('md', 'path ' + PathUtils.profileDir + ' and ' + Services.dirsvc.get('Home',
                       Ci.nsIFile).path + '\\u0000\\u202e');"""
    )
    text = browser.diag("return Diag.report();")
    assert str(browser.profile) not in text and str(Path.home()) not in text
    assert not any(char in text for char in FORBIDDEN)


def test_the_markdown_report_cannot_be_broken_by_the_events_in_it(browser):
    browser.diag(
        "Diag.error('md', 'x ```\\n# heading | pipe <b>');Diag.error('a|b', 'second ``` fence');"
    )
    text = browser.diag("return Diag.report();")
    lines = text.splitlines()
    assert lines[0] == "# Peek-a-Foxy diagnostic info"
    start = lines.index("```text")
    end = lines.index("```", start + 1)
    assert "```" not in "".join(lines[start + 1 : end]) and lines[end + 1] == ""
    assert text.count("```") == 2  # exactly one fenced block, opened and closed by us
    table = [line for line in lines if line.startswith("| ")]
    assert len(table) == 1 + len(HEALTH)
    assert all(line.count("|") - line.count("\\|") == 4 for line in table)
    assert report.NOTICE in text and report.ISSUES_NEW_URL in text


def test_the_markdown_report_lists_every_check_and_the_failures_in_plain_words(browser):
    with renamed(browser, "nav-bar"):
        browser.diag("Diag.check(window);")
        text = browser.diag("return Diag.report();")
    assert "| FAIL | nav-bar | The element #nav-bar (the navigation bar) was not found." in text
    assert f"- Program version: {VERSION}" in text and "- Windows open: 1" in text
    assert "| OK | navigator-toolbox |" in text
    assert "**Result: 1 FAIL, 12 OK**" in text


# --- the Support group --------------------------------------------------------------------------


def open_support(browser) -> None:
    browser.open_settings("#peekafoxy")
    browser.wait(f"{PANE}?.hidden === false", 10, "the pane did not open")


def test_the_support_group_is_the_last_one_and_says_that_it_works(browser):
    open_support(browser)
    shown = browser.settings(SUPPORT)
    assert shown["heads"][-1] == "Support"
    assert shown["state"] == "ok"
    assert shown["lines"] == [f"Working: Peek-a-Foxy {VERSION} is loaded in this window."]
    assert shown["button"] == "Copy diagnostic info"
    assert shown["done"] == "" and shown["failed"] == ""  # live regions start empty
    note = browser.settings(
        """const a = doc.querySelector('#peekafoxy-pane a[href]');
           return {text: a.closest('p').textContent, href: a.href, target: a.target, rel: a.rel};"""
    )
    assert note["href"] == report.ISSUES_NEW_URL
    assert note["target"] == "_blank" and "noopener" in note["rel"]
    assert note["text"].startswith("Nothing is sent anywhere") and note["text"].endswith(
        "issue page."
    )


def test_the_live_regions_and_the_button_are_accessible(browser):
    open_support(browser)
    facts = browser.settings(
        """const b = doc.getElementById('peekafoxy-copy');
           const area = doc.getElementById('peekafoxy-copy-text');
           return {
             type: b.type, disabled: b.disabled, tabIndex: b.tabIndex,
             done: doc.getElementById('peekafoxy-copy-done').getAttribute('role'),
             failed: doc.getElementById('peekafoxy-copy-failed').getAttribute('role'),
             areaHidden: area.hidden, areaLabel: area.getAttribute('aria-label'),
             areaReadonly: area.readOnly, areaDir: area.dir, areaLang: area.lang,
           };"""
    )
    assert facts == {
        "type": "button", "disabled": False, "tabIndex": 0,
        "done": "status", "failed": "alert",
        "areaHidden": True, "areaLabel": "Diagnostic info, to copy by hand",
        "areaReadonly": True, "areaDir": "ltr", "areaLang": "en",
    }  # fmt: skip
    focused = browser.settings(
        "const b = doc.getElementById('peekafoxy-copy'); b.focus(); return doc.activeElement === b;"
    )
    assert focused


def test_the_copy_button_puts_the_redacted_report_on_the_real_clipboard(browser):
    browser.diag("Peek.Clipboard.copy('something that was there before');")
    open_support(browser)
    browser.settings("doc.getElementById('peekafoxy-copy').click();")
    browser.wait(
        "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-copy-done')"
        ".textContent !== ''",
        5,
        "no confirmation was shown",
    )
    shown = browser.settings(SUPPORT)
    assert shown["done"] == (
        "The diagnostic info was copied. Please read it before you paste it into an issue."
    )
    assert shown["failed"] == ""
    text = browser.js(READ_CLIPBOARD)
    assert text.startswith("# Peek-a-Foxy diagnostic info\n")
    assert f"- Program version: {VERSION}" in text
    assert "- Firefox: " in text and "channel" in text and "| OK | nav-bar |" in text
    assert report.NOTICE in text
    assert str(browser.profile) not in text and str(Path.home()) not in text
    assert not any(char in text for char in FORBIDDEN)
    assert browser.settings("return doc.getElementById('peekafoxy-copy-text').hidden;") is True


def test_the_copied_report_is_fresh_even_when_nothing_triggered_a_check(browser):
    open_support(browser)
    with renamed(browser, "PersonalToolbar"):
        browser.settings("doc.getElementById('peekafoxy-copy').click();")
        browser.wait(
            "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-copy-done')"
            ".textContent !== ''"
        )
        text = browser.js(READ_CLIPBOARD)
    assert "| FAIL | bookmarks-toolbar |" in text


def break_clipboard(browser) -> None:
    browser.diag(
        """Peek.Clipboard.copyKept = Peek.Clipboard.copy;
           Peek.Clipboard.copy = () => { throw Components.Exception('no clipboard here', Cr.NS_ERROR_FAILURE); };"""
    )


def fix_clipboard(browser) -> None:
    browser.diag(
        "if (Peek.Clipboard.copyKept) { Peek.Clipboard.copy = Peek.Clipboard.copyKept; "
        "delete Peek.Clipboard.copyKept; }"
    )


def test_when_the_clipboard_is_unavailable_the_user_is_told_and_can_copy_by_hand(browser):
    open_support(browser)
    break_clipboard(browser)
    try:
        browser.settings("doc.getElementById('peekafoxy-copy').click();")
        browser.wait(
            "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-copy-failed')"
            ".textContent !== ''",
            5,
            "no failure message was shown",
        )
        shown = browser.settings(SUPPORT)
        assert shown["failed"].startswith("Firefox could not copy the text automatically.")
        assert shown["done"] == ""  # the success message is not shown next to the failure
        area = browser.settings(
            """const a = doc.getElementById('peekafoxy-copy-text');
               return {hidden: a.hidden, value: a.value, focused: doc.activeElement === a,
                       selected: a.selectionEnd - a.selectionStart === a.value.length};"""
        )
        assert area["hidden"] is False and area["focused"] and area["selected"]
        assert area["value"].startswith("# Peek-a-Foxy diagnostic info\n")
        assert "no clipboard here" in "".join(
            e["message"]
            for e in browser.diag("return Diag.events();")
            if e["where"] == "settings:copy"
        )
    finally:
        fix_clipboard(browser)
    # Once it works again, the next click succeeds and the fallback goes away.
    browser.settings("doc.getElementById('peekafoxy-copy').click();")
    browser.wait(
        "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-copy-done')"
        ".textContent !== ''",
        5,
    )
    shown = browser.settings(SUPPORT)
    assert shown["failed"] == "" and shown["done"].startswith("The diagnostic info was copied")
    assert browser.settings("return doc.getElementById('peekafoxy-copy-text').hidden;") is True


def test_the_status_line_names_the_first_failed_check_and_follows_changes_live(browser):
    open_support(browser)
    with renamed(browser, "nav-bar"), renamed(browser, "urlbar"):
        browser.diag("Diag.check(window);")
        browser.wait(f"{STATE_IS('problem')}", 5, "the status line did not follow the check")
        shown = browser.settings(SUPPORT)
        assert shown["lines"][0].startswith("Problem found: The element #")
        assert "was not found. Firefox may have renamed or removed it" in shown["lines"][0]
        assert shown["lines"][1] == (
            "Other problems were found as well, and the diagnostic info lists them all."
        )
    browser.diag("Diag.check(window);")
    browser.wait(STATE_IS("ok"), 5, "the status line did not go back to working")


def STATE_IS(state: str) -> str:
    return (
        "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-status')"
        f".dataset.state === '{state}'"
    )


def test_recorded_errors_turn_the_status_line_to_working_with_errors(browser):
    open_support(browser)
    browser.diag("Diag.error('test', 'something broke');")
    browser.wait(STATE_IS("errors"), 5)
    assert "Working, with errors:" in browser.settings(SUPPORT)["lines"][0]
    browser.diag("Diag.reset(); Diag.error('x','y'); Diag.reset(); Diag.check(window);")
    browser.wait(STATE_IS("ok"), 5)


def test_a_window_whose_script_did_not_finish_is_said_so_on_the_settings_page(browser):
    browser.diag("Diag.windowGone(window);")
    try:
        open_support(browser)
        shown = browser.settings(SUPPORT)
        assert shown["state"] == "notstarted"
        assert shown["lines"][0].startswith("Problem found: Peek-a-Foxy did not finish starting")
    finally:
        browser.diag("Diag.windowStarted(window);")


def test_a_pref_of_the_wrong_type_is_visible_on_the_settings_page(browser_with_a_bad_pref):
    browser = browser_with_a_bad_pref
    open_support(browser)
    shown = browser.settings(SUPPORT)
    assert shown["state"] == "problem"
    assert "peekafoxy.urlbar.autohide" in shown["lines"][0]
    browser.close_settings_tabs()


def test_the_support_group_is_in_portuguese_for_a_portuguese_firefox(browser_in_portuguese):
    browser = browser_in_portuguese
    open_support(browser)
    shown = browser.settings(SUPPORT)
    assert shown["heads"][-1] == "Suporte"
    assert shown["lines"] == [
        f"Funcionando: o Peek-a-Foxy {VERSION} est\u00e1 carregado nesta janela."
    ]
    assert shown["button"] == "Copiar informa\u00e7\u00f5es de diagn\u00f3stico"
    note = browser.settings(
        "return doc.querySelector('#peekafoxy-pane a[href]').closest('p').textContent;"
    )
    assert note.startswith("Nada \u00e9 enviado a lugar nenhum") and note.endswith(
        "issues do Peek-a-Foxy."
    )
    # The report is for an issue tracker, so it stays in English; the confirmation is translated.
    browser.settings("doc.getElementById('peekafoxy-copy').click();")
    browser.wait(
        "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-copy-done')"
        ".textContent !== ''",
        5,
    )
    assert browser.settings(SUPPORT)["done"].startswith(
        "As informa\u00e7\u00f5es de diagn\u00f3stico foram copiadas"
    )
    assert browser.js(READ_CLIPBOARD).startswith("# Peek-a-Foxy diagnostic info\n")
    browser.close_settings_tabs()


def test_the_strings_of_both_languages_have_the_same_keys_and_placeholders(browser):
    problems = browser.diag(
        """const out = [];
           const walk = (en, pt, path) => {
             for (const key of new Set([...Object.keys(en), ...Object.keys(pt)])) {
               const here = path + '.' + key;
               if (!(key in en) || !(key in pt)) { out.push('missing: ' + here); continue; }
               if (typeof en[key] === 'object') { walk(en[key], pt[key], here); continue; }
               const holes = (t) => (t.match(/\\{\\w+\\}/g) || []).sort().join();
               if (holes(en[key]) !== holes(pt[key])) out.push('placeholders: ' + here);
               if (!pt[key].trim() || !en[key].trim()) out.push('empty: ' + here);
             }
           };
           walk(Peek.STRINGS.en, Peek.STRINGS.pt, 'STRINGS');
           return out;"""
    )
    assert problems == []


@pytest.fixture
def small_window(browser):
    size = browser.js("return [window.outerWidth, window.outerHeight];")
    yield browser
    browser.js("window.resizeTo(arguments[0], arguments[1]);", *size)


@pytest.mark.parametrize("width", [320, 480])
def test_the_support_group_fits_a_tiny_window_without_sideways_scrolling(small_window, width):
    browser = small_window
    open_support(browser)
    browser.js("window.resizeTo(arguments[0], 520);", width)
    time.sleep(0.8)  # Firefox keeps a minimum window size: the test uses whatever it allowed
    fit = browser.settings(
        """const pane = doc.getElementById('peekafoxy-pane');
           pane.querySelector('#peekafoxy-copy').scrollIntoView();
           const box = (id) => doc.getElementById(id).getBoundingClientRect();
           const view = doc.documentElement.clientWidth;
           return {view, scroll: doc.documentElement.scrollWidth, pane: pane.scrollWidth,
                   paneClient: pane.clientWidth, button: box('peekafoxy-copy').right,
                   status: box('peekafoxy-status').right};"""
    )
    assert fit["scroll"] <= fit["view"] + 1, fit
    assert fit["button"] <= fit["view"] and fit["status"] <= fit["view"], fit
    assert fit["pane"] <= fit["paneClient"] + 1, fit


def test_the_fallback_text_fits_a_tiny_window_too(small_window):
    browser = small_window
    open_support(browser)
    break_clipboard(browser)
    try:
        browser.js("window.resizeTo(340, 520);")
        time.sleep(0.5)
        browser.settings("doc.getElementById('peekafoxy-copy').click();")
        browser.wait(
            "gBrowser.selectedBrowser.contentDocument.getElementById('peekafoxy-copy-text').hidden === false",
            5,
        )
        fit = browser.settings(
            """const r = doc.getElementById('peekafoxy-copy-text').getBoundingClientRect();
               return {right: r.right, view: doc.documentElement.clientWidth,
                       sideways: doc.documentElement.scrollWidth - doc.documentElement.clientWidth};"""
        )
        assert fit["right"] <= fit["view"] and fit["sideways"] <= 1, fit
    finally:
        fix_clipboard(browser)


CONTRAST = """
  // rgb(), rgba(), color(srgb ...) and oklch(), which is what newer Firefox gives for some colours.
  const oklch = (L, C, h) => {
    const a = C * Math.cos((h * Math.PI) / 180), b = C * Math.sin((h * Math.PI) / 180);
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    const lin = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
                 -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
                 -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
    return lin.map((v) => 255 * Math.min(1, Math.max(0, v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)));
  };
  const parse = (css) => {
    const n = css.match(/[\\d.]+/g).map(Number);
    if (css.startsWith('oklch(')) return [...oklch(n[0], n[1], n[2]), n[3] ?? 1];
    return css.startsWith('color(') ? [n[0] * 255, n[1] * 255, n[2] * 255, n[3] ?? 1]
                                    : [n[0], n[1], n[2], n[3] ?? 1];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // The colour behind a node: every background from the page down to the node, laid over each other
  // (many are translucent), starting from the canvas colour.
  const background = (node) => {
    const probe = doc.createElement('div');
    probe.style.cssText = 'background-color: Canvas';
    doc.body.append(probe);
    let back = parse(win.getComputedStyle(probe).backgroundColor);
    probe.remove();
    const chain = [];
    for (let n = node; n; n = n.parentElement) chain.unshift(win.getComputedStyle(n).backgroundColor);
    for (const css of chain) {
      const layer = parse(css);
      back = [0, 1, 2].map((i) => layer[i] * layer[3] + back[i] * (1 - layer[3])).concat([1]);
    }
    return `rgb(${back.slice(0, 3).join(',')})`;
  };
  const ratio = (node) => {
    const back = parse(background(node)), front = parse(win.getComputedStyle(node).color);
    const mixed = [0, 1, 2].map((i) => front[i] * front[3] + back[i] * (1 - front[3]));
    const a = lum(mixed), b = lum(back);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  const ids = ['peekafoxy-status', 'peekafoxy-copy', 'peekafoxy-copy-done'];
  const out = {};
  for (const id of ids) out[id] = ratio(doc.getElementById(id));
  out.note = ratio(doc.querySelector('#peekafoxy-pane a[href]').closest('p'));
  out.link = ratio(doc.querySelector('#peekafoxy-pane a[href]'));
  out.dark = win.matchMedia('(prefers-color-scheme: dark)').matches;
  out.forced = win.matchMedia('(forced-colors: active)').matches;
  return out;
"""


@pytest.mark.parametrize(
    "prefs",
    [
        pytest.param({}, id="light"),
        pytest.param({"ui.systemUsesDarkTheme": 1}, id="dark"),
        pytest.param(
            {"browser.display.document_color_use": 2, "ui.useAccessibilityTheme": 1},
            id="high-contrast",
        ),
    ],
)
def test_the_support_group_stays_readable_in_light_dark_and_high_contrast(browser, prefs):
    for name, value in prefs.items():
        browser.js(f"Services.prefs.setIntPref('{name}', {value});")
    open_support(browser)
    time.sleep(0.5)
    ratios = browser.settings(CONTRAST)
    for name, ratio in ratios.items():
        if name in ("dark", "forced"):
            continue
        assert ratio >= 4.5, f"{name} has a contrast of {ratio:.1f}:1 ({ratios})"


def test_portuguese_firefox_labels_survive_a_missing_language(browser):
    # An unknown language gets English, for the new strings as for all the others.
    assert browser.diag("return Peek.textFor('xx-YY').settings.supportGroup;") == "Support"
    assert browser.diag("return Peek.textFor('pt-PT').settings.supportGroup;") == "Suporte"
    assert _speaking("pt-BR")  # (the fixture that fakes the language is the one used above)


# --- the health notes in Portuguese (the file and the report stay in English) --------------------

SAMPLE_VALUES = (
    "{name: 'peekafoxy.strip.px', actual: 'int', expected: 'bool', default: false, value: 99, min: 1,"
    " max: 40, used: 40, text: 'Ctrl+Alt+K', n: 2, what: 'x', names: ['gBrowser.tabContainer', 'SessionStore'],"
    " ids: ['tabs-autohide-button', 'urlbar-autohide-button']}"
)


def test_a_failed_check_is_shown_in_portuguese_but_written_in_english(browser_in_portuguese):
    browser = browser_in_portuguese
    browser.wait_for_status_file()
    open_support(browser)
    with renamed(browser, "nav-bar"):
        browser.diag("Diag.check(window);")
        browser.wait(STATE_IS("problem"), 5)
        shown = browser.settings(SUPPORT)
        file_note = failed_health(status_of(browser))["nav-bar"]
        text = (browser.chrome_dir / STATUS_FILE).read_text(encoding="utf-8")
        report_text = browser.diag("return Diag.report();")
    browser.close_settings_tabs()
    assert shown["state"] == "problem"
    assert shown["lines"][0] == (
        "Problema encontrado: O elemento #nav-bar (a barra de navegação) não foi encontrado. "
        "O Firefox pode tê-lo renomeado ou removido, então a barra de navegação não "
        "pode ser ocultada."
    )
    assert file_note == (
        "The element #nav-bar (the navigation bar) was not found. Firefox may have renamed or removed "
        "it, so the navigation bar cannot be hidden."
    )
    assert "não foi encontrado" not in text and "não foi encontrado" not in report_text
    assert "was not found" in report_text


def test_every_note_has_a_portuguese_sentence_that_is_complete_and_not_cut(browser):
    problems = browser.diag(
        f"""const out = [], values = {SAMPLE_VALUES};
           const en = Peek.STRINGS.en.settings.health, pt = Peek.STRINGS.pt.settings.health;
           for (const key of Object.keys(en)) {{
             if (key === 'and' || key === 'kinds') continue;
             for (const [label, health] of [['en', en], ['pt', pt]]) {{
               const text = Peek.noteFor({{ parts: [[key, values]] }}, health);
               if (/[{{}}]|undefined/.test(text)) out.push(label + ' ' + key + ': unfilled: ' + text);
               if (text.endsWith('\\u2026')) out.push(label + ' ' + key + ': cut: ' + text);
               if (label === 'pt' && text === Peek.noteFor({{ parts: [[key, values]] }}, en))
                 out.push(key + ': pt equals en');
             }}
           }}
           return out;"""
    )
    assert problems == []


def test_a_sentence_missing_in_portuguese_falls_back_to_english(browser):
    texts = browser.diag(
        f"""const values = {SAMPLE_VALUES};
           const some = {{ ...Peek.STRINGS.pt.settings.health }};
           delete some.shortcutsSame;
           const part = [['shortcutsSame', {{ text: 'Ctrl+Alt+K' }}], ['shortcutMore']];
           return [Peek.noteFor({{ parts: part }}, some),
                   Peek.noteFor({{ parts: [['prefType', values]] }}, {{}}),
                   Peek.noteFor({{ parts: part }})];"""
    )
    assert texts[0].startswith(
        "Both bars use the shortcut Ctrl+Alt+K"
    )  # English, for the missing one
    assert texts[0].endswith(
        "O outro atalho tem o mesmo problema."
    )  # Portuguese, for the present one
    assert texts[1].startswith(
        "The setting peekafoxy.strip.px holds a number instead of a true/false value"
    )
    assert texts[2].startswith("Both bars use the shortcut") and texts[2].endswith(
        "The other shortcut has the same problem."
    )


def test_portuguese_notes_name_the_kinds_and_join_the_lists_in_portuguese(browser):
    text = browser.diag(
        f"""const values = {SAMPLE_VALUES};
           const pt = Peek.STRINGS.pt.settings.health;
           return [Peek.noteFor({{ parts: [['prefType', values]] }}, pt),
                   Peek.noteFor({{ parts: [['toolbarButtons', values]] }}, pt)];"""
    )
    assert "contém um número em vez de um valor verdadeiro/falso" in text[0]
    assert "tabs-autohide-button e urlbar-autohide-button" in text[1]


def test_a_hostile_value_in_a_portuguese_note_is_cleaned_like_any_other_text(browser):
    text = browser.diag(
        """const pt = Peek.STRINGS.pt.settings.health;
           return Peek.noteFor({ parts: [['shortcutBad', { name: 'n', text: 'a\\u0000b\\u202e', default: 'd' }],
                                         ['settingsPage', { what: 'x'.repeat(5000) }]] }, pt);"""
    )
    assert not any(char in text for char in FORBIDDEN) and len(text) <= 420
