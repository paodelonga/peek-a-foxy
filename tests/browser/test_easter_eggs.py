"""The easter eggs of the settings page: three clicks on the fox, S W S W S A D and typing ``peek``.

All three end the same way: the browser window darkens and a video player opens in it, a remote
``<browser>`` inside a modal ``<dialog>`` (see EasterEgg in peekafoxy.sys.mjs). The real YouTube is
never used here: ``Peek.Player.url`` is pointed at a page of a local HTTP server, which also records
every request it gets (with its Referer), and a second server on another port stands for "any other
site", which must never get a request at all.

Clicks are trusted mouse events from ``windowUtils.sendMouseEvent`` (Window.synthesizeMouseEvent in newer versions) (they are hit-tested like a real
pointer, so a click beside the fox really lands on the title text); keys are real Marionette key
actions where the path matters (the search box, the shortcut field, the plain sequences) and
synthetic ``keydown`` events where a keyboard cannot be driven that way (auto-repeat, AltGr).
"""

# ruff: noqa: E501  (the long lines are JavaScript snippets)

from __future__ import annotations

import http.server
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import pytest
from conftest import TABS_HEIGHT, launched
from marionette_driver.keys import Keys

pytestmark = pytest.mark.browser

PEEK = "const Peek = ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs');"
REAL_URL = "https://www.youtube-nocookie.com/embed/6uJf2IT2Zh8?start=59&autoplay=1"
REPO = "https://github.com/paodelonga/peek-a-foxy"
TITLE = "Peek a Foxy 🦊"
DIALOG = "document.getElementById('peekafoxy-player')"
PLAYER = "document.querySelector('#peekafoxy-player browser')"
# The fox of the title, in the page's light DOM or in moz-page-header's shadow root.
FOX = (
    "(doc.querySelector('#peekafoxy-pane .pf-fox') ?? "
    "doc.querySelector('#peekafoxy-pane moz-page-header')?.shadowRoot?.querySelector('.pf-fox'))"
)
HEADING = (
    "(doc.querySelector('#peekafoxy-pane h1') ?? "
    "doc.querySelector('#peekafoxy-pane moz-page-header')?.shadowRoot?.getElementById('heading'))"
)
OBSERVERS = """
  let n = 0;
  const all = Services.obs.enumerateObservers('http-on-modify-request');
  while (all.hasMoreElements()) { all.getNext(); n++; }
  return n;
"""
BUSY = (
    "ChromeUtils.importESModule('chrome://userchrome/content/peekafoxy.sys.mjs').EasterEgg.busy()"
)
# A trusted click at (x, y) of window ``w``: Window.synthesizeMouseEvent in newer Firefox, which
# replaced windowUtils.sendMouseEvent (still the one in older versions).
CLICK = """
  const click = (w, x, y) => {
    for (const type of ['mousedown', 'mouseup']) {
      if (w.synthesizeMouseEvent) w.synthesizeMouseEvent(type, x, y, {button: 0, clickCount: 1});
      else w.windowUtils.sendMouseEvent(type, x, y, 0, 1, 0);
    }
  };
"""
PARTS = "return document.querySelectorAll('#peekafoxy-player, #peekafoxy-player browser').length;"
PROCESSES = "return ChromeUtils.getAllDOMProcesses().map(p => p.remoteType).filter(t => t && t !== 'prealloc').sort();"

# --- the local sites -----------------------------------------------------------------------------

VIDEO = """<!doctype html><title>video</title><p>video</p>
<a id="out" target="_blank" href="/embed/next.html">out</a>
<script>
  const q = new URLSearchParams(location.search);
  if (q.has("swallow")) addEventListener("keydown", (event) => {
    document.title = "key:" + event.key;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  if (q.has("go")) setTimeout(() => { location.href = q.get("go"); }, 150);
  if (q.has("popup")) setTimeout(() => {
    let opened;
    try { opened = window.open("/embed/next.html"); } catch (e) { opened = String(e); }
    document.getElementById("out").click();
    document.title = "popped:" + (opened === null ? "null" : String(opened));
  }, 150);
</script>"""
PAGES = {
    "/embed/video.html": VIDEO,
    "/embed/next.html": "<!doctype html><title>next</title>",
    "/watch.html": "<!doctype html><title>watch</title>",
}


@dataclass
class Site:
    server: http.server.ThreadingHTTPServer
    seen: list[dict] = field(default_factory=list)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def paths(self) -> list[str]:
        return [request["path"] for request in self.seen]


