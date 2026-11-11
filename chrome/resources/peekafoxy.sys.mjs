// Shared by the two Peek-a-Foxy scripts (JS/autohide.uc.js in every browser window and
// JS/autohide-prefs.uc.js in about:preferences): the prefs, their limits, the shortcut format and
// every text the user can read. Loaded with
//   ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs")
// (fx-autoconfig maps chrome://userchrome/content/ to the profile's chrome/resources/).
// It also holds Diag, the diagnostics both scripts use: a ring buffer of recent events, the health
// check and the status file that `peek-a-foxy doctor` reads (see the diagnostics section), and the
// easter eggs of the settings page (the last section).

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  AppConstants: "resource://gre/modules/AppConstants.sys.mjs",
  setTimeout: "resource://gre/modules/Timer.sys.mjs",
  clearTimeout: "resource://gre/modules/Timer.sys.mjs",
});

// The version of the Peek-a-Foxy files (a test keeps it equal to the package version).
export const SCRIPT_VERSION = "0.2.0";

// The default shortcuts, the same on every system. Ctrl+Alt+U is Firefox's own shortcut for the tabs
// sidebar, so the navigation bar uses Ctrl+Alt+Shift+U.
export const DEFAULT_TABS_SHORTCUT = "Ctrl+Alt+T";
export const DEFAULT_URLBAR_SHORTCUT = "Ctrl+Alt+Shift+U";

// One entry per pref. Everything is registered on Firefox's default branch (see registerDefaults),
// so about:config lists the prefs with the right type and nothing is written until a value changes.
//   type    "bool" | "int" | "string"
//   min/max limits of an int; a value outside them is clamped
export const PREFS = {
  tabsAutohide: { name: "peekafoxy.tabs.autohide", type: "bool", default: false },
  urlbarAutohide: { name: "peekafoxy.urlbar.autohide", type: "bool", default: false },
  stripPx: { name: "peekafoxy.strip.px", type: "int", default: 8, min: 1, max: 40 },
  tabsStripPx: { name: "peekafoxy.tabs.strip.px", type: "int", default: 0, min: 0, max: 40 },
  urlbarStripPx: { name: "peekafoxy.urlbar.strip.px", type: "int", default: 0, min: 0, max: 40 },
  showMs: { name: "peekafoxy.show.ms", type: "int", default: 120, min: 0, max: 2000 },
  showDelayMs: { name: "peekafoxy.show.delay.ms", type: "int", default: 100, min: 0, max: 5000 },
  hideMs: { name: "peekafoxy.hide.ms", type: "int", default: 200, min: 0, max: 2000 },
  hideDelayMs: { name: "peekafoxy.hide.delay.ms", type: "int", default: 300, min: 0, max: 5000 },
  flashMs: { name: "peekafoxy.tabs.flash.ms", type: "int", default: 1500, min: 0, max: 10000 },
  revealSwitch: { name: "peekafoxy.tabs.reveal.switch", type: "bool", default: true },
  revealNew: { name: "peekafoxy.tabs.reveal.new", type: "bool", default: true },
  revealLink: { name: "peekafoxy.tabs.reveal.link", type: "bool", default: true },
  revealLoad: { name: "peekafoxy.tabs.reveal.load", type: "bool", default: false },
  revealDownload: { name: "peekafoxy.tabs.reveal.download", type: "bool", default: false },
  revealTitle: { name: "peekafoxy.tabs.reveal.title", type: "bool", default: false },
  tabsShortcut: { name: "peekafoxy.tabs.shortcut", type: "string", default: DEFAULT_TABS_SHORTCUT },
  urlbarShortcut: { name: "peekafoxy.urlbar.shortcut", type: "string", default: DEFAULT_URLBAR_SHORTCUT },
  easing: { name: "peekafoxy.easing", type: "string", default: "smooth", values: ["smooth", "linear", "snappy"] },
  bookmarks: { name: "peekafoxy.bookmarks", type: "string", default: "follow", values: ["follow", "visible"] },
  welcomed: { name: "peekafoxy.welcomed", type: "bool", default: false },
};
export const PREF_BRANCH = "peekafoxy.";

// The animation curves: [opening, closing]. The first is Firefox's own pair (ease-out, ease-in).
export const EASINGS = {
  smooth: ["ease-out", "ease-in"],
  linear: ["linear", "linear"],
  snappy: ["cubic-bezier(0.2, 0.9, 0.3, 1)", "cubic-bezier(0.4, 0, 1, 1)"],
};

// --- prefs -------------------------------------------------------------------------------------

export function registerDefaults() {
  const branch = Services.prefs.getDefaultBranch("");
  for (const pref of Object.values(PREFS)) {
    try {
      if (pref.type === "bool") branch.setBoolPref(pref.name, pref.default);
      else if (pref.type === "int") branch.setIntPref(pref.name, pref.default);
      else branch.setStringPref(pref.name, pref.default);
    } catch (e) {
      Diag.warn("module:register", `could not register ${pref.name}: ${describe(e)}`, e);
    }
  }
}

export const clamp = (pref, value) => Math.min(pref.max, Math.max(pref.min, value));

// Reads never throw: a pref of another type (say, a number in user.js for a boolean) gives the default.
export function read(pref) {
  try {
    if (pref.type === "bool") return Services.prefs.getBoolPref(pref.name, pref.default);
    if (pref.type === "int") return clamp(pref, Services.prefs.getIntPref(pref.name, pref.default));
    const value = Services.prefs.getStringPref(pref.name, pref.default);
    if (pref.values && !pref.values.includes(value)) {
      Diag.warn("module:read", `${pref.name} is "${value}", which is not one of ${pref.values.join(", ")}; using ${pref.default}`);
      return pref.default;
    }
    return value;
  } catch (e) {
    Diag.warn("module:read", `${pref.name} has the wrong type, using ${pref.default}: ${describe(e)}`, e);
    return pref.default;
  }
}

export const hasUserValue = (pref) => {
  try {
    return Services.prefs.prefHasUserValue(pref.name);
  } catch (e) {
    Diag.warn("module:hasUserValue", `${pref.name} could not be read: ${describe(e)}`, e);
    return false;
  }
};

export function write(pref, value) {
  if (pref.type === "bool") Services.prefs.setBoolPref(pref.name, Boolean(value));
  else if (pref.type === "int") Services.prefs.setIntPref(pref.name, clamp(pref, Number(value)));
  else Services.prefs.setStringPref(pref.name, String(value));
}

export const reset = (pref) => Services.prefs.clearUserPref(pref.name);

// --- shortcuts ---------------------------------------------------------------------------------
//
// "Ctrl+Alt+T": any of Ctrl, Alt, Shift, Meta, then one key (a letter, a digit or F1 to F12). At
// least one of Ctrl, Alt or Meta is required: Shift alone would swallow typing. The key is matched
// by KeyboardEvent.code, so it does not depend on the keyboard layout.

const MODIFIERS = { ctrl: "Ctrl", control: "Ctrl", alt: "Alt", option: "Alt", shift: "Shift",
                    meta: "Meta", cmd: "Meta", command: "Meta" };
const ORDER = ["Ctrl", "Alt", "Shift", "Meta"];

const codeOf = (key) => {
  if (/^[A-Za-z]$/.test(key)) return `Key${key.toUpperCase()}`;
  if (/^[0-9]$/.test(key)) return `Digit${key}`;
  if (/^[Ff]([1-9]|1[0-2])$/.test(key)) return key.toUpperCase();
  return null;
};
const keyOf = (code) => {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-2])$/.test(code)) return code;
  return null;
};

const format = (mods, key) => [...ORDER.filter((m) => mods.has(m)), key].join("+");

// {ok: true, text, ctrl, alt, shift, meta, code} or {ok: false, reason}; reasons are "format",
// "key" and "modifier" (the same words as the error texts).
export function parseShortcut(input) {
  const parts = String(input ?? "").split("+").map((p) => p.trim());
  const rawKey = parts.pop();
  if (!rawKey || parts.some((p) => !p)) return { ok: false, reason: "format" };
  const mods = new Set();
  for (const part of parts) {
    const mod = MODIFIERS[part.toLowerCase()];
    if (!mod || mods.has(mod)) return { ok: false, reason: "format" };
    mods.add(mod);
  }
  const code = codeOf(rawKey);
  if (!code) return { ok: false, reason: "key" };
  if (!mods.has("Ctrl") && !mods.has("Alt") && !mods.has("Meta")) return { ok: false, reason: "modifier" };
  return {
    ok: true, code, text: format(mods, keyOf(code)),
    ctrl: mods.has("Ctrl"), alt: mods.has("Alt"), shift: mods.has("Shift"), meta: mods.has("Meta"),
  };
}

// The shortcut a keydown event stands for, as text, or null if it is only a modifier or an
// unsupported key.
// AltGr is where some layouts (Portuguese ABNT2, German, Czech...) type characters, and Windows reports
// it as Ctrl+Alt. Such presses are never shortcuts, in the recorder or in the matcher.
const isAltGraph = (event) => Boolean(event.getModifierState?.("AltGraph"));

export function shortcutFromEvent(event) {
  const key = keyOf(event.code);
  if (!key || isAltGraph(event)) return null;
  const mods = new Set(ORDER.filter((m) => event[`${m.toLowerCase()}Key`]));
  return format(mods, key);
}

export const matches = (binding, event) =>
  !isAltGraph(event) && event.code === binding.code && event.ctrlKey === binding.ctrl && event.altKey === binding.alt &&
  event.shiftKey === binding.shift && event.metaKey === binding.meta;

