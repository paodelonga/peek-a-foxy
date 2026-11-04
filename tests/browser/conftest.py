"""A real Firefox for the tests in this folder.

Opt-in: ``pytest -m browser``. It needs a Firefox install (``PEEK_A_FOXY_FIREFOX`` = path to its
binary, otherwise the first one found), ``marionette-driver`` and network access (the real
fx-autoconfig is cloned). Firefox runs headless with a throwaway profile, and from a *copy* of its
install directory, because the loader has to be written there.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
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


class Browser:
    """Thin helper around a Marionette session in the browser's chrome (privileged) context."""

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
        return new[0]

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

    def heights(self) -> dict[str, int]:
        return self.js(
            """const h = id =>
                 Math.round(document.getElementById(id).getBoundingClientRect().height);
               return {
                 tabs: h('TabsToolbar'), nav: h('nav-bar'), bookmarks: h('PersonalToolbar'),
               };"""
        )


@pytest.fixture(scope="session")
def firefox_install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A private copy of Firefox's install directory; the loader gets written into it."""
    install_dir = tmp_path_factory.mktemp("install") / "firefox"
    shutil.copytree(_firefox_dir(), install_dir, symlinks=True)
    return install_dir


@contextmanager
def launched(install_dir: Path, root: Path, extra_user_js: str = "") -> Iterator[Browser]:
    """Install into a fresh profile, start Firefox headless on it, and yield a connected helper."""
    profile = root / "profile"
    profile.mkdir()
    port = _free_port()
    (profile / "user.js").write_text(SETTINGS.format(port=port) + extra_user_js)

    plan_install(profile, install_dir).execute()  # the real loader, into the copy

    process = subprocess.Popen(
        [
            str(install_dir / "firefox"),
            "--headless",
            "--marionette",
            "--remote-allow-system-access",
            "--no-remote",
            "--profile",
            str(profile),
        ],
        env={**os.environ, "MOZ_HEADLESS": "1"},
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
        client.delete_session()
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()


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