def _site(pages: dict[str, str] | None) -> Site:
    site: Site

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (the name http.server calls)
            site.seen.append({"path": self.path, "referer": self.headers.get("Referer")})
            body = (
                pages.get(urlsplit(self.path).path, "<title>missing</title>")
                if pages is not None
                else "<!doctype html><title>other</title>"
            )
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    site = Site(server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return site


@pytest.fixture(scope="module")
def sites() -> Iterator[tuple[Site, Site]]:
    """The site of the "video" and another site that must never be reached."""
    video, other = _site(PAGES), _site(None)
    yield video, other
    for site in (video, other):
        site.server.shutdown()
        site.server.server_close()


@pytest.fixture
def video(browser, sites) -> Site:
    """The local video site, empty of requests, with the player pointed at it."""
    site, other = sites
    site.seen.clear()
    other.seen.clear()
    point_player(browser, site.origin + "/embed/video.html")
    return site


@pytest.fixture
def other(sites) -> Site:
    return sites[1]


@pytest.fixture(autouse=True)
def clean(browser):
    """Every test starts and ends with no player, the real address, no settings tab, one window."""

    def reset() -> None:
        for handle in browser.client.chrome_window_handles:
            if handle != browser.first_window:
                browser.switch_to(handle)
                browser.js("window.close();")
        browser.switch_to(browser.first_window)
        browser.js(
            PEEK
            + """Peek.EasterEgg.close();
               Peek.Player.url = arguments[0]; Peek.Player.referrer = arguments[1];
               for (const name of ['ui.prefersReducedMotion', 'ui.useAccessibilityTheme', 'dom.disable_open_during_load'])
                 Services.prefs.clearUserPref(name);
               for (const attr of ['autohide-tabs', 'autohide-urlbar', 'peekafoxy-popup-open'])
                 document.documentElement.removeAttribute(attr);
               if (window.fullScreen) window.fullScreen = false;
               // The clicks of a test leave the pointer where they were, maybe over a tab, whose
               // preview popup would keep the tab bar open in the next test: park it over the page.
               const r = gBrowser.tabpanels.getBoundingClientRect();
               const [x, y] = [r.left + r.width / 2, r.top + r.height / 2];
               if (window.synthesizeMouseEvent) window.synthesizeMouseEvent('mousemove', x, y, {});
               else window.windowUtils.sendMouseEvent('mousemove', x, y, 0, 0, 0);""",
            REAL_URL,
            REPO,
        )
        browser.close_settings_tabs()

    reset()
    # A Windows machine may ask for reduced motion (the CI runner does), which would skip the fade
    # and the peeking that these tests look at; the tests about reduced motion turn it on themselves.
    browser.js("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
    browser.wait("!matchMedia('(prefers-reduced-motion: reduce)').matches", 5)
    yield
    reset()


# --- helpers -------------------------------------------------------------------------------------


def point_player(browser, url: str) -> None:
    browser.js(PEEK + "Peek.Player.url = arguments[0];", url)


def open_page(browser) -> None:
    """The settings page at the Peek-a-Foxy category, with the keyboard, and its fox wrapped."""
    browser.open_settings("#peekafoxy")
    browser.wait(
        f"(() => {{ const doc = gBrowser.selectedBrowser.contentDocument; return {FOX}; }})()",
        10,
        "the fox of the title was never wrapped",
    )
    # about:preferences gives its search box the focus when it opens; a person clicks the page first.
    browser.settings("doc.activeElement?.blur();")
    browser.js("window.focus(); gBrowser.selectedBrowser.focus();")


def player_open(browser) -> bool:
    return browser.js(f"return Boolean({DIALOG});")


def wait_for_player(browser, timeout: float = 10.0) -> None:
    browser.wait(f"{DIALOG}?.open && {PLAYER}", timeout, "the player did not open")


def wait_until_closed(browser) -> None:
    browser.wait(f"!{DIALOG} && !{PLAYER}", 10, "the player was not removed")


def wait_for_processes(browser, expected: list[str]) -> None:
    """The content processes (not the spare ones Firefox keeps ready) are back to ``expected``."""
    deadline = time.monotonic() + 15
    while (now := browser.js(PROCESSES)) != expected:
        assert time.monotonic() < deadline, f"processes {now}, expected {expected}"
        time.sleep(0.2)


def busy(browser) -> bool:
    return browser.js(PEEK + "return Peek.EasterEgg.busy();")


def stays_closed(browser, seconds: float = 0.8) -> bool:
    """Nothing opens for ``seconds`` (the keys and clicks are handled at once, so this is plenty)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if player_open(browser) or busy(browser):
            return False
        time.sleep(0.1)
    return True


def click_fox(browser, times: int = 3) -> None:
    """``times`` trusted clicks in a row on the middle of the fox."""
    browser.settings(
        CLICK
        + f"""const fox = {FOX};
            const r = fox.getBoundingClientRect();
            for (let i = 0; i < arguments[0]; i++) click(win, r.left + r.width / 2, r.top + r.height / 2);""",
        times,
    )


def click_title_text(browser) -> None:
    """One trusted click on the first letter of the title (the "P"), not on the fox."""
    browser.settings(
        CLICK
        + f"""const heading = {HEADING};
            const walker = doc.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
            const text = walker.nextNode();
            const range = doc.createRange();
            range.setStart(text, 0); range.setEnd(text, 1);
            const r = range.getBoundingClientRect();
            click(win, r.left + r.width / 2, r.top + r.height / 2);"""
    )


def type_real(browser, text: str) -> None:
    """Type ``text`` with real keys into whatever has the focus in the selected tab."""
    browser.client.set_context(browser.client.CONTEXT_CHROME)
    keys = browser.client.actions.sequence("key", "keyboard")
    for char in text:
        keys.key_down(char).key_up(char)
    keys.perform()
    browser.client.actions.release()


def type_synthetic(browser, presses: list[tuple[str, dict]]) -> None:
    """``keydown`` events (code, extra init) sent to the element that has the focus in the page."""
    browser.settings(
        """let target = doc.activeElement;
           while (target?.shadowRoot?.activeElement) target = target.shadowRoot.activeElement;
           target ??= doc.body;
           for (const [code, extra] of arguments[0]) {
             target.dispatchEvent(new win.KeyboardEvent('keydown', {
               code, key: code.replace(/^Key/, '').toLowerCase(), bubbles: true, cancelable: true,
               composed: true, ...extra,
             }));
           }""",
        [list(press) for press in presses],
    )


def codes(text: str, **extra) -> list[tuple[str, dict]]:
    return [(f"Key{char.upper()}", dict(extra)) for char in text]


def record_peeks(browser) -> None:
    """Keep every value the root's peekafoxy-peek takes in window.__peeks (null when it goes), and
    the height of the tab bar at that moment in window.__peekHeights."""
    browser.js(
        f"""window.__peeks = []; window.__peekHeights = [];
           window.__peekWatch?.disconnect();
           window.__peekWatch = new MutationObserver(() => {{
             window.__peeks.push(document.documentElement.getAttribute('peekafoxy-peek'));
             window.__peekHeights.push({TABS_HEIGHT});
           }});
           window.__peekWatch.observe(document.documentElement, {{attributes: true, attributeFilter: ['peekafoxy-peek']}});"""
    )


def peeks(browser) -> list[str | None]:
    return browser.js("return window.__peeks;")


def events_at(browser, where: str) -> list[dict]:
    return browser.diag("return Diag.events().filter(e => e.where === arguments[0]);", where)


# --- the three triggers --------------------------------------------------------------------------


def test_three_quick_clicks_on_the_fox_open_the_player_in_this_window(browser, video):
    """Default path: the dialog, its name and modal role, the remote browser at the video address."""
    open_page(browser)
    assert not player_open(browser)
    click_fox(browser)
    wait_for_player(browser)
    dialog = browser.js(
        f"""const d = {DIALOG}, b = {PLAYER};
            return {{role: d.getAttribute('role'), modal: d.getAttribute('aria-modal'),
                    name: d.getAttribute('aria-label'), isModal: d.matches(':modal'),
                    remote: b.isRemoteBrowser, type: b.getAttribute('type'),
                    buttons: d.querySelectorAll('button').length}};"""
    )
    assert dialog == {
        "role": "dialog",
        "modal": "true",
        "name": "Peek-A-Boo",
        "isModal": True,
        "remote": True,
        "type": "content",
        "buttons": 0,  # it closes with Escape or a click outside, not with a button
    }
    browser.wait(f"{PLAYER}.contentTitle === 'video'", 10, "the video page did not load")


def test_clicks_that_are_too_slow_do_not_count(browser, video):
    """Adversarial: three clicks spread over more than 2.8 s; three quick ones right after do."""
    open_page(browser)
    for _ in range(3):
        click_fox(browser, 1)
        time.sleep(1.6)
    assert stays_closed(browser)
    click_fox(browser)
    wait_for_player(browser)


def test_two_clicks_do_nothing_and_four_open_one_player(browser, video):
    """Adversarial: the count is exactly three, and a fourth click does not open a second player."""
    open_page(browser)
    click_fox(browser, 2)
    assert stays_closed(browser, 1.5)  # and the two clicks have expired by now
    click_fox(browser, 4)
    wait_for_player(browser)
    assert browser.js("return document.querySelectorAll('#peekafoxy-player').length;") == 1


def test_clicks_on_the_title_text_do_not_count_and_start_the_count_over(browser, video):
    """Adversarial: only the fox is a target; a click on the words in between resets the count."""
    open_page(browser)
    for _ in range(3):
        click_title_text(browser)
    assert stays_closed(browser)
    click_fox(browser, 2)
    click_title_text(browser)
    click_fox(browser, 1)
    assert stays_closed(browser)


def test_the_fox_is_not_a_tab_stop_and_the_title_reads_as_before(browser):
    """Adversarial: the span adds no role, no tab stop and nothing to the accessible name."""
    open_page(browser)
    # The accessibility service builds its tree a moment after it is first asked for.
    browser.wait(
        f"""(() => {{ const doc = gBrowser.selectedBrowser.contentDocument;
              return Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService)
                .getAccessibleFor({HEADING}); }})()""",
        10,
        "the title has no accessible",
    )
    state = browser.settings(
        f"""const fox = {FOX}, heading = {HEADING};
            const acc = Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService);
            fox.focus();
            return {{tabindex: fox.getAttribute('tabindex'), tabIndex: fox.tabIndex, role: fox.getAttribute('role'),
                    hidden: fox.getAttribute('aria-hidden'), focused: fox.matches(':focus'),
                    text: heading.textContent, name: acc.getAccessibleFor(heading)?.name,
                    nav: doc.getElementById('category-peekafoxy').textContent.trim()
                      || doc.getElementById('category-peekafoxy').getAttribute('label')}};"""
    )
    assert state == {
        "tabindex": None,
        "tabIndex": -1,
        "role": None,
        "hidden": None,
        "focused": False,
        "text": TITLE,
        "name": TITLE,
        "nav": "Peek a Foxy",
    }


def test_swswsad_makes_the_bars_peek_and_then_opens_the_player(browser, video):
    """Default path, real keys: the pattern runs on the root, then the player opens."""
    browser.js(
        "for (const a of ['autohide-tabs', 'autohide-urlbar']) document.documentElement.setAttribute(a, '');"
    )
    open_page(browser)
    # Opening the settings tab opened the tab bar for a moment (a new tab): wait until it is closed.
    browser.wait("!document.documentElement.hasAttribute('tabs-flash')", 5)
    browser.wait(f"{browser.TABS_HEIGHT} <= 8", 3, "the tab bar did not close after the new tab")
    record_peeks(browser)
    type_real(browser, "swswsad")
    browser.wait("document.documentElement.getAttribute('peekafoxy-peek') === 'tabs'", 3)
    browser.wait(f"{browser.TABS_HEIGHT} > 8", 3, "the tab bar did not open for its beat")
    assert not player_open(browser)  # not before the bars have peeked
    wait_for_player(browser)
    assert peeks(browser) == ["", "tabs", "", "navbar", "", "tabs navbar", None]
    # The pause after the tab bar's beat closes it again before the next beat, which the hide delay
    # of the pointer (300 ms by default) would not.
    assert browser.js("return window.__peekHeights;")[3] <= 8


def test_typing_peek_opens_the_player_without_the_bars_peeking(browser, video):
    """Default path, real keys."""
    open_page(browser)
    record_peeks(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    assert peeks(browser) == []


def test_capital_letters_count_too(browser, video):
    """Adversarial: Shift does not change KeyboardEvent.code, and the keydown of Shift (or of Caps
    Lock) that comes before a capital letter is not a wrong key."""
    open_page(browser)
    shift = ("ShiftLeft", {"key": "Shift", "shiftKey": True})
    caps = ("CapsLock", {"key": "CapsLock"})
    type_synthetic(
        browser,
        [caps, *codes("pe", shiftKey=True), shift, *codes("e", shiftKey=True), shift, *codes("k")],
    )
    wait_for_player(browser)


@pytest.mark.parametrize(
    "keys", ["swxswsad", "swswswad", "pexek", "pek", "swswsa"], ids=lambda k: k
)
def test_a_wrong_key_or_a_missing_one_breaks_the_sequence(browser, video, keys):
    """Adversarial: the keys must come one right after the other, all of them."""
    open_page(browser)
    type_real(browser, keys)
    assert stays_closed(browser)


def test_a_sequence_typed_after_a_broken_one_still_counts(browser, video):
    """Adversarial: "swsws" followed by "wsad" ends with the whole sequence (the extra "sw" is noise)."""
    open_page(browser)
    type_real(browser, "pexswswswsad")
    wait_for_player(browser)


def test_a_held_key_counts_once(browser, video):
    """Adversarial: auto-repeat keydowns are one press. S and W held still give S W S W S A D; E held
    in "peek" gives only one E, so it is not "peek"."""
    open_page(browser)
    repeat = {"repeat": True}
    type_synthetic(browser, codes("pe") + codes("eee", **repeat) + codes("k"))
    assert stays_closed(browser)
    type_synthetic(
        browser,
        codes("s") + codes("ss", **repeat) + codes("w") + codes("ww", **repeat) + codes("swsad"),
    )
    wait_for_player(browser)


@pytest.mark.parametrize(
    "held",
    [{"ctrlKey": True}, {"altKey": True}, {"metaKey": True}, {"modifierAltGraph": True}],
    ids=["ctrl", "alt", "meta", "altgr"],
)
def test_keys_with_ctrl_alt_meta_or_altgr_do_not_count(browser, video, held):
    """Adversarial: each letter with the modifier, then one modifier press in the middle of a plain
    sequence; the plain sequence at the end proves the page was listening."""
    open_page(browser)
    type_synthetic(browser, codes("peek", **held))
    type_synthetic(browser, codes("pe") + codes("e", **held) + codes("ek"))
    assert stays_closed(browser)
    type_synthetic(browser, codes("peek"))
    wait_for_player(browser)


def test_typing_in_the_search_box_does_not_count(browser, video):
    """Adversarial, real keys: "Find in Settings" is a text field (inside a custom element)."""
    open_page(browser)
    browser.settings("doc.getElementById('searchInput').focus();")
    type_real(browser, "peek swswsad")
    assert stays_closed(browser)


def test_typing_in_a_number_field_of_the_page_does_not_count(browser, video):
    """Adversarial, real keys: a field of the Peek-a-Foxy category itself, so the page is showing."""
    open_page(browser)
    browser.settings("doc.getElementById('peekafoxy-peekafoxy.strip.px').focus();")
    type_real(browser, "peek")
    assert stays_closed(browser)


def test_typing_in_a_shortcut_field_does_not_count(browser, video):
    """Adversarial, real keys: the recorder has the focus."""
    open_page(browser)
    browser.settings("doc.getElementById('peekafoxy-peekafoxy.tabs.shortcut').focus();")
    type_real(browser, "peek")
    assert stays_closed(browser)


def test_typing_works_in_another_category_and_in_a_normal_page(browser, video):
    """The keys count anywhere in the window, not only on the settings page: another category, and
    the empty area of the tab strip (which leaves the focus in the page's browser)."""
    open_page(browser)
    browser.settings("win.gotoPref('paneGeneral');")
    browser.settings("doc.activeElement?.blur?.();")
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    browser.js("gBrowser.selectedBrowser.focus();")
    type_real(browser, "peek")
    wait_for_player(browser)


def test_typing_in_a_text_field_of_a_web_page_does_not_count(browser, video):
    """Adversarial: the focus is in an <input> of a remote page; the IME state says so."""
    browser.js(
        "gBrowser.selectedTab = gBrowser.addTab(arguments[0], {triggeringPrincipal: "
        "Services.scriptSecurityManager.getSystemPrincipal()});",
        "data:text/html,<input id=i autofocus><textarea id=t></textarea>",
    )
    browser.wait("gBrowser.selectedBrowser.currentURI.spec.startsWith('data:')", 10)
    time.sleep(1)
    browser.js("gBrowser.selectedBrowser.focus();")
    time.sleep(0.5)
    type_real(browser, "peek")
    assert stays_closed(browser)


def test_the_bars_peek_even_when_they_are_showing(browser, video):
    """Both bars are visible (autohide off): the pattern hides, shows and restores them, and what
    it leaves behind is exactly what was there, with no saved state touched."""
    open_page(browser)
    browser.wait("!document.documentElement.hasAttribute('tabs-flash')", 5)
    assert browser.js("return !document.documentElement.hasAttribute('autohide-tabs');")
    before = browser.js(ROOT_STATE)
    record_peeks(browser)
    browser.js("gBrowser.selectedBrowser.focus();")
    type_synthetic(browser, codes("swswsad"))
    wait_for_player(browser)
    assert peeks(browser) == ["", "tabs", "", "navbar", "", "tabs navbar", None]
    heights = browser.js("return window.__peekHeights;")
    assert heights[1] <= 8 and heights[2] > 8  # hidden for the pattern, then open for its beat
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    assert browser.js(ROOT_STATE) == before


def test_clicking_a_bar_button_in_the_middle_of_a_peek_stops_it(browser, video):
    """Adversarial: the toolbar button changes the real state, so the pattern first gives way."""
    open_page(browser)
    browser.js(
        PEEK + "Peek.EasterEgg.play(window, {peek: true});"
        "document.getElementById('tabs-autohide-button')?.click();"
    )
    time.sleep(0.3)
    assert not busy(browser)
    assert browser.js("return document.documentElement.hasAttribute('peekafoxy-peek');") is False


def test_triggers_are_ignored_while_the_player_is_open(browser, video):
    """Adversarial: a second trigger, sent straight to the page (which is inert behind the dialog)
    and straight to the module, opens nothing more."""
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    type_synthetic(browser, codes("peek"))
    click_fox(browser)
    browser.js(PEEK + "Peek.EasterEgg.play(window); Peek.EasterEgg.play(window, {peek: true});")
    time.sleep(0.5)
    assert browser.js(PARTS) == 2
    assert not browser.js("return document.documentElement.hasAttribute('peekafoxy-peek');")


# --- the player ----------------------------------------------------------------------------------


def test_nothing_is_created_or_fetched_until_a_trigger(browser, video):
    """Adversarial: opening the page uses no network for the video and makes no player; the local
    site gets its first request only after the trigger. The real address is watched as well."""
    browser.js(
        """window.__fetched = [];
           window.__fetchWatch = {observe(subject) {
             const spec = subject.QueryInterface(Ci.nsIChannel).URI.spec;
             if (/youtube|ytimg|googlevideo|127\\.0\\.0\\.1/.test(spec)) window.__fetched.push(spec);
           }};
           Services.obs.addObserver(window.__fetchWatch, 'http-on-opening-request');"""
    )
    try:
        point_player(browser, REAL_URL)
        # The browsers of the window, plus the one of the settings tab about to open.
        browsers = browser.js("return document.querySelectorAll('browser').length;") + 1
        open_page(browser)
        time.sleep(1.5)
        assert browser.js("return window.__fetched;") == []
        point_player(browser, video.origin + "/embed/video.html")
        click_title_text(browser)  # the page is in use, still nothing
        time.sleep(0.5)
        assert video.seen == []
        assert not player_open(browser)
        assert browser.js("return document.querySelectorAll('browser').length;") == browsers
        click_fox(browser)
        wait_for_player(browser)
        browser.wait(f"{PLAYER}.contentTitle === 'video'", 10)
        assert video.paths() == ["/embed/video.html"]
    finally:
        browser.js("Services.obs.removeObserver(window.__fetchWatch, 'http-on-opening-request');")


def test_the_video_is_loaded_with_the_repository_as_its_referrer(browser, video):
    """Default path: without a Referer YouTube refuses the embed (Error 153)."""
    point_player(browser, video.origin + "/embed/video.html?start=59")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.wait(f"{PLAYER}.contentTitle === 'video'", 10)
    assert video.seen == [{"path": "/embed/video.html?start=59", "referer": REPO}]


def test_the_player_cannot_navigate_to_another_site(browser, video, other):
    """Adversarial: the page sends itself elsewhere; the load is stopped before any request leaves,
    the video stays, and the attempt is recorded."""
    point_player(browser, video.origin + "/embed/video.html?go=" + quote(other.origin + "/x"))
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.wait(f"{PLAYER}.contentTitle === 'video'", 10)
    time.sleep(1.5)
    assert other.seen == []
    assert player_open(browser)
    assert browser.js(f"return {PLAYER}.currentURI.spec;").startswith(
        video.origin + "/embed/video.html"
    )
    assert any(other.origin in e["message"] for e in events_at(browser, "easter-egg:blocked"))


def test_the_player_cannot_leave_the_embed_folder_of_the_same_site(browser, video):
    """Adversarial: same host, another path (YouTube's own watch page, for the real one)."""
    point_player(browser, video.origin + "/embed/video.html?go=/watch.html")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    time.sleep(1.5)
    assert "/watch.html" not in video.paths()
    assert player_open(browser)


def test_the_player_may_move_inside_the_embed_folder(browser, video):
    """The control for the two tests above: the same mechanism lets the video page change itself."""
    point_player(browser, video.origin + "/embed/video.html?go=/embed/next.html")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.wait(f"{PLAYER}.contentTitle === 'next'", 10, "an allowed navigation was stopped")


def test_a_player_that_ends_up_on_about_blank_is_closed(browser, video):
    """Adversarial: an address without http is not seen by the request check; the location check
    closes the player instead."""
    point_player(browser, video.origin + "/embed/video.html?go=about:blank")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    wait_until_closed(browser)
    assert events_at(browser, "easter-egg:blocked")
    assert not busy(browser)


def test_the_player_cannot_open_windows_or_tabs(browser, video):
    """Adversarial: with Firefox's popup blocker off, window.open and a target=_blank link still do
    nothing, because the player is sandboxed (without the sandbox both open a tab)."""
    browser.js("Services.prefs.setBoolPref('dom.disable_open_during_load', false);")
    point_player(browser, video.origin + "/embed/video.html?popup=1")
    open_page(browser)
    tabs = browser.js("return gBrowser.tabs.length;")
    windows = len(browser.client.chrome_window_handles)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.wait(f"{PLAYER}.contentTitle.startsWith('popped:')", 10)
    time.sleep(1)
    title = browser.js(f"return {PLAYER}.contentTitle;")
    assert "Window" not in title, title  # window.open gave no window (it may throw instead)
    assert browser.js("return gBrowser.tabs.length;") == tabs
    assert len(browser.client.chrome_window_handles) == windows
    assert "/embed/next.html" not in video.paths()


def test_focus_goes_into_the_dialog_and_back_to_the_page(browser, video):
    """The video gets the focus; afterwards the settings tab and its field have it again.
    While it is open the rest of the window takes no focus (the dialog is modal)."""
    open_page(browser)
    browser.settings("doc.getElementById('peekafoxy-peekafoxy.tabs.reveal.switch').focus();")
    type_real(browser, "peek")
    wait_for_player(browser)
    assert browser.js(f"return document.activeElement === {PLAYER};")
    browser.js("gURLBar.focus();")
    assert browser.js(f"return {DIALOG}.contains(document.activeElement);")
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    assert browser.js("return document.activeElement === gBrowser.selectedBrowser;")
    assert (
        browser.settings("return doc.activeElement?.id;")
        == "peekafoxy-peekafoxy.tabs.reveal.switch"
    )


def test_focus_goes_back_to_the_settings_tab_after_a_tab_switch(browser, video):
    """Adversarial: a keyboard shortcut still switches tabs behind the dialog; closing brings the
    settings tab back to the front."""
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.js("gBrowser.selectedTab = gBrowser.tabs[0];")
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    assert (
        browser.js("return gBrowser.selectedBrowser.currentURI.spec;")
        == "about:preferences#peekafoxy"
    )
    assert browser.js("return document.activeElement === gBrowser.selectedBrowser;")


@pytest.mark.parametrize("way", ["escape", "escape-in-video", "backdrop"])
def test_every_way_of_closing_removes_everything(browser, video, way):
    """Escape (also inside a video page that stops every key) and the dark area each remove the dialog, the browser, the request observer and the video's process."""
    observers = browser.js(OBSERVERS)
    processes = browser.js(PROCESSES)
    if way == "escape-in-video":
        point_player(browser, video.origin + "/embed/video.html?swallow=1")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.wait(f"{PLAYER}.contentTitle === 'video'", 10)
    assert browser.js(OBSERVERS) == observers + 1
    if way == "escape":
        browser.real_keys(Keys.ESCAPE)
    elif way == "escape-in-video":
        browser.js(f"{PLAYER}.focus();")
        browser.real_keys("x")
        browser.wait(
            f"{PLAYER}.contentTitle === 'key:x'", 5, "the video page does not have the keyboard"
        )
        browser.real_keys(Keys.ESCAPE)
    else:
        browser.js(CLICK + "click(window, 3, 3);")
    wait_until_closed(browser)
    assert browser.js(OBSERVERS) == observers
    assert not busy(browser)
    wait_for_processes(browser, processes)


def test_a_click_on_the_video_area_does_not_close_it(browser, video):
    """Adversarial: only the dark area around the video closes it, not the frame around the video."""
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.js(
        CLICK
        + f"const r = {DIALOG}.querySelector('.pf-frame').getBoundingClientRect(); click(window, r.left + 2, r.top + 2);"
    )
    time.sleep(0.3)
    assert player_open(browser)


def test_ten_rounds_leak_nothing(browser, video):
    """Adversarial: processes, observers, elements, Diag events and console errors after ten rounds."""
    observers = browser.js(OBSERVERS)
    processes = browser.js(PROCESSES)
    browser.diag("Diag.reset();")
    browser.js(
        """window.__consoleErrors = [];
           window.__consoleWatch = {observe(message) {
             try {
               const e = message.QueryInterface(Ci.nsIScriptError);
               if (!(e.flags & Ci.nsIScriptError.warningFlag) && /peekafoxy|autohide/.test(e.sourceName + e.errorMessage))
                 window.__consoleErrors.push(e.errorMessage);
             } catch (x) {}
           }};
           Services.console.registerListener(window.__consoleWatch);"""
    )
    try:
        open_page(browser)
        for _ in range(10):
            type_real(browser, "peek")
            wait_for_player(browser)
            browser.wait(f"{PLAYER}.contentTitle === 'video'", 10)
            browser.real_keys(Keys.ESCAPE)
            wait_until_closed(browser)
            browser.js("gBrowser.selectedBrowser.focus();")
        assert browser.js(OBSERVERS) == observers
        assert browser.js(PARTS) == 0
        wait_for_processes(browser, processes)
        assert browser.diag("return Diag.stats().events;") == 0
        assert browser.diag("return Diag.summary(window).state;") == "ok"
        assert browser.js("return window.__consoleErrors;") == []
        assert len(video.seen) == 10
    finally:
        browser.js("Services.console.unregisterListener(window.__consoleWatch);")


def test_closing_the_window_while_the_player_is_open(browser, video):
    """Adversarial: the window goes with the player in it; nothing is left behind, nothing is
    recorded as having gone wrong, and the next trigger, in another window, works."""
    observers = browser.js(OBSERVERS)
    browser.diag("Diag.reset();")
    second = browser.new_window()
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    browser.js("window.close();")
    browser.switch_to(browser.first_window)
    browser.wait(f"!{BUSY}", 10)
    assert second not in browser.client.chrome_window_handles
    assert browser.js(OBSERVERS) == observers
    assert browser.diag("return Diag.events().filter(e => e.level !== 'info');") == []
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)


