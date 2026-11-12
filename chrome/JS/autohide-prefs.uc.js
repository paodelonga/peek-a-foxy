// ==UserScript==
// @name           Peek-a-Foxy: settings page in about:preferences
// @description    Adds a "Peek-a-Foxy" category to Firefox's settings: the autohide defaults, the strip size, the timings and the shortcuts, all applied to every open window at once.
// @include        about:preferences*
// ==/UserScript==

// Runs in every about:preferences tab through fx-autoconfig. It touches Firefox's own page in three
// places (the category list, the pane container and the category registry), so it checks that they
// are what it expects and, if Firefox has changed them, does nothing and says so in the console:
// the settings are real prefs, so they can still be changed in about:config.

(() => {
  const Peek = ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs");
  const { PREFS, Diag } = Peek;
  Diag.watch(window, "settings");

  const CATEGORY = "panePeekafoxy"; // what Firefox derives from the address about:preferences#peekafoxy
  const FRIENDLY = "peekafoxy";
  const LOCALE = Services.locale.appLocaleAsBCP47;
  const TEXT = Peek.textFor(LOCALE).settings;
  const startedOnOurPage = document.location.hash === `#${FRIENDLY}`;

  // What the page needs from Firefox. Names are checked, not assumed.
  const requirements = () => {
    const missing = [];
    if (!document.getElementById("categories")) missing.push("#categories");
    if (!document.getElementById("mainPrefPane")) missing.push("#mainPrefPane");
    if (typeof gCategoryInits === "undefined" || typeof gCategoryInits?.set !== "function") missing.push("gCategoryInits");
    if (typeof gCategoryModules === "undefined" || typeof gCategoryModules?.set !== "function") missing.push("gCategoryModules");
    if (typeof gotoPref !== "function") missing.push("gotoPref");
    if (typeof gLastCategory === "undefined") missing.push("gLastCategory");
    return missing;
  };

  const el = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "text") node.textContent = value;
      else if (value !== undefined) node.setAttribute(key, value);
    }
    node.append(...children);
    return node;
  };
  const fill = (template, values) => template.replace(/\{(\w+)\}/g, (_, name) => values[name]);

  const STYLE = `
    #peekafoxy-pane .pf-card { margin-block: 0 16px; }
    #peekafoxy-pane .pf-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-block: 8px; }
    #peekafoxy-pane .pf-row > label { flex: 1 1 10em; }
    #peekafoxy-pane .pf-row input[type="number"] { width: 7em; }
    #peekafoxy-pane .pf-row input[type="text"] { width: 12em; }
    #peekafoxy-pane .pf-row select { flex: 0 1 auto; min-width: 0; max-width: min(100%, 14em); }
    #peekafoxy-pane .pf-reset { flex: none; background-image: url("chrome://global/skin/icons/arrow-counterclockwise-16.svg");
      background-repeat: no-repeat; background-position: 8px center; background-size: 16px;
      padding-inline-start: 32px; -moz-context-properties: fill; fill: currentColor; }
    #peekafoxy-pane .pf-reset:dir(rtl) { background-position: right 8px center; }
    #peekafoxy-pane .pf-note { color: var(--text-color-deemphasized); margin-block: 4px; }
    #peekafoxy-pane .pf-problem { color: var(--text-color-error, #c50042); margin-block: 0; }
    #peekafoxy-pane .pf-problem:not(:empty) { margin-block: 0 8px; }
    #peekafoxy-pane h2 { margin-block: 0 8px; font-size: 1.2em; }
    #peekafoxy-pane .pf-status { margin-block: 0 8px; padding: 8px 12px; border-inline-start: 4px solid var(--border-color-success, #058b00); border-radius: 4px; background: var(--background-color-box, transparent); }
    #peekafoxy-pane .pf-status[data-state="errors"] { border-color: var(--border-color-warning, #cc9900); }
    #peekafoxy-pane .pf-status[data-state="problem"], #peekafoxy-pane .pf-status[data-state="notstarted"] { border-color: var(--border-color-critical, #c50042); }
    #peekafoxy-pane .pf-status p { margin: 0; }
    #peekafoxy-pane .pf-status p + p { margin-block-start: 4px; }
    #peekafoxy-pane .pf-fallback { box-sizing: border-box; inline-size: 100%; max-inline-size: 100%; font-family: monospace; }
    @media (forced-colors: active) { #peekafoxy-pane .pf-status { border: 1px solid CanvasText; border-inline-start-width: 6px; } }
  `;

  // --- the controls ---

  const controls = []; // {refresh()} for each, so a pref change from anywhere updates the page

  const group = (title, ...children) => {
    const card = customElements.get("moz-card") ? "moz-card" : "section";
    return el(card, { class: "pf-card" }, el("h2", { text: title }), ...children);
  };

  const checkbox = (pref, label) => {
    const input = el("input", { type: "checkbox", id: `peekafoxy-${pref.name}` });
    input.addEventListener("change", () => Peek.write(pref, input.checked));
    controls.push({ refresh: () => { input.checked = Peek.read(pref); } });
    return el("div", { class: "pf-row" }, el("label", {}, input, ` ${label}`));
  };

  // A live region only announces a change, so the text is cleared first and set a moment later (also
  // when it is the same text again). A text still waiting is dropped, so it cannot come back after a
  // newer call has cleared the line.
  const announcing = new WeakMap();
  const announce = (node, text) => {
    window.clearTimeout(announcing.get(node));
    node.textContent = "";
    if (text) announcing.set(node, window.setTimeout(() => { node.textContent = text; }, 50));
  };

  // The button gets the focus back on its field once it is pressed: it disables itself when the
  // default is back, and focus must not stay on a disabled button.
  const resetButton = (pref, field, label) => {
    const button = el("button", { type: "button", class: "pf-reset", text: TEXT.reset });
    button.setAttribute("aria-label", fill(TEXT.resetFor, { label })); // else the six buttons share one name
    button.addEventListener("click", () => {
      Peek.reset(pref);
      field.focus();
    });
    controls.push({ refresh: () => { button.disabled = !Peek.hasUserValue(pref); } });
    return button;
  };

  const problemLine = () => el("p", { class: "pf-problem", role: "alert" });
  const showProblem = (line, reason, values = {}) => {
    announce(line, reason ? fill(TEXT.problems[reason], values) : "");
  };

  // A list of choices; the pref holds the key of the one picked (Peek.read gives the default for a
  // value that is not one of them).
  const choiceField = (pref, label, labels) => {
    const id = `peekafoxy-${pref.name}`;
    const select = el("select", { id },
      ...pref.values.map((key) => el("option", { value: key, text: labels[key] ?? key })));
    const refresh = () => { select.value = Peek.read(pref); };
    select.addEventListener("change", () => Peek.write(pref, select.value));
    controls.push({ refresh });
    return el("div", { class: "pf-row" },
      el("label", { for: id, text: label }), select, resetButton(pref, select, label));
  };

  const numberField = (pref, label) => {
    const id = `peekafoxy-${pref.name}`;
    const input = el("input", { type: "number", id, min: pref.min, max: pref.max, step: 1 });
    const problem = problemLine();
    const refresh = () => { input.value = Peek.read(pref); };
    input.addEventListener("change", () => {
      const text = input.value.trim();
      const value = Number(text);
      if (!text || !Number.isInteger(value) || value < pref.min || value > pref.max) {
        showProblem(problem, "range", { min: pref.min, max: pref.max });
        refresh();
        return;
      }
      showProblem(problem, null);
      Peek.write(pref, value);
    });
    controls.push({ refresh });
    return el("div", {},
      el("div", { class: "pf-row" }, el("label", { for: id, text: label }), input, resetButton(pref, input, label)),
      problem);
  };

  // The keys that are only the start of a shortcut: the recorder waits for the key that follows.
  const MODIFIER_KEYS = ["Control", "Alt", "Shift", "Meta", "AltGraph", "OS"];

  // Firefox already uses the shortcut that was just saved: say what for. It is only a warning, the
  // shortcut stays.
  const warnAboutFirefox = (problem, text) => {
    const used = Peek.firefoxShortcut(ownerWindow(), text);
    if (!used) return;
    showProblem(problem, used.label ? "firefoxUses" : "firefoxUsesUnnamed", { name: used.label });
  };

  const shortcutField = (pref, other, label) => {
    const id = `peekafoxy-${pref.name}`;
    const input = el("input", { type: "text", id, readonly: "", "aria-describedby": `${id}-prompt` });
    const prompt = el("p", { class: "pf-note", id: `${id}-prompt`, text: TEXT.shortcutPrompt });
    const problem = problemLine();
    input.addEventListener("keydown", (event) => {
      if (event.key === "Tab" || event.key === "Escape") return showProblem(problem, null); // leave
      if (MODIFIER_KEYS.includes(event.key)) return; // wait for the key
      if (event.key === "Enter" || event.key === " ") return showProblem(problem, null); // nothing to record
      event.preventDefault();
      event.stopPropagation();
      if ((event.key === "Backspace" || event.key === "Delete") && !event.ctrlKey && !event.altKey && !event.metaKey) {
        showProblem(problem, null);
        Peek.reset(pref); // the natural way to clear a field: the default comes back
        return;
      }
      const text = Peek.shortcutFromEvent(event);
      const reason = text ? Peek.shortcutProblem(text, other) : "unsupported";
      showProblem(problem, reason);
      if (reason) return;
      Peek.write(pref, text);
      warnAboutFirefox(problem, text);
    });
    // The windows' own shortcut handler ignores the keys while a field is recording (see
    // Peek.Recorder); a page that goes away with the focus in it stops recording too.
    input.addEventListener("focus", () => Peek.Recorder.focused(input));
    input.addEventListener("blur", () => {
      Peek.Recorder.blurred(input);
      showProblem(problem, null);
    });
    window.addEventListener("pagehide", () => Peek.Recorder.blurred(input));
    controls.push({ refresh: () => { input.value = Peek.bindingFor(pref).text; } });
    return el("div", {},
      el("div", { class: "pf-row" }, el("label", { for: id, text: label }), input, resetButton(pref, input, label)),
      prompt, problem);
  };

  // --- the Support group: how things stand, and the diagnostic info for a bug report ---

  // The browser window this settings tab belongs to (its script is the one that has to be running).
  const ownerWindow = () => {
    try {
      return window.browsingContext?.topChromeWindow ?? Services.wm.getMostRecentWindow("navigator:browser");
    } catch (e) {
      return null;
    }
  };

  const supportStatus = () => {
    const line = el("div", { class: "pf-status", id: "peekafoxy-status", role: "status" });
    const refresh = () => {
      const { state, version, failed } = Diag.summary(ownerWindow());
      const lines = [];
      if (state === "ok") lines.push(fill(TEXT.supportOk, { version }));
      else if (state === "errors") lines.push(fill(TEXT.supportErrors, { version }));
      else if (state === "notstarted") lines.push(TEXT.supportNotStarted);
      else {
        lines.push(fill(TEXT.supportProblem, { note: Peek.noteFor(failed[0], TEXT.health) }));
        if (failed.length > 1) lines.push(TEXT.supportMore);
      }
      line.dataset.state = state;
      line.replaceChildren(...lines.map((text) => el("p", { text })));
    };
    const observer = { observe: refresh };
    Services.obs.addObserver(observer, "peekafoxy-diag-changed");
    window.addEventListener("unload", () => Services.obs.removeObserver(observer, "peekafoxy-diag-changed"), { once: true });
    controls.push({ refresh });
    return line;
  };

  // With vertical tabs Firefox has no tab bar to hide, so the tab bar options do nothing: say so, but
  // only while the pref is on, and follow it live.
  const VERTICAL_TABS = "sidebar.verticalTabs";
  const verticalTabsNote = () => {
    const note = el("p", { class: "pf-note", id: "peekafoxy-vertical-tabs-note", text: TEXT.verticalTabsNote, hidden: "" });
    const refresh = () => {
      let on = false;
      try {
        on = Services.prefs.getBoolPref(VERTICAL_TABS, false);
      } catch (e) {
        Diag.warn("settings:verticalTabs", e); // the pref holds another type: not on
      }
      note.hidden = !on;
    };
    const observer = { observe: refresh };
    Services.prefs.addObserver(VERTICAL_TABS, observer);
    window.addEventListener("unload", () => Services.prefs.removeObserver(VERTICAL_TABS, observer), { once: true });
    controls.push({ refresh });
    return note;
  };

  const issuesNote = () => {
    const link = el("a", { href: Peek.ISSUES_URL, target: "_blank", rel: "noopener noreferrer", text: TEXT.supportLink });
    // A plain target="_blank" link from this page opens a tab that stays blank (about:blank), so the
    // click is handed to Firefox's own function for opening a link in a tab. If it is not there the
    // link keeps its normal behavior.
    const open = (event) => {
      if (typeof window.openTrustedLinkIn !== "function") return;
      event.preventDefault();
      window.openTrustedLinkIn(Peek.ISSUES_URL, "tab");
    };
    link.addEventListener("click", open);
    link.addEventListener("auxclick", (event) => event.button === 1 && open(event));
    const [before, after = ""] = TEXT.supportNote.split("{link}");
    return el("p", { class: "pf-note" }, before, link, after);
  };

  const supportCopy = () => {
    const button = el("button", { type: "button", id: "peekafoxy-copy", text: TEXT.supportCopy });
    const done = el("p", { class: "pf-note", id: "peekafoxy-copy-done", role: "status" });
    const failure = el("p", { class: "pf-problem", id: "peekafoxy-copy-failed", role: "alert" });
    // Shown only when the clipboard is not available: the text to select and copy by hand.
    const fallback = el("textarea", {
      class: "pf-fallback", id: "peekafoxy-copy-text", readonly: "", rows: 12, dir: "ltr", lang: "en",
      "aria-label": TEXT.supportFallbackLabel, hidden: "",
    });
    button.addEventListener("click", () => {
      Diag.check(ownerWindow()); // the report is as fresh as the click
      const text = Diag.report();
      try {
        Peek.Clipboard.copy(text);
        fallback.hidden = true;
        announce(failure, "");
        announce(done, TEXT.supportCopied);
      } catch (e) {
        Diag.warn("settings:copy", e);
        announce(done, "");
        announce(failure, TEXT.supportCopyFailed);
        fallback.value = text;
        fallback.hidden = false;
        fallback.focus();
        fallback.select();
      }
    });
    return el("div", {}, el("div", { class: "pf-row" }, button, done), failure, fallback);
  };

  // --- the easter eggs (see EasterEgg in peekafoxy.sys.mjs) ---
  //
  // Three quick clicks on the 🦊 of the title open the video player in the browser window. The fox
  // gets a span of its own so that only it counts for the clicks; the span has no role, name or tab
  // stop, so the title reads and is announced exactly as before (keyboard users have the two typed
  // ways, which the browser window's own script listens for).

  const FOX = "🦊";
  const CLICKS = 3, CLICKS_MS = 2800;
  let fox = null;

  // Wraps the first fox in the text of `heading` in a span and returns it, or null if there is none.
  const wrapFox = (heading) => {
    const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const at = node.data.indexOf(FOX);
      if (at < 0) continue;
      const found = node.splitText(at);
      found.splitText(FOX.length);
      const span = el("span", { class: "pf-fox" });
      found.replaceWith(span);
      span.append(found);
      return span;
    }
    return null;
  };
  // Firefox's moz-page-header draws its heading in its shadow root, once it is defined and rendered.
  const findFox = (header) => {
    const wrap = (heading) => {
      fox = heading ? wrapFox(heading) : null;
      if (!fox) Diag.info("settings:fox", "the title has no fox to click; the keys still work");
    };
    try {
      if (header.localName !== "moz-page-header") wrap(header.querySelector("h1"));
      else {
        customElements.whenDefined("moz-page-header")
          .then(() => header.updateComplete)
          .then(() => wrap(header.shadowRoot?.getElementById("heading")))
          .catch((e) => Diag.info("settings:fox", e));
      }
    } catch (e) {
      Diag.info("settings:fox", e); // only the clicks are lost
    }
  };

  const armEggs = () => {
    const play = () => {
      try {
        Peek.EasterEgg.play(ownerWindow(), { locale: LOCALE });
      } catch (e) {
        Diag.warn("easter-egg:play", e);
      }
    };

    let clicks = 0, firstClick = 0;
    const onClick = (event) => {
      if (!fox || !event.composedPath().includes(fox)) {
        clicks = 0; // a click anywhere else starts the count over
        return;
      }
      if (!clicks || event.timeStamp - firstClick > CLICKS_MS) {
        clicks = 0;
        firstClick = event.timeStamp;
      }
      clicks += 1;
      if (clicks === CLICKS && !Peek.EasterEgg.busy()) play();
      if (clicks >= CLICKS) clicks = 0;
    };

    document.addEventListener("click", onClick, true);
    window.addEventListener("pagehide", () => document.removeEventListener("click", onClick, true), { once: true });
  };

  const buildPage = () => {
    const header = customElements.get("moz-page-header")
      ? el("moz-page-header", { heading: TEXT.category, description: TEXT.description })
      : el("div", {}, el("h1", { text: TEXT.category }), el("p", { text: TEXT.description }));
    findFox(header);
    return el("section", {},
      header,
      verticalTabsNote(),
      group(TEXT.startGroup,
        checkbox(PREFS.tabsAutohide, TEXT.startTabs),
        checkbox(PREFS.urlbarAutohide, TEXT.startUrlbar),
        el("p", { class: "pf-note", text: TEXT.startNote })),
      group(TEXT.revealGroup,
        checkbox(PREFS.revealSwitch, TEXT.revealSwitch),
        checkbox(PREFS.revealNew, TEXT.revealNew),
        checkbox(PREFS.revealLink, TEXT.revealLink),
        checkbox(PREFS.revealLoad, TEXT.revealLoad),
        checkbox(PREFS.revealDownload, TEXT.revealDownload),
        checkbox(PREFS.revealTitle, TEXT.revealTitle),
        checkbox(PREFS.revealMove, TEXT.revealMove),
        checkbox(PREFS.revealClose, TEXT.revealClose),
        checkbox(PREFS.revealPin, TEXT.revealPin),
        checkbox(PREFS.revealMute, TEXT.revealMute),
        checkbox(PREFS.revealAttention, TEXT.revealAttention),
        numberField(PREFS.flashMs, TEXT.flashMs),
        el("p", { class: "pf-note", text: TEXT.revealNote })),
      group(TEXT.timingGroup,
        numberField(PREFS.stripPx, TEXT.stripPx),
        numberField(PREFS.tabsStripPx, TEXT.tabsStripPx),
        numberField(PREFS.urlbarStripPx, TEXT.urlbarStripPx),
        numberField(PREFS.showDelayMs, TEXT.showDelayMs),
        numberField(PREFS.showMs, TEXT.showMs),
        numberField(PREFS.hideMs, TEXT.hideMs),
        numberField(PREFS.hideDelayMs, TEXT.hideDelayMs),
        choiceField(PREFS.easing, TEXT.easing, TEXT.easingOptions)),
      group(TEXT.bookmarksGroup,
        choiceField(PREFS.bookmarks, TEXT.bookmarks, TEXT.bookmarksOptions)),
      group(TEXT.shortcutsGroup,
        shortcutField(PREFS.tabsShortcut, PREFS.urlbarShortcut, TEXT.tabsShortcut),
        shortcutField(PREFS.urlbarShortcut, PREFS.tabsShortcut, TEXT.urlbarShortcut),
        el("p", { class: "pf-note", text: Peek.shortcutHint(TEXT) })),
      group(TEXT.supportGroup, supportStatus(), supportCopy(), issuesNote()),
    );
  };

  // --- hooking into Firefox's page ---

  const install = () => {
    const missing = requirements();
    if (missing.length) throw new Error(`missing from about:preferences: ${missing.join(", ")}`);

    Peek.registerDefaults();
    const nav = document.getElementById("categories");
    const mainPane = document.getElementById("mainPrefPane");

    const button = el("moz-page-nav-button", {
      id: "category-peekafoxy", view: CATEGORY, iconsrc: "chrome://browser/skin/tabs.svg", text: TEXT.category.replace(FOX, "").trim(),
    });
    // The texts are in the language Peek.textFor chose, which is English for a Firefox in a language
    // that has no texts: the pane says so, so a right-to-left Firefox does not lay them out as such.
    const pane = el("div", {
      id: "peekafoxy-pane", "data-category": CATEGORY, hidden: "", lang: Peek.languageFor(LOCALE), dir: Peek.directionFor(LOCALE),
    },
      el("style", { text: STYLE }), buildPage());
    const separator = document.getElementById("nav-separator");

    // Register first, attach last, and undo everything if any step throws: Firefox must never be left
    // with a category button that leads nowhere.
    const observer = { observe: (subject, topic, name) => name?.startsWith(Peek.PREF_BRANCH) && refresh() };
    const refresh = () => controls.forEach((control) => control.refresh());
    try {
      gCategoryInits.set(CATEGORY, { init() {} });
      gCategoryModules.set(CATEGORY, {});
      mainPane.append(pane);
      nav.insertBefore(button, separator?.parentNode === nav ? separator : null);
      refresh();
      Services.prefs.addObserver(Peek.PREF_BRANCH, observer);
    } catch (e) {
      gCategoryInits.delete?.(CATEGORY);
      gCategoryModules.delete?.(CATEGORY);
      pane.remove();
      button.remove();
      throw e;
    }
    window.addEventListener("unload", () => Services.prefs.removeObserver(Peek.PREF_BRANCH, observer), { once: true });
    try {
      armEggs();
    } catch (e) {
      Diag.warn("easter-egg:arm", e); // the page works without them
    }

    // The page was opened straight at #peekafoxy and Firefox has already fallen back to its default.
    if (startedOnOurPage && gLastCategory?.category && gLastCategory.category !== CATEGORY) {
      gotoPref(CATEGORY, "Hash");
    }
  };

  try {
    install();
    Diag.setHealth("settings", [{ name: "settings-page", ok: true, parts: [], note: "" }]);
    Diag.check(ownerWindow()); // so the status line is up to date as soon as the page is opened
  } catch (e) {
    Diag.warn("settings:install", `the Peek-a-Foxy category was not added: ${Peek.describe(e)}`, e);
    Diag.setHealth("settings", [Peek.healthFail("settings-page", ["settingsPage", { what: e?.message }])]);
  }
})();