// The binding for a shortcut pref: the user's value if it is valid, else the default.
export function bindingFor(pref) {
  const parsed = parseShortcut(read(pref));
  return parsed.ok ? parsed : parseShortcut(pref.default);
}

// Why `text` cannot become the shortcut of `pref`, or null if it can. `other` is the other bar's pref.
export function shortcutProblem(text, other) {
  const parsed = parseShortcut(text);
  if (!parsed.ok) return parsed.reason;
  return bindingFor(other).text === parsed.text ? "duplicate" : null;
}

// --- Firefox's own shortcuts -------------------------------------------------------------------
//
// Firefox declares its keyboard shortcuts as <key> elements in the window's #mainKeyset, with the key
// (or a keycode such as VK_F5) and the modifiers, where "accel" is Ctrl (Cmd on macOS). A shortcut that
// the person records here would be taken from Firefox in every window, so the settings page can say
// so. This reads Firefox's markup, which may change: whatever is not as expected gives null (no
// warning), never an error.

const keyNameOf = (key) => {
  const char = key.getAttribute("key");
  if (char && char.length === 1) return char.toUpperCase();
  const code = /^VK_(F(?:[1-9]|1[0-2]))$/.exec(key.getAttribute("keycode") ?? "");
  return code ? code[1] : null;
};

const modifiersOf = (key, os) => {
  const found = { ctrl: false, alt: false, shift: false, meta: false };
  for (const word of String(key.getAttribute("modifiers") ?? "").toLowerCase().split(/[\s,]+/)) {
    if (word === "accel") found[os === "Darwin" ? "meta" : "ctrl"] = true;
    else if (word === "control") found.ctrl = true;
    else if (word === "os") found.meta = true;
    else if (word in found) found[word] = true;
  }
  return found;
};

// What the person reads for a key: the menu item that shows it, else the command it runs.
const labelOfKey = (doc, key) => {
  const labelOf = (node) => node?.getAttribute("label")?.trim() || null;
  const item = key.id
    ? [...doc.querySelectorAll("[key]")].find((node) => node.localName !== "key" && node.getAttribute("key") === key.id)
    : null;
  const command = key.getAttribute("command");
  return labelOf(item) ?? (command ? labelOf(doc.getElementById(command)) : null);
};

// {id, label} when Firefox already uses the shortcut `text` in window `win` (label is null when no
// name could be found), else null.
export function firefoxShortcut(win, text, os = Services.appinfo.OS) {
  try {
    const parsed = parseShortcut(text);
    const doc = win?.document;
    const keyset = doc?.getElementById("mainKeyset");
    if (!parsed.ok || !keyset) return null;
    for (const key of keyset.querySelectorAll("key")) {
      if (key.getAttribute("disabled") === "true" || keyNameOf(key) !== keyOf(parsed.code)) continue;
      const mods = modifiersOf(key, os);
      if (mods.ctrl === parsed.ctrl && mods.alt === parsed.alt && mods.shift === parsed.shift && mods.meta === parsed.meta) {
        return { id: key.id || key.getAttribute("command") || "", label: labelOfKey(doc, key) };
      }
    }
  } catch (e) {
    Diag.warn("module:firefoxShortcut", e);
  }
  return null;
}

// --- the shortcut recorder tells the windows that it is listening --------------------------------
//
// The fields of the settings page that record a shortcut are in another document, but a key press in
// them reaches the shortcut handler of the browser window first, which would toggle a bar while the
// person is only choosing a key. A field says when it has the focus; the handler asks. The fields
// are kept, not counted, so a page that goes away without a blur (its tab was closed) stops counting:
// an element that is gone, no longer in its page or no longer the focused one is dropped.
const recording = new Set();
export const Recorder = {
  focused(input) {
    recording.add(input);
  },
  blurred(input) {
    recording.delete(input);
  },
  isRecording() {
    for (const input of [...recording]) {
      try {
        if (input.isConnected && input.ownerDocument.activeElement === input) continue;
      } catch (e) {
        // A dead object (its page is gone) cannot be asked anything: it is not recording.
      }
      recording.delete(input);
    }
    return recording.size > 0;
  },
};

// --- texts -------------------------------------------------------------------------------------
//
// In the language of Firefox's interface: Portuguese (pt, pt-BR, pt-PT...) gets the Brazilian
// Portuguese strings, everything else English. To add a language, add an entry keyed by its language
// code (the part before the "-" or "_"). "{key}", "{min}" and "{max}" are replaced where they appear.