def test_closing_the_window_while_the_bars_peek(browser, video):
    """Adversarial: the pattern stops with its window and opens no player anywhere."""
    browser.diag("Diag.reset();")
    browser.new_window()
    open_page(browser)
    type_synthetic(browser, codes("swswsad"))
    browser.wait("document.documentElement.hasAttribute('peekafoxy-peek')", 3)
    browser.js("window.close();")
    browser.switch_to(browser.first_window)
    browser.wait(f"!{BUSY}", 5)
    time.sleep(2)
    assert not player_open(browser)
    assert video.seen == []
    assert browser.diag("return Diag.events().filter(e => e.level !== 'info');") == []


def test_closing_the_settings_tab_while_the_bars_peek(browser, video):
    """Adversarial: the typed trigger belongs to the window, so the pattern runs on when the page it
    was typed after goes away, and the bars end up as they were."""
    browser.js("document.documentElement.setAttribute('autohide-tabs', '');")
    open_page(browser)
    type_synthetic(browser, codes("swswsad"))
    browser.wait("document.documentElement.hasAttribute('peekafoxy-peek')", 3)
    browser.close_settings_tabs()
    wait_for_player(browser)
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    assert browser.js("return document.documentElement.hasAttribute('peekafoxy-peek');") is False
    assert browser.js("return document.documentElement.hasAttribute('autohide-urlbar');") is False


