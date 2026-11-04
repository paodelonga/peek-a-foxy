// ==UserScript==
// @name           Tabs autohide (per window)
// @description    Per-window toggle (Ctrl+Alt+T or toolbar button) for the tab bar autohide; flashes the bar on tab switch.
// @include        main
// ==/UserScript==

(() => {
  const PREF = "userchrome.tabs.autohide";
  const FLASH_MS = 1500;
  const BTN_ID = "tabs-autohide-button";
  const root = document.documentElement;

  const setEnabled = (on) => {
    if (on) root.setAttribute("autohide-tabs", "");
    else root.removeAttribute("autohide-tabs");
    try {
      SessionStore.setCustomWindowValue(window, "autohideTabs", on ? "1" : "0");
    } catch (e) {}
  };
  const toggle = () => setEnabled(!root.hasAttribute("autohide-tabs"));

  // Initial state: saved per-window value, else the pref default.
  let saved = null;
  try { saved = SessionStore.getCustomWindowValue(window, "autohideTabs"); } catch (e) {}
  try {
    setEnabled(saved ? saved === "1" : Services.prefs.getBoolPref(PREF, true));
  } catch (e) { console.error("[tabs_autohide] init:", e, e?.stack); }

  // Flash the bar on tab switch and when a tab is opened (link clicks, background tabs, ...).
  let timer = null;
  const flash = (ev) => {
    try {
      root.setAttribute("tabs-flash", "");
      clearTimeout(timer);
      timer = setTimeout(() => root.removeAttribute("tabs-flash"), FLASH_MS);
    } catch (e) { console.error(`[tabs_autohide] ${ev.type}:`, e, e?.stack); }
  };
  for (const type of ["TabSelect", "TabOpen"]) gBrowser.tabContainer.addEventListener(type, flash);

  // Ctrl+Alt+T toggles for this window only.
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.altKey && !e.shiftKey && !e.metaKey && e.code === "KeyT") {
      e.preventDefault();
      toggle();
    }
  }, true);

  // Toolbar button (widget is created once, shared by all windows).
  try {
    UC_API.Utils.createWidget({
      id: BTN_ID,
      type: "toolbarbutton",
      label: "Tabs autohide",
      tooltip: "Toggle tab bar autohide for this window (Ctrl+Alt+T)",
      image: "chrome://browser/skin/tabs.svg",
      callback(ev) {
        // Stateless on purpose: the first window's closure outlives that window.
        const win = ev.target.ownerDocument.defaultView;
        const r = win.document.documentElement;
        const on = !r.hasAttribute("autohide-tabs");
        r.toggleAttribute("autohide-tabs", on);
        try { win.SessionStore.setCustomWindowValue(win, "autohideTabs", on ? "1" : "0"); } catch (e) {}
      },
    });
  } catch (e) {
    // "already exists" is expected for every window after the first.
    if (!/already exists/.test(String(e))) console.error("[tabs_autohide] createWidget failed:", e);
  }
})();