export const STRINGS = {
  en: {
    greeting: "Instaalleeeeed PEEK A BOO!!! >.<",
    greetingButton: "Peek-a-boo!",
    playerLabel: "Peek-A-Boo",
    keyboardHint: { title: "Keyboard combos" },
    tabs: { label: "Auto-hide the tab bar", tooltip: "Hide or show the tab bar in this window ({key})" },
    urlbar: { label: "Auto-hide the navigation bar", tooltip: "Hide or show the navigation bar in this window ({key})" },
    settings: {
      category: "Peek a Foxy 🦊",
      description: "Hide the tab bar and the navigation bar until you need them. Timings, shortcuts and what reveals the tab bar apply to all open windows right away; the two options for new windows only affect windows you open afterwards.",
      startGroup: "New windows",
      startTabs: "Hide the tab bar in new windows",
      startUrlbar: "Hide the navigation bar in new windows",
      startNote: "Windows that are already open keep their own setting. Use the shortcut or the toolbar button in them.",
      timingGroup: "Size and timing",
      stripPx: "Activation strip thickness (px)",
      tabsStripPx: "Activation strip thickness of the tab bar (px, 0 uses the value above)",
      urlbarStripPx: "Activation strip thickness of the navigation bar (px, 0 uses the value above)",
      showMs: "Opening animation duration (ms)",
      showDelayMs: "Time the pointer must stay on the activation strip before the bar opens (ms)",
      hideMs: "Closing animation duration (ms)",
      easing: "Animation curve",
      easingOptions: { smooth: "Smooth", linear: "Linear", snappy: "Snappy" },
      bookmarksGroup: "Bookmarks bar",
      bookmarks: "When the navigation bar is hidden, the bookmarks bar",
      bookmarksOptions: { follow: "Opens and closes with it", visible: "Always visible" },
      hideDelayMs: "Time the bar waits after the pointer leaves it before it closes (ms)",
      flashMs: "How long the tab bar stays open after these (ms)",
      revealGroup: "Show the tab bar when",
      revealSwitch: "Tabs are switched",
      revealNew: "A new tab is opened",
      revealLink: "A new tab opens by itself (clicking a link, a bookmark, or a page that opens a new window)",
      revealLoad: "The page of the current tab finishes loading",
      revealDownload: "A download finishes",
      revealTitle: "The title of a tab in the background changes",
      revealNote: "Hovering the strip always opens the tab bar, regardless of what is chosen here.",
      shortcutsGroup: "Shortcuts",
      tabsShortcut: "Toggle tab bar visibility",
      urlbarShortcut: "Toggle navigation bar visibility",
      shortcutPrompt: "Click here, then press the new shortcut",
      shortcutHint: "Combine Ctrl, Alt or Meta with a letter, a digit or F1–F12. Your system keeps some shortcuts for itself; if one does nothing, try another. Letters and digits name the key's position on a US keyboard, so on other layouts the label may differ from the keycap.",
      shortcutHintWindows: "AltGr counts as Ctrl+Alt on layouts that have it (Portuguese ABNT2, German, Czech...), so it isn't accepted. Use the left Ctrl and Alt, or Ctrl+Shift with a letter.",
      reset: "Restore default",
      resetFor: "Restore default: {label}",
      verticalTabsNote: "Vertical tabs are on, so Firefox already hides the tab bar and the tab bar options have no effect.",
      supportGroup: "Support",
      supportOk: "Working: Peek-a-Foxy {version} is loaded in this window.",
      supportErrors: "Working, with errors: Peek-a-Foxy {version} is loaded in this window, but its script recorded errors, which the diagnostic info lists.",
      supportProblem: "Problem found: {note}",
      supportMore: "Other problems were found as well, and the diagnostic info lists them all.",
      supportNotStarted: "Problem found: Peek-a-Foxy did not finish starting in this window, so autohide may not work here. The diagnostic info can help to find out why.",
      supportCopy: "Copy diagnostic info",
      supportCopied: "The diagnostic info was copied. Please read it before you paste it into an issue.",
      supportCopyFailed: "Firefox could not copy the text automatically. Select all of the text below, copy it yourself and read it before you paste it into an issue.",
      supportFallbackLabel: "Diagnostic info, to copy by hand",
      supportNote: "Nothing is sent anywhere: the diagnostic info only goes to your clipboard, with your user name, home folder and profile folder hidden. Read it before you paste it into an issue at {link}.",
      supportLink: "the Peek-a-Foxy issue page",
      health: {
        and: "and",
        kinds: { bool: "a true/false value", int: "a number", string: "text" },
        "navigator-toolbox": "The element #navigator-toolbox (the container of Firefox's toolbars) was not found. Firefox may have renamed or removed it, so the bars cannot be hidden or shown.",
        "tabs-toolbar": "The element #TabsToolbar (the tab bar) was not found. Firefox may have renamed or removed it, so the tab bar cannot be hidden.",
        "nav-bar": "The element #nav-bar (the navigation bar) was not found. Firefox may have renamed or removed it, so the navigation bar cannot be hidden.",
        urlbar: "The element #urlbar (the address bar) was not found. Firefox may have renamed or removed it, so the navigation bar may close while the address bar's drop-down list is open.",
        "bookmarks-toolbar": "The element #PersonalToolbar (the bookmarks bar) was not found. Firefox may have renamed or removed it, so it will not hide and show together with the navigation bar.",
        tabsHolder: "The element #tabbrowser-tabs (the tabs themselves) was not found. Firefox may have renamed it, so the tab bar may not collapse properly.",
        tabsHolderCustom: "The window draws its own title bar (customtitlebar), but #TabsToolbar .toolbar-items, the part of the tab bar that holds the tabs, was not found. Firefox may have moved the tabs, so hiding the tab bar may hide the window buttons or do nothing.",
        customtitlebar: "The window buttons are inside the tab bar, but the window does not have the customtitlebar attribute that the stylesheet looks for. Firefox may have renamed it, so hiding the tab bar could hide the window buttons too.",
        browserApis: "These parts of Firefox or of the loader that the script uses are missing: {names}. Firefox or fx-autoconfig may have changed them, so some features of the script will not work.",
        toolbarButtons: "The toolbar button {ids} is not registered with Firefox, so it is missing from Customize Toolbar. Firefox may have changed how toolbar buttons are made, or the script stopped before it made them.",
        prefMissing: "The setting {name} is not registered, so it is missing from about:config and the script uses its built-in default.",
        prefType: "The setting {name} holds {actual} instead of {expected}, probably from a line in user.js or prefs.js with the wrong kind of value, so the script ignores it and uses the default ({default}). Reset it in about:config.",
        prefsMore: "More settings have the same kind of problem ({n}).",
        rangeBad: "The setting {name} is {value}, outside the allowed {min} to {max}, so the script uses {used} instead.",
        rangeMore: "More settings are out of range too ({n}).",
        shortcutBad: "The shortcut setting {name} says \"{text}\", which is not a valid shortcut, so the default {default} is used.",
        shortcutMore: "The other shortcut has the same problem.",
        shortcutsSame: "Both bars use the shortcut {text}, so only one of them reacts to it. Choose a different shortcut for one of them in the Peek-a-Foxy settings.",
        settingsPage: "Firefox's settings page is not what the script expects ({what}), so the Peek-a-Foxy category was not added. The settings can still be changed in about:config: search for peekafoxy.",
      },
      problems: {
        format: "That isn't a valid shortcut.",
        key: "Use a letter, a digit or F1–F12.",
        modifier: "Add Ctrl, Alt or Meta.",
        duplicate: "The other bar already uses this shortcut.",
        firefoxUses: "Firefox already uses this shortcut for “{name}”, which will stop working.",
        firefoxUsesUnnamed: "Firefox already uses this shortcut, which will stop working.",
        unsupported: "That key can't be used.",
        range: "Enter a number between {min} and {max}.",
      },
    },
  },
  pt: {
    greeting: "Instaalaadoooo PEEK A BOO!!! >.<",
    greetingButton: "Peek-a-boo!",
    playerLabel: "Peek-A-Boo",
    keyboardHint: { title: "Combos de teclado" },
    tabs: { label: "Ocultar a barra de abas automaticamente",
            tooltip: "Oculta ou mostra a barra de abas nesta janela ({key})" },
    urlbar: { label: "Ocultar a barra de navegação automaticamente",
              tooltip: "Oculta ou mostra a barra de navegação nesta janela ({key})" },
    settings: {
      category: "Peek a Foxy 🦊",
      description: "Oculta a barra de abas e a barra de navegação até você precisar delas. Os tempos, os atalhos e o que faz a barra de abas aparecer valem na hora para todas as janelas abertas; as duas opções de novas janelas só afetam as janelas que você abrir depois.",
      startGroup: "Novas janelas",
      startTabs: "Ocultar a barra de abas em novas janelas",
      startUrlbar: "Ocultar a barra de navegação em novas janelas",
      startNote: "Janelas que já estão abertas mantêm a configuração delas. Nelas, use o atalho ou o botão da barra de ferramentas.",
      timingGroup: "Tamanho e tempos",
      stripPx: "Largura da faixa de ativação (px)",
      tabsStripPx: "Largura da faixa de ativação da barra de abas (px; 0 usa o valor acima)",
      urlbarStripPx: "Largura da faixa de ativação da barra de navegação (px; 0 usa o valor acima)",
      showMs: "Duração da animação de abertura (ms)",
      showDelayMs: "Tempo que o cursor deve permanecer na faixa de ativação antes de abrir a barra (ms)",
      hideMs: "Duração da animação de fechamento (ms)",
      easing: "Curva da animação",
      easingOptions: { smooth: "Suave", linear: "Linear", snappy: "Ágil" },
      bookmarksGroup: "Barra de favoritos",
      bookmarks: "Quando a barra de navegação está oculta, a barra de favoritos",
      bookmarksOptions: { follow: "Abre e fecha junto com ela", visible: "Sempre visível" },
      hideDelayMs: "Tempo que a barra espera depois de o cursor sair dela antes de fechar (ms)",
      flashMs: "Por quanto tempo a barra de abas fica aberta depois desses eventos (ms)",
      revealGroup: "Mostrar a barra de abas ao:",
      revealSwitch: "Ocorrer troca de abas",
      revealNew: "Ocorrer abertura de uma nova aba",
      revealLink: "Ocorrer abertura automática de uma nova aba (clique em um link, um favorito ou uma página que abre uma nova janela)",
      revealLoad: "A página da aba atual terminar de carregar",
      revealDownload: "Um download terminar",
      revealTitle: "O título de uma aba em segundo plano mudar",
      revealNote: "Passar o mouse sobre a faixa sempre abre a barra de abas, independentemente da escolha feita aqui.",
      shortcutsGroup: "Atalhos",
      tabsShortcut: "Alternar a exibição da barra de abas",
      urlbarShortcut: "Alternar a exibição da barra de navegação",
      shortcutPrompt: "Clique aqui e pressione o novo atalho",
      shortcutHint: "Combine Ctrl, Alt ou Meta com uma letra, um dígito ou F1–F12. O sistema reserva alguns atalhos para ele; se um não fizer nada, tente outro. As letras e os dígitos indicam a posição da tecla em um teclado americano; em outros layouts, o nome pode não coincidir com o que está impresso na tecla.",
      shortcutHintWindows: "Em layouts com AltGr (ABNT2, alemão, tcheco...), o AltGr conta como Ctrl+Alt e não é aceito. Use o Ctrl e o Alt da esquerda, ou Ctrl+Shift com uma letra.",
      reset: "Restaurar padrão",
      resetFor: "Restaurar padrão: {label}",
      verticalTabsNote: "As abas verticais estão ativadas, então o Firefox já oculta a barra de abas e as opções da barra de abas não têm efeito.",
      supportGroup: "Suporte",
      supportOk: "Funcionando: o Peek-a-Foxy {version} está carregado nesta janela.",
      supportErrors: "Funcionando, com erros: o Peek-a-Foxy {version} está carregado nesta janela, mas o script registrou erros, que as informações de diagnóstico listam.",
      supportProblem: "Problema encontrado: {note}",
      supportMore: "Outros problemas também foram encontrados, e as informações de diagnóstico listam todos eles.",
      supportNotStarted: "Problema encontrado: o Peek-a-Foxy não terminou de iniciar nesta janela, então o ocultamento automático pode não funcionar aqui. As informações de diagnóstico podem ajudar a descobrir o motivo.",
      supportCopy: "Copiar informações de diagnóstico",
      supportCopied: "As informações de diagnóstico foram copiadas. Leia-as antes de colá-las em uma issue.",
      supportCopyFailed: "O Firefox não conseguiu copiar o texto automaticamente. Selecione todo o texto abaixo, copie-o você mesmo e leia-o antes de colá-lo em uma issue.",
      supportFallbackLabel: "Informações de diagnóstico, para copiar manualmente",
      supportNote: "Nada é enviado a lugar nenhum: as informações de diagnóstico só vão para a sua área de transferência, com o seu nome de usuário, a sua pasta pessoal e a pasta do perfil ocultos. Leia-as antes de colá-las em uma issue em {link}.",
      supportLink: "a página de issues do Peek-a-Foxy",
      health: {
        and: "e",
        kinds: { bool: "um valor verdadeiro/falso", int: "um número", string: "um texto" },
        "navigator-toolbox": "O elemento #navigator-toolbox (o container das barras de ferramentas do Firefox) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então as barras não podem ser ocultadas nem mostradas.",
        "tabs-toolbar": "O elemento #TabsToolbar (a barra de abas) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então a barra de abas não pode ser ocultada.",
        "nav-bar": "O elemento #nav-bar (a barra de navegação) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então a barra de navegação não pode ser ocultada.",
        urlbar: "O elemento #urlbar (a barra de endereços) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então a barra de navegação pode se fechar enquanto a lista suspensa da barra de endereços está aberta.",
        "bookmarks-toolbar": "O elemento #PersonalToolbar (a barra de favoritos) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então ela não vai se ocultar e se mostrar junto com a barra de navegação.",
        tabsHolder: "O elemento #tabbrowser-tabs (as abas em si) não foi encontrado. O Firefox pode tê-lo renomeado, então a barra de abas pode não se recolher corretamente.",
        tabsHolderCustom: "A janela desenha a própria barra de título (customtitlebar), mas #TabsToolbar .toolbar-items, a parte da barra de abas que contém as abas, não foi encontrada. O Firefox pode ter movido as abas, então ocultar a barra de abas pode ocultar os botões da janela ou não fazer nada.",
        customtitlebar: "Os botões da janela estão dentro da barra de abas, mas a janela não tem o atributo customtitlebar que o stylesheet procura. O Firefox pode tê-lo renomeado, então ocultar a barra de abas pode ocultar também os botões da janela.",
        browserApis: "Estas partes do Firefox ou do loader que o script usa estão ausentes: {names}. O Firefox ou o fx-autoconfig pode tê-las alterado, então alguns recursos do script não vão funcionar.",
        toolbarButtons: "O botão da barra de ferramentas {ids} não está registrado no Firefox, então ele não aparece em Personalizar barra de ferramentas. O Firefox pode ter mudado a forma de criar botões da barra de ferramentas, ou o script parou antes de criá-los.",
        prefMissing: "A configuração {name} não está registrada, então ela não aparece no about:config e o script usa o valor padrão embutido.",
        prefType: "A configuração {name} contém {actual} em vez de {expected}, provavelmente por uma linha do user.js ou do prefs.js com o tipo de valor errado, então o script a ignora e usa o valor padrão ({default}). Restaure-a no about:config.",
        prefsMore: "Há mais configurações com o mesmo tipo de problema ({n}).",
        rangeBad: "A configuração {name} está em {value}, fora do intervalo permitido de {min} a {max}, então o script usa {used} no lugar.",
        rangeMore: "Há mais configurações fora do intervalo ({n}).",
        shortcutBad: "A configuração de atalho {name} diz \"{text}\", que não é um atalho válido, então o atalho padrão {default} é usado.",
        shortcutMore: "O outro atalho tem o mesmo problema.",
        shortcutsSame: "As duas barras usam o atalho {text}, então só uma delas reage a ele. Escolha um atalho diferente para uma delas nas configurações do Peek-a-Foxy.",
        settingsPage: "A página de configurações do Firefox não é a que o script espera ({what}), então a categoria Peek-a-Foxy não foi adicionada. As configurações ainda podem ser alteradas no about:config: procure por peekafoxy.",
      },
      problems: {
        format: "Esse atalho não é válido.",
        key: "Use uma letra, um dígito ou F1–F12.",
        modifier: "Adicione Ctrl, Alt ou Meta.",
        duplicate: "A outra barra já usa esse atalho.",
        firefoxUses: "O Firefox já usa esse atalho para “{name}”, que vai deixar de funcionar.",
        firefoxUsesUnnamed: "O Firefox já usa esse atalho, que vai deixar de funcionar.",
        unsupported: "Essa tecla não pode ser usada.",
        range: "Digite um número entre {min} e {max}.",
      },
    },
  },
};

