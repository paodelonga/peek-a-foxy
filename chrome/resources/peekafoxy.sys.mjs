// Shared by the two Peek-a-Foxy scripts (JS/autohide.uc.js in every browser window and
// JS/autohide-prefs.uc.js in about:preferences): the prefs, their limits, the shortcut format and
// every text the user can read. Loaded with
//   ChromeUtils.importESModule("chrome://userchrome/content/peekafoxy.sys.mjs")
// (fx-autoconfig maps chrome://userchrome/content/ to the profile's chrome/resources/).
// It also holds Diag, the diagnostics both scripts use: a ring buffer of recent events, the health
// check and the status file that `peek-a-foxy doctor` reads (see the section at the end of the file).

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  AppConstants: "resource://gre/modules/AppConstants.sys.mjs",
  setTimeout: "resource://gre/modules/Timer.sys.mjs",
  clearTimeout: "resource://gre/modules/Timer.sys.mjs",
});

// The version of the Peek-a-Foxy files (a test keeps it equal to the package version).
export const SCRIPT_VERSION = "0.2.0";

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
  revealSwitch: { name: "peekafoxy.tabs.reveal.switch", type: "bool", default: true },
  revealNew: { name: "peekafoxy.tabs.reveal.new", type: "bool", default: true },
  revealLink: { name: "peekafoxy.tabs.reveal.link", type: "bool", default: true },
  tabsShortcut: { name: "peekafoxy.tabs.shortcut", type: "string", default: "Ctrl+Alt+T" },
  urlbarShortcut: { name: "peekafoxy.urlbar.shortcut", type: "string", default: "Ctrl+Alt+U" },
  welcomed: { name: "peekafoxy.welcomed", type: "bool", default: false },
};
export const PREF_BRANCH = "peekafoxy.";

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
    return Services.prefs.getStringPref(pref.name, pref.default);
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
      flashMs: "How long the tab bar stays open after one of these (milliseconds)",
      revealGroup: "Reveal the tab bar when",
      revealSwitch: "you switch to another tab",
      revealNew: "you open a new tab (Ctrl+T, the + button)",
      revealLink: "a tab opens straight to an address (a link you click, a bookmark, a page opening a window)",
      revealNote: "Hovering the tab bar's strip always opens it, whatever is chosen here.",
      shortcutsGroup: "Shortcuts",
      tabsShortcut: "Toggle the tab bar",
      urlbarShortcut: "Toggle the navigation bar",
      shortcutPrompt: "Click here, then press the new shortcut",
      shortcutHint: "Use Ctrl, Alt or Meta with a letter, a digit or F1 to F12. Your system keeps a few shortcuts for itself: if one does nothing, pick another.",
      shortcutHintLinux: "For example, Ctrl+Alt+T opens a terminal on GNOME, Ubuntu and Linux Mint.",
      shortcutHintWindows: "On layouts with an AltGr key (Portuguese ABNT2, German, Czech...), AltGr counts as Ctrl+Alt and types characters, so AltGr presses are not accepted: press the left Ctrl and Alt, or use Ctrl+Shift.",
      reset: "Reset",
      greetingGroup: "Greeting",
      greetingShow: "Show the greeting again",
      greetingDone: "The greeting will show in the next window you open.",
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
        prefsMore: "{n} more setting(s) have the same kind of problem.",
        rangeBad: "The setting {name} is {value}, outside the allowed {min} to {max}, so the script uses {used} instead.",
        rangeMore: "{n} more setting(s) are out of range too.",
        shortcutBad: "The shortcut setting {name} says \"{text}\", which is not a valid shortcut, so the default {default} is used.",
        shortcutMore: "The other shortcut has the same problem.",
        shortcutsSame: "Both bars use the shortcut {text}, so only one of them reacts to it. Choose a different shortcut for one of them in the Peek-a-Foxy settings.",
        settingsPage: "Firefox's settings page is not what the script expects ({what}), so the Peek-a-Foxy category was not added. The settings can still be changed in about:config: search for peekafoxy.",
      },
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
      flashMs: "Quanto tempo a barra de abas fica aberta depois de um desses eventos (milissegundos)",
      revealGroup: "Revelar a barra de abas quando",
      revealSwitch: "você troca para outra aba",
      revealNew: "você abre uma aba nova (Ctrl+T, o botão +)",
      revealLink: "uma aba abre direto num endereço (um link em que você clica, um favorito, uma página que abre uma janela)",
      revealNote: "Passar o mouse na faixa da barra de abas sempre a abre, seja qual for a escolha aqui.",
      shortcutsGroup: "Atalhos",
      tabsShortcut: "Alternar a barra de abas",
      urlbarShortcut: "Alternar a barra de navegação",
      shortcutPrompt: "Clique aqui e pressione o novo atalho",
      shortcutHint: "Use Ctrl, Alt ou Meta com uma letra, um dígito ou F1 a F12. O seu sistema reserva alguns atalhos para si: se um não fizer nada, escolha outro.",
      shortcutHintLinux: "Por exemplo, o Ctrl+Alt+T abre um terminal no GNOME, no Ubuntu e no Linux Mint.",
      shortcutHintWindows: "Em layouts com a tecla AltGr (ABNT2, alemão, tcheco...), o AltGr vale como Ctrl+Alt e digita caracteres, então combinações com AltGr não são aceitas: use o Ctrl e o Alt da esquerda, ou Ctrl+Shift.",
      reset: "Restaurar",
      greetingGroup: "Saudação",
      greetingShow: "Mostrar a saudação de novo",
      greetingDone: "A saudação aparecerá na próxima janela que você abrir.",
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
        urlbar: "O elemento #urlbar (a barra de endereço) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então a barra de navegação pode se fechar enquanto a lista suspensa da barra de endereço está aberta.",
        "bookmarks-toolbar": "O elemento #PersonalToolbar (a barra de favoritos) não foi encontrado. O Firefox pode tê-lo renomeado ou removido, então ela não vai se ocultar e se mostrar junto com a barra de navegação.",
        tabsHolder: "O elemento #tabbrowser-tabs (as abas em si) não foi encontrado. O Firefox pode tê-lo renomeado, então a barra de abas pode não se recolher corretamente.",
        tabsHolderCustom: "A janela desenha a própria barra de título (customtitlebar), mas #TabsToolbar .toolbar-items, a parte da barra de abas que contém as abas, não foi encontrada. O Firefox pode ter movido as abas, então ocultar a barra de abas pode ocultar os botões da janela ou não fazer nada.",
        customtitlebar: "Os botões da janela estão dentro da barra de abas, mas a janela não tem o atributo customtitlebar que o stylesheet procura. O Firefox pode tê-lo renomeado, então ocultar a barra de abas pode ocultar também os botões da janela.",
        browserApis: "Estas partes do Firefox ou do loader que o script usa estão ausentes: {names}. O Firefox ou o fx-autoconfig pode tê-las alterado, então alguns recursos do script não vão funcionar.",
        toolbarButtons: "O botão da barra de ferramentas {ids} não está registrado no Firefox, então ele não aparece em Personalizar barra de ferramentas. O Firefox pode ter mudado a forma de criar botões da barra de ferramentas, ou o script parou antes de criá-los.",
        prefMissing: "A configuração {name} não está registrada, então ela não aparece no about:config e o script usa o valor padrão embutido.",
        prefType: "A configuração {name} contém {actual} em vez de {expected}, provavelmente por uma linha do user.js ou do prefs.js com o tipo de valor errado, então o script a ignora e usa o valor padrão ({default}). Restaure-a no about:config.",
        prefsMore: "Mais {n} configuração(ões) têm o mesmo tipo de problema.",
        rangeBad: "A configuração {name} está em {value}, fora do intervalo permitido de {min} a {max}, então o script usa {used} no lugar.",
        rangeMore: "Mais {n} configuração(ões) também estão fora do intervalo.",
        shortcutBad: "A configuração de atalho {name} diz \"{text}\", que não é um atalho válido, então o atalho padrão {default} é usado.",
        shortcutMore: "O outro atalho tem o mesmo problema.",
        shortcutsSame: "As duas barras usam o atalho {text}, então só uma delas reage a ele. Escolha um atalho diferente para uma delas nas configurações do Peek-a-Foxy.",
        settingsPage: "A página de configurações do Firefox não é a que o script espera ({what}), então a categoria Peek-a-Foxy não foi adicionada. As configurações ainda podem ser alteradas no about:config: procure por peekafoxy.",
      },
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

