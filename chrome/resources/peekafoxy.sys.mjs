// Shared by the two Peek-a-Foxy scripts (JS/autohide.uc.js in every browser window and
// JS/autohide-prefs.uc.js in about:preferences): the prefs, their limits, the shortcut format and
// every text the user can read. Loaded with
//   ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs")
// (fx-autoconfig maps chrome://userchrome/content/ to the profile's chrome/resources/).

// One entry per pref. Everything is registered on Firefox's default branch (see registerDefaults),
// so about:config lists the prefs with the right type and nothing is written until a value changes.
//   type    "bool" | "int" | "string"
//   min/max limits of an int; a value outside them is clamped
export const PREFS = {
  tabsAutohide: { name: "peekafoxy.tabs.autohide", type: "bool", default: false },
  urlbarAutohide: { name: "peekafoxy.urlbar.autohide", type: "bool", default: false },
  stripPx: { name: "peekafoxy.strip.px", type: "int", default: 8, min: 1, max: 40 },
  showMs: { name: "peekafoxy.show.ms", type: "int", default: 120, min: 0, max: 2000 },
  hideDelayMs: { name: "peekafoxy.hide.delay.ms", type: "int", default: 300, min: 0, max: 5000 },
  flashMs: { name: "peekafoxy.tabs.flash.ms", type: "int", default: 1500, min: 0, max: 10000 },
  tabsShortcut: { name: "peekafoxy.tabs.shortcut", type: "string", default: "Ctrl+Alt+T" },
  urlbarShortcut: { name: "peekafoxy.urlbar.shortcut", type: "string", default: "Ctrl+Alt+U" },
  welcomed: { name: "peekafoxy.welcomed", type: "bool", default: false },
};
export const PREF_BRANCH = "peekafoxy.";

// --- prefs -------------------------------------------------------------------------------------

export function registerDefaults(log = console) {
  const branch = Services.prefs.getDefaultBranch("");
  for (const pref of Object.values(PREFS)) {
    try {
      if (pref.type === "bool") branch.setBoolPref(pref.name, pref.default);
      else if (pref.type === "int") branch.setIntPref(pref.name, pref.default);
      else branch.setStringPref(pref.name, pref.default);
    } catch (e) {
      log.warn(`[peekafoxy] could not register ${pref.name}:`, e);
    }
  }
}

export const clamp = (pref, value) => Math.min(pref.max, Math.max(pref.min, value));

// Reads never throw: a pref of another type (say, a number in user.js for a boolean) gives the default.
export function read(pref) {
  try {
    if (pref.type === "bool") return Services.prefs.getBoolPref(pref.name, pref.default);
    if (pref.type === "int") return clamp(pref, Services.prefs.getIntPref(pref.name, pref.default));
    return Services.prefs.getStringPref(pref.name, pref.default);
  } catch (e) {
    console.warn(`[peekafoxy] ${pref.name} has the wrong type, using ${pref.default}:`, e);
    return pref.default;
  }
}