// The hint under the shortcuts: the same everywhere, plus what is true on Windows
// (Services.appinfo.OS is "Linux", "WINNT" or "Darwin").
export function shortcutHint(settings, os = Services.appinfo.OS) {
  const extra = { WINNT: settings.shortcutHintWindows }[os];
  return extra ? `${settings.shortcutHint} ${extra}` : settings.shortcutHint;
}

const languageKey = (locale) => {
  const key = String(locale).split(/[-_]/)[0].toLowerCase();
  return Object.hasOwn(STRINGS, key) ? key : "en";
};

export const textFor = (locale) => STRINGS[languageKey(locale)];

// The language and direction of the texts that textFor gives, which is not Firefox's own when it falls
// back to English: the page sets them on its pane so that a mirrored (right-to-left) Firefox does
// not lay English out right-to-left, and a screen reader picks the voice of the text.
const LANGUAGE_TAGS = { en: "en", pt: "pt-BR" };
const RIGHT_TO_LEFT = new Set(["ar", "fa", "he", "ur"]);
export const languageFor = (locale) => LANGUAGE_TAGS[languageKey(locale)] ?? languageKey(locale);
export const directionFor = (locale) => (RIGHT_TO_LEFT.has(languageKey(locale)) ? "rtl" : "ltr");

// --- diagnostics -------------------------------------------------------------------------------
//
// Diag is shared by every window and by the settings page (Firefox gives all of them the same
// instance of this module), and it does three things:
//   1. keeps the last 50 events (errors first), so nothing a script does wrong is swallowed silently;
//   2. runs the health check: do the elements, attributes, prefs and shortcuts that the stylesheet
//      and the scripts depend on still exist and make sense in this Firefox?
//   3. writes both to <profile>/chrome/peekafoxy-status.json (schema 1, documented in
//      src/peek_a_foxy/status.py, which `peek-a-foxy doctor` reads), and builds the Markdown that the
//      "Copy diagnostic info" button puts on the clipboard.
// Nothing here is ever sent anywhere, and nothing here throws: a diagnostic must not break the thing
// it diagnoses. Every text is redacted (home folder, user name, profile folder and name) and cleaned
// of control characters before it is stored, so the file and the clipboard text are safe to share.

export const STATUS_FILE = "peekafoxy-status.json";
export const STATUS_SCHEMA = 1;
export const ISSUES_URL = "https://github.com/paodelonga/peek-a-foxy/issues/new/choose";
export const NOTICE = "Nothing was sent anywhere. Review it, then paste it into your issue.";
export const TOOLBAR_BUTTONS = ["tabs-autohide-button", "urlbar-autohide-button"];

const MAX_EVENTS = 50; // the ring buffer
const MAX_WHERE = 60; // characters kept of the place of an event
const MAX_MESSAGE = 300; // ... of its message
const MAX_NOTE = 420; // ... of a health note
const MAX_FIELD = 80; // ... of a plain field (version, channel...)
const RAW_LIMIT = 4000; // a text is cut to this before anything else happens to it
const WRITE_DELAY_MS = 2000; // writes are coalesced: one per this many milliseconds at most
const NOTIFY_DELAY_MS = 300;
const SEVERITY = { info: 0, warn: 1, error: 2 };

const BREAKS = /[\t\n\r\v\f\u0085\u2028\u2029]/g;
const CONTROLS = /[\u0000-\u0008\u000e-\u001f\u007f-\u0084\u0086-\u009f]/g;
const DIRECTION = /[\u202a-\u202e\u2066-\u2069]/g; // overrides and isolates, which can mislead a reader
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

// One text, ready to be stored: redacted, line breaks and tabs as spaces, other control characters
// and direction overrides as U+FFFD (what the Python report does too), cut to `max` characters.
// Right-to-left letters stay.
export function sanitize(text, max, redact = (t) => t) {
  let out;
  try {
    out = String(text ?? "");
  } catch (e) {
    out = "(a text that could not be shown)";
  }
  if (out.length > RAW_LIMIT) out = out.slice(0, RAW_LIMIT);
  out = redact(out).replace(BREAKS, " ").replace(CONTROLS, "\ufffd").replace(DIRECTION, "\ufffd").trim();
  if (out.length > max) out = `${out.slice(0, max - 1)}\u2026`;
  return out.replace(LONE_SURROGATE, "\ufffd");
}

// An error (from any compartment) or a text as one line: "TypeError: x is null (fn@file:3:5)".
export function describe(what) {
  try {
    if (typeof what === "string") return what;
    if (what && typeof what === "object" && typeof what.message === "string") {
      const frame = String(what.stack ?? "").split("\n")[0].trim();
      return `${what.name || "Error"}: ${what.message}${frame ? ` (${frame.slice(0, 160)})` : ""}`;
    }
    return String(what);
  } catch (e) {
    return "(an error that could not be shown)";
  }
}

// --- redaction: the same placeholders as the Python report (~, <user>, <profile>) ---

const STANDARD_PROFILE_NAMES = new Set(
  ["default", "default-release", "default-esr", "default-nightly", "dev-edition-default"]);
const SCRIPT_SUFFIX = /^(?:uc\.js|sys\.mjs|m?js|css|json|py|x?html|ini)(?![A-Za-z0-9_-])/i;
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const WORD = (text) => `(?<![\\p{L}\\p{N}_])${escapeRegExp(text)}(?![\\p{L}\\p{N}_])`;
// A home folder is a whole folder name, as in the Python side (src/peek_a_foxy/logs.py): /home/al is
// not the start of /home/alice, nor of /home/al-bob, and the same text one folder deeper
// (/var/home/jo for /home/jo) is another place. So it must not follow a word character, and must not
// be followed by one or by a hyphen.
const WHOLE_FOLDER = (alternatives) => `(?<![\\p{L}\\p{N}_])(?:${alternatives})(?![\\p{L}\\p{N}_-])`;