// The hint under the shortcuts: the same everywhere, plus what is true on this operating system
// (Services.appinfo.OS is "Linux", "WINNT" or "Darwin").
export function shortcutHint(settings, os = Services.appinfo.OS) {
  const extra = { Linux: settings.shortcutHintLinux, WINNT: settings.shortcutHintWindows }[os];
  return extra ? `${settings.shortcutHint} ${extra}` : settings.shortcutHint;
}

export const textFor = (locale) =>
  STRINGS[String(locale).split(/[-_]/)[0].toLowerCase()] ?? STRINGS.en;

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
  const paths = (list, replacement, minimum) => {
    const spelled = new Set();
    for (const path of list) {
      const trimmed = String(path || "").replace(/[\\/]+$/, "");
      const bare = trimmed.replace(/^[\\/]+/, "");
      if (bare.length >= minimum && !/^[A-Za-z]:$/.test(bare)) spellings(trimmed).forEach((p) => spelled.add(p));
    }
    if (spelled.size) {
      const pattern = [...spelled].sort((a, b) => b.length - a.length).map(escapeRegExp).join("|");
      rules.push([new RegExp(pattern, flags), replacement]);
    }
  };
  paths([profileDir], "<profile>", 2);
  paths(homes, "~", 2);
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

const liveWindows = () => {
  for (const win of [...started]) {
    let closed = true;
    try {
      closed = win.closed;
    } catch (e) {
      // A dead window reference counts as closed.
    }
    if (closed) forget(win);
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
  stats: () => ({ events: events.length, writes, writesFailed, syncMs: spentMs }),
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
      if (win && isNormalWindow(win)) healthBySource.set(win, browserChecks(win));
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
  },
};
