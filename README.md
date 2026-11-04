<div align="center">

# Peek-a-Foxy 🦊

**Peek-a-boo for Firefox: your tab bar and navigation bar hide, then peek out when you hover. Independently, per window.**

[![CI](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml/badge.svg)](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Firefox 121+](https://img.shields.io/badge/Firefox-121%2B-FF7139?logo=firefoxbrowser&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey)

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
- [Uninstall](#uninstall)
- [Roadmap](#roadmap)
- [About the name](#about-the-name)
- [Contributing](#contributing)
- [License and credits](#license-and-credits)

## Features

- **Tab bar autohide.** The bar collapses to a thin hover strip. It slides open when the cursor is on the strip (hovering the URL bar does not reveal it), briefly on every tab switch (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) and when a new tab opens (links, background tabs), and stays open while a tab is dragged or its context menu is open.
- **Navigation bar autohide** (urlbar, buttons, extensions). It opens from its own hover strip, whenever the URL bar gets focus (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`), and while its dropdown or a toolbar popup is open.
- **Opt-in and per window.** Both are off until you turn them on, and each window keeps its own state, saved with the session.
- **A hello when it loads.** The first time the script runs in a profile, Firefox shows a one-time notification ("Instaalleeeeed PEEK A BOO!!! >.<"), so you know it is working. It follows Firefox's language: English, or Brazilian Portuguese when Firefox is in Portuguese. Its button opens the song the name is a nod to ([see below](#about-the-name)).
- **Non-invasive installer.** Your own `userChrome.css` is left alone, an existing autoconfig setup is never overwritten, and everything can be removed with one command.

## Requirements

- Firefox 121 or newer (the CSS uses `:has()`).
- Linux. Snap and Flatpak builds of Firefox are not supported (their install directory is read-only).
- Python 3.10 or newer and `git`.
- `sudo`, only if the Firefox install directory isn't writable by you.

macOS and Windows are on the [roadmap](#roadmap). The code contains macOS paths that have never been run on a Mac, so treat macOS as unsupported for now.

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
│ 2 │ Copy autohide.css and autohide.uc.js into …/chrome             │
│ 3 │ Add the @import line to …/chrome/userChrome.css                │
│ 4 │ Set the prefs in …/user.js                                     │
│ 5 │ Copy fx-autoconfig's utils into …/chrome/utils                 │
│ 6 │ Install the loader into /usr/lib/firefox (uses sudo if needed) │
└───┴────────────────────────────────────────────────────────────────┘
Apply these changes? [Y/n]:
```

With several profiles or several Firefox installations (release and developer edition, for example) it asks which one to use. It never guesses: with `--yes`, an ambiguous choice is an error and you pass `--profile` / `--firefox-dir`.

```text
peek-a-foxy install [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--dry-run] [--yes]
peek-a-foxy uninstall [--profile DIR] [--dry-run] [--yes]

  --profile DIR       profile to use instead of choosing from profiles.ini
  --firefox-dir DIR   Firefox install directory for the loader (default: auto-detected)
  --skip-loader       only install the profile files; leave the Firefox install directory alone
  --dry-run           show the plan without changing anything
  --yes, -y           don't ask for confirmation or choose interactively
```

### What gets installed

In your profile (`~/.mozilla/firefox/<profile>/`):

```text
chrome/
├── autohide.css            ← this project
├── JS/autohide.uc.js       ← this project
├── utils/                  ← fx-autoconfig (the per-profile half of the loader)
└── userChrome.css          ← yours; one line is added at the top, the rest is untouched
user.js                     ← three prefs added (below)
```

One line at the top of your `userChrome.css`:

```css
@import url("autohide.css");
```

Three lines in `user.js`. The two `userchrome.*` ones are only added if you haven't set them:

```js
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("userchrome.tabs.autohide", false);
user_pref("userchrome.urlbar.autohide", false);
```

In Firefox's install directory (for example `/usr/lib/firefox/`), the [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) loader, cloned at a pinned and verified commit:

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

The buttons are in *Customize Toolbar* as **Tabs autohide** and **Urlbar autohide**. The urlbar button lives in the bar it hides, so reveal the bar with its hover strip to click it; the shortcut works at any time.

## Settings

The first two prefs only define the initial state of windows that have none saved; existing windows keep their own, and the installer never overwrites them once set.

| Pref | Default | Meaning |
| --- | --- | --- |
| `userchrome.tabs.autohide` | `false` | Start new windows with the tab bar hidden. |
| `userchrome.urlbar.autohide` | `false` | Start new windows with the navigation bar hidden. |
| `userchrome.peekafoxy.welcomed` | `false` | Set to `true` by Firefox after the one-time greeting. Set it back to `false` in `about:config` to see it again. |

Change them in `about:config`, or add lines like these to `user.js` in your profile folder (`~/.mozilla/firefox/<profile>/user.js`):

```js
// <profile>/user.js
user_pref("userchrome.tabs.autohide", true);
user_pref("userchrome.urlbar.autohide", true);
```

Strip height, bar heights and animation timings are CSS variables at the top of [`chrome/autohide.css`](chrome/autohide.css). To change them, edit the installed copy in your profile (or the repository copy and install again):

```css
/* <profile>/chrome/autohide.css */
:root {
  --autohide-strip: 12px;                 /* hover strip height */
  --autohide-tabs-height: 40px;           /* tab bar height when open */
  --autohide-show: 0.12s ease-out 0s;     /* opening: duration, easing, delay */
  --autohide-hide: 0.2s ease-in 0.6s;     /* closing: wait 0.6s before collapsing */
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

The CSS keys on attributes that the script sets per window. Collapsed, the bar shrinks to a strip; hover, focus, a tab switch (`tabs-flash`) or an open popup expand it:

```css
:root[autohide-tabs] #TabsToolbar {
  height: var(--autohide-strip) !important;
  overflow: hidden !important;
  opacity: 0;
}
:root[autohide-tabs] #TabsToolbar:hover,
:root[autohide-tabs] #TabsToolbar:focus-within,
:root[autohide-tabs][tabs-flash] #TabsToolbar {
  height: var(--autohide-tabs-height) !important;
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
- **Nothing after a Firefox update:** the update replaced the install directory; run `peek-a-foxy install` again.
- **Errors:** open the Browser Console (`Ctrl+Shift+J`) and filter for `autohide`.

## Uninstall

```bash
peek-a-foxy uninstall
```

Removes this project's files and prefs. It leaves `chrome/utils` and the loader in the Firefox install directory, since other scripts may use them.

## Roadmap

Planned; contributions are welcome.

- [ ] Windows support
- [ ] macOS compatibility
- [ ] Tiling window managers and context menus: some tiling WMs steal the pointer when a context menu opens, so the tab bar may close while the menu is open.
- [ ] Open the bars over the page instead of pushing it down. Today a revealed bar pushes the page down, which reflows the page on every animation frame.
- [ ] A settings UI for strip size, delays and shortcuts, instead of editing CSS variables.

## About the name

**Peek-a-Foxy** is a pun on *peek-a-boo*, the game where something hides and then pops back out with a cheerful "found you!". That is what the bars do: they hide, and peek back out 👀 when you hover over their strip.

> And when I picked the name I was listening to "Peek-A-Boo", and [AT THAT EXACT MOMENT](https://youtu.be/6uJf2IT2Zh8?t=59) my bar disappeared and came back, giving me a little scare 😅

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow, commit style and how to run the tests.

## License and credits

[MIT](LICENSE). Built on [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) by MrOtherGuy, which is MIT-licensed and not redistributed here.