ROOT_STATE = """
  const root = document.documentElement;
  const value = (key) => { try { return SessionStore.getCustomWindowValue(window, key); } catch (e) { return 'n/a'; } };
  return {
    attrs: root.getAttributeNames().filter(a => a.startsWith('autohide') || a.startsWith('peekafoxy')).sort(),
    session: [value('autohideTabs'), value('autohideUrlbar')],
    checked: ['tabs-autohide-button', 'urlbar-autohide-button'].map(id => document.getElementById(id)?.getAttribute('checked') ?? null),
  };
"""


@pytest.mark.parametrize(
    "setup",
    [
        "",
        "root.setAttribute('autohide-tabs', ''); root.setAttribute('autohide-urlbar', '');",
        "root.setAttribute('autohide-urlbar', ''); root.setAttribute('peekafoxy-popup-open', 'navbar');",
    ],
    ids=["nothing-hidden", "both-hidden", "navbar-held-open"],
)
def test_the_bars_are_exactly_as_before_after_peeking(browser, video, setup):
    """Adversarial: the attributes, the saved state and the buttons are what they were, including a
    navigation bar that something else was keeping open (it stays open)."""
    open_page(browser)
    browser.js("const root = document.documentElement;" + setup)
    browser.wait("!document.documentElement.hasAttribute('tabs-flash')", 5)
    before = browser.js(ROOT_STATE)
    nav_before = browser.settled_heights()["nav"]
    browser.js("gBrowser.selectedBrowser.focus();")
    type_synthetic(browser, codes("swswsad"))
    wait_for_player(browser)
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    assert browser.js(ROOT_STATE) == before
    assert browser.settled_heights()["nav"] == nav_before


