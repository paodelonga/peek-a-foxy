// ==UserScript==
// @name           Peek-a-Foxy: autohide for tabs and urlbar, per window
// @description    Per-window autohide for the tab bar (button + Ctrl+Alt+T) and the navigation bar (button + Ctrl+Alt+U).
// @include        main
// ==/UserScript==

// Runs once per browser window through fx-autoconfig. It only flips attributes on the window root;
// chrome/autohide.css does the actual collapsing and revealing.

(() => {
  const LOG = "[autohide]";
  const FLASH_MS = 1500; // how long the tab bar stays open after a tab switch/open

  const root = document.documentElement;

  // One entry per autohidden bar.
  //   attr    :root attribute that chrome/autohide.css keys on
  //   pref    default state for windows that have no saved state
  //   session key under which the state is stored with the window (SessionStore)
  //   code    KeyboardEvent.code of the Ctrl+Alt shortcut
  //   button  toolbar button shown in Customize Toolbar
  const TARGETS = [
    {
      attr: "autohide-tabs", pref: "userchrome.tabs.autohide", defaultOn: false,
      session: "autohideTabs", code: "KeyT",
      button: { id: "tabs-autohide-button", label: "Tabs autohide",
                tooltip: "Toggle tab bar autohide for this window (Ctrl+Alt+T)",
                image: "chrome://browser/skin/tabs.svg" },
    },
    {
      attr: "autohide-urlbar", pref: "userchrome.urlbar.autohide", defaultOn: false,
      session: "autohideUrlbar", code: "KeyU",
      button: { id: "urlbar-autohide-button", label: "Urlbar autohide",
                tooltip: "Toggle navigation bar autohide for this window (Ctrl+Alt+U)",
                image: "chrome://global/skin/icons/search-glass.svg" },
    },
  ];

  const setEnabled = (target, on) => {
    root.toggleAttribute(target.attr, on);
    try {
      SessionStore.setCustomWindowValue(window, target.session, on ? "1" : "0");
    } catch (e) {
      // Not fatal: the state just won't survive a session restore.
    }
  };

  // --- initial state: saved per-window value, else the pref default ---

  for (const target of TARGETS) {
    let saved = null;
    try {
      saved = SessionStore.getCustomWindowValue(window, target.session);
    } catch (e) {
      // No saved state for a brand new window.
    }
    setEnabled(target, saved ? saved === "1" : Services.prefs.getBoolPref(target.pref, target.defaultOn));
  }

  // --- flash the tab bar when tabs change (shortcuts, links, background tabs) ---

  let flashTimer = null;
  const flashTabs = () => {
    root.setAttribute("tabs-flash", "");
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => root.removeAttribute("tabs-flash"), FLASH_MS);
  };
  for (const type of ["TabSelect", "TabOpen"]) {
    gBrowser.tabContainer.addEventListener(type, flashTabs);
  }

  // --- Ctrl+Alt+T / Ctrl+Alt+U toggle the current window only ---

  window.addEventListener("keydown", (event) => {
    if (!event.ctrlKey || !event.altKey || event.shiftKey || event.metaKey) return;
    const target = TARGETS.find((t) => t.code === event.code);
    if (!target) return;
    event.preventDefault();
    setEnabled(target, !root.hasAttribute(target.attr));
  }, true);

  // --- one-time greeting ---
  //
  // Shown once per profile, so you can tell the script is loaded and working. The pref is set before
  // the notification so that other windows opening right now don't show it again.
  //
  // The text follows Firefox's interface language: Portuguese (pt, pt-BR, pt-PT...) gets the
  // Brazilian Portuguese strings, everything else gets English. To add a language, add an entry to
  // GREETING keyed by its language code (the part before the "-" or "_").

  const GREETING = {
    en: { label: "Instaalleeeeed PEEK A BOO!!! >.<", button: "Peek-a-boo!" },
    pt: { label: "Instaalaadoooo PEEK A BOO!!! >.<", button: "Peek-a-boo!" },
  };
  const greetingFor = (locale) => GREETING[String(locale).split(/[-_]/)[0].toLowerCase()] ?? GREETING.en;

  if (!Services.prefs.getBoolPref("userchrome.peekafoxy.welcomed", false)) {
    Services.prefs.setBoolPref("userchrome.peekafoxy.welcomed", true);
    try {
      const text = greetingFor(Services.locale.appLocaleAsBCP47);
      UC_API.Notifications.show({
        label: text.label,
        type: "peekafoxy-welcome",
        priority: "info",
        window,
        buttons: [
          {
            label: text.button,
            callback() {
              // The argument Firefox passes here changes between versions, so don't rely on it:
              // the notification lives in this window, which is the one that should open the tab.
              window.openWebLinkIn("https://youtu.be/6uJf2IT2Zh8?t=59", "tab");
              return false;
            },
          },
        ],
      });
    } catch (e) {
      console.error(`${LOG} greeting failed:`, e);
    }
  }

  // --- toolbar buttons ---
  //
  // A widget is created once and then shared by every window, so its callback is kept alive by the
  // first window's script. To stay valid after that window closes it must not use anything from this
  // scope: everything it needs is read from attributes on the clicked button (fx-autoconfig copies
  // extra properties of the description onto the button).
  // The urlbar button sits in the bar it hides; reveal the bar with its hover strip to use it.

  for (const { attr, session, button } of TARGETS) {
    try {
      UC_API.Utils.createWidget({
        id: button.id,
        type: "toolbarbutton",
        label: button.label,
        tooltip: button.tooltip,
        image: button.image,
        "autohide-attr": attr,
        "autohide-session": session,
        callback(event) {
          const win = event.target.ownerDocument.defaultView;
          const attrName = event.target.getAttribute("autohide-attr");
          const sessionKey = event.target.getAttribute("autohide-session");
          const on = !win.document.documentElement.hasAttribute(attrName);
          win.document.documentElement.toggleAttribute(attrName, on);
          try {
            win.SessionStore.setCustomWindowValue(win, sessionKey, on ? "1" : "0");
          } catch (e) {
            // Not fatal: the state just won't survive a session restore.
          }
        },
      });
    } catch (e) {
      // "already exists" is expected for every window after the first.
      if (!/already exists/.test(String(e))) console.error(`${LOG} createWidget ${button.id} failed:`, e);
    }
  }
})();