// One path as it may be printed: as given, with either slash, escaped (a repr), and as part of a URL.
function spellings(path) {
  const forward = path.replace(/\\/g, "/");
  const backward = path.replace(/\//g, "\\");
  const found = new Set([path, forward, backward, backward.replace(/\\/g, "\\\\")]);
  try {
    found.add(encodeURI(forward));
  } catch (e) {
    // A path with a lone surrogate cannot be URL-encoded; the plain spellings still apply.
  }
  return [...found];
}

// {homes, user, profileDir, profileName, ignoreCase} -> a function that hides them in a text. A home
// folder that is only "/" or "C:\" would blank out every path, and a user name shorter than three
// characters would match inside ordinary words, so neither is used.
export function makeRedactor({ homes = [], user = "", profileDir = "", profileName = "", ignoreCase = false } = {}) {
  const flags = `gu${ignoreCase ? "i" : ""}`;
  const rules = [];
  const paths = (list, replacement, minimum, whole = false) => {
    const spelled = new Set();
    for (const path of list) {
      const trimmed = String(path || "").replace(/[\\/]+$/, "");
      const bare = trimmed.replace(/^[\\/]+/, "");
      if (bare.length >= minimum && !/^[A-Za-z]:$/.test(bare)) spellings(trimmed).forEach((p) => spelled.add(p));
    }
    if (spelled.size) {
      const pattern = [...spelled].sort((a, b) => b.length - a.length).map(escapeRegExp).join("|");
      rules.push([new RegExp(whole ? WHOLE_FOLDER(pattern) : pattern, flags), replacement]);
    }
  };
  paths([profileDir], "<profile>", 2);
  paths(homes, "~", 2, true);
  // Firefox names profile folders like a1b2c3d4.default-release. The same shape is a file name in
  // eight letters ("autohide.uc.js:12" in an error's stack), which is kept: the real profile folder
  // was hidden above, by its whole path, and a stack without its file names would be useless.
  rules.push([/(?<=[\\/])[a-z0-9]{8}\.(?<rest>[^\\/\s'"]+)/gu, (found, ...args) =>
    SCRIPT_SUFFIX.test(args.at(-1).rest) ? found : "<profile>"]);
  if (profileName && profileName.length >= 3 && !STANDARD_PROFILE_NAMES.has(profileName)) {
    rules.push([new RegExp(WORD(profileName), flags), "<profile>"]);
  }
  if (user && user.length >= 3) rules.push([new RegExp(WORD(user), flags), "<user>"]);
  rules.push(
    [/(?<scheme>[A-Za-z][A-Za-z0-9+.-]*:\/\/)[^/\s:@]+(?::[^/\s@]*)?@/gu, "$<scheme>***@"],
    [/(?<head>authorization:\s*(?:bearer|basic|token)\s+)\S+/giu, "$<head>***"],
    [/\b(?<name>access_token|token|api[_-]?key|key|secret|password|passwd|auth|sig|signature)=[^&\s"']+/giu, "$<name>=***"],
    [/\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}/gu, "***"],
  );
  return (text) => rules.reduce((out, [pattern, replacement]) => out.replace(pattern, replacement), text);
}

let redactor = null;
function machineRedactor() {
  if (redactor) return redactor;
  const env = (name) => {
    try {
      return Services.env.get(name) || "";
    } catch (e) {
      return "";
    }
  };
  const tryGet = (fn) => {
    try {
      return fn() || "";
    } catch (e) {
      return "";
    }
  };
  redactor = makeRedactor({
    homes: [tryGet(() => Services.dirsvc.get("Home", Ci.nsIFile).path), env("HOME"), env("USERPROFILE")],
    user: env("USER") || env("USERNAME") || env("LOGNAME"),
    profileDir: tryGet(() => PathUtils.profileDir),
    profileName: tryGet(() =>
      Cc["@mozilla.org/toolkit/profile-service;1"].getService(Ci.nsIToolkitProfileService).currentProfile?.name),
    ignoreCase: Services.appinfo.OS === "WINNT",
  });
  return redactor;
}

// --- the ring buffer ---

const events = []; // {time, level, where, message, base, count}
let spentMs = 0; // time the synchronous parts of Diag took (see Diag.stats)
let writes = 0;
let writesFailed = 0;
let skippedClosed = 0; // window checks that were not run because the window had closed (see Diag.check)
let writeTimer = null;
let writeChain = Promise.resolve();
let notifyTimer = null;

const notify = () => {
  if (notifyTimer !== null) return;
  notifyTimer = lazy.setTimeout(() => {
    notifyTimer = null;
    try {
      Services.obs.notifyObservers(null, "peekafoxy-diag-changed");
    } catch (e) {
      // Nobody listening is not a problem.
    }
  }, NOTIFY_DELAY_MS);
};

function scheduleWrite() {
  if (writeTimer !== null) return;
  writeTimer = lazy.setTimeout(() => {
    writeTimer = null;
    writeNow();
  }, WRITE_DELAY_MS);
}

// When the buffer is full the oldest event of the lowest severity makes room, so a flood of harmless
// events never pushes out an error. A new event less severe than everything in a full buffer is dropped.
function makeRoom(level) {
  if (events.length < MAX_EVENTS) return true;
  for (const kind of Object.keys(SEVERITY)) {
    if (SEVERITY[kind] > SEVERITY[level]) break;
    const index = events.findIndex((e) => e.level === kind);
    if (index >= 0) {
      events.splice(index, 1);
      return true;
    }
  }
  return false;
}

function record(level, where, what, extra, { write = true } = {}) {
  try {
    const began = now();
    const redact = machineRedactor();
    const place = sanitize(where, MAX_WHERE, redact);
    const base = sanitize(typeof what === "string" ? what : describe(what), MAX_MESSAGE, redact);
    const last = events.at(-1);
    if (last && last.level === level && last.where === place && last.base === base) {
      last.count += 1;
      last.message = sanitize(`${base} (repeated ${last.count} times)`, MAX_MESSAGE + 30);
    } else {
      if (level !== "info") {
        const detail = extra ?? (typeof what === "string" ? undefined : what);
        console[level](`[peekafoxy ${place}] ${base}`, ...(detail === undefined ? [] : [detail]));
      }
      if (makeRoom(level)) {
        events.push({ time: new Date().toISOString(), level, where: place, message: base, base, count: 1 });
      }
    }
    if (write) scheduleWrite();
    if (level === "error") notify();
    spentMs += now() - began;
  } catch (e) {
    // Diag must never be the reason something fails.
  }
}

const publicEvent = ({ time, level, where, message }) => ({ time, level, where, message });

// --- health checks ---
//
// Each check gives {name, ok, parts, note}. When it fails, `parts` are the sentences of the note as
// [key, values] (the texts are in STRINGS.<language>.settings.health) and `note` is the same in
// English, which is what the status file and the report hold, whatever language Firefox speaks:
// they go to an issue. The settings page shows the parts in the language of Firefox (see noteFor).
// A note says in plain words what was not found and which change in Firefox it suggests.

const pass = (name) => ({ name, ok: true, parts: [], note: "" });
const PREF_TYPES = { 128: "bool", 64: "int", 32: "string" }; // nsIPrefBranch.PREF_BOOL, PREF_INT, PREF_STRING

// The sentences of one language. `values` are filled in where "{name}" appears; a list is joined with
// the language's own "and", and the names of the kinds of pref value are translated.
function sentence(health, [key, values = {}]) {
  const english = STRINGS.en.settings.health;
  const template = health[key] ?? english[key];
  return template.replace(/\{(\w+)\}/g, (_, name) => {
    const value = values[name];
    if (Array.isArray(value)) return value.join(name === "ids" ? ` ${health.and ?? english.and} ` : ", ");
    if (name === "actual" || name === "expected") return (health.kinds ?? english.kinds)[value];
    return String(value ?? "");
  });
}

export const healthFail = (name, ...parts) => ({
  name, ok: false, parts,
  note: parts.map((part) => sentence(STRINGS.en.settings.health, part)).join(" "),
});

// A failed check as the settings page shows it: in `health`'s language, and in English for any
// sentence that language does not have (yet).
export const noteFor = (failed, health = STRINGS.en.settings.health) =>
  sanitize(failed.parts.map((part) => sentence(health, part)).join(" "), MAX_NOTE, machineRedactor());

const ELEMENTS = [
  ["navigator-toolbox", "navigator-toolbox"],
  ["tabs-toolbar", "TabsToolbar"],
  ["nav-bar", "nav-bar"],
  ["urlbar", "urlbar"],
  ["bookmarks-toolbar", "PersonalToolbar"],
];

// A popup window (window.open with features) has no toolbars of its own to check.
const isNormalWindow = (win) => {
  try {
    return win.toolbar?.visible !== false;
  } catch (e) {
    return true;
  }
};

export function browserChecks(win) {
  const doc = win.document;
  const root = doc.documentElement;
  const out = [];
  for (const [name, id] of ELEMENTS) {
    out.push(doc.getElementById(id) ? pass(name) : healthFail(name, [name]));
  }

  const custom = root.hasAttribute("customtitlebar");
  if (!doc.getElementById("tabbrowser-tabs")) {
    out.push(healthFail("tabs-holder", ["tabsHolder"]));
  } else if (custom && !doc.querySelector("#TabsToolbar .toolbar-items")) {
    out.push(healthFail("tabs-holder", ["tabsHolderCustom"]));
  } else {
    out.push(pass("tabs-holder"));
  }

  // The stylesheet has one variant with the root attribute customtitlebar (window buttons inside the
  // tab bar) and one without. Window buttons that are visible without the attribute mean that Firefox
  // may have renamed it, and the wrong variant would hide the buttons together with the tabs.
  let buttons = false;
  try {
    buttons = [...doc.querySelectorAll("#TabsToolbar .titlebar-buttonbox-container")].some(
      (box) => win.getComputedStyle(box).display !== "none" && box.getBoundingClientRect().width > 0);
  } catch (e) {
    Diag.info("diag:buttons", e);
  }
  out.push(buttons && !custom ? healthFail("customtitlebar", ["customtitlebar"]) : pass("customtitlebar"));

  const missing = [
    ["gBrowser.tabContainer", win.gBrowser?.tabContainer],
    ["SessionStore.setCustomWindowValue", win.SessionStore?.setCustomWindowValue],
    ["CustomizableUI.getWidget", win.CustomizableUI?.getWidget],
    ["UC_API.Utils.createWidget", win.UC_API?.Utils?.createWidget],
  ].filter(([, value]) => !value).map(([name]) => name);
  out.push(missing.length ? healthFail("browser-apis", ["browserApis", { names: missing }]) : pass("browser-apis"));

  const unregistered = TOOLBAR_BUTTONS.filter((id) => {
    try {
      return !win.CustomizableUI.getWidget(id);
    } catch (e) {
      return true;
    }
  });
  out.push(unregistered.length
    ? healthFail("toolbar-buttons", ["toolbarButtons", { ids: unregistered }])
    : pass("toolbar-buttons"));
  return out;
}

const userValue = (pref, type) => {
  try {
    if (type === "bool") return Services.prefs.getBoolPref(pref.name);
    if (type === "int") return Services.prefs.getIntPref(pref.name);
    return Services.prefs.getStringPref(pref.name);
  } catch (e) {
    return undefined;
  }
};

// The first problem in full, and how many others there are.
const firstAndMore = (name, problems, moreKey) =>
  problems.length ? healthFail(name, problems[0], ...(problems.length > 1 ? [[moreKey, { n: problems.length - 1 }]] : [])) : pass(name);

export function globalChecks() {
  const out = [];
  const prefs = [];
  const wrongType = new Set();
  for (const pref of Object.values(PREFS)) {
    const actual = PREF_TYPES[Services.prefs.getPrefType(pref.name)];
    if (!actual) {
      prefs.push(["prefMissing", { name: pref.name }]);
    } else if (actual !== pref.type) {
      wrongType.add(pref.name);
      prefs.push(["prefType", { name: pref.name, actual, expected: pref.type, default: pref.default }]);
    }
  }
  out.push(firstAndMore("prefs", prefs, "prefsMore"));

  const ranges = [];
  for (const pref of Object.values(PREFS)) {
    if (pref.type !== "int" || wrongType.has(pref.name)) continue;
    const value = userValue(pref, "int");
    if (value !== undefined && (value < pref.min || value > pref.max)) {
      ranges.push(["rangeBad", { name: pref.name, value, min: pref.min, max: pref.max, used: clamp(pref, value) }]);
    }
  }
  out.push(firstAndMore("settings-values", ranges, "rangeMore"));

  const shortcuts = [PREFS.tabsShortcut, PREFS.urlbarShortcut];
  const bad = [];
  for (const pref of shortcuts) {
    if (wrongType.has(pref.name)) continue;
    const raw = userValue(pref, "string");
    if (raw !== undefined && !parseShortcut(raw).ok) {
      bad.push(["shortcutBad", { name: pref.name, text: sanitize(raw, 40), default: pref.default }]);
    }
  }
  out.push(bad.length
    ? healthFail("shortcuts", bad[0], ...(bad.length > 1 ? [["shortcutMore"]] : []))
    : pass("shortcuts"));

  const [tabs, urlbar] = shortcuts.map((pref) => bindingFor(pref).text);
  out.push(tabs === urlbar ? healthFail("shortcuts-distinct", ["shortcutsSame", { text: tabs }]) : pass("shortcuts-distinct"));
  return out;
}

// --- the registry of windows and of the checks each one reported ---

const started = new Set(); // browser windows whose script ran to the end
const healthBySource = new Map(); // a window, or a string for something that is not a window
let checkTimer = null;
let checkWindow = null;

const isClosed = (win) => {
  try {
    return win.closed;
  } catch (e) {
    return true; // a dead window reference counts as closed
  }
};

const liveWindows = () => {
  for (const win of [...started]) {
    if (isClosed(win)) forget(win);
  }
  return [...started];
};

function forget(win) {
  started.delete(win);
  healthBySource.delete(win);
}

// The checks of every source in one list: a name fails if it failed anywhere.
function combinedHealth() {
  const merged = new Map();
  for (const results of healthBySource.values()) {
    for (const result of results) {
      const seen = merged.get(result.name);
      if (!seen || (seen.ok && !result.ok)) merged.set(result.name, result);
    }
  }
  return [...merged.values()];
}

const healthObject = () => {
  const redact = machineRedactor();
  const out = {};
  for (const { name, ok, note } of combinedHealth()) {
    out[sanitize(name, MAX_WHERE)] = ok ? "ok" : `fail: ${sanitize(note, MAX_NOTE, redact)}`;
  }
  return out;
};

function buildStatus() {
  const redact = machineRedactor();
  const field = (value) => sanitize(value, MAX_FIELD, redact);
  return {
    schema: STATUS_SCHEMA,
    scriptVersion: SCRIPT_VERSION,
    firefoxVersion: field(Services.appinfo.version),
    buildID: field(Services.appinfo.appBuildID),
    channel: field(lazy.AppConstants.MOZ_UPDATE_CHANNEL),
    os: field(Services.appinfo.OS),
    locale: field(Services.locale.appLocaleAsBCP47),
    updated: new Date().toISOString(),
    windows: liveWindows().length,
    health: healthObject(),
    errors: events.map(publicEvent),
  };
}

// One write at a time, in order, so that windows writing together cannot interleave; and each write
// goes to a temporary file that is then moved over the real one, so a reader sees the old file or
// the new one and never half of one. It never rejects.
async function doWrite() {
  try {
    const path = PathUtils.join(PathUtils.profileDir, "chrome", STATUS_FILE);
    const text = `${JSON.stringify(buildStatus(), null, 2)}\n`;
    await IOUtils.writeUTF8(path, text, { tmpPath: `${path}.tmp`, mode: "overwrite" });
    writes += 1;
  } catch (e) {
    writesFailed += 1;
    record("warn", "status:write", `the status file could not be written: ${describe(e)}`, e, { write: false });
  }
}

function writeNow() {
  if (writeTimer !== null) {
    lazy.clearTimeout(writeTimer);
    writeTimer = null;
  }
  writeChain = writeChain.then(doWrite);
  return writeChain;
}

// --- the report that the button copies ---

const cell = (text) => text.replace(/\s+/g, " ").replace(/\|/g, "\\|").replace(/</g, "\\<");

export function reportMarkdown(status) {
  const failed = Object.entries(status.health).filter(([, value]) => value !== "ok");
  const lines = [
    "# Peek-a-Foxy diagnostic info",
    "",
    `This was written by the Peek-a-Foxy script ${cell(status.scriptVersion)} in Firefox on ${status.updated} and uses status format ${status.schema}.`,
    "",
    `- Program version: ${cell(status.scriptVersion)}`,
    `- Firefox: ${cell(status.firefoxVersion)} (build ${cell(status.buildID)}, channel ${cell(status.channel)})`,
    `- System: ${cell(status.os)}`,
    `- Language: ${cell(status.locale)}`,
    `- Windows open: ${status.windows}`,
    "",
    `**Result: ${failed.length} FAIL, ${Object.keys(status.health).length - failed.length} OK**`,
    "",
    "## Health checks",
    "",
    "| Status | Check | Result |",
    "|---|---|---|",
  ];
  for (const [name, value] of Object.entries(status.health)) {
    const note = value === "ok" ? "" : value.replace(/^fail:\s*/, "");
    lines.push(`| ${value === "ok" ? "OK" : "FAIL"} | ${cell(name)} | ${cell(note)} |`);
  }
  lines.push("", "## Last events (newest last)", "");
  if (status.errors.length) {
    lines.push("```text");
    for (const e of status.errors) {
      lines.push(`${e.time} ${e.level} ${e.where}: ${e.message}`.replace(/`/g, "'"));
    }
    lines.push("```");
  } else {
    lines.push("None.");
  }
  lines.push("", NOTICE, ISSUES_URL, "");
  return lines.join("\n");
}

// Puts text on the system clipboard; `copy` throws when Firefox cannot. It is an object so that a
// test can swap the method for one that fails.
export const Clipboard = {
  copy(text) {
    Cc["@mozilla.org/widget/clipboardhelper;1"].getService(Ci.nsIClipboardHelper).copyString(text);
  },
};

const OUR_FILES = /(?:autohide(?:-prefs)?\.uc\.js|peekafoxy\.sys\.mjs)/;

export const Diag = {
  error: (where, what, extra) => record("error", where, what, extra),
  warn: (where, what, extra) => record("warn", where, what, extra),
  info: (where, what, extra) => record("info", where, what, extra),

  // A copy of the events, oldest first.
  events: () => events.map(publicEvent),
  stats: () => ({
    events: events.length, writes, writesFailed, syncMs: spentMs, skippedClosed,
    checkedWindows: [...healthBySource.keys()].filter((source) => typeof source !== "string").length,
  }),
  redact: (text, max = MAX_MESSAGE) => sanitize(text, max, machineRedactor()),

  // Records the errors that come from the Peek-a-Foxy files: Firefox's own are not ours to report.
  watch(win, label) {
    win.addEventListener("error", (event) => {
      if (OUR_FILES.test(String(event.filename ?? ""))) {
        Diag.error(`${label}:uncaught`, `${event.message} (${String(event.filename).split("/").pop()}:${event.lineno})`);
      }
    });
    win.addEventListener("unhandledrejection", (event) => {
      const stack = String(event.reason?.stack ?? "");
      if (OUR_FILES.test(stack)) Diag.error(`${label}:rejected`, event.reason);
    });
  },

  // A browser window whose script ran to the end; it leaves the count when the window closes.
  windowStarted(win) {
    started.add(win);
    win.addEventListener("unload", () => {
      forget(win);
      scheduleWrite();
      notify();
    }, { once: true });
    scheduleWrite();
    notify();
  },
  windowGone: (win) => forget(win),
  hasStarted: (win) => started.has(win),

  // Stores the checks of one source (a window, or a name such as "settings") and queues a write.
  setHealth(source, results) {
    healthBySource.set(source, results);
    scheduleWrite();
    notify();
  },

  // The health check, now: this window's elements and the prefs. Returns the combined results.
  check(win) {
    try {
      const began = now();
      // A window that has closed since the check was asked for must not get an entry again: nothing
      // would ever remove it (forget() already ran when the window unloaded).
      if (win && isClosed(win)) skippedClosed += 1;
      else if (win && isNormalWindow(win)) healthBySource.set(win, browserChecks(win));
      healthBySource.set("global", globalChecks());
      spentMs += now() - began;
      scheduleWrite();
      notify();
    } catch (e) {
      Diag.error("diag:check", e);
    }
    return combinedHealth();
  },

  // The same, a moment later and at most once for a burst of changes (a pref edited in about:config).
  checkSoon(win) {
    checkWindow = win;
    if (checkTimer !== null) return;
    checkTimer = lazy.setTimeout(() => {
      checkTimer = null;
      Diag.check(checkWindow);
    }, NOTIFY_DELAY_MS);
  },

  health: () => combinedHealth(),

  // How things stand, for the status line: "notstarted" (this window's script did not finish),
  // "problem" (a health check failed), "errors" (the script recorded errors) or "ok".
  summary(win) {
    const failed = combinedHealth().filter((r) => !r.ok);
    let state = "ok";
    if (win && !started.has(win)) state = "notstarted";
    else if (failed.length) state = "problem";
    else if (events.some((e) => e.level === "error")) state = "errors";
    return { state, version: SCRIPT_VERSION, failed: failed.map(({ name, note, parts }) => ({ name, parts, note: sanitize(note, MAX_NOTE, machineRedactor()) })) };
  },

  status: () => buildStatus(),
  report: () => {
    try {
      return reportMarkdown(buildStatus());
    } catch (e) {
      return `# Peek-a-Foxy diagnostic info\n\nThe report could not be built: ${sanitize(describe(e), MAX_MESSAGE)}\n\n${NOTICE}\n${ISSUES_URL}\n`;
    }
  },
  schedule: scheduleWrite,
  flush: writeNow, // a promise that resolves when the file has been written (or the attempt failed)

  // For tests: forget the events and the counters (not the windows and their checks).
  reset() {
    events.length = 0;
    spentMs = 0;
    writes = 0;
    writesFailed = 0;
    skippedClosed = 0;
  },
};

// --- the easter eggs -----------------------------------------------------------------------------
//
// Three ways to the same ending: three quick clicks on the 🦊 of the title of the settings page
// (JS/autohide-prefs.uc.js), or, anywhere in a browser window while nothing that takes typing has
// the focus (JS/autohide.uc.js), S W S W S A D (which first makes the bars of the window peek in
// rhythm) or typing "peek". The ending darkens the browser window and plays a video in it.
// The settings page cannot show the player itself (its CSP, default-src chrome:, blocks frames), so
// the player is a remote <browser> made in the browser window when a trigger fires: nothing is
// loaded before that, and everything is removed again when the player closes. Only one runs at a
// time, in all windows together.

const HTML_NS = "http://www.w3.org/1999/xhtml";

// The video, and the page it says it is embedded in: YouTube does not play an embed that comes
// without a Referer (Error 153). An object so that a test can point it at a page of its own.
export const Player = {
  url: "https://www.youtube-nocookie.com/embed/6uJf2IT2Zh8?start=59&autoplay=1",
  referrer: "https://github.com/paodelonga/peek-a-foxy",
};
const ReferrerInfo = Components.Constructor("@mozilla.org/referrer-info;1", "nsIReferrerInfo", "init");
// The person asked for the video with their own keys or clicks, but in another document, so
// Firefox's autoplay rule would still make them press play: this tells the video page about it.
const ACTIVATE = "data:,content.document.notifyUserGestureActivation();";

// The key sequences, as KeyboardEvent.code, so that they do not depend on the keyboard layout
// (WASD, not the arrows, which are Firefox's own keys).
export const SEQUENCES = {
  konami: ["KeyS", "KeyW", "KeyS", "KeyW", "KeyS", "KeyA", "KeyD"],
  peek: ["KeyP", "KeyE", "KeyE", "KeyK"],
};
const LONGEST_SEQUENCE = Math.max(...Object.values(SEQUENCES).map((keys) => keys.length));

// The keys typed so far with `code` added: {keys, matched}, where `matched` names the sequence the
// keys now end with (and the keys start over), or is null. A sequence counts only when its keys come
// one right after the other, so any other key in between starts it over.
export function nextKeys(keys, code) {
  const typed = [...keys, code].slice(-LONGEST_SEQUENCE);
  for (const [name, sequence] of Object.entries(SEQUENCES)) {
    const tail = typed.slice(-sequence.length);
    if (tail.length === sequence.length && tail.every((key, i) => key === sequence[i])) return { keys: [], matched: name };
  }
  return { keys: typed, matched: null };
}

// [the bars that peek, for how many milliseconds]: none (so that bars that were showing hide first),
// tabs, navigation bar, both, with a pause between. No bar opens more than about twice a second
// (flashes faster than three a second can harm).
const PEEK_STEPS = [["", 350], ["tabs", 350], ["", 250], ["navbar", 350], ["", 250], ["tabs navbar", 600]];
const BAR_ATTRIBUTES = ["autohide-tabs", "autohide-urlbar"];

const MODIFIER_KEYS = ["Control", "Alt", "Shift", "Meta", "AltGraph", "OS", "CapsLock"];
const NOT_TYPING = new Set(["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image"]);
// `node` is the event's originalTarget: the element that really has the focus, also inside the
// shadow root of a custom element (the search box is an <input> inside moz-input-search).
function takesTyping(node) {
  const element = node?.nodeType === 1 ? node : node?.parentElement;
  if (!element?.closest) return false;
  if (element.isContentEditable) return true;
  const field = element.closest("input, textarea, select");
  return Boolean(field) && !(field.localName === "input" && NOT_TYPING.has(field.type));
}
const typedIn = new WeakMap(); // browser window -> the keys typed so far

// What the page loaded in the player may not do: open windows or tabs, make a frame navigate the top,
// show alert() and the like, download, or launch other applications through their protocols
// (nsSandboxFlags.h: AUXILIARY_NAVIGATION, TOPLEVEL_NAVIGATION, MODALS, DOWNLOADS and
// TOPLEVEL_NAVIGATION_CUSTOM_PROTOCOLS). Navigating itself away is not covered by a flag; see guard().
const PLAYER_SANDBOX = 0x2 | 0x4 | 0x800 | 0x10000 | 0x40000;

const PLAYER_STYLE = `
  #peekafoxy-player { box-sizing: border-box; inset: 0; margin: 0; width: 100%; height: 100%; max-width: none;
    max-height: none; border: none; padding: 16px; background: rgb(0 0 0 / 0.85); color: #fff;
    animation: peekafoxy-player-fade 0.4s ease-out; }
  #peekafoxy-player[open] { display: flex; align-items: center; justify-content: center; }
  #peekafoxy-player::backdrop { background: transparent; }
  #peekafoxy-player .pf-frame { display: flex; flex-direction: column; gap: 8px;
    width: min(100%, calc((100vh - 96px) * 16 / 9)); }
  #peekafoxy-player browser { display: block; width: 100%; aspect-ratio: 16 / 9; background: #000; }
  @keyframes peekafoxy-player-fade { from { opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { #peekafoxy-player { animation: none; } }
  @media (forced-colors: active), (prefers-contrast: more) {
    #peekafoxy-player { background: Canvas; color: CanvasText; }
    #peekafoxy-player browser { outline: 2px solid CanvasText; }
  }
`;

let egg = null; // the one running: {win, timer, dialog, previous, cleanups}

// The address the player may show: anything in the folder of the video's address (".../embed/"),
// so that the video page can change its own query, and nothing else.
const allowedPrefix = () => new URL(".", Player.url).href;
const placeOf = (uri) => {
  try {
    return uri.prePath;
  } catch (e) {
    return `${uri?.scheme}:`; // a URI without a host (data:, about:...)
  }
};

// Undoes everything, last thing first. It runs once, whatever asks first (Escape, a click, the
// window closing, an error). Closing the dialog gives the focus back to what had it before (the
// settings tab, and in it the element that had it); a tab switched to meanwhile is switched back.
function finish(run) {
  if (egg !== run) return;
  egg = null;
  for (const undo of run.cleanups.reverse()) {
    try {
      undo();
    } catch (e) {
      Diag.warn("easter-egg:close", e);
    }
  }
  if (!run.dialog || isClosed(run.win)) return;
  try {
    const tab = run.previous?.isConnected && run.win.gBrowser?.getTabForBrowser?.(run.previous);
    if (tab && run.win.gBrowser.selectedTab !== tab) run.win.gBrowser.selectedTab = tab;
  } catch (e) {
    Diag.info("easter-egg:focus", e);
  }
}

// The bars of `run.win` peek in rhythm: the root gets peekafoxy-peek with the bars that are open in
// each step (chrome/autohide.css treats it as one more way to reveal a hidden bar), and loses it at
// the end or when anything stops the egg. A bar that was showing is hidden for the pattern (its
// attribute is added here and taken away again, and nothing is saved with the window), so that it
// peeks too and is exactly what it was afterwards.
function peekBars(run, then) {
  const root = run.win.document.documentElement;
  const added = BAR_ATTRIBUTES.filter((attr) => !root.hasAttribute(attr));
  const restore = () => {
    for (const attr of added.splice(0)) root.removeAttribute(attr);
    root.removeAttribute("peekafoxy-peek");
  };
  root.setAttribute("peekafoxy-peek", ""); // first, so that the bar buttons know this is not a change of state
  for (const attr of added) root.setAttribute(attr, "");
  run.cleanups.push(() => {
    lazy.clearTimeout(run.timer);
    restore();
  });
  let step = 0;
  const next = () => {
    run.timer = null;
    if (egg !== run || isClosed(run.win)) return;
    if (step === PEEK_STEPS.length) {
      restore();
      then();
      return;
    }
    const [bars, ms] = PEEK_STEPS[step++];
    root.setAttribute("peekafoxy-peek", bars);
    run.timer = lazy.setTimeout(next, ms);
  };
  next();
}

// The player may only show the video. A load of another page in it is cancelled before anything is
// sent (http-on-modify-request), and if the player ends up anywhere else all the same (an address
// that is not http, such as about:blank), it is closed. Both are recorded.
function guard(run, browser) {
  const prefix = allowedPrefix();
  const observer = {
    observe(subject) {
      try {
        const channel = subject.QueryInterface(Ci.nsIHttpChannel);
        const info = channel.loadInfo;
        if (info.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT) return;
        if (BrowsingContext.get(info.browsingContextID)?.browserId !== browser.browserId) return;
        if (channel.URI.spec.startsWith(prefix)) return;
        channel.cancel(Cr.NS_BINDING_ABORTED);
        Diag.warn("easter-egg:blocked", `the video player tried to load ${placeOf(channel.URI)}, which was stopped`);
      } catch (e) {
        Diag.warn("easter-egg:guard", e);
      }
    },
  };
  Services.obs.addObserver(observer, "http-on-modify-request");
  run.cleanups.push(() => Services.obs.removeObserver(observer, "http-on-modify-request"));

  let arrived = false;
  const listener = {
    QueryInterface: ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"]),
    onLocationChange(webProgress, request, location) {
      if (!webProgress?.isTopLevel || egg !== run) return;
      const spec = location?.spec ?? "";
      if (spec.startsWith(prefix)) {
        arrived = true;
        try {
          browser.messageManager.loadFrameScript(ACTIVATE, false);
        } catch (e) {
          Diag.info("easter-egg:autoplay", e); // the video then waits for a click on its play button
        }
      } else if (arrived || spec !== "about:blank") {
        Diag.warn("easter-egg:blocked", `the video player went to ${placeOf(location)}, so it was closed`);
        lazy.setTimeout(() => finish(run), 0); // not while the browser is still telling its listeners
      }
    },
    onStateChange() {},
    onProgressChange() {},
    onStatusChange() {},
    onSecurityChange() {},
    onContentBlockingEvent() {},
  };
  browser.addProgressListener(listener, Ci.nsIWebProgress.NOTIFY_LOCATION);
  run.cleanups.push(() => browser.removeProgressListener(listener));
}

function openPlayer(run, locale) {
  const { win } = run;
  const doc = win.document;
  try {
    const text = textFor(locale);
    const element = (tag, props = {}) => {
      const node = doc.createElementNS(HTML_NS, tag);
      for (const [key, value] of Object.entries(props)) node.setAttribute(key, value);
      return node;
    };
    // A modal <dialog> keeps the rest of the window inert (no focus, no clicks) while it is open, and
    // the browser window already shows its own prompts that way.
    const dialog = element("dialog", { id: "peekafoxy-player", role: "dialog", "aria-modal": "true", "aria-label": text.playerLabel });
    const style = element("style");
    style.textContent = PLAYER_STYLE;
    const frame = element("div", { class: "pf-frame" });
    dialog.append(style, frame);
    run.previous = doc.activeElement;
    run.dialog = dialog;
    doc.body.append(dialog);
    run.cleanups.push(() => {
      if (dialog.open) dialog.close();
      dialog.remove();
    });

    const browser = doc.createXULElement("browser");
    for (const [key, value] of Object.entries({
      type: "content", remote: "true", maychangeremoteness: "true", disableglobalhistory: "true", nodefaultsrc: "true",
    })) browser.setAttribute(key, value);
    frame.append(browser);
    run.cleanups.push(() => {
      browser.destroy?.();
      browser.remove();
    });
    browser.browsingContext.sandboxFlags = PLAYER_SANDBOX;
    guard(run, browser);

    // Escape (also while the video has the keyboard, so in the capture phase of the window, unless
    // a page is full screen, where Escape only leaves full screen) and a click on the dark area
    // around the video close it.
    const onKey = (event) => {
      if (event.key !== "Escape" || doc.fullscreenElement) return;
      event.preventDefault();
      finish(run);
    };
    const onCancel = (event) => {
      event.preventDefault();
      finish(run);
    };
    const onClick = (event) => {
      if (event.target === dialog) finish(run);
    };
    win.addEventListener("keydown", onKey, true);
    dialog.addEventListener("cancel", onCancel);
    dialog.addEventListener("click", onClick);
    run.cleanups.push(() => {
      win.removeEventListener("keydown", onKey, true);
      dialog.removeEventListener("cancel", onCancel);
      dialog.removeEventListener("click", onClick);
    });

    dialog.showModal();
    browser.focus();
    browser.loadURI(Services.io.newURI(Player.url), {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
      referrerInfo: new ReferrerInfo(Ci.nsIReferrerInfo.UNSAFE_URL, true, Services.io.newURI(Player.referrer)),
    });
  } catch (e) {
    Diag.warn("easter-egg:open", `the video player could not be opened: ${describe(e)}`, e);
    finish(run);
  }
}

// A hint on Firefox's keyboard shortcuts page (about:keyboard), under its "Restore defaults" button, in
// the style of a "keyboard combos" tip: the keys of the konami sequence, for whoever looks there. The
// page lives in a content process, where the scripts of this project do not run, so a frame script adds
// the hint once the page has loaded. It does nothing in a Firefox whose page looks different, and
// puts the hint in only once.
function keyboardHintInPage(text) {
  const { setTimeout } = ChromeUtils.importESModule("resource://gre/modules/Timer.sys.mjs");
  const doc = content.document;
  let tries = 0;
  const put = () => {
    try {
      if (content.location.href.split("#")[0] !== "about:keyboard") return;
      if (doc.getElementById("peekafoxy-hint")) return;
      const actions = doc.querySelector(".customkeys-sidebar-actions");
      if (!actions) {
        if (++tries < 50) setTimeout(put, 100);
        return;
      }
      const html = (name, css, words) => {
        const node = doc.createElement(name);
        if (css) node.style.cssText = css;
        if (words) node.textContent = words;
        return node;
      };
      const box = html("div", "display: flex; flex-direction: column; gap: 6px; margin-block-start: 16px;");
      box.id = "peekafoxy-hint";
      box.append(html("strong", "", text.title));
      const keys = html("div", "display: flex; flex-wrap: wrap; gap: 3px;");
      for (const key of ["S", "W", "S", "W", "S", "A", "D"]) {
        keys.append(html("kbd",
          "min-width: 1.4em; padding: 2px 4px; text-align: center; font: 600 0.8em monospace; " +
          "border: 1px solid var(--border-color, GrayText); border-bottom-width: 3px; border-radius: 6px; " +
          "background: var(--background-color-box, Canvas); color: var(--text-color, CanvasText);", key));
      }
      box.append(keys);
      actions.append(box);
    } catch (e) {
      // The page is not the one this was written for: leave it alone.
    }
  };
  put();
}

// Called when a tab has loaded: puts the hint on the keyboard shortcuts page.
export function hintOnKeyboardPage(browser, locale = Services.locale.appLocaleAsBCP47) {
  try {
    if (browser.currentURI?.specIgnoringRef !== "about:keyboard") return;
    const text = textFor(locale).keyboardHint;
    const code = `(${keyboardHintInPage.toString()})(${JSON.stringify(text)});`;
    browser.messageManager.loadFrameScript(`data:,${encodeURIComponent(code)}`, false);
  } catch (e) {
    Diag.info("easter-egg:keyboard-hint", e); // only the hint is lost
  }
}

export const EasterEgg = {
  // Whether one is running (the bars are peeking or the player is open): triggers wait for it to end.
  busy: () => egg !== null,

  // A keydown of browser window `win` (JS/autohide.uc.js): the keys count while nothing that takes
  // typing has the focus, in the window itself or in the page it shows (the IME is off then), and
  // no Ctrl, Alt or Meta is held. Only the last few keys are kept, and only in memory.
  typed(win, event) {
    if (event.repeat || MODIFIER_KEYS.includes(event.key)) return; // a held key counts once
    let counts = false;
    try {
      counts = !egg && !event.ctrlKey && !event.altKey && !event.metaKey && !event.getModifierState?.("AltGraph") &&
        win.windowUtils.IMEStatus === Ci.nsIDOMWindowUtils.IME_STATUS_DISABLED &&
        !takesTyping(event.originalTarget ?? event.target);
    } catch (e) {
      Diag.info("easter-egg:typed", e);
    }
    if (!counts) {
      typedIn.delete(win);
      return;
    }
    const { keys, matched } = nextKeys(typedIn.get(win) ?? [], event.code);
    typedIn.set(win, keys);
    if (matched) EasterEgg.play(win, { peek: matched === "konami" });
  },

  // The ending in browser window `win`, after the bars peek when `peek` is true (not with reduced
  // motion).
  play(win, { peek = false, locale = Services.locale.appLocaleAsBCP47 } = {}) {
    if (egg || !win || isClosed(win)) return;
    const run = { win, timer: null, dialog: null, previous: null, cleanups: [] };
    egg = run;
    try {
      const onUnload = () => finish(run);
      win.addEventListener("unload", onUnload);
      run.cleanups.push(() => win.removeEventListener("unload", onUnload));
      const reduced = win.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (peek && !reduced) peekBars(run, () => openPlayer(run, locale));
      else openPlayer(run, locale);
    } catch (e) {
      Diag.warn("easter-egg:play", e);
      finish(run);
    }
  },

  // Closes whatever is running, as Escape does.
  close() {
    if (egg) finish(egg);
  },

  // Before the state of a bar of `win` changes: bars that are peeking there stop, so that the
  // change starts from the state the bars really have.
  settle(win) {
    if (egg && egg.win === win && !egg.dialog) finish(egg);
  },
};