def test_reduced_motion_means_no_fade_and_no_peeking(browser, video):
    """Adversarial: with reduced motion the dialog has no animation and S W S W S A D goes straight
    to the player; the default (control) has the 0.4 s fade."""
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    assert browser.js(
        f"const s = getComputedStyle({DIALOG}); return [s.animationName, s.animationDuration];"
    ) == [
        "peekafoxy-player-fade",
        "0.4s",
    ]
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
    browser.js("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
    browser.wait("matchMedia('(prefers-reduced-motion: reduce)').matches", 5)
    browser.js(
        "document.documentElement.setAttribute('autohide-tabs', ''); gBrowser.selectedBrowser.focus();"
    )
    record_peeks(browser)
    type_synthetic(browser, codes("swswsad"))
    wait_for_player(browser, 1)
    assert peeks(browser) == []
    assert browser.js(f"return getComputedStyle({DIALOG}).animationName;") == "none"


def test_high_contrast_keeps_the_overlay_opaque_in_system_colours(browser, video):
    """Adversarial: with an accessibility theme (prefers-contrast: more; forced colors cannot be
    turned on in the browser window on Linux) the overlay is opaque in system colours, and the
    player still closes with Escape."""
    browser.js("Services.prefs.setIntPref('ui.useAccessibilityTheme', 1);")
    browser.wait("matchMedia('(prefers-contrast: more)').matches", 5)
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    look = browser.js(
        f"""const d = {DIALOG};
            const probe = document.createElementNS('http://www.w3.org/1999/xhtml', 'div');
            probe.style.background = 'Canvas'; d.append(probe);
            const canvas = getComputedStyle(probe).backgroundColor; probe.remove();
            return {{overlay: getComputedStyle(d).backgroundColor, canvas}};"""
    )
    assert look["overlay"] == look["canvas"]
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)


