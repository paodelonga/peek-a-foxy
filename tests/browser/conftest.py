"""A real Firefox for the tests in this folder.

Opt-in: ``pytest -m browser``. It needs a Firefox install (``PEEK_A_FOXY_FIREFOX`` = path to its
binary, otherwise the first one found), ``marionette-driver`` and network access (the real
fx-autoconfig is cloned). Firefox runs headless with a throwaway profile, and from a *copy* of its
install directory, because the loader has to be written there.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from peek_a_foxy import platform
from peek_a_foxy.installer import plan_install

marionette = pytest.importorskip("marionette_driver.marionette")

pytestmark = pytest.mark.browser

SETTINGS = """\
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.page", 0);
user_pref("browser.newtabpage.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
user_pref("intl.locale.requested", "en-US");
user_pref("marionette.port", {port});
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _firefox_dir() -> Path:
    binary = os.environ.get("PEEK_A_FOXY_FIREFOX")
    if binary:
        return Path(binary).resolve().parent
    candidates = platform.firefox_dir_candidates()
    if not candidates:
        pytest.skip("no Firefox found (set PEEK_A_FOXY_FIREFOX)")
    return candidates[0]


# The element that collapses when the tab bar hides. Without ``customtitlebar`` on the root (a
# native title bar) that is #TabsToolbar itself; with it (Firefox draws the title bar: Windows,
# macOS, Linux with client-side decorations) #TabsToolbar also holds the window buttons, so only
# its tabs holder collapses. A JS expression, usable inside Browser.js() and Browser.wait().
TABS_HOLDER = (
    "(document.documentElement.hasAttribute('customtitlebar')"
    " ? document.querySelector('#TabsToolbar .toolbar-items')"
    " : document.getElementById('TabsToolbar'))"
)
TABS_HEIGHT = f"Math.round({TABS_HOLDER}.getBoundingClientRect().height)"


FIREFOX_BINARY = "firefox.exe" if sys.platform == "win32" else "firefox"


def _stop(process: subprocess.Popen) -> None:
    """End Firefox and its child processes; on Windows terminate() kills only the parent."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


# A keydown for a shortcut, as a dispatchEvent on the window. ``arguments``: the key code, then
# whether Shift is held (null: as in the default shortcut of that bar, which depends on the system).
KEYDOWN = """
  const prefs = {KeyT: 'peekafoxy.tabs.shortcut', KeyU: 'peekafoxy.urlbar.shortcut'};
  let shift = arguments[1];
  if (shift === null) {
    const name = prefs[arguments[0]];
    shift = !!name && Services.prefs.getDefaultBranch('').getStringPref(name).includes('Shift');
  }
  window.dispatchEvent(new KeyboardEvent('keydown',
    {code: arguments[0], ctrlKey: true, altKey: true, shiftKey: shift,
     bubbles: true, cancelable: true}));
"""


class Browser:
    """Thin helper around a Marionette session in the browser's chrome (privileged) context."""

    #: JS expressions (see TABS_HOLDER), for use inside wait() conditions.
    TABS_HOLDER = TABS_HOLDER
    TABS_HEIGHT = TABS_HEIGHT

    profile: Path
    install_dir: Path
    process: subprocess.Popen

    def __init__(self, client) -> None:
        self.client = client
        self.first_window = client.current_chrome_window_handle

    def js(self, script: str, *args):
        """Run ``script`` (a function body) in the current window's chrome context."""
        self.client.set_context(self.client.CONTEXT_CHROME)
        return self.client.execute_script(script, script_args=list(args))

    def wait(self, condition: str, timeout: float = 15.0, message: str = "") -> None:
        """Poll a JS expression until it is truthy."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(f"return Boolean({condition});"):
                return
            time.sleep(0.1)
        state = self.js(
            """return {focused: document.hasFocus(), active: document.activeElement?.id,
                      attrs: [...document.documentElement.getAttributeNames()]
                        .filter(a => a.startsWith('autohide') || a.startsWith('tabs-'))};"""
        )
        raise AssertionError(
            f"{message or 'timed out waiting for: ' + condition}\n"
            f"heights={self.heights()} state={state}"
        )

    def new_window(self) -> str:
        """Open a window, switch to it and wait for the script to have run in it."""
        before = set(self.client.chrome_window_handles)
        self.js("OpenBrowserWindow();")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            new = [h for h in self.client.chrome_window_handles if h not in before]
            if new:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("no new window opened")
        self.client.switch_to_window(new[0])
        self.wait(
            "typeof gBrowser !== 'undefined' && document.getElementById('tabs-autohide-button')"
        )
        self.settle_window()
        return new[0]

    def settle_window(self) -> None:
        """Leave the window the way a test expects it: startup done and nothing focused in a bar.

        Firefox may focus the URL bar of a new blank window while it finishes starting, and a
        focused URL bar correctly keeps the navigation bar (and the bookmarks bar) open, which would
        make a test that expects them to collapse fail at random.
        """
        self.wait(
            "gBrowserInit.delayedStartupFinished", message="the window never finished starting"
        )
        self.js("gURLBar.blur(); gBrowser.selectedBrowser.focus();")
        self.wait("!gURLBar.focused", message="the URL bar kept the focus")

    #: A function body that has the shared module (``Peek``) and its ``Diag`` at hand.
    DIAG = (
        "const Peek = ChromeUtils.importESModule("
        "'chrome://userchrome/content/peekafoxy.sys.mjs'); const Diag = Peek.Diag;"
    )

    def diag(self, script: str, *args):
        """Run ``script`` (a function body) with ``Peek`` and ``Diag`` of the real module."""
        return self.js(self.DIAG + script, *args)

    def flush(self) -> None:
        """Wait until Diag has written the status file (or failed to)."""
        self.client.set_context(self.client.CONTEXT_CHROME)
        self.client.execute_async_script(
            self.DIAG + "const done = arguments[arguments.length - 1];"
            "Diag.flush().then(() => done(true));"
        )

    @property
    def chrome_dir(self) -> Path:
        return self.profile / "chrome"

    def wait_for_status_file(self, timeout: float = 30.0) -> Path:
        """The status file once Firefox has written it (it is written after the window is idle)."""
        path = self.chrome_dir / "peekafoxy-status.json"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return path
            time.sleep(0.2)
        raise AssertionError(f"{path} was never written")

    def open_settings(self, hash_: str = "") -> None:
        """Open about:preferences in a new tab of the current window and wait for it to be ready."""
        self.js(
            "gBrowser.selectedTab = gBrowser.addTrustedTab('about:preferences' + arguments[0]);",
            hash_,
        )
        self.wait(
            "gBrowser.selectedBrowser.contentDocument?.getElementById('categories') && "
            "gBrowser.selectedBrowser.contentDocument.readyState === 'complete'",
            20,
            "about:preferences did not open",
        )

    def settings(self, script: str, *args):
        """Run ``script`` (a function body) with ``doc`` = the selected about:preferences tab."""
        return self.js(
            "const doc = gBrowser.selectedBrowser.contentDocument; const win = doc.defaultView;"
            + script,
            *args,
        )

    def close_settings_tabs(self) -> None:
        self.js(
            """for (const tab of [...gBrowser.tabs]) {
                 if (tab.linkedBrowser.currentURI.spec.startsWith('about:preferences'))
                   gBrowser.removeTab(tab);
               }"""
        )

    def quit_gracefully(self) -> None:
        """Quit the way a person does (Firefox saves the session on the way out) and wait for it."""
        try:
            self.client.set_context(self.client.CONTEXT_CHROME)
            self.client.execute_script(
                "Services.tm.dispatchToMainThread(() =>"
                " Services.startup.quit(Services.startup.eAttemptQuit));"
            )
        except Exception:
            pass  # the connection goes away with Firefox
        self.process.wait(timeout=60)

    def switch_to(self, handle: str) -> None:
        self.client.switch_to_window(handle)

    def settled_heights(self, quiet: float = 0.5, timeout: float = 10.0) -> dict[str, int]:
        """Heights once they have stopped changing; right after a layout change they still move."""
        deadline = time.monotonic() + timeout
        last, since = self.heights(), time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.1)
            current = self.heights()
            if current != last:
                last, since = current, time.monotonic()
            elif time.monotonic() - since >= quiet:
                return current
        raise AssertionError(f"layout never settled: {last}")

    def move_pointer(self, x: float, y: float) -> None:
        """A real pointer move (Marionette actions), so that :hover is updated like for a person."""
        self.client.set_context(self.client.CONTEXT_CHROME)
        self.client.actions.sequence("pointer", "mouse", {"pointerType": "mouse"}).pointer_move(
            int(x), int(y), duration=0
        ).perform()
        self.client.actions.release()

    def default_shortcut(self, bar: str) -> str:
        """The default shortcut of ``tabs`` or ``urlbar`` as registered in about:config."""
        return self.js(
            "return Services.prefs.getDefaultBranch('').getStringPref(arguments[0]);",
            f"peekafoxy.{bar}.shortcut",
        )

    def keydown(self, code: str, shift: bool | None = None) -> None:
        """A synthetic Ctrl+Alt keydown, with Shift as the default shortcut of KeyT / KeyU has it
        unless ``shift`` says otherwise (use ``shift=False`` for a shortcut that was recorded)."""
        self.js(KEYDOWN, code, shift)

    def real_shortcut(self, bar: str) -> None:
        """Press the default shortcut of ``tabs`` or ``urlbar`` with real keys."""
        from marionette_driver.keys import Keys

        text = self.default_shortcut(bar)
        modifiers = {"Ctrl": Keys.CONTROL, "Alt": Keys.ALT, "Shift": Keys.SHIFT}
        *held, letter = text.split("+")
        self.real_keys(letter.lower(), *(modifiers[name] for name in held))

    def real_keys(self, key: str, *modifiers: str) -> None:
        """Press ``key`` with ``modifiers`` the way a keyboard does: through Firefox's key handling.

        A ``dispatchEvent`` on the window skips that path (the capture phase, ``preventDefault``
        and what a page gets to see); a chain of Marionette key actions takes it.
        """
        self.client.set_context(self.client.CONTEXT_CHROME)
        self.js("window.focus();")
        keys = self.client.actions.sequence("key", "keyboard")
        for modifier in modifiers:
            keys.key_down(modifier)
        keys.key_down(key).key_up(key)
        for modifier in reversed(modifiers):
            keys.key_up(modifier)
        keys.perform()
        self.client.actions.release()

    def tabs_height(self) -> int:
        """Height of whatever collapses with the tab bar (see TABS_HOLDER)."""
        return self.js(f"return {TABS_HEIGHT};")

    def tabs_collapsed(self) -> bool:
        """Whether the tab bar is down to the strip (at most 8 px; 0 when only the tabs hide)."""
        return self.tabs_height() <= 8

    def heights(self) -> dict[str, int]:
        return self.js(
            f"""const h = id =>
                 Math.round(document.getElementById(id).getBoundingClientRect().height);
               return {{
                 tabs: {TABS_HEIGHT}, nav: h('nav-bar'), bookmarks: h('PersonalToolbar'),
               }};"""
        )


@pytest.fixture(scope="session")
def firefox_install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A private copy of Firefox's install directory; the loader gets written into it."""
    install_dir = tmp_path_factory.mktemp("install") / "firefox"
    shutil.copytree(_firefox_dir(), install_dir, symlinks=True)
    return install_dir


@contextmanager
def launched(
    install_dir: Path,
    root: Path,
    extra_user_js: str = "",
    edit_script: Callable[[str], str] | None = None,
    edit_module: Callable[[str], str] | None = None,
    before_start: Callable[[Path], None] | None = None,
    existing_profile: Path | None = None,
) -> Iterator[Browser]:
    """Install into a fresh profile, start Firefox headless on it, and yield a connected helper.

    ``edit_script`` may rewrite each installed ``*.uc.js`` and ``edit_module`` the shared module
    before Firefox starts; ``before_start`` is called with the profile folder, once everything is
    installed, to set up a state (a hostile file, a read-only folder) for Firefox to find.

    ``existing_profile`` starts Firefox again on a profile that an earlier ``launched`` left behind
    (to see what survives a restart): nothing is installed again, and only the Marionette port in
    its user.js is replaced.
    """
    port = _free_port()
    if existing_profile is not None:
        profile = existing_profile
        user_js = profile / "user.js"
        user_js.write_text(
            re.sub(
                r'user_pref\("marionette.port", \d+\);',
                f'user_pref("marionette.port", {port});',
                user_js.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )
    else:
        profile = root / "profile"
        profile.mkdir()
        (profile / "user.js").write_text(SETTINGS.format(port=port) + extra_user_js)
        plan_install(profile, install_dir).execute()  # the real loader, into the copy
    if existing_profile is None and edit_script is not None:
        for installed in sorted((profile / "chrome" / "JS").glob("*.uc.js")):
            installed.write_text(
                edit_script(installed.read_text(encoding="utf-8")), encoding="utf-8"
            )

    if existing_profile is None and edit_module is not None:
        module = profile / "chrome" / "resources" / "peekafoxy.sys.mjs"
        module.write_text(edit_module(module.read_text(encoding="utf-8")), encoding="utf-8")
    if before_start is not None:
        before_start(profile)

    process = subprocess.Popen(
        [
            str(install_dir / FIREFOX_BINARY),
            "--headless",
            "--marionette",
            "--remote-allow-system-access",
            "--no-remote",
            "--profile",
            str(profile),
        ],
        env={**os.environ, "MOZ_HEADLESS": "1", "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        client = marionette.Marionette(host="127.0.0.1", port=port)
        deadline = time.monotonic() + 60
        while True:
            try:
                client.start_session()
                break
            except Exception:
                if time.monotonic() > deadline or process.poll() is not None:
                    raise
                time.sleep(0.5)
        helper = Browser(client)
        helper.profile = profile
        helper.install_dir = install_dir
        helper.process = process
        helper.wait(
            "typeof UC_API !== 'undefined'", timeout=30, message="fx-autoconfig did not load"
        )
        helper.wait("document.getElementById('tabs-autohide-button')", timeout=30)
        # What the very first window looked like, before any test touches it.
        helper.initial = helper.js(
            """const box = window.gNotificationBox;
               return {
                 attrs: [...document.documentElement.getAttributeNames()]
                   .filter(a => a.startsWith('autohide') || a.startsWith('tabs-')),
                 notifications: [...box.allNotifications].map(n => ({
                   value: n.getAttribute('value'),
                   text: n.messageText.textContent.trim(),
                   buttons: [...n.querySelectorAll('button.notification-button')].map(b => b.label),
                 })),
               };"""
        )
        yield helper
        try:
            client.delete_session()
        except Exception:
            if process.poll() is None:  # a test may have quit Firefox on purpose
                raise
    finally:
        _stop(process)


@pytest.fixture(scope="session")
def browser(firefox_install: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Browser]:
    with launched(firefox_install, tmp_path_factory.mktemp("browser")) as helper:
        yield helper


@pytest.fixture(scope="session")
def browser_with_a_bad_pref(
    firefox_install: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Browser]:
    """A Firefox whose user.js sets one of our prefs to a number instead of a boolean."""
    bad = 'user_pref("peekafoxy.urlbar.autohide", 5);\n'
    with launched(firefox_install, tmp_path_factory.mktemp("bad-pref"), bad) as helper:
        yield helper


LOCALE_LINE = "Services.locale.appLocaleAsBCP47"


def _speaking(locale: str) -> Callable[[str], str]:
    """Make the script believe Firefox's interface language is ``locale``.

    A stock Firefox only has en-US, so the language the script sees can't be changed from outside;
    this replaces the one expression that asks for it and fails loudly if that expression moves.
    """

    def edit(source: str) -> str:
        assert source.count(LOCALE_LINE) == 1, f"{LOCALE_LINE} is not in the script exactly once"
        return source.replace(LOCALE_LINE, f'"{locale}"')

    return edit


@pytest.fixture(scope="session")
def browser_in_portuguese(
    firefox_install: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Browser]:
    """A Firefox whose interface language, as far as the script can tell, is pt-BR."""
    root = tmp_path_factory.mktemp("portuguese")
    with launched(firefox_install, root, edit_script=_speaking("pt-BR")) as helper:
        yield helper


# What the settings page asks of Firefox's about:preferences (see requirements() in the script).
SETTINGS_PAGE_ID = '"mainPrefPane"'


def _after_firefox_renames_the_pane_container(source: str) -> str:
    """Pretend Firefox renamed an element the settings page depends on."""
    if "@include        about:preferences*" not in source:
        return source  # the script for the browser window is left alone
    assert SETTINGS_PAGE_ID in source, f"{SETTINGS_PAGE_ID} is not in the settings script"
    return source.replace(SETTINGS_PAGE_ID, '"mainPrefPane-renamed"')


@pytest.fixture(scope="session")
def browser_with_a_changed_settings_page(
    firefox_install: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Browser]:
    """A Firefox whose about:preferences no longer has what the settings page looks for."""
    root = tmp_path_factory.mktemp("changed-settings")
    with launched(
        firefox_install, root, edit_script=_after_firefox_renames_the_pane_container
    ) as helper:
        yield helper


def _after_firefox_renames_the_last_category(source: str) -> str:
    """Pretend Firefox renamed ``gLastCategory``: the settings page asks for a name that is gone."""
    if "@include        about:preferences*" not in source:
        return source  # the script for the browser window is left alone
    assert "gLastCategory" in source, "gLastCategory is not in the settings script"
    return source.replace("gLastCategory", "gLastCategoryRenamedByFirefox")


@pytest.fixture(scope="session")
def browser_with_a_renamed_last_category(
    firefox_install: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Browser]:
    """A Firefox whose about:preferences has no ``gLastCategory`` any more."""
    root = tmp_path_factory.mktemp("renamed-last-category")
    with launched(
        firefox_install, root, edit_script=_after_firefox_renames_the_last_category
    ) as helper:
        yield helper
