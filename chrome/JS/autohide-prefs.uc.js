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
  const LOG = "[peekafoxy settings]";
  const Peek = ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs");
  const { PREFS } = Peek;

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
    #peekafoxy-pane .pf-note { color: var(--text-color-deemphasized); margin-block: 4px; }
    #peekafoxy-pane .pf-problem { color: var(--text-color-error, #c50042); margin-block: 0 8px; min-height: 1.2em; }
    #peekafoxy-pane h2 { margin-block: 0 8px; font-size: 1.2em; }
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
    const button = el("button", { type: "button", text: TEXT.reset });
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

  const greetingButton = () => {
    const button = el("button", { type: "button", id: "peekafoxy-greeting", text: TEXT.greetingShow });
    const done = el("p", { class: "pf-note", role: "status" });
    button.addEventListener("click", () => {
      Peek.write(PREFS.welcomed, false);
      done.textContent = TEXT.greetingDone;
    });
    return el("div", { class: "pf-row" }, button, done);
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
      group(TEXT.greetingGroup, greetingButton()),
    );
  };

  // --- hooking into Firefox's page ---

  const install = () => {
    const missing = requirements();
    if (missing.length) throw new Error(`missing from about:preferences: ${missing.join(", ")}`);

    Peek.registerDefaults(console);
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
  } catch (e) {
    console.warn(`${LOG} the Peek-a-Foxy category was not added:`, e);
  }
})();