export const hasUserValue = (pref) => {
  try {
    return Services.prefs.prefHasUserValue(pref.name);
  } catch (e) {
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
export function shortcutFromEvent(event) {
  const key = keyOf(event.code);
  if (!key) return null;
  const mods = new Set(ORDER.filter((m) => event[`${m.toLowerCase()}Key`]));
  return format(mods, key);
}

export const matches = (binding, event) =>
  event.code === binding.code && event.ctrlKey === binding.ctrl && event.altKey === binding.alt &&
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

// --- texts -------------------------------------------------------------------------------------
//
// In the language of Firefox's interface: Portuguese (pt, pt-BR, pt-PT...) gets the Brazilian
// Portuguese strings, everything else English. To add a language, add an entry keyed by its language
// code (the part before the "-" or "_"). "{key}", "{min}" and "{max}" are replaced where they appear.

export const STRINGS = {
  en: {
    greeting: "Instaalleeeeed PEEK A BOO!!! >.<",
    greetingButton: "Peek-a-boo!",
    tabs: { label: "Tabs autohide", tooltip: "Toggle tab bar autohide for this window ({key})" },
    urlbar: { label: "Urlbar autohide", tooltip: "Toggle navigation bar autohide for this window ({key})" },
    settings: {
      category: "Peek-a-Foxy",
      description: "Autohide for the tab bar and the navigation bar. Changes apply to every open window at once.",
      startGroup: "New windows",
      startTabs: "Hide the tab bar automatically in new windows",
      startUrlbar: "Hide the navigation bar automatically in new windows",
      startNote: "Windows that are already open keep their own state: use the shortcut or the toolbar button there.",
      timingGroup: "Size and timing",
      stripPx: "Hover strip height (pixels)",
      showMs: "Opening animation (milliseconds)",
      hideDelayMs: "Delay before a bar closes (milliseconds)",
      flashMs: "How long the tab bar stays open after a tab switch or a new tab (milliseconds)",
      shortcutsGroup: "Shortcuts",
      tabsShortcut: "Toggle the tab bar",
      urlbarShortcut: "Toggle the navigation bar",
      shortcutPrompt: "Click here, then press the new shortcut",
      shortcutHint: "Use Ctrl, Alt or Meta with a letter, a digit or F1 to F12. Some desktops keep a few shortcuts for themselves (Ctrl+Alt+T opens a terminal on GNOME, Ubuntu and Linux Mint): if one does nothing, pick another.",
      reset: "Reset",
      greetingGroup: "Greeting",
      greetingShow: "Show the greeting again",
      greetingDone: "The greeting will show in the next window you open.",
      problems: {
        format: "That is not a valid shortcut.",
        key: "Use a letter, a digit or F1 to F12.",
        modifier: "Include Ctrl, Alt or Meta.",
        duplicate: "The other bar already uses this shortcut.",
        unsupported: "That key cannot be used.",
        range: "Enter a number between {min} and {max}.",
      },
    },
  },
  pt: {
    greeting: "Instaalaadoooo PEEK A BOO!!! >.<",
    greetingButton: "Peek-a-boo!",
    tabs: { label: "Ocultar abas automaticamente",
            tooltip: "Alterna o ocultamento automático da barra de abas nesta janela ({key})" },
    urlbar: { label: "Ocultar barra de endereço automaticamente",
              tooltip: "Alterna o ocultamento automático da barra de navegação nesta janela ({key})" },
    settings: {
      category: "Peek-a-Foxy",
      description: "Ocultamento automático da barra de abas e da barra de navegação. As mudanças valem para todas as janelas abertas, na hora.",
      startGroup: "Novas janelas",
      startTabs: "Ocultar a barra de abas automaticamente em novas janelas",
      startUrlbar: "Ocultar a barra de navegação automaticamente em novas janelas",
      startNote: "As janelas que já estão abertas mantêm o próprio estado: use o atalho ou o botão da barra de ferramentas nelas.",
      timingGroup: "Tamanho e tempos",
      stripPx: "Altura da faixa de hover (pixels)",
      showMs: "Animação de abertura (milissegundos)",
      hideDelayMs: "Atraso antes de uma barra se fechar (milissegundos)",
      flashMs: "Quanto tempo a barra de abas fica aberta ao trocar de aba ou abrir uma nova (milissegundos)",
      shortcutsGroup: "Atalhos",
      tabsShortcut: "Alternar a barra de abas",
      urlbarShortcut: "Alternar a barra de navegação",
      shortcutPrompt: "Clique aqui e pressione o novo atalho",
      shortcutHint: "Use Ctrl, Alt ou Meta com uma letra, um dígito ou F1 a F12. Alguns desktops reservam atalhos para si (o Ctrl+Alt+T abre um terminal no GNOME, no Ubuntu e no Linux Mint): se um não fizer nada, escolha outro.",
      reset: "Restaurar",
      greetingGroup: "Saudação",
      greetingShow: "Mostrar a saudação de novo",
      greetingDone: "A saudação aparecerá na próxima janela que você abrir.",
      problems: {
        format: "Esse atalho não é válido.",
        key: "Use uma letra, um dígito ou F1 a F12.",
        modifier: "Inclua Ctrl, Alt ou Meta.",
        duplicate: "A outra barra já usa esse atalho.",
        unsupported: "Essa tecla não pode ser usada.",
        range: "Digite um número entre {min} e {max}.",
      },
    },
  },
};

export const textFor = (locale) =>
  STRINGS[String(locale).split(/[-_]/)[0].toLowerCase()] ?? STRINGS.en;
