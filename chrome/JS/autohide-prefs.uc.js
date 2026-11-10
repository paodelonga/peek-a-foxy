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
  const TEXT = Peek.textFor(Services.locale.appLocaleAsBCP47).settings;
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
    #peekafoxy-pane .pf-row > label { flex: 1 1 24em; }
    #peekafoxy-pane .pf-row input[type="number"] { width: 7em; }
    #peekafoxy-pane .pf-row input[type="text"] { width: 16em; }
    #peekafoxy-pane .pf-reset { background: url("chrome://global/skin/icons/reset.svg") no-repeat 8px center / 16px;
      padding-inline-start: 32px; -moz-context-properties: fill; fill: currentColor; }
    #peekafoxy-pane .pf-note { color: var(--text-color-deemphasized); margin-block: 4px; }
    #peekafoxy-pane .pf-problem { color: var(--text-color-error, #c50042); margin-block: 0 8px; min-height: 1.2em; }
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

  const resetButton = (pref) => {
    const button = el("button", { type: "button", class: "pf-reset", text: TEXT.reset });
    button.addEventListener("click", () => Peek.reset(pref));
    controls.push({ refresh: () => { button.disabled = !Peek.hasUserValue(pref); } });
    return button;
  };

  const problemLine = () => el("p", { class: "pf-problem", role: "alert" });
  const showProblem = (line, reason, values = {}) => {
    line.textContent = reason ? fill(TEXT.problems[reason], values) : "";
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
      el("div", { class: "pf-row" }, el("label", { for: id, text: label }), input, resetButton(pref)), problem);
  };

  const shortcutField = (pref, other, label) => {
    const id = `peekafoxy-${pref.name}`;
    const input = el("input", { type: "text", id, readonly: "", placeholder: TEXT.shortcutPrompt });
    const problem = problemLine();
    input.addEventListener("keydown", (event) => {
      if (event.key === "Tab" || event.key === "Escape") return showProblem(problem, null); // leave
      if (["Control", "Alt", "Shift", "Meta", "AltGraph", "OS"].includes(event.key)) return; // wait for the key
      event.preventDefault();
      event.stopPropagation();
      const text = Peek.shortcutFromEvent(event);
      const reason = text ? Peek.shortcutProblem(text, other) : "unsupported";
      showProblem(problem, reason);
      if (!reason) Peek.write(pref, text);
    });
    input.addEventListener("blur", () => showProblem(problem, null));
    controls.push({ refresh: () => { input.value = Peek.bindingFor(pref).text; } });
    return el("div", {},
      el("div", { class: "pf-row" }, el("label", { for: id, text: label }), input, resetButton(pref)), problem);
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
    const line = el("div", { class: "pf-status", id: "peekafoxy-status" });
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

  // A live region only announces a change, so the text is cleared first and set a moment later.
  const announce = (node, text) => {
    node.textContent = "";
    if (text) window.setTimeout(() => { node.textContent = text; }, 50);
  };

  const issuesNote = () => {
    const link = el("a", { href: Peek.ISSUES_URL, target: "_blank", rel: "noopener noreferrer", text: TEXT.supportLink });
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

  const buildPage = () => {
    const header = customElements.get("moz-page-header")
      ? el("moz-page-header", { heading: TEXT.category, description: TEXT.description })
      : el("div", {}, el("h1", { text: TEXT.category }), el("p", { text: TEXT.description }));
    return el("section", {},
      header,
      group(TEXT.startGroup,
        checkbox(PREFS.tabsAutohide, TEXT.startTabs),
        checkbox(PREFS.urlbarAutohide, TEXT.startUrlbar),
        el("p", { class: "pf-note", text: TEXT.startNote })),
      group(TEXT.revealGroup,
        checkbox(PREFS.revealSwitch, TEXT.revealSwitch),
        checkbox(PREFS.revealNew, TEXT.revealNew),
        checkbox(PREFS.revealLink, TEXT.revealLink),
        numberField(PREFS.flashMs, TEXT.flashMs),
        el("p", { class: "pf-note", text: TEXT.revealNote })),
      group(TEXT.timingGroup,
        numberField(PREFS.stripPx, TEXT.stripPx),
        numberField(PREFS.showMs, TEXT.showMs),
        numberField(PREFS.hideDelayMs, TEXT.hideDelayMs)),
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
      id: "category-peekafoxy", view: CATEGORY, iconsrc: "chrome://browser/skin/tabs.svg", text: TEXT.category,
    });
    const pane = el("div", { id: "peekafoxy-pane", "data-category": CATEGORY, hidden: "" },
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
