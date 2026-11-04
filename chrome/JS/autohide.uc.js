// ==UserScript==
// @name           Autohide (tabs and urlbar, per window)
// @description    Per-window autohide for the tab bar (button + Ctrl+Alt+T) and the navigation bar (Ctrl+Alt+U).
// @include        main
// ==/UserScript==

(() => {
  const FLASH_MS = 1500;
  const BTN_ID = "tabs-autohide-button";
  const root = document.documentElement;

  // One entry per autohide target. `attr` is the :root attribute the CSS keys on.
  const TARGETS = {
    tabs:   { attr: "autohide-tabs",   pref: "userchrome.tabs.autohide",   session: "autohideTabs",   code: "KeyT", def: true },
    urlbar: { attr: "autohide-urlbar", pref: "userchrome.urlbar.autohide", session: "autohideUrlbar", code: "KeyU", def: false },
  };

  const setEnabled = (t, on) => {
    root.toggleAttribute(t.attr, on);
    try { SessionStore.setCustomWindowValue(window, t.session, on ? "1" : "0"); } catch (e) {}
  };

  // Initial state: saved per-window value, else the pref default.
  for (const t of Object.values(TARGETS)) {
    try {
      let saved = null;
      try { saved = SessionStore.getCustomWindowValue(window, t.session); } catch (e) {}
      setEnabled(t, saved ? saved === "1" : Services.prefs.getBoolPref(t.pref, t.def));
    } catch (e) { console.error("[autohide] init:", e, e?.stack); }
  }

  // Flash the tab bar on tab switch and when a tab is opened (link clicks, background tabs, ...).
  let timer = null;
  const flash = (ev) => {
    try {
      root.setAttribute("tabs-flash", "");
      clearTimeout(timer);
      timer = setTimeout(() => root.removeAttribute("tabs-flash"), FLASH_MS);
    } catch (e) { console.error(`[autohide] ${ev.type}:`, e, e?.stack); }
  };
  for (const type of ["TabSelect", "TabOpen"]) gBrowser.tabContainer.addEventListener(type, flash);

  // Ctrl+Alt+T / Ctrl+Alt+U toggle the current window only.
  window.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey && e.altKey) || e.shiftKey || e.metaKey) return;
    const t = Object.values(TARGETS).find((x) => x.code === e.code);
    if (!t) return;
    e.preventDefault();
    setEnabled(t, !root.hasAttribute(t.attr));
  }, true);

  // Toolbar button for the tab bar (it lives in the navbar, so it can't toggle the navbar itself).
  // The widget is created once and shared by all windows, so its callback must not close over this window.
  try {
    UC_API.Utils.createWidget({
      id: BTN_ID,
      type: "toolbarbutton",
      label: "Tabs autohide",
      tooltip: "Toggle tab bar autohide for this window (Ctrl+Alt+T)",
      image: "chrome://browser/skin/tabs.svg",
      callback(ev) {
        const win = ev.target.ownerDocument.defaultView;
        const r = win.document.documentElement;
        const on = !r.hasAttribute("autohide-tabs");
        r.toggleAttribute("autohide-tabs", on);
        try { win.SessionStore.setCustomWindowValue(win, "autohideTabs", on ? "1" : "0"); } catch (e) {}
      },
    });
  } catch (e) {
    // "already exists" is expected for every window after the first.
    if (!/already exists/.test(String(e))) console.error("[autohide] createWidget failed:", e);
  }
})();