def test_the_player_in_a_private_window_is_private(browser, video):
    """Adversarial: the video's cookies must not land in the normal profile."""
    before = set(browser.client.chrome_window_handles)
    browser.js("OpenBrowserWindow({private: true});")
    browser.wait("Services.wm.getEnumerator('navigator:browser').getNext() && true", 5)
    deadline = time.monotonic() + 15
    while not (new := [h for h in browser.client.chrome_window_handles if h not in before]):
        assert time.monotonic() < deadline, "no private window opened"
        time.sleep(0.1)
    browser.switch_to(new[0])
    browser.wait("typeof gBrowser !== 'undefined' && gBrowserInit.delayedStartupFinished", 15)
    assert browser.js("return PrivateBrowsingUtils.isWindowPrivate(window);")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    assert browser.js(f"return {PLAYER}.browsingContext.usePrivateBrowsing;")
    browser.switch_to(browser.first_window)
    assert not player_open(browser)


def test_the_player_opens_and_closes_in_full_screen(browser, video):
    """Adversarial: the window is in full screen (F11)."""
    browser.js("window.fullScreen = true;")
    browser.wait("window.fullScreen", 5, "the window did not go full screen")
    open_page(browser)
    type_real(browser, "peek")
    wait_for_player(browser)
    covers = browser.js(
        f"const r = {DIALOG}.getBoundingClientRect(); return r.width >= innerWidth - 1 && r.height >= innerHeight - 1;"
    )
    assert covers
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)


