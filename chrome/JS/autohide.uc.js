// ==UserScript==
// @name           Peek-a-Foxy: autohide for tabs and urlbar, per window
// @description    Peek-a-boo for Foxys: per-window autohide for the tab bar (button + Ctrl+Alt+T) and the navigation bar (button + Ctrl+Alt+U).
// @include        main
// ==/UserScript==

// Runs once per browser window through fx-autoconfig. It flips attributes and sets variables on the
// window root; chrome/autohide.css does the actual collapsing and revealing. The prefs, the shortcut
// format and the texts are in chrome/resources/peekafoxy.sys.mjs, shared with the settings page
// (JS/autohide-prefs.uc.js).

(() => {
  const LOG = "[autohide]";
  const Peek = ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs");
  const { PREFS } = Peek;

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

  Peek.registerDefaults(console);

  const setEnabled = (target, on) => {
    root.toggleAttribute(target.attr, on);
    try {
      SessionStore.setCustomWindowValue(window, target.session, on ? "1" : "0");
    } catch (e) {
      // Not fatal: the state just won't survive a session restore.
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
    [PREFS.showMs, "--autohide-show-duration", (v) => `${v}ms`],
    [PREFS.hideDelayMs, "--autohide-hide-delay", (v) => `${v}ms`],
  ];

  const updateTooltips = () => {
    for (const target of TARGETS) {
      try {
        const node = CustomizableUI.getWidget(target.button.id).forWindow(window).node;
        node?.setAttribute("tooltiptext", tooltipFor(target));
      } catch (e) {
        // The button may not exist yet or any more; the tooltip is only a convenience.
      }
    }
  };

  const applySettings = () => {
    for (const [pref, variable, css] of CSS_SETTINGS) {
      if (Peek.hasUserValue(pref)) root.style.setProperty(variable, css(Peek.read(pref)));
      else root.style.removeProperty(variable);
    }
    for (const target of TARGETS) target.binding = Peek.bindingFor(target.shortcut);
    updateTooltips();
  };

  applySettings();
  const settingsObserver = {
    observe: (subject, topic, name) => {
      if (name?.startsWith(Peek.PREF_BRANCH)) applySettings();
    },
  };
  Services.prefs.addObserver(Peek.PREF_BRANCH, settingsObserver);
  window.addEventListener("unload", () => Services.prefs.removeObserver(Peek.PREF_BRANCH, settingsObserver), { once: true });

  // --- initial state: saved per-window value, else the pref default ---

  for (const target of TARGETS) {
    let saved = null;
    try {
      saved = SessionStore.getCustomWindowValue(window, target.session);
    } catch (e) {
      // No saved state for a brand new window.
    }
    setEnabled(target, saved ? saved === "1" : Peek.read(target.pref));
  }

  // --- flash the tab bar when tabs change (shortcuts, links, background tabs) ---

  let flashTimer = null;
  const flashTabs = () => {
    root.setAttribute("tabs-flash", "");
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => root.removeAttribute("tabs-flash"), Peek.read(PREFS.flashMs));
  };
  for (const type of ["TabSelect", "TabOpen"]) {
    gBrowser.tabContainer.addEventListener(type, flashTabs);
  }

  // --- keep a bar open while something is dragged out of it ---
  //
  // Hover is not updated during a drag, so a bar would collapse under the item being dragged (a tab, a
  // bookmark, a toolbar button). The drag's source bar is recorded on the window root as
  // peekafoxy-dragging="tabs|navbar|bookmarks"; the CSS treats that as one more way to reveal it.
  // The drag is over on dragend/drop, or, if the source node was rebuilt and those never arrive, on
  // the first mouse movement once no drag session is running (mouse events pause during a drag).

  const DRAG_SOURCES = { TabsToolbar: "tabs", "nav-bar": "navbar", PersonalToolbar: "bookmarks" };
  const endDrag = () => root.removeAttribute("peekafoxy-dragging");
  const dragInProgress = () => {
    try {
      return Boolean(Services.dragService.getCurrentSession(window));
    } catch (e) {
      return false;
    }
  };
  window.addEventListener("dragstart", (event) => {
    const node = event.composedTarget ?? event.target;
    const bar = (node?.closest ? node : node?.parentElement)?.closest("#TabsToolbar, #nav-bar, #PersonalToolbar");
    if (bar) root.setAttribute("peekafoxy-dragging", DRAG_SOURCES[bar.id]);
  }, true);
  for (const type of ["dragend", "drop"]) window.addEventListener(type, endDrag, true);
  window.addEventListener("mousemove", () => {
    if (root.hasAttribute("peekafoxy-dragging") && !dragInProgress()) endDrag();
  }, true);

  // --- the shortcuts (Ctrl+Alt+T and Ctrl+Alt+U by default) toggle the current window only ---

  window.addEventListener("keydown", (event) => {
    const target = TARGETS.find((t) => Peek.matches(t.binding, event));
    if (!target) return;
    event.preventDefault();
    setEnabled(target, !root.hasAttribute(target.attr));
  }, true);

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

  for (const target of TARGETS) {
    const { attr, session, button } = target;
    try {
      UC_API.Utils.createWidget({
        id: button.id,
        type: "toolbarbutton",
        label: TEXT[target.name].label,
        tooltip: tooltipFor(target),
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
