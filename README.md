<div align="center">

# Peek-a-Foxy 🦊

**Peek-a-boo for Foxys: autohide the tab bar and navigation bar per window. They hide, they peek, then BOOO! out when you hover.**

[![CI](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml/badge.svg)](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Firefox 121+](https://img.shields.io/badge/Firefox-121%2B-FF7139?logo=firefoxbrowser&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform: Linux and Windows](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)

English · [Português (Brasil)](README.pt-BR.md)

</div>

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [Settings](#settings)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Windows notes](#windows-notes)
- [Uninstall](#uninstall)
- [Roadmap](#roadmap)
- [About the name](#about-the-name)
- [Contributing](#contributing)
- [License and credits](#license-and-credits)

## Features

- **Tab bar autohide.** The bar collapses to a thin hover strip. It slides open when the cursor is on the strip (hovering the URL bar does not reveal it), briefly on every tab switch (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) and when a new tab opens (links, background tabs), and stays open while a tab is dragged or its context menu is open.
- **Navigation bar autohide** (urlbar, buttons, extensions). It opens from its own hover strip, whenever the URL bar gets focus (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`), and while its dropdown or a toolbar popup is open. The bookmarks bar hides and shows together with it, and the bars try to stay open while something is dragged out of them (for bookmarks this is not reliable yet, see the [roadmap](#roadmap)).
- **Stays out of the way.** Customize Toolbar and full screen are left to Firefox: the bars are fully visible there.
- **Opt-in and per window.** Both are off until you turn them on, and each window keeps its own state, saved with the session.
- **Settings inside Firefox.** A **Peek a Foxy 🦊** section in the settings page changes the defaults, the strip size, the timings and the shortcuts for every open window at once ([details](#settings)).
- **A hello when it loads.** The first time the script runs in a profile, Firefox shows a one-time notification ("Instaalleeeeed PEEK A BOO!!! >.<"), so you know it is working. It follows Firefox's language: English, or Brazilian Portuguese when Firefox is in Portuguese. Its button opens the song the name is a nod to ([see below](#about-the-name)).
- **Non-invasive installer.** Your own `userChrome.css` is left alone, an existing autoconfig setup is never overwritten, and everything can be removed with one command.

## Requirements

- Firefox 121 or newer (the CSS uses `:has()`).
- Linux or Windows 10/11. Snap, Flatpak and Microsoft Store (MSIX) builds of Firefox are not supported (their install directory is read-only).
- Python 3.10 or newer and `git`.
- `sudo` (Linux) or an administrator prompt (Windows, UAC), only if the Firefox install directory isn't writable by you. Only the copy of two files is elevated; everything else runs as you.
- On Windows, [Git for Windows](https://git-scm.com/download/win) (`winget install Git.Git`), which the installer uses to fetch the loader.

**Windows** is tested in CI on a real Windows runner (unit tests, the whole headless-Firefox suite, the real loader download), but not yet by hand on a desktop: see [Windows notes](#windows-notes). The code contains macOS paths that have never been run on a Mac, so treat macOS as unsupported for now.

Developed and used on Firefox Developer Edition.

## Install

```bash
pipx install git+https://github.com/paodelonga/peek-a-foxy.git   # or: uv tool install git+https://...
peek-a-foxy install
```

From a clone, use `pipx install .` instead. Then close **all** Firefox windows and start it again. Nothing changes visibly yet: both autohides start off. Turn one on with its [shortcut or button](#usage).

`install` shows what it is about to do and asks before changing anything. The download comes first, so a network failure leaves your profile untouched:

```text
$ peek-a-foxy install
Install into ~/.mozilla/firefox/abcd1234.default-release
┌───┬────────────────────────────────────────────────────────────────┐
│ 1 │ Fetch fx-autoconfig (dfdab5684f, verified)                     │
│ 2 │ Copy autohide.css, autohide.uc.js, autohide-prefs.uc.js and    │
│   │ peekafoxy.sys.mjs into …/chrome                                │
│ 3 │ Add the @import line to …/chrome/userChrome.css                │
│ 4 │ Enable userChrome.css loading and the settings page in         │
│   │ …/user.js                                                      │
│ 5 │ Copy fx-autoconfig's utils into …/chrome/utils                 │
│ 6 │ Install the loader into /usr/lib/firefox (uses sudo if needed) │
└───┴────────────────────────────────────────────────────────────────┘
Apply these changes? [Y/n]:
```

With several profiles or several Firefox installations (release and developer edition, for example) it asks which one to use. It never guesses: with `--yes`, an ambiguous choice is an error and you pass `--profile` / `--firefox-dir`.

Without a terminal (a pipe, cron, CI) there is nobody to confirm, so `install` and `uninstall` refuse to change anything unless you pass `--yes`. `--dry-run` always works.

```text
peek-a-foxy install [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--dry-run] [--yes]
peek-a-foxy uninstall [--profile DIR] [--dry-run] [--yes]

  --profile DIR       profile to use instead of choosing from profiles.ini
  --firefox-dir DIR   Firefox install directory for the loader (default: auto-detected)
  --skip-loader       only install the profile files; leave the Firefox install directory alone
  --dry-run           show the plan without changing anything
  --yes, -y           don't ask anything: apply without confirming, no profile or Firefox picker
                      (an unclear choice is an error instead)
```

### What gets installed

In your profile (`~/.mozilla/firefox/<profile>/`):

```text
chrome/
├── autohide.css            ← this project
├── JS/autohide.uc.js       ← this project (the autohide itself)
├── JS/autohide-prefs.uc.js ← this project (the settings page)
├── resources/peekafoxy.sys.mjs ← this project (shared by both scripts)
├── utils/                  ← fx-autoconfig (the per-profile half of the loader)
└── userChrome.css          ← yours; one line is added at the top, the rest is untouched
user.js                     ← two prefs added (below)
```

One line at the top of your `userChrome.css`:

```css
@import url("autohide.css");
```

Two lines in `user.js`: the pref Firefox needs in order to load `userChrome.css`, and the one fx-autoconfig needs to run the settings page's script inside `about:preferences` (by default it only runs scripts in the browser window):

```js
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("userChromeJS.persistent_domcontent_callback", true);
```

The autohide prefs are deliberately *not* written there: Firefox re-applies `user.js` on every start, which would undo any change you make in `about:config`. Instead, the script registers them (with their defaults and right types) every time it loads, so they are listed in `about:config` and nothing is written to disk until you change a value.

In Firefox's install directory (for example `/usr/lib/firefox/`), the [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) loader, fetched at a pinned and verified commit (only that commit, without its history):

```text
config.js                       ← loads the profile's chrome/utils
defaults/pref/config-prefs.js   ← tells Firefox to use config.js
```

```js
// defaults/pref/config-prefs.js
pref("general.config.obscure_value", 0);
pref("general.config.filename", "config.js");
pref("general.config.sandbox_enabled", false);
```

If a *different* `config.js` is already there (another autoconfig setup), it is **not** overwritten: the installer warns and skips the loader.

A Firefox update can remove the loader from its install directory; run `peek-a-foxy install` again if the buttons and shortcuts stop working.

## Usage

| | Tab bar | Navigation bar |
| --- | --- | --- |
| Toggle for the current window | `Ctrl+Alt+T` or toolbar button | `Ctrl+Alt+U` or toolbar button |
| Reveal temporarily | hover the top strip, switch or open a tab | hover its strip, focus the URL bar |

The buttons are in *Customize Toolbar* as **Auto-hide the tab bar** and **Auto-hide the navigation bar** (in a Portuguese Firefox: **Ocultar a barra de abas automaticamente** and **Ocultar a barra de navegação automaticamente**). The urlbar button lives in the bar it hides, so reveal the bar with its hover strip to click it; the shortcut works at any time.

**`Ctrl+Alt+T` does not work on GNOME, Ubuntu and Linux Mint.** There it opens a terminal: the desktop takes the shortcut before Firefox sees it. Use the toolbar button, or give the shortcut up on that desktop (`Ctrl+Alt+U` is not affected). You can change it in Firefox's settings (see [Settings](#settings)).

### Command line

`-h` works like `--help`, on every command. Shell completion (bash, zsh, fish) completes commands, options, and the profiles from `profiles.ini` for `--profile`:

```bash
peek-a-foxy install -h
peek-a-foxy --install-completion      # then restart your shell
```

## Settings

Firefox's own settings page has a **Peek a Foxy 🦊** section (`about:preferences#peekafoxy`, or *Settings* in the menu). Everything below is applied to every open window at once, with no restart:

- whether **new windows** start with the tab bar and the navigation bar hidden (windows that are already open keep their own state);
- **what opens the tab bar for a moment**, each on its own switch: switching to another tab, opening a new tab (`Ctrl+T`, the `+` button), and a tab that opens straight to an address (a link you click, a bookmark, a page opening a window); plus **how long it stays open** afterwards. Hovering its strip always opens it. Firefox does not say how a tab was opened, so "straight to an address" means any tab that is going to load something other than the new-tab page or your home page;
- the **hover strip height**, the **opening animation** and the **delay before a bar closes**;
- the **shortcuts** that toggle each bar: click the field and press the new one (a letter, a digit or F1 to F12, with Ctrl, Alt or Meta; it is checked, and the two bars cannot share one). Each setting has a **Reset** button;
- a button to **show the greeting again**.

The page is added by a second script, `autohide-prefs.uc.js`, which needs Firefox to run scripts in `about:preferences` (the installer sets the `userChromeJS.persistent_domcontent_callback` pref for that, so run `peek-a-foxy install` again after updating, then restart Firefox). If a Firefox update changes the settings page in a way the script does not expect, it adds nothing and says why in the Browser Console; the prefs below still work in `about:config`.

Every setting is a real pref, listed in `about:config` with its type, and nothing is written to disk until you change a value:

| Pref | Default | Meaning |
| --- | --- | --- |
| `peekafoxy.tabs.autohide` | `false` | Start new windows with the tab bar hidden. |
| `peekafoxy.urlbar.autohide` | `false` | Start new windows with the navigation bar hidden. |
| `peekafoxy.strip.px` | `8` | Hover strip height, in pixels (1 to 40). |
| `peekafoxy.show.ms` | `120` | Opening animation, in milliseconds (0 to 2000). |
| `peekafoxy.hide.delay.ms` | `300` | Wait before a bar closes, in milliseconds (0 to 5000). |
| `peekafoxy.tabs.reveal.switch` | `true` | Open the tab bar for a moment when you switch to another tab. |
| `peekafoxy.tabs.reveal.new` | `true` | Same, when you open a new tab (the new-tab page or your home page). |
| `peekafoxy.tabs.reveal.link` | `true` | Same, when a tab opens straight to any other address (a link, a bookmark, `window.open`...). |
| `peekafoxy.tabs.flash.ms` | `1500` | How long the tab bar stays open after one of those (0 to 10000). |
| `peekafoxy.tabs.shortcut` | `Ctrl+Alt+T` | Shortcut that toggles the tab bar in the current window. |
| `peekafoxy.urlbar.shortcut` | `Ctrl+Alt+U` | Shortcut that toggles the navigation bar. |
| `peekafoxy.welcomed` | `false` | Set to `true` after the one-time greeting. Set it back to `false` to see it again. |

A number outside its range is clamped, and a shortcut that is not valid falls back to the default. To pin a value in a file instead (it is then re-applied on every start), put the line in `user.js` in your profile folder (`~/.mozilla/firefox/<profile>/user.js`):

```js
// <profile>/user.js
user_pref("peekafoxy.tabs.autohide", true);
user_pref("peekafoxy.urlbar.autohide", true);
```

These are the defaults in the stylesheet. The strip height and the two timings can also be set in Firefox's settings, and a value set there wins; the bar heights are only here. To edit the stylesheet, change the installed copy in your profile (or the repository copy and install again):

```css
/* <profile>/chrome/autohide.css */
:root {
  --autohide-strip: 8px;                  /* hover strip height */
  --autohide-tabs-height: 64px;           /* ceiling: the tab bar opens to its natural height, up to this */
  --autohide-nav-height: 52px;            /* the navigation bar's open height (close to its natural one) */
  --autohide-bookmarks-height: 40px;      /* the bookmarks bar's open height */
  --autohide-show-duration: 0.12s;        /* opening: how long it takes */
  --autohide-hide-delay: 0.3s;            /* closing: how long to wait before collapsing */
  --autohide-show: var(--autohide-show-duration) ease-out 0s;     /* opening: duration, easing, delay */
  --autohide-hide: 0.2s ease-in var(--autohide-hide-delay);       /* closing: duration, easing, delay */
}
```

## How it works

```text
 shortcut / button / tab switch
              │
              ▼
 JS/autohide.uc.js ── sets an attribute on the window root:  <window autohide-tabs>
              │
              ▼
   autohide.css   ── collapses #TabsToolbar when that attribute is present
```

The CSS keys on attributes that the script sets per window. Collapsed, the bar shrinks to a strip; hover, focus, a tab switch (`tabs-flash`) or an open popup open it to its natural height. The collapsed rule only matches while none of those holds, so Firefox's own spacing and borders come back untouched when the bar opens:

```css
/* collapsed: only a strip is left */
:root[autohide-tabs] #TabsToolbar:not(:hover, :focus-within /* , ... */) {
  max-height: var(--autohide-strip) !important;
  opacity: 0;
}
/* revealed */
:root[autohide-tabs] #TabsToolbar:is(:hover, :focus-within),
:root[autohide-tabs][tabs-flash] #TabsToolbar {
  max-height: var(--autohide-tabs-height) !important;
  opacity: 1;
}
```

The script flips the attribute and stores the state with the window, so it survives a session restore:

```js
root.toggleAttribute("autohide-tabs", on);
SessionStore.setCustomWindowValue(window, "autohideTabs", on ? "1" : "0");
```

Pure CSS cannot detect tab switches or keep a separate state per window, hence the script. Firefox only runs such scripts through an autoconfig file in its install directory, which needs root and may be replaced by package updates. That is what the [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) loader provides.

> **Security note:** the loader runs every script in the profile's `chrome/JS` with full browser privileges. Only install scripts you trust.

## Troubleshooting

- **No button, no shortcut:** the loader did not run. Close every Firefox window, start it again, then clear the startup cache from `about:support`.
- **No Peek a Foxy section in the settings:** run `peek-a-foxy install` again (it sets the pref the page needs) and restart Firefox. If it is still missing, Firefox may have changed the page; the reason is in the Browser Console, filtered by `peekafoxy settings`.
- **Nothing after a Firefox update:** the update replaced the install directory; run `peek-a-foxy install` again.
- **Errors:** open the Browser Console (`Ctrl+Shift+J`) and filter for `autohide`.

## Windows notes

- **Install:** with Python for now: `pipx install git+https://github.com/paodelonga/peek-a-foxy.git` (or `uv tool install`), then `peek-a-foxy install`. A standalone program for Scoop and winget is planned (see the [roadmap](#roadmap)).
- **Administrator prompt.** Firefox's folder under `C:\Program Files` is read-only for a normal user, so Windows asks (UAC) before two files, `config.js` and `defaults\pref\config-prefs.js`, are copied there. Only that copy is elevated. The elevated process is a fresh, isolated run of the base Python (not the copy inside a pipx or uv environment) that receives the two files' bytes and refuses anything that does not match the pinned fx-autoconfig. If you say no, nothing is written to Firefox's folder and the command says so. Residual risk: it runs `python.exe` with your approval, so a Python installation that something else can rewrite can abuse that prompt.
- **Which Firefox:** found through the registry, `Program Files`, `Program Files (x86)`, your local app data and `PATH`; pass `--firefox-dir` for a portable copy. The Microsoft Store (MSIX) build is refused.
- **Firefox updates** can replace its install folder and remove the loader: run `peek-a-foxy install` again if the buttons and the settings section disappear.
- **Antivirus** may ask about `config.js` in Firefox's folder: it is the fx-autoconfig loader, which Firefox runs on start.
- **Git Bash / mintty** does not look like a terminal to Python, so use `--yes` (or run through `winpty`). `cmd`, PowerShell and Windows Terminal are fine.
- **Title bar.** When Firefox draws its own title bar (the Windows default), the tab bar's autohide hides only the tabs and keeps the window buttons and the drag area, so a slim row stays. Turn on Firefox's own title bar (Customize Toolbar, *Title Bar*) to collapse the whole tab bar to the strip.
- **Shortcuts with AltGr.** On layouts where AltGr types characters (ABNT2, German, Czech...), AltGr counts as Ctrl+Alt and is never taken as a shortcut; use the left Ctrl and Alt.

## Uninstall

```bash
peek-a-foxy uninstall
```

Removes this project's files and prefs. It leaves `chrome/utils` and the loader in the Firefox install directory, since other scripts may use them.

## Roadmap

Planned; contributions are welcome.

- [ ] A standalone `peek-a-foxy.exe` with [Scoop](https://scoop.sh) and [winget](https://learn.microsoft.com/windows/package-manager/) packages, so Windows users need no Python.
- [ ] Hands-on testing on Windows (the UAC prompt, a Firefox update, per-user installs, the real title bar and window dragging, AltGr layouts).
- [ ] macOS compatibility
- [ ] Tiling window managers and context menus: some tiling WMs steal the pointer when a context menu opens, so the tab bar may close while the menu is open.
- [ ] Open the bars over the page instead of pushing it down. Today a revealed bar pushes the page down, which reflows the page on every animation frame.
- [ ] The bookmarks bar closing when a bookmark is pressed and held or dragged, seen on at least one setup (Linux, tiling window manager). The automated tests send synthetic drag events and do not reproduce it. Reports are welcome, with your Firefox build, desktop or window manager, and display server (X11 or Wayland).

## About the name

**Peek-a-Foxy** is a pun on *peek-a-boo*, the game where something hides and then pops back out with a cheerful "found you!". That is what the bars do: they hide, and peek back out 👀 when you hover over their strip.

> And when I picked the name I was listening to "Peek-A-Boo", and [AT THAT EXACT MOMENT](https://youtu.be/6uJf2IT2Zh8?t=59) my bar disappeared and came back, giving me a little scare 😅

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow, commit style and how to run the tests. Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through the [security policy](SECURITY.md).

## License and credits

[MIT](LICENSE). Built on [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) by MrOtherGuy, which is MIT-licensed and not redistributed here.