def test_a_player_that_cannot_be_made_leaves_the_window_as_it_was(browser, video):
    """Adversarial: two failures (a bad address, a browser element that cannot be made): nothing
    stays behind, a warning is recorded and the status of the page does not turn into a problem."""
    observers = browser.js(OBSERVERS)
    open_page(browser)
    browser.wait("!document.documentElement.hasAttribute('tabs-flash')", 5)
    before = browser.js(ROOT_STATE)
    point_player(browser, "not an address")
    type_real(browser, "peek")
    time.sleep(0.5)
    assert not player_open(browser)
    assert not busy(browser)
    assert events_at(browser, "easter-egg:open")
    point_player(browser, video.origin + "/embed/video.html")
    browser.js("document.createXULElement = () => { throw new Error('no browser today'); };")
    try:
        browser.js("gBrowser.selectedBrowser.focus();")
        type_real(browser, "peek")
        time.sleep(0.5)
        assert not player_open(browser)
        assert not busy(browser)
    finally:
        browser.js("delete document.createXULElement;")
    assert browser.js(OBSERVERS) == observers
    assert browser.js(ROOT_STATE) == before
    assert browser.diag("return Diag.summary(window).state;") in ("ok",)
    assert video.seen == []
    browser.js("gBrowser.selectedBrowser.focus();")
    type_real(browser, "peek")
    wait_for_player(browser)


def test_the_labels_are_in_portuguese_for_a_portuguese_firefox(browser_in_portuguese, sites):
    """The dialog's name and the settings sidebar entry follow the language of the settings page."""
    browser = browser_in_portuguese
    point_player(browser, sites[0].origin + "/embed/video.html")
    try:
        open_page(browser)
        type_real(browser, "peek")
        wait_for_player(browser)
        assert browser.js(f"return {DIALOG}.getAttribute('aria-label');") == "Peek-A-Boo"
    finally:
        browser.js(PEEK + "Peek.EasterEgg.close(); Peek.Player.url = arguments[0];", REAL_URL)
        browser.close_settings_tabs()


def _with_moz_page_header(source: str) -> str:
    """Make the page use Firefox's moz-page-header for its title (all three tested versions define
    it only after the script has run, so they get the plain heading)."""
    if "@include        about:preferences*" not in source:
        return source
    test = 'customElements.get("moz-page-header")'
    assert source.count(test) == 1, f"{test} is not in the settings script exactly once"
    return source.replace(test, "true")


@pytest.fixture(scope="module")
def browser_with_moz_page_header(firefox_install, tmp_path_factory):
    root = tmp_path_factory.mktemp("moz-page-header")
    with launched(firefox_install, root, edit_script=_with_moz_page_header) as helper:
        yield helper


def test_the_fox_works_inside_moz_page_header_too(browser_with_moz_page_header, sites):
    """Adversarial: the heading is in the shadow root of a custom element that renders later."""
    browser = browser_with_moz_page_header
    point_player(browser, sites[0].origin + "/embed/video.html")
    open_page(browser)
    assert browser.settings(
        f"const h = doc.querySelector('#peekafoxy-pane moz-page-header'); return [Boolean(h?.shadowRoot?.querySelector('.pf-fox')), {HEADING}.textContent];"
    ) == [True, TITLE]
    click_fox(browser)
    wait_for_player(browser)


