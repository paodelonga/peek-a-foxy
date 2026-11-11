// ==UserScript==
// @name           Peek-a-Foxy: autohide for tabs and urlbar, per window
// @description    Peek-a-boo for Foxys: per-window autohide for the tab bar (button + shortcut) and the navigation bar (button + shortcut).
// @include        main
// ==/UserScript==

// Runs once per browser window through fx-autoconfig. It flips attributes and sets variables on the
// window root; chrome/autohide.css does the actual collapsing and revealing. The prefs, the shortcut
// format and the texts are in chrome/resources/peekafoxy.sys.mjs, shared with the settings page
// (JS/autohide-prefs.uc.js).

(() => {
  const Peek = ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs");
  const { PREFS, Diag } = Peek;

  // A window that a page opens (window.open with features) runs this script twice: first while it has
  // no browser UI yet (no gBrowser, no toolbox), then again once it has. The early run does nothing
  // and says so only as information; the mark keeps any later run from registering everything twice.
  if (typeof gBrowser === "undefined" || !document.getElementById("navigator-toolbox")) {
    Diag.info("autohide:init", "the window has no browser UI yet; the script waits for its next run");
    return;
  }
  if (window.__peekAFoxyStarted) return;
  window.__peekAFoxyStarted = true;

  Diag.watch(window, "autohide");

  // Whatever goes wrong in the script is recorded (and shown in the Browser Console) instead of
  // only stopping it halfway without a trace.
  try {
    const root = document.documentElement;

    // One entry per autohidden bar.
    //   name     key of the bar's texts in Peek.STRINGS
    //   attr     :root attribute that chrome/autohide.css keys on
    //   pref     default state for windows that have no saved state
    //   shortcut pref holding the shortcut that toggles the bar in the current window
    //   session  key under which the state is stored with the window (SessionStore)
    //   button   toolbar button shown in Customize Toolbar (its texts are in Peek.STRINGS)
    //   binding  the parsed shortcut (kept up to date by applySettings)
    const TARGETS = [
      {
        name: "tabs", attr: "autohide-tabs", pref: PREFS.tabsAutohide, shortcut: PREFS.tabsShortcut,
        session: "autohideTabs",
        button: { id: "tabs-autohide-button", image: "chrome://browser/skin/tabs.svg" },
      },
      {
        name: "urlbar", attr: "autohide-urlbar", pref: PREFS.urlbarAutohide, shortcut: PREFS.urlbarShortcut,
        session: "autohideUrlbar",
        button: { id: "urlbar-autohide-button", image: "chrome://global/skin/icons/search-glass.svg" },
      },
    ];

    // --- texts ---
    //
    // The toolbar buttons are created once, by the first window, so their texts follow the language
    // Firefox started with.

    const LOCALE = Services.locale.appLocaleAsBCP47;
    const TEXT = Peek.textFor(LOCALE);
    const tooltipFor = (target) => TEXT[target.name].tooltip.replace("{key}", target.binding.text);

    // --- prefs ---
    //
    // Registered on Firefox's *default* branch, so they are listed in about:config with the right type
    // (nobody has to create them by hand, or pick the wrong type). That is not "pinning" them: nothing
    // is written to user.js or prefs.js until someone changes a value. Reads never throw: a pref of
    // another type gives the default.

    Peek.registerDefaults();

    // The state of a bar is an attribute on the window root. Changing it with setEnabled() also saves
    // it with the window (SessionStore), so that a session restore brings it back; applyState() only
    // changes the attribute (used at startup, before the window is known to SessionStore).
    //
    // A window that a page opened with features (a popup: window.toolbar.visible is false) always shows
    // its address, so that the person can tell which site it is; its navigation bar is never hidden.
    const isPopup = () => {
      try {
        return window.toolbar.visible === false;
      } catch (e) {
        return false;
      }
    };
    const mayHide = (target) => target.name !== "urlbar" || !isPopup();
    const applyState = (target, on) => root.toggleAttribute(target.attr, on && mayHide(target));
    const setEnabled = (target, on) => {
      applyState(target, on);
      try {
        SessionStore.setCustomWindowValue(window, target.session, root.hasAttribute(target.attr) ? "1" : "0");
      } catch (e) {
        // Not fatal: the state just won't survive a session restore.
        Diag.warn("autohide:session", e);
      }
    };

    // --- settings that apply live ---
    //
    // The strip height and the timings are CSS variables set on the root, but only while the user has
    // changed the pref: with no user value the variable stays whatever autohide.css says (which people
    // may have edited). The shortcuts are re-read and the button tooltips rewritten. The observer lives
    // as long as the window.

    const CSS_SETTINGS = [
      [PREFS.stripPx, "--autohide-strip", (v) => `${v}px`],
      [PREFS.tabsStripPx, "--autohide-tabs-strip", (v) => (v > 0 ? `${v}px` : null)], // 0: follow the shared strip
      [PREFS.urlbarStripPx, "--autohide-nav-strip", (v) => (v > 0 ? `${v}px` : null)],
      [PREFS.showMs, "--autohide-show-duration", (v) => `${v}ms`],
      [PREFS.showDelayMs, "--autohide-show-delay", (v) => `${v}ms`],
      [PREFS.hideMs, "--autohide-hide-duration", (v) => `${v}ms`],
      [PREFS.hideDelayMs, "--autohide-hide-delay", (v) => `${v}ms`],
    ];

    const updateTooltips = () => {
      for (const target of TARGETS) {
        try {
          const node = CustomizableUI.getWidget(target.button.id).forWindow(window).node;
          node?.setAttribute("tooltiptext", tooltipFor(target));
        } catch (e) {
          // The button may not exist yet or any more; the tooltip is only a convenience.
          Diag.info("autohide:tooltip", e);
        }
      }
    };

    const applySettings = () => {
      for (const [pref, variable, css] of CSS_SETTINGS) {
        const value = Peek.hasUserValue(pref) ? css(Peek.read(pref)) : null;
        if (value !== null) root.style.setProperty(variable, value);
        else root.style.removeProperty(variable);
      }
      for (const target of TARGETS) target.binding = Peek.bindingFor(target.shortcut);
      updateTooltips();
    };

    applySettings();
    const settingsObserver = {
      observe: (subject, topic, name) => {
        if (!name?.startsWith(Peek.PREF_BRANCH)) return;
        applySettings();
        Diag.checkSoon(window); // a setting that is now out of range or wrong is a health problem
      },
    };
    Services.prefs.addObserver(Peek.PREF_BRANCH, settingsObserver);
    window.addEventListener("unload", () => Services.prefs.removeObserver(Peek.PREF_BRANCH, settingsObserver), { once: true });

    // --- initial state: saved per-window value, else the pref default ---
    //
    // The pref default is applied right away, so that the window never starts in a state nobody chose.
    // The value saved with the window is another matter: while a window starts, SessionStore does not
    // know it yet ("Window is not tracked"), and a window that is restored from a session only gets its
    // saved values when its state is restored, which is later still (it ends with SSWindowStateReady).
    // So the saved state is looked at again at those two moments:
    //   - once SessionStore knows the window (its load event, retried a few times if it is not yet): a
    //     saved value is applied, and a bar that has none (a new window) is saved as it is now, so that
    //     the state exists from the start and not only after the first toggle;
    //   - whenever a window state has been restored (SSWindowStateReady: startup, "restore previous
    //     session", "reopen closed window"): the restored values are applied.

    for (const target of TARGETS) applyState(target, Peek.read(target.pref));

    // true: every bar was looked at; false: SessionStore does not know this window yet.
    const syncSession = () => {
      for (const target of TARGETS) {
        let saved;
        try {
          saved = SessionStore.getCustomWindowValue(window, target.session);
        } catch (e) {
          if (/not tracked/i.test(String(e))) return false;
          Diag.warn("autohide:state", e);
          continue;
        }
        if (saved === "1" || saved === "0") {
          applyState(target, saved === "1");
        } else if (saved === "") {
          try {
            SessionStore.setCustomWindowValue(window, target.session, root.hasAttribute(target.attr) ? "1" : "0");
          } catch (e) {
            Diag.warn("autohide:session", e);
          }
        }
      }
      return true;
    };

    // At most about two seconds: a window that is still not known by then keeps the state it has, and
    // the next toggle saves it, as before.
    const SYNC_TRIES = 40, SYNC_DELAY_MS = 50;
    const syncWhenTracked = (tries = 0) => {
      if (window.closed || syncSession() || tries >= SYNC_TRIES) return;
      setTimeout(() => syncWhenTracked(tries + 1), SYNC_DELAY_MS);
    };
    window.addEventListener("SSWindowStateReady", syncSession);
    if (document.readyState === "complete") syncWhenTracked();
    else window.addEventListener("load", () => syncWhenTracked(), { once: true });

    // --- flash the tab bar when tabs change (shortcuts, links, background tabs) ---

    let flashTimer = null;
    const flashTabs = () => {
      root.setAttribute("tabs-flash", "");
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => root.removeAttribute("tabs-flash"), Peek.read(PREFS.flashMs));
    };

    // Which events open the bar is up to the user (three prefs). A tab that is opened and selected fires
    // TabOpen and then TabSelect in the same task: the open decides, so that turning "new tab" off is
    // not undone by the switch that comes with it.
    //
    // Firefox does not say whether a tab was opened by a link, so it is told apart by what the tab is
    // going to load: the new-tab page, the home page or nothing is a tab you opened; any other address
    // (a link, a bookmark, window.open...) counts as "opens straight to an address". The load is started
    // right after TabOpen, so the address is read one tick later.
    const justOpened = new WeakSet();
    // What is always a new tab, and the two places that name another one: the module that knows the
    // new-tab page and the one that knows the home page. The addresses they give can change while
    // Firefox runs (the person edits the home page), so those are read on every call; the fixed list
    // and the imported modules are not rebuilt. A module that cannot be imported is tried again.
    const FIXED_NEW_TAB_ADDRESSES = new Set(["", "about:blank", "about:newtab", "about:home"]);
    const NEW_TAB_SOURCES = [
      ["AboutNewTab", (module) => module.AboutNewTab.newTabURL],
      ["HomePage", (module) => module.HomePage.get(window)],
    ];
    const importedModules = new Map();
    const isNewTabPage = (spec) => {
      if (FIXED_NEW_TAB_ADDRESSES.has(spec)) return true;
      for (const [name, addressOf] of NEW_TAB_SOURCES) {
        try {
          if (!importedModules.has(name)) {
            importedModules.set(name, ChromeUtils.importESModule(`resource:///modules/${name}.sys.mjs`));
          }
          if (addressOf(importedModules.get(name)) === spec) return true;
        } catch (e) {
          // Not fatal: the fixed list above still covers the usual cases.
          Diag.warn("autohide:newtab", e);
        }
      }
      return false;
    };
    gBrowser.tabContainer.addEventListener("TabSelect", (event) => {
      if (!justOpened.has(event.target) && Peek.read(PREFS.revealSwitch)) flashTabs();
    });
    gBrowser.tabContainer.addEventListener("TabOpen", (event) => {
      const tab = event.target;
      justOpened.add(tab);
      setTimeout(() => {
        justOpened.delete(tab);
        const browser = tab.linkedBrowser;
        const address = browser?.userTypedValue ?? browser?.currentURI?.spec ?? "";
        if (Peek.read(isNewTabPage(address) ? PREFS.revealNew : PREFS.revealLink)) flashTabs();
      }, 0);
    });

    // --- keep a bar open while something is dragged out of it ---
    //
    // Hover is not updated during a drag, so a bar would collapse under the item being dragged (a tab, a
    // bookmark, a toolbar button). The drag's source bar is recorded on the window root as
    // peekafoxy-dragging="tabs|navbar|bookmarks"; the CSS treats that as one more way to reveal it.
    // The drag is over on dragend/drop, or, if the source node was rebuilt and those never arrive, on
    // the first mouse movement once no drag session is running (mouse events pause during a drag).

    const BAR_NAMES = { TabsToolbar: "tabs", "nav-bar": "navbar", PersonalToolbar: "bookmarks" };
    const barOf = (node) => (node?.closest ? node : node?.parentElement)?.closest("#TabsToolbar, #nav-bar, #PersonalToolbar");
    const endDrag = () => root.removeAttribute("peekafoxy-dragging");
    const dragInProgress = () => {
      try {
        return Boolean(Services.dragService.getCurrentSession(window));
      } catch (e) {
        Diag.warn("autohide:drag", e);
        return false;
      }
    };
    window.addEventListener("dragstart", (event) => {
      const bar = barOf(event.composedTarget ?? event.target);
      if (bar) root.setAttribute("peekafoxy-dragging", BAR_NAMES[bar.id]);
    }, true);
    for (const type of ["dragend", "drop"]) window.addEventListener(type, endDrag, true);
    window.addEventListener("mousemove", () => {
      if (root.hasAttribute("peekafoxy-dragging") && !dragInProgress()) endDrag();
    }, true);

    // --- keep a bar open while a popup that belongs to it is open ---
    //
    // A popup (the list of all tabs, a button's menu, a bookmarks folder) is a window of its own: while
    // the pointer is in it, hover has left the bar, which would collapse under its popup. The bars that
    // have an open popup are recorded on the window root as peekafoxy-popup-open="tabs navbar bookmarks"
    // (the ones that apply); the CSS treats that as one more way to reveal them. The popups are kept in
    // a set, so that nested ones count correctly, and a popup that is gone without a popuphidden (it was
    // removed, or its popupshowing was cancelled) is dropped the next time anything is looked at.

    const openPopups = new Map(); // popup element -> name of the bar it belongs to
    const showPopupBars = () => {
      for (const popup of [...openPopups.keys()]) {
        if (popup.state === "closed") openPopups.delete(popup); // also what a removed popup reports
      }
      const bars = [...new Set(openPopups.values())].join(" ");
      if (bars) root.setAttribute("peekafoxy-popup-open", bars);
      else root.removeAttribute("peekafoxy-popup-open");
    };
    window.addEventListener("popupshowing", (event) => {
      const popup = event.target;
      if (popup.localName === "tooltip") return; // a tooltip is not something to keep a bar open for
      try {
        const bar = barOf(popup.anchorNode ?? popup.triggerNode ?? popup.parentNode);
        if (bar) openPopups.set(popup, BAR_NAMES[bar.id]);
      } catch (e) {
        Diag.warn("autohide:popup", e);
      }
      showPopupBars();
      setTimeout(showPopupBars, 0); // a popupshowing that was cancelled never gets a popuphidden
    }, true);
    window.addEventListener("popuphidden", (event) => {
      openPopups.delete(event.target);
      showPopupBars();
    }, true);
    window.addEventListener("mousemove", () => {
      if (openPopups.size) showPopupBars();
    }, true);

    // --- the shortcuts (see PREFS in peekafoxy.sys.mjs for the defaults) toggle the current window only ---
    //
    // While a shortcut field of the settings page has the focus, the keys are what the person is
    // choosing, not shortcuts: this handler sees them first (the page is inside this window), so it
    // has to ask the field's module whether one is recording.

    window.addEventListener("keydown", (event) => {
      if (Peek.Recorder.isRecording()) return;
      Peek.EasterEgg.typed(window, event);
      const target = TARGETS.find((t) => Peek.matches(t.binding, event));
      if (!target) return;
      event.preventDefault();
      Peek.EasterEgg.settle(window);
      setEnabled(target, !root.hasAttribute(target.attr));
    }, true);

    // --- the toolbar buttons show whether their window's bar is hidden ---
    //
    // A button is pressed (checked="true", which Firefox draws as pressed and tells assistive
    // technology about) while its bar's autohide is on in the window the button is in. The state of a
    // bar is the attribute on this window's root, however it came to change (the shortcut, the button,
    // a restored session, a test), so the buttons follow the attribute instead of each place that sets
    // it. The first window makes the widgets only at the end of this script, after the state may
    // have been applied, so it syncs once more there. (A button that is moved in Customize Toolbar is
    // the same node, not a new one, and keeps its state.)

    const syncButtons = () => {
      if (root.hasAttribute("peekafoxy-peek")) return; // the bars only peek (the easter egg): no state changed
      for (const target of TARGETS) {
        try {
          const node = CustomizableUI.getWidget(target.button.id).forWindow(window).node;
          if (!node) continue;
          if (root.hasAttribute(target.attr)) node.setAttribute("checked", "true");
          else node.removeAttribute("checked");
        } catch (e) {
          // The button may not exist yet or any more; the state is only a convenience.
          Diag.info("autohide:checked", e);
        }
      }
    };
    const stateObserver = new window.MutationObserver(syncButtons);
    stateObserver.observe(root, { attributes: true, attributeFilter: [...TARGETS.map((t) => t.attr), "peekafoxy-peek"] });
    window.addEventListener("unload", () => stateObserver.disconnect(), { once: true });

    // --- one-time greeting ---
    //
    // Shown once per profile, so you can tell the script is loaded and working. The pref is set before
    // the notification so that other windows opening right now don't show it again.

    if (!Peek.read({ ...PREFS.welcomed, default: true })) {
      try {
        Peek.write(PREFS.welcomed, true);
        UC_API.Notifications.show({
          label: TEXT.greeting,
          type: "peekafoxy-welcome",
          priority: "info",
          window,
          buttons: [
            {
              label: TEXT.greetingButton,
              callback() {
                // The argument Firefox passes here changes between versions, so don't rely on it:
                // the notification lives in this window, which is the one that should open the tab.
                window.openWebLinkIn("https://github.com/paodelonga/peek-a-foxy", "tab");
                return false;
              },
            },
          ],
        });
      } catch (e) {
        Diag.error("autohide:greeting", e);
      }
    }

    // --- toolbar buttons ---
    //
    // A widget is created once and then shared by every window, so its callback is kept alive by the
    // first window's script. To stay valid after that window closes it must not use anything from this
    // scope: everything it needs is read from attributes on the clicked button (fx-autoconfig copies
    // extra properties of the description onto the button).
    // The urlbar button sits in the bar it hides; reveal the bar with its hover strip to use it.

    for (const target of TARGETS) {
      const { attr, session, button } = target;
      try {
        UC_API.Utils.createWidget({
          id: button.id,
          type: "toolbarbutton",
          label: TEXT[target.name].label,
          tooltip: tooltipFor(target), // fx-autoconfig's name for tooltiptext (it also copies it as a stray attribute)
          image: button.image,
          "autohide-attr": attr,
          "autohide-session": session,
          callback(event) {
            const win = event.target.ownerDocument.defaultView;
            const attrName = event.target.getAttribute("autohide-attr");
            const sessionKey = event.target.getAttribute("autohide-session");
            try {
              // Bars that are only peeking (the easter egg) stop first: the click is about their real state.
              win.ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs").EasterEgg.settle(win);
            } catch (e) {
              console.error(e);
            }
            const on = !win.document.documentElement.hasAttribute(attrName);
            win.document.documentElement.toggleAttribute(attrName, on);
            try {
              win.SessionStore.setCustomWindowValue(win, sessionKey, on ? "1" : "0");
            } catch (e) {
              // Not fatal: the state just won't survive a session restore. Nothing from this window's
              // scope is used here (it may be gone): the module is imported again, from the clicked window.
              win.ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs")
                .Diag.warn("autohide:button", e);
            }
          },
        });
      } catch (e) {
        // "already exists" is expected for every window after the first.
        if (/already exists/.test(String(e))) Diag.info("autohide:widget", `${button.id} already exists`);
        else Diag.error("autohide:widget", `createWidget ${button.id} failed: ${e}`, e);
      }
    }

    syncButtons(); // the widgets exist now (or already did), and the state may have been restored before

    // --- diagnostics ---
    //
    // From here the window counts as started; the health check waits until the window is idle, so it
    // never delays the window opening.

    Diag.info("autohide:init", "the script started in a window");
    Diag.windowStarted(window);
    window.requestIdleCallback(() => Diag.check(window), { timeout: 5000 });

  } catch (e) {
    Diag.error("autohide:init", e);
  }
})();