# --- the key sequences on their own ---------------------------------------------------------------


def test_the_sequence_matcher_needs_the_keys_in_a_row(browser):
    """Adversarial, straight on the module: overlapping starts, wrong keys, both sequences."""
    result = browser.js(
        PEEK
        + """const run = (codes) => {
               let keys = [], hits = [];
               for (const code of codes) { const r = Peek.nextKeys(keys, code); keys = r.keys; if (r.matched) hits.push(r.matched); }
               return hits;
             };
             const k = (text) => [...text].map(c => 'Key' + c.toUpperCase());
             return {
               konami: run(k('swswsad')), overlap: run(k('swswswsad')), wrong: run(k('swswxsad')),
               peek: run(k('peek')), peekTwice: run(k('peekpeek')), ppeek: run(k('ppeek')),
               mixed: run(k('peekswswsad')), digit: run([...k('pee'), 'Digit1', 'KeyK']),
             };"""
    )
    assert result == {
        "konami": ["konami"],
        "overlap": ["konami"],
        "wrong": [],
        "peek": ["peek"],
        "peekTwice": ["peek", "peek"],
        "ppeek": ["peek"],
        "mixed": ["peek", "konami"],
        "digit": [],
    }


# --- the hint on the keyboard shortcuts page (about:keyboard) -----------------------------------

ASK_FRAME = """
window.__answer = null;
const mm = gBrowser.selectedBrowser.messageManager;
const listener = (msg) => { window.__answer = msg.data; mm.removeMessageListener('zz:frame', listener); };
mm.addMessageListener('zz:frame', listener);
const code = `sendAsyncMessage('zz:frame', (function () { ${arguments[0]} })());`;
mm.loadFrameScript('data:,' + encodeURIComponent(code), false);
"""


def ask_frame(browser, body: str):
    """Run ``body`` (a function body returning JSON) in the selected tab's content process."""
    browser.js(ASK_FRAME, body)
    browser.wait("window.__answer !== null", 8, "the page did not answer")
    return browser.js("return window.__answer;")


HINT_STATE = """
  const hint = content.document.getElementById('peekafoxy-hint');
  const actions = content.document.querySelector('.customkeys-sidebar-actions');
  return {
    count: content.document.querySelectorAll('#peekafoxy-hint').length,
    keys: hint ? [...hint.querySelectorAll('kbd')].map(k => k.textContent) : [],
    texts: hint ? [hint.querySelector('strong').textContent] : [],
    spans: hint ? hint.querySelectorAll('span').length : null,
    after: hint?.previousElementSibling?.id ?? null,
    inside: hint?.parentElement === actions,
  };
"""


def open_keyboard_page(browser, url: str = "about:keyboard") -> None:
    browser.js(
        "gBrowser.selectedTab = gBrowser.addTab(arguments[0], {triggeringPrincipal: "
        "Services.scriptSecurityManager.getSystemPrincipal()});",
        url,
    )
    browser.wait(
        "gBrowser.selectedBrowser.currentURI.spec.startsWith(arguments[0]) && "
        "!gBrowser.selectedTab.hasAttribute('busy')".replace("arguments[0]", repr(url)),
        10,
        "the page did not load",
    )
    time.sleep(1.5)


def has_keyboard_page(browser) -> bool:
    """Firefox ESR 153 has no such page: its about:keyboard has nothing of the sidebar."""
    return ask_frame(
        browser, "return !!content.document.querySelector('.customkeys-sidebar-actions');"
    )


def test_the_keyboard_shortcuts_page_gets_the_hint_under_its_reset_button(browser, video):
    """Default path: the keys, in order, under "Restore defaults", once."""
    open_keyboard_page(browser)
    if not has_keyboard_page(browser):
        pytest.skip("this Firefox has no keyboard shortcuts page")
    assert ask_frame(browser, HINT_STATE) == {
        "count": 1,
        "keys": ["S", "W", "S", "W", "S", "A", "D"],
        "texts": ["Keyboard combos"],
        "spans": 0,
        "after": "resetAll",
        "inside": True,
    }


def test_the_hint_is_not_added_twice_when_the_page_is_reloaded(browser, video):
    """Adversarial: reload, and load the page again in the same tab."""
    open_keyboard_page(browser)
    if not has_keyboard_page(browser):
        pytest.skip("this Firefox has no keyboard shortcuts page")
    browser.js("gBrowser.selectedBrowser.reload();")
    time.sleep(2.5)
    browser.js(
        "gBrowser.selectedBrowser.loadURI(Services.io.newURI('about:keyboard#again'), "
        "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});"
    )
    time.sleep(2.5)
    assert ask_frame(browser, HINT_STATE)["count"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "about:blank",
        "about:preferences",
        "about:keyboardx",
        "data:text/html,<div class='customkeys-sidebar-actions'></div>",
    ],
)
def test_other_pages_never_get_the_hint(browser, video, url):
    """Adversarial: only about:keyboard does, not a page that is named or built like it."""
    open_keyboard_page(browser, url)
    time.sleep(1.5)
    assert (
        ask_frame(browser, "return content.document.querySelectorAll('#peekafoxy-hint').length;")
        == 0
    )


def test_the_hint_follows_the_language_of_firefox(browser_in_portuguese, sites):
    browser = browser_in_portuguese
    open_keyboard_page(browser)
    if not has_keyboard_page(browser):
        pytest.skip("this Firefox has no keyboard shortcuts page")
    assert ask_frame(browser, HINT_STATE)["texts"] == ["Combos de teclado"]


def test_the_konami_sequence_works_with_the_keyboard_page_in_front(browser, video):
    """The point of the hint: typed on that page, the keys open the player (after the bars peek)."""
    open_keyboard_page(browser)
    if not has_keyboard_page(browser):
        pytest.skip("this Firefox has no keyboard shortcuts page")
    browser.js("window.focus(); gBrowser.selectedBrowser.focus();")
    type_real(browser, "swswsad")
    wait_for_player(browser)
    browser.real_keys(Keys.ESCAPE)
    wait_until_closed(browser)
