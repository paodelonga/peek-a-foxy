<div align="center">

# Peek-a-Foxy 🦊

**A customization tool for Firefox that hides the tab bar and the navigation bar and shows them when you need them. Peek-a-boo for Foxys: they hide, they peek, then BOOO! out when you hover.**

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
  - [Common problems](#common-problems)
  - [peek-a-foxy doctor](#peek-a-foxy-doctor)
  - [Asking for help from inside Firefox](#asking-for-help-from-inside-firefox)
  - [The log](#the-log)
  - [The status file](#the-status-file)
  - [Exit codes](#exit-codes)
  - [Error codes](#error-codes)
- [Windows notes](#windows-notes)
- [Uninstall](#uninstall)
- [Roadmap](#roadmap)
- [About the name](#about-the-name)
- [Contributing](#contributing)
- [License and credits](#license-and-credits)

## Features

- **Tab bar autohide.** The bar collapses to a thin hover strip. It slides open when the cursor is on the strip (hovering the URL bar does not reveal it), briefly on every tab switch (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) and when a new tab opens (links, background tabs), and stays open while a tab is dragged or its context menu is open.
- **Navigation bar autohide** (urlbar, buttons, extensions). It opens from its own hover strip, whenever the URL bar gets focus (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`), and while its dropdown or a popup opened from one of its buttons is open. The bookmarks bar hides and shows together with it, and the bars try to stay open while something is dragged out of them (for bookmarks this is not reliable yet, see the [roadmap](#roadmap)).
- **Stays out of the way.** Customize Toolbar and full screen are left to Firefox: the bars are fully visible there.
- **Opt-in and per window.** Both are off until you turn them on, and each window keeps its own state, saved with the session.
- **Settings inside Firefox.** A **Peek a Foxy 🦊** section in the settings page changes the defaults, the strip size, the timings and the shortcuts for every open window at once, and its **Support** group says whether the script is working ([details](#settings)).
- **Help when something fails.** Every error has a code, a plain explanation and a hint about what to do next, and `peek-a-foxy doctor` checks your computer and writes a report that you can paste into an issue. Nothing is ever sent anywhere ([details](#troubleshooting)).
- **A hello when it loads.** The first time the script runs in a profile, Firefox shows a one-time notification ("Instaalleeeeed PEEK A BOO!!! >.<"), so you know it is working. It follows Firefox's language: English, or Brazilian Portuguese when Firefox is in Portuguese. Its button opens the song the name is a nod to ([see below](#about-the-name)).
- **Non-invasive installer.** Your own rules in `userChrome.css` are left alone (one line is added), a copy of `userChrome.css` and of `user.js` is kept before the first change, an existing autoconfig setup is never overwritten, and everything can be removed with one command.

## Requirements

- Firefox 121 or newer (the CSS uses `:has()`).
- Linux or Windows 10/11. Snap, Flatpak and Microsoft Store (MSIX) builds of Firefox are not supported (their install directory is read-only).
- Python 3.10 or newer and `git`. The standalone Windows program, once a release includes it, needs no Python; it still needs `git` (see [Windows notes](#windows-notes)).
- `sudo` (Linux) or an administrator prompt (Windows, UAC), only if the Firefox install directory isn't writable by you. Only the copy of two files is elevated; everything else runs as you.
- On Windows, [Git for Windows](https://git-scm.com/download/win) (`winget install Git.Git`), which the installer uses to fetch the loader.

**Windows** is tested in CI on a real Windows runner (unit tests, the whole headless-Firefox suite, the real loader download), but not yet by hand on a desktop: see [Windows notes](#windows-notes). The code also knows where Firefox keeps its files on macOS, but that has never been tried on a real Mac, so treat macOS as unsupported for now.

Developed and used on Firefox Developer Edition.

## Install

```bash
pipx install git+https://github.com/paodelonga/peek-a-foxy.git   # or: uv tool install git+https://...
peek-a-foxy install
```

From a clone, use `pipx install .` instead. Then close **all** Firefox windows and start it again. Nothing changes visibly yet: both autohides start off. Turn one on with its [shortcut or button](#usage).

On Windows, a standalone program that needs no Python is built by the release workflow but is not published yet; until it is, use `pipx` or `uv` as above (see [Windows notes](#windows-notes)).

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
peek-a-foxy install [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--allow-unverified-loader]
                    [--dry-run] [--yes] [--verbose] [--log-file FILE] [--no-log]
peek-a-foxy uninstall [--profile DIR] [--dry-run] [--yes] [--verbose] [--log-file FILE] [--no-log]
peek-a-foxy doctor [--profile DIR] [--firefox-dir DIR] [--markdown | --json] [--copy] [--save [PATH]]
                   [--verbose] [--log-file FILE] [--no-log]
peek-a-foxy logs [--open | --clear] [--yes] [--log-file FILE]

  --profile DIR       profile to use instead of choosing from profiles.ini
  --firefox-dir DIR   Firefox install directory for the loader (default: auto-detected)
  --skip-loader       only install the profile files; leave the Firefox install directory alone
  --allow-unverified-loader
                      with FXAC_REPO or FXAC_COMMIT set (they are meant for tests), let sudo copy
                      that loader without checking it against the pinned one; only for a loader
                      you wrote or trust (Windows has no such option)
  --dry-run           show the plan without changing any of your files
  --yes, -y           don't ask anything: apply without confirming, no profile or Firefox picker
                      (an unclear choice is an error instead)
  --verbose, -v       also print the technical details of each step and of an error
  --log-file FILE     write the log to FILE instead of the default place
  --no-log            do not write a log for this run
```

`--verbose`, `--log-file` and `--no-log` can be written before or after the command name. `uninstall --yes` is the same as above without the Firefox picker, since `uninstall` never looks at the Firefox installation. For `logs`, `--yes` only answers the question that `--clear` asks, and `--log-file FILE` names the log to look at instead of the one to write. The log is described in [The log](#the-log), and `doctor` and `logs` in [Troubleshooting](#troubleshooting).

### What gets installed

In your profile (`~/.mozilla/firefox/<profile>/`):

```text
chrome/
├── autohide.css            ← this project
├── JS/autohide.uc.js       ← this project (the autohide itself)
├── JS/autohide-prefs.uc.js ← this project (the settings page)
├── resources/peekafoxy.sys.mjs ← this project (shared by both scripts)
├── utils/                  ← fx-autoconfig (the per-profile half of the loader)
├── peekafoxy-status.json   ← written by the script while Firefox runs, read by `peek-a-foxy doctor`
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

**Your own files are edited with care.** `userChrome.css` and `user.js` are replaced in one step (a temporary file next to them is written first and then renamed over them), so a crash or a full disk can never leave half a file. If either is a symbolic link, the file it points to is the one that changes and the link stays. Their permissions are kept, a read-only file is not replaced, and if a program changes one of them while the command is working, the command starts over from the new content instead of overwriting it.

**A backup is kept once.** The first time the command is about to change one of these files, it keeps a copy next to it, named `userChrome.css.peek-a-foxy.bak` or `user.js.peek-a-foxy.bak`. The copy is made only if the file already existed and only if no copy exists yet, and it is never replaced afterwards, so it holds your file as it was when a version of Peek-a-Foxy that makes backups first changed it. Version 0.2.0 and earlier made no backups, so if you installed one of them, the copy already contains the lines that version added. The same is true when `install` created the file itself and `uninstall` is the first command to change it afterwards. `uninstall` never deletes these copies; delete them yourself when you no longer need them. A file larger than 64 MiB is not edited at all.

**Only ordinary files are edited, and comments are respected.** If `userChrome.css` or `user.js` (or the file a link points to) is a folder, a named pipe, a socket or a device (for example a link to `/dev/null`, which some people use to switch a file off), the command stops before it changes anything and says so with error `PAF-402`; it never replaces such an item with a regular file. Both files are read the way Firefox reads them: a line inside a `/* ... */` comment (or, in `user.js`, after `//`) does not count, so a pref that only exists inside a comment is not taken as set, and an `@import` line inside a comment is neither moved nor deleted. When a pref has to be added and the file ends inside a comment that is never closed, the new line goes in front of that comment, because Firefox would ignore anything after it. Every line keeps its own ending: in a file that mixes LF and CRLF, only the lines the command adds use the ending that most lines have.

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

**The copy into a folder that needs `sudo` is verified.** When Firefox's install directory is not writable by you (Linux and macOS), the command reads the two loader files once, checks their SHA-256 against the values pinned in the package (the same ones that the Windows administrator copy uses) and hands exactly those bytes to `sudo`, so a file that changes on disk while you type your password cannot reach a folder owned by root. On Linux the bytes go to `sudo install`; on macOS they go through `sudo tee` and `chmod`, because macOS's `install` may refuse input that is not a file (this has not been run on a Mac). A loader that is already in the folder with the same content is left alone, and then `sudo` is not started at all. With `FXAC_REPO` or `FXAC_COMMIT`, which are meant for your own tests and cannot match the pinned values, the root copy is refused with error `PAF-207` unless you add `--allow-unverified-loader`; the log then records that the copy was made without verification.

A Firefox update can remove the loader from its install directory; run `peek-a-foxy install` again if the buttons and shortcuts stop working.

## Usage

| | Tab bar | Navigation bar |
| --- | --- | --- |
| Toggle for the current window | `Ctrl+Alt+T` or toolbar button | `Ctrl+Alt+Shift+U` or toolbar button |
| Reveal temporarily | hover the top strip, switch or open a tab | hover its strip, focus the URL bar |

The buttons are in *Customize Toolbar* as **Auto-hide the tab bar** and **Auto-hide the navigation bar** (in a Portuguese Firefox: **Ocultar a barra de abas automaticamente** and **Ocultar a barra de navegação automaticamente**). While a bar's autohide is on in a window, the button looks pressed in that window. The urlbar button lives in the bar it hides, so reveal the bar with its hover strip to click it; the shortcut works at any time.

`Ctrl+Alt+U` is Firefox's own shortcut for the Open Tabs sidebar, so the navigation bar uses `Ctrl+Alt+Shift+U` instead of it. Versions up to 0.2.0 used `Ctrl+Alt+U` for the navigation bar: if you never changed that shortcut, it changed with the update. If a shortcut clashes with something on your system, change it in Firefox's settings (see [Settings](#settings)); a shortcut that you chose yourself is kept, and the page warns you when the one you record is already used by Firefox.

A bar also stays open while a popup that belongs to it is open (the menu of one of its buttons, the list of all tabs, a bookmarks folder). A window that a page opens as a popup never hides its navigation bar, so its address stays visible. With Firefox's vertical tabs turned on there is no tab bar to hide, so the tab bar options do nothing, and the settings page says so.

### Command line

`-h` works like `--help`, on every command. Shell completion (bash, zsh, fish) completes commands, options, and the profiles from `profiles.ini` for `--profile`:

```bash
peek-a-foxy install -h
peek-a-foxy --install-completion      # then restart your shell
```

`--install-completion` is Typer's own installer, and it edits your shell's startup file: for bash it adds a `source` line to `~/.bashrc` and writes `~/.bash_completions/peek-a-foxy.sh`; for zsh it adds lines to `~/.zshrc` and writes `~/.zfunc/_peek-a-foxy`; for fish it writes `~/.config/fish/completions/peek-a-foxy.fish`. This was read from Typer 0.27.3 and runs outside the care that `install` takes with your files (no backup, no entry in the log). `peek-a-foxy --show-completion` prints the script without installing anything, so you can read it first and add it yourself.

`--install-completion` is refused in PowerShell. Typer's installer first sets your PowerShell execution policy to `Unrestricted` for your user, which lets any script run, and Peek-a-Foxy will not make that change for you. In PowerShell, run `peek-a-foxy --show-completion` and add what it prints to your PowerShell profile yourself.

Warnings go to the error output (stderr) and only the result of a command goes to the standard output, so `peek-a-foxy doctor --json` and `--markdown` can always be read by a program or pasted, even when the log cannot be written. `--firefox-dir` must name a folder that contains `omni.ja` (on Windows also `firefox.exe`); anything else, such as `/usr/lib`, is refused with error `PAF-109`. For `doctor`, `--profile` and `--firefox-dir` also accept a folder that does not exist: the report then says so (`PAF-605`) instead of ending with a usage error. `--save` takes the next word as its path even when that word starts with `-` (`--save -report.json`), unless the word is one of the command's own options.

If the output of a command is cut off (`peek-a-foxy install --yes | head -1`, a closed terminal, a full disk), `install` and `uninstall` still finish their work and exit normally, and `logs` and `doctor` exit with code 1 because their text is what they are for. Nothing is printed about it.

## Settings

Firefox's own settings page has a **Peek a Foxy 🦊** section (`about:preferences#peekafoxy`, or *Settings* in the menu). Everything below is applied to every open window at once, with no restart:

- whether **new windows** start with the tab bar and the navigation bar hidden (windows that are already open keep their own state);
- **what opens the tab bar for a moment**, each on its own switch: switching to another tab, opening a new tab (`Ctrl+T`, the `+` button), and a tab that opens straight to an address (a link you click, a bookmark, a page opening a window); plus **how long it stays open** afterwards. Hovering its strip always opens it. Firefox does not say how a tab was opened, so "straight to an address" means any tab that is going to load something other than the new-tab page or your home page;
- the **hover strip thickness**, the **opening animation** and the **delay before a bar closes**;
- the **shortcuts** that toggle each bar: click the field and press the new one (a letter, a digit or F1 to F12, with Ctrl, Alt or Meta and optionally Shift; it is checked, and the two bars cannot share one). Letters and digits name a key's position on a US keyboard, so on other layouts the name may differ from the key cap. Backspace or Delete in the field restores the default, and each setting has a **Restore default** button;
- a **Support** group at the bottom, which says whether the script is working in the window you are looking at and has a button that copies a diagnostic report ([details](#asking-for-help-from-inside-firefox)).

If Firefox's vertical tabs are on, the page also says that the tab bar options have no effect.

The page is added by a second script, `autohide-prefs.uc.js`, which needs Firefox to run scripts in `about:preferences` (the installer sets the `userChromeJS.persistent_domcontent_callback` pref for that, so run `peek-a-foxy install` again after updating, then restart Firefox). If a Firefox update changes the settings page in a way the script does not expect, it adds nothing and says why in the Browser Console; the prefs below still work in `about:config`.

Every setting is a real pref, listed in `about:config` with its type, and nothing is written to disk until you change a value:

| Pref | Default | Meaning |
| --- | --- | --- |
| `peekafoxy.tabs.autohide` | `false` | Start new windows with the tab bar hidden. |
| `peekafoxy.urlbar.autohide` | `false` | Start new windows with the navigation bar hidden. |
| `peekafoxy.strip.px` | `8` | Activation strip thickness, in pixels (1 to 40). |
| `peekafoxy.tabs.strip.px` | `0` | Activation strip thickness of the tab bar only, in pixels (0 to 40); 0 uses `peekafoxy.strip.px`. |
| `peekafoxy.urlbar.strip.px` | `0` | Same for the navigation bar. |
| `peekafoxy.show.ms` | `120` | Opening animation, in milliseconds (0 to 2000). |
| `peekafoxy.show.delay.ms` | `100` | How long the pointer has to stay on the activation strip before its bar opens, in milliseconds (0 to 5000). |
| `peekafoxy.hide.ms` | `200` | Closing animation, in milliseconds (0 to 2000). |
| `peekafoxy.hide.delay.ms` | `300` | Wait before a bar closes, in milliseconds (0 to 5000). |
| `peekafoxy.tabs.reveal.switch` | `true` | Open the tab bar for a moment when you switch to another tab. |
| `peekafoxy.tabs.reveal.new` | `true` | Same, when you open a new tab (the new-tab page or your home page). |
| `peekafoxy.tabs.reveal.load` | `false` | Same, when the page of the current tab finishes loading. |
| `peekafoxy.tabs.reveal.download` | `false` | Same, when a download finishes. |
| `peekafoxy.tabs.reveal.title` | `false` | Same, when the title of a tab in the background changes. |
| `peekafoxy.tabs.reveal.link` | `true` | Same, when a tab opens straight to any other address (a link, a bookmark, `window.open`...). |
| `peekafoxy.tabs.flash.ms` | `1500` | How long the tab bar stays open after one of those (0 to 10000). |
| `peekafoxy.tabs.shortcut` | `Ctrl+Alt+T` | Shortcut that toggles the tab bar in the current window. |
| `peekafoxy.urlbar.shortcut` | `Ctrl+Alt+Shift+U` | Shortcut that toggles the navigation bar. |
| `peekafoxy.welcomed` | `false` | Set to `true` after the one-time greeting. Set it back to `false` to see it again. |

A number outside its range is clamped, and a shortcut that is not valid falls back to the default. To pin a value in a file instead (it is then re-applied on every start), put the line in `user.js` in your profile folder (`~/.mozilla/firefox/<profile>/user.js`):

```js
// <profile>/user.js
user_pref("peekafoxy.tabs.autohide", true);
user_pref("peekafoxy.urlbar.autohide", true);
```

These are the defaults in the stylesheet. The strip thickness and the two timings can also be set in Firefox's settings, and a value set there wins; the bar heights are only here. To edit the stylesheet, change the installed copy in your profile (or the repository copy and install again):

```css
/* <profile>/chrome/autohide.css */
:root {
  --autohide-strip: 8px;                  /* activation strip height */
  --autohide-tabs-strip: var(--autohide-strip);   /* the tab bar's own strip */
  --autohide-nav-strip: var(--autohide-strip);    /* the navigation bar's own strip */
  --autohide-tabs-height: 64px;           /* ceiling: the tab bar opens to its natural height, up to this */
  --autohide-nav-height: 52px;            /* the navigation bar's open height (close to its natural one) */
  --autohide-bookmarks-height: 40px;      /* the bookmarks bar's open height */
  --autohide-show-duration: 0.12s;        /* opening: how long it takes */
  --autohide-show-delay: 0.1s;            /* opening: how long the pointer stays on the strip first */
  --autohide-hide-delay: 0.3s;            /* closing: how long to wait before collapsing */
  --autohide-show: var(--autohide-show-duration) ease-out 0s;     /* opening: duration, easing, delay */
  --autohide-hide-duration: 0.2s;         /* closing: how long it takes */
  --autohide-hide: var(--autohide-hide-duration) ease-in var(--autohide-hide-delay);       /* closing: duration, easing, delay */
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

### Common problems

- **No button, no shortcut:** the loader did not run. Close every Firefox window, start it again, then clear the startup cache from `about:support`. `peek-a-foxy doctor` tells you whether the loader is in place.
- **A shortcut does nothing:** your desktop may take it before Firefox sees it, or the settings may hold another one. Open the **Shortcuts** group in the Peek a Foxy settings and record a different combination.
- **No Peek a Foxy section in the settings:** run `peek-a-foxy install` again (it sets the pref the page needs) and restart Firefox. If it is still missing, Firefox may have changed the page; the reason is in the Browser Console, filtered by `peekafoxy settings`.
- **Nothing after a Firefox update:** the update replaced the install directory; run `peek-a-foxy install` again.
- **A command stopped with `error [PAF-...]`:** the code, what it means and what to do are in [Error codes](#error-codes).
- **Errors inside Firefox:** open the Browser Console (`Ctrl+Shift+J`) and filter for `autohide`.
- **None of that helps:** run `peek-a-foxy doctor` and read [the next section](#peek-a-foxy-doctor).

When a command fails in an expected way, Peek-a-Foxy prints what happened, a code and what to do next:

```text
error [PAF-401]: /home/you/.mozilla/firefox/xxxx.default/user.js is not valid UTF-8
What to do: Open the file in a text editor and save it as UTF-8, or move it aside, then run the command again.
Details were saved to /home/you/.local/state/peek-a-foxy/peek-a-foxy.log
```

Add `--verbose` (or `-v`) to see the technical details as well. The terminal shows paths as they are; the log and the reports hide your home folder and your user name.

### peek-a-foxy doctor

When something does not work, for example when a button or a shortcut is missing or when a command prints an error, run:

```bash
peek-a-foxy doctor
```

The command looks at your computer and tells you, in plain words, what is in the way of Peek-a-Foxy. It changes none of your files and sends nothing anywhere; the only thing it writes is the local [log](#the-log) (`--no-log` avoids even that). Each line of the report is marked **OK**, **WARN** or **FAIL**: a WARN is worth a look but is probably harmless, while a FAIL stops Peek-a-Foxy from working. Every WARN and every FAIL comes with a one-sentence explanation, a *What to do* hint and a code such as `PAF-601`, which is listed in the [error codes](#error-codes).

The report has four parts:

- **Program.** The version, how Peek-a-Foxy runs (as a standalone program, installed with pipx or pip, or from a source checkout), the Python version, your operating system, whether you are an administrator, the terminal and its encoding, whether `git` is installed, the version of the loader that Peek-a-Foxy expects, whether the Firefox files that come with the program were found, and where the log is kept.
- **Firefox installs.** Every Firefox installation that it finds, not only the first one: the version and the channel, whether you can change the folder, whether it is a Snap, Flatpak or Microsoft Store build (which cannot be changed), whether the loader files are present and are the expected version, whether another autoconfig setup could get in the way, and whether `distribution/policies.json` exists (and nothing more about it). If one installation is broken but another one works, the broken one is reported as a warning instead of a failure.
- **Profiles.** The profiles listed in `profiles.ini`, with the default of each Firefox marked, and a detailed check of the profile you name with `--profile` or, without it, of the default one (of all of them when none is marked): the four Peek-a-Foxy files and whether they are identical to the ones that came with this version, the `chrome/utils` folder, the `@import` line in `userChrome.css` and whether it is at the top of the file, the settings that Firefox needs in `user.js` and `prefs.js`, any `peekafoxy.*` settings, and a hint when Firefox may still be using an old startup cache.
- **Script status.** What the script itself saw from inside Firefox, read from [the status file](#the-status-file). When Firefox has not run the script yet, the report says so and asks you to close all Firefox windows and start it again; a WARN here right after an installation only means that Firefox has not been restarted.

In a terminal the report is a table; when the output is not a terminal, it is Markdown. The options are:

| Option | What it does |
| --- | --- |
| `--profile DIR`, `--firefox-dir DIR` | Mean the same as in `install`: the profile or the Firefox folder to look at, instead of the ones found automatically. A folder that does not exist is reported (`PAF-605`, `PAF-105`) instead of being a usage error. |
| `--markdown` | Prints the report as Markdown, ready to paste into an issue. |
| `--json` | Prints the report as JSON (`"schema": 1`), for use by other programs. |
| `--copy` | Also copies the report to the clipboard (the Markdown, or the JSON with `--json`). When no clipboard tool works, the report is printed so that you can copy it yourself. |
| `--save [PATH]` | Also saves the report to a file. Without a path, the file is placed next to the log; an existing file is never replaced (`PAF-403`). |
| `--verbose`, `-v`, `--log-file`, `--no-log` | Work as in the other commands. |

To ask for help:

1. Run `peek-a-foxy doctor --copy`, or `peek-a-foxy doctor --save` if you would rather have a file.
2. Read the report before you share it. Your home folder, your user name, the names of Firefox profile folders and the names you gave your profiles are replaced by `~`, `<user>`, `<profile>`, `<profile 1>`, `<profile 2>` and so on, and anything that looks like a password or a token is hidden too, but you are the one who decides what to share.
3. Paste the report into a new issue at <https://github.com/paodelonga/peek-a-foxy/issues/new/choose>. The bug report form has a field for it.

Peek-a-Foxy never sends anything anywhere, and the report ends with the sentence "Nothing was sent anywhere. Review it, then paste it into your issue."

Text that comes from a file (a status message, a profile name, a path) is shortened and stripped of line breaks, control characters and invisible text-direction marks before it is printed, so that a damaged or hostile file cannot disturb your terminal or make the report unreadable. A file bigger than 16 MB (2 MB for the loader files and the Peek-a-Foxy files, 1 MB for the status file) is reported as too big instead of being read, and only the first 50 profiles are listed and the first 10 are checked in detail.

### Asking for help from inside Firefox

If Peek-a-Foxy does not work as you expect, open Firefox's settings, choose the **Peek a Foxy 🦊** category and look at the **Support** group at the bottom. The first line says in plain words whether the script is working in the window you are looking at. When it is not, the line says what Peek-a-Foxy found, for example that Firefox may have renamed the navigation bar, so that you do not have to guess.

The **Copy diagnostic info** button puts a short report on your clipboard, and no terminal is needed. You can paste it into an issue at <https://github.com/paodelonga/peek-a-foxy/issues/new/choose>. The report is written in English so that anyone who helps you can read it, whatever language Firefox uses for you. It contains the version of Peek-a-Foxy, the version, channel and operating system of Firefox, the language of Firefox, the number of open windows, the result of each health check (for example whether the navigation bar and the toolbar buttons were found), and the last events that the script recorded.

The script does not collect the addresses of the pages you visit, your bookmarks, your passwords or the contents of your tabs. The text of an error message that Firefox raised is copied as it is, with your home folder, user name and profile folder hidden, which is one more reason to read the report before you paste it. Nothing is sent anywhere: the report only goes to your clipboard. If Firefox cannot reach the clipboard, the text is shown in a box under the button so that you can select it and copy it yourself.

### The log

Every run writes a small log on your machine, to help find out what went wrong. Nothing is sent anywhere. Your home folder, your user name, Firefox profile folder names, tokens and credentials in URLs, and values written as `NAME_TOKEN=...`, `password: ...` or `Bearer ...` are hidden in it (`~`, `<user>`, `<profile>`, `***`), but read it before you share it.

| System | Where the log is |
| --- | --- |
| Linux | `$XDG_STATE_HOME/peek-a-foxy/peek-a-foxy.log` (usually `~/.local/state/peek-a-foxy/`) |
| macOS | `~/Library/Logs/peek-a-foxy/peek-a-foxy.log` |
| Windows | `%LOCALAPPDATA%\peek-a-foxy\logs\peek-a-foxy.log` |

It keeps three files of at most 5 MB each (`peek-a-foxy.log`, `peek-a-foxy.log.1` and `peek-a-foxy.log.2`). It is private to your account (mode `600`, in a folder created with mode `700`; Windows ignores the modes). The commands are:

- `peek-a-foxy logs` shows where the log is, how big it is and what the last run did.
- `peek-a-foxy logs --open` opens the folder that holds it.
- `peek-a-foxy logs --clear` deletes the log files after asking (add `--yes` to skip the question). It deletes only files that are logs.

`--verbose`/`-v`, `--log-file FILE` and `--no-log` work on `install`, `uninstall` and `doctor`, before or after the command name. In the environment, `PEEK_A_FOXY_LOG=off` turns the log off and `PEEK_A_FOXY_LOG=/some/file.log` moves it. A log only ever goes to a file that is a log: if the variable or `--log-file` names a file that exists and does not begin with a log line (a `user.js`, say), or is not a regular file (a named pipe, a device), the run goes on without a log and says so on the error output. If the log cannot be written at all, you get one warning and the command carries on. A value that starts with `~` and cannot be expanded (`~nosuchuser/x.log`) is a warning for the variable and error `PAF-402` for `--log-file` and `doctor --save`.

### The status file

Every time Firefox starts, and whenever something changes, the script saves what it found in the file `chrome/peekafoxy-status.json` inside your Firefox profile. The file is small, it is replaced as a whole each time, and it never leaves your computer. `peek-a-foxy doctor` reads it, which is how the doctor can tell you what Firefox itself saw, and you can open it in a text editor if you are curious. Deleting it is safe: the script writes it again at the next start (see [Uninstall](#uninstall) for removing it for good).

It is a JSON object with the keys `schema` (always `1` for now), `scriptVersion`, `firefoxVersion`, `buildID`, `channel`, `os`, `locale`, `updated` (an ISO 8601 time in UTC), `windows` (how many windows run the script), `health` (each check is `"ok"` or `"fail: a note"`) and `errors` (the last events, as objects with `time`, `level`, `where` and `message`; the script keeps 50 and the doctor shows the latest 20). Unknown keys are ignored, so a newer script can add keys without breaking an older doctor. A status file that is older than the installed files, dated in the future, damaged or too big is reported as a warning with the reason.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Done. For `doctor`: nothing failed (warnings are acceptable). |
| `1` | It failed in an expected way (the message says why, with a code), or you answered no to a question. For `doctor`: at least one check failed. `logs` and `doctor` also end with `1` when their output could not be written, because the text is what they are for. |
| `2` | A wrong option or argument. |
| `70` | A bug in Peek-a-Foxy (code `PAF-900`): please report it and attach the log. |
| `130` | You pressed `Ctrl+C`. |

### Error codes

A code is `PAF-` followed by three digits. The first digit is the area, and the table is split the same way. A code never changes its meaning and is never reused, so you can search for it.

**Profiles and Firefox (`PAF-1xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-101` | Firefox's list of profiles (`profiles.ini`) was not found. | Start Firefox once so it creates a profile, then run the command again. Or give the profile folder yourself with `--profile`. |
| `PAF-102` | Firefox's list of profiles (`profiles.ini`) could not be read. | Give the profile folder yourself with `--profile`. |
| `PAF-103` | Firefox's list of profiles has no profile in it. | Start Firefox once so it creates a profile, then run the command again. Or give the profile folder yourself with `--profile`. |
| `PAF-104` | There is more than one default profile, so the right one is unclear. | Run the command without `--yes` to pick one from a list, or give the folder with `--profile`. |
| `PAF-105` | The Firefox install folder was not found. | Give the folder that contains `omni.ja` with `--firefox-dir`. If fx-autoconfig is already set up in your Firefox, use `--skip-loader` instead. |
| `PAF-106` | More than one Firefox install was found and the choice cannot be asked. | Give the one you want with `--firefox-dir`, or run the command without `--yes` to pick one. |
| `PAF-107` | This Firefox is a Snap, Flatpak or Microsoft Store build, which cannot be changed. | Install Firefox from mozilla.org or from your system's regular package instead. If fx-autoconfig is already set up in it, use `--skip-loader`. |
| `PAF-108` | The number typed is not one of the numbers in the list. | Run the command again and type one of the numbers shown. |
| `PAF-109` | The folder given with `--firefox-dir` does not look like the install folder of Firefox. | Give the folder that contains `omni.ja`, for example `/usr/lib/firefox` on Linux or `/Applications/Firefox.app/Contents/Resources` on macOS. If fx-autoconfig is already set up in your Firefox, use `--skip-loader` instead. |

**The loader: git, the network and copying it (`PAF-2xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-201` | git is not installed, and it is needed to download the loader. | Install git and run the command again. If fx-autoconfig is already set up in your Firefox, use `--skip-loader`. |
| `PAF-202` | git could not download the loader. | Check your internet connection (and any proxy or firewall) and run the command again. Running it with `--verbose` shows git's own output. |
| `PAF-203` | The `FXAC_COMMIT` environment variable is not a full commit hash. | Remove `FXAC_COMMIT`, or set it to a full 40-digit commit hash. |
| `PAF-204` | The downloaded loader is not the version this program expects. | Run the command again. If it keeps happening, please report it: it should not happen. |
| `PAF-205` | sudo could not copy the loader into the Firefox folder. | Run the command in a terminal where sudo can ask for your password, or make the Firefox folder writable for your user. |
| `PAF-206` | The Firefox folder cannot be written, even as administrator. | Check that Firefox is not a Microsoft Store build and that no antivirus is blocking writes to the Firefox folder, then run the command again. |
| `PAF-207` | The loader to copy as administrator is not the pinned one, so it was not copied. | Remove `FXAC_REPO` and `FXAC_COMMIT` from the environment and run the command again. Only if you wrote that loader yourself or trust its source, add `--allow-unverified-loader` to copy it without checking it. |

**Administrator rights (`PAF-3xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-301` | The administrator prompt was cancelled. | Run the command again and answer Yes to the prompt. It is only used to copy two small files into the Firefox folder. |
| `PAF-302` | The administrator prompt was not answered in time. | Run the command again and answer the prompt within three minutes. |
| `PAF-303` | Windows would not show the administrator prompt. | Run the command from a normal terminal in your own desktop session, or open the terminal as administrator and run it again. |
| `PAF-304` | The administrator step started but could not finish. | Run the command again. If it keeps happening, run it with `--verbose` and report the details. |
| `PAF-305` | `FXAC_REPO` or `FXAC_COMMIT` is set, and the administrator copy refuses a loader that is not the pinned one. | Remove `FXAC_REPO` and `FXAC_COMMIT` from the environment and run the command again. |
| `PAF-306` | The command for the administrator step is longer than Windows allows, so it was not started. | This should not happen with the files that Peek-a-Foxy installs. Please report it at https://github.com/paodelonga/peek-a-foxy/issues with the result of `peek-a-foxy doctor --copy`. |
| `PAF-307` | The system policy keeps PowerShell in a restricted mode, so the administrator step cannot run. | Ask whoever manages this computer to allow Windows PowerShell in its normal mode, or copy `config.js` and `defaults/pref/config-prefs.js` into the Firefox folder by hand. |

**Your files (`PAF-4xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-401` | One of your Firefox files is not valid UTF-8 text, so it cannot be edited safely. | Open the file in a text editor and save it as UTF-8, or move it aside, then run the command again. |
| `PAF-402` | A file or folder could not be read or changed. | Check that it exists, that you may change it, and that no other program (an editor, an antivirus) has it open. Then run the command again: it is safe to repeat. |
| `PAF-403` | A file with that name already exists, so nothing was saved. | Choose another name with `--save PATH`, or move the old file away first. |
| `PAF-404` | The `chrome/utils` folder in your profile is a link, so nothing was copied into it. | Replace the link with a real folder, or remove it, then run `peek-a-foxy install` again. Peek-a-Foxy never copies the loader's utils through a link, because the files would end up somewhere else. |

**This system (`PAF-5xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-501` | This operating system is not supported. | Peek-a-Foxy works on Linux and Windows. It also knows where Firefox keeps its files on macOS, but that has never been tried on a real Mac. On another system, `--profile` with `--skip-loader` skips the automatic search. |
| `PAF-502` | There is no terminal to ask for confirmation. | Add `--yes` to apply the changes without asking. |
| `PAF-503` | The Peek-a-Foxy files to install were not found next to the program. | Reinstall Peek-a-Foxy (for example: `pipx reinstall peek-a-foxy`) and run the command again. |

**What `peek-a-foxy doctor` reports (`PAF-6xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-601` | This Firefox does not have the loader (fx-autoconfig), so it cannot run the Peek-a-Foxy script. | Run `peek-a-foxy install` and allow the request for administrator rights; it only copies two small files into the Firefox folder. |
| `PAF-602` | The loader in this Firefox is not exactly the version that Peek-a-Foxy installs. | If Peek-a-Foxy works for you, leave it as it is; if it does not, remove `config.js` and `defaults/pref/config-prefs.js` from the Firefox folder and run `peek-a-foxy install` again. |
| `PAF-603` | Another autoconfig setup is present in the Firefox folder and may prevent the loader from starting. | The report names the files involved. If you do not need the other setup, remove it; otherwise make sure that it also loads fx-autoconfig's `config.js`. |
| `PAF-604` | Firefox's `application.ini` file could not be read, so the version of this Firefox is unknown. | Nothing needs to be done unless something else fails; if it does, mention which Firefox you use, which `about:support` shows. |
| `PAF-605` | The profile folder does not exist. | Choose an existing profile with `--profile`, or start Firefox once so that it creates one. |
| `PAF-606` | Some of the Peek-a-Foxy files are missing from the profile. | Run `peek-a-foxy install` again. |
| `PAF-607` | Some of the Peek-a-Foxy files in the profile are not the ones that came with this version. | Run `peek-a-foxy install` to update them; any change you made to those files will be replaced. |
| `PAF-608` | The loader's utils folder is missing from the profile's chrome folder. | Run `peek-a-foxy install` again. |
| `PAF-609` | The file `userChrome.css` does not load the Peek-a-Foxy stylesheet. | Run `peek-a-foxy install` again; it adds the missing line and keeps the rest of your file. |
| `PAF-610` | The line that loads the Peek-a-Foxy stylesheet is placed below other rules, so Firefox ignores it. | Run `peek-a-foxy install`; it moves the line to the top and keeps the rest of your file. |
| `PAF-611` | A setting that Firefox needs in order to run the script is missing or turned off. | Run `peek-a-foxy install` again; it adds the settings to your `user.js` file. |
| `PAF-612` | Firefox may still be using a copy of its files from before Peek-a-Foxy was installed. | Close all Firefox windows, start Firefox, open `about:support`, press the 'Clear startup cache' button and let Firefox restart. |
| `PAF-613` | Firefox has not run the script yet, so it has not reported anything. | Close all Firefox windows and start Firefox again; if this message stays, the loader is not working, so look at the Firefox checks above it. |
| `PAF-614` | The status file written by Firefox could not be read, has an impossible date, or is older than the installed files. | Close all Firefox windows, start Firefox again, and then run `peek-a-foxy doctor` once more. |
| `PAF-615` | The script found something in this Firefox that it cannot work with. | Update Peek-a-Foxy and Firefox; if the message stays, include this report when you ask for help, because Firefox may have changed something. |
| `PAF-616` | The script recorded errors while it was running in Firefox. | Include this report when you ask for help, because the errors are listed in it. |
| `PAF-617` | This terminal cannot show every character, so some of the text may look wrong. | This is harmless; for clean output use a terminal that is set to UTF-8, as Windows Terminal is. |

**Unexpected (`PAF-9xx`)**

| Code | What happened | What to do |
| --- | --- | --- |
| `PAF-900` | Something unexpected went wrong; this is a bug in Peek-a-Foxy. | Please report it at https://github.com/paodelonga/peek-a-foxy/issues: run `peek-a-foxy doctor --copy`, paste the result into your report and attach the log file, whose location `peek-a-foxy logs` shows. |

## Windows notes

- **Install with Python (works today):** `pipx install git+https://github.com/paodelonga/peek-a-foxy.git` (or `uv tool install`), then `peek-a-foxy install`. It needs Python 3.10 or newer and [Git for Windows](https://git-scm.com/download/win).
- **The standalone program (not published yet).** When a release is published, the workflow `.github/workflows/exe.yml` builds `peek-a-foxy.exe` with PyInstaller on a Windows runner, runs a few checks on it, and attaches it to the release together with `peek-a-foxy.exe.sha256`, `install.ps1` and the Scoop and winget manifests. No release made so far has these files, and none of what follows has been run against a real release or by hand on a Windows desktop, so read it as the plan for the next release and not as something to rely on today. The program needs no Python, but it still needs Git for Windows to fetch the loader.
  - **`install.ps1`** is meant to be run with `irm https://github.com/paodelonga/peek-a-foxy/releases/latest/download/install.ps1 | iex`. It downloads `peek-a-foxy.exe` and its `.sha256` file, stops if the program does not match the hash, copies the program to `%LOCALAPPDATA%\Programs\peek-a-foxy` and adds that folder to your user `PATH`. It needs no administrator rights and runs nothing else; afterwards you open a new terminal and run `peek-a-foxy install`. To read the script before it runs, download it with `irm https://github.com/paodelonga/peek-a-foxy/releases/latest/download/install.ps1 -OutFile install.ps1`; it also takes `-Version`, `-InstallDir` and `-NoPath`.
  - **Checking the download.** The SHA-256 file catches a damaged or truncated download. It does not prove who built the program, because the program and the hash come from the same place. To check that the file was built by this repository's release workflow, install the [GitHub CLI](https://cli.github.com) and run `gh attestation verify peek-a-foxy.exe -R paodelonga/peek-a-foxy` in the folder that holds the program. The workflow signs a build provenance statement for the program through Sigstore, but this has not been tried on a real release yet.
  - **No code signing yet.** The program is not signed, so Windows SmartScreen or an antivirus program may warn about it. Signing is a long-term item in the GitHub Project (see the [roadmap](#roadmap)).
  - **Scoop and winget.** The manifests that the workflow attaches (`peek-a-foxy.json` for Scoop and the `paodelonga.PeekAFoxy*.yaml` files for winget) are templates from `packaging/templates`, filled in with the version and the hash when a release is published. Nothing has been submitted to a Scoop bucket or to winget's community repository, so `scoop install` and `winget install` do not work yet. Both manifests name Git as a dependency.
- **Administrator prompt.** Firefox's folder under `C:\Program Files` is read-only for a normal user, so when copying `config.js` and `defaults\pref\config-prefs.js` there is refused, Windows asks (UAC) before the two files are copied. Only that copy is elevated. If you say no, nothing is written to Firefox's folder and the command says so.
  - **What runs elevated.** The elevated process is Windows PowerShell from the system folder (`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`, a location that Windows itself reports and that is never taken from `PATH` or from an environment variable), started with `-NoProfile -NonInteractive -EncodedCommand`. Peek-a-Foxy generates the script it runs, and the script carries everything it needs: the Firefox folder, the two files and their pinned SHA-256 values. The same route serves the standalone program and an installation with Python, so neither a Python installation nor the program itself runs with the rights you approve.
  - **What the script checks.** Before it writes anything, the script stops if PowerShell is not in its full language mode (a system policy that restricts it ends as `PAF-307`), if the two files do not match the pinned fx-autoconfig, if the folder is not a Firefox folder (it needs `firefox.exe`, `omni.ja` and an `application.ini` that names Firefox), or if the path contains a link, a junction, a short (8.3) name or a substituted drive between the drive root and the files. Peek-a-Foxy makes the last check once more before it asks, so that you are not shown a prompt that could only end in a refusal. The script reports only through its exit code.
  - **The command length.** The command that starts the elevated step is about 12.7 thousand characters long (12,740 measured with the real file sizes and `C:\Program Files\Mozilla Firefox`). Windows accepts command lines of up to 32,767 characters, and Peek-a-Foxy refuses to start the elevated step if its command would be longer than that, saying so with error `PAF-306` instead of failing inside Windows.
  - **Residual risk.** The elevated process starts with the settings of your own account, so a program that already runs as you could still try to abuse the prompt you approve through what Windows and .NET read from those settings, for example environment variables that make .NET load a profiler into PowerShell. That cannot be removed from inside Peek-a-Foxy. In the same way, when the Firefox folder is writable by you but the copy still failed (a read-only `config.js`, a file held by an antivirus), a program of yours could in theory replace the `defaults` folder by a junction between the checks and the writes; what could be written is limited to the fixed content of the two pinned files. None of this has been tried on a real Windows desktop; see also the [security policy](SECURITY.md).
- **Which Firefox:** found through the registry, `Program Files`, `Program Files (x86)`, your local app data and `PATH`; pass `--firefox-dir` for a portable copy. The Microsoft Store (MSIX) build is refused.
- **Firefox updates** can replace its install folder and remove the loader: run `peek-a-foxy install` again if the buttons and the settings section disappear.
- **Antivirus** may ask about `config.js` in Firefox's folder: it is the fx-autoconfig loader, which Firefox runs on start. It may also question the elevated PowerShell step, because that step is started with `-EncodedCommand`, a form that other programs use too; this has not been observed.
- **Git Bash / mintty** does not look like a terminal to Python, so use `--yes` (or run through `winpty`). `cmd`, PowerShell and Windows Terminal are fine.
- **Title bar.** When Firefox draws its own title bar (the Windows default), the tab bar's autohide hides only the tabs and keeps the window buttons and the drag area, so a slim row stays. Turn on Firefox's own title bar (Customize Toolbar, *Title Bar*) to collapse the whole tab bar to the strip.
- **Shortcuts with AltGr.** On layouts where AltGr types characters (ABNT2, German, Czech...), AltGr counts as Ctrl+Alt and is never taken as a shortcut; use the left Ctrl and Alt, or `Ctrl+Shift` with a letter.

## Uninstall

```bash
peek-a-foxy uninstall
```

Removes this project's files and prefs. It leaves `chrome/utils` and the loader in the Firefox install directory, since other scripts may use them, and it leaves the `.peek-a-foxy.bak` copies of your files, which are yours to keep or delete. When its files are gone it also removes the `chrome/JS` and `chrome/resources` folders, but only if they are empty: a folder that still holds anything, or that is a link, is left as it is, without a warning.

`uninstall` also removes `chrome/peekafoxy-status.json` (the file Firefox's script writes for `peek-a-foxy doctor`) and its `.tmp` leftover. If something else is at that name (a folder, a file that cannot be deleted) it is kept and the command only warns. If Firefox is running when you uninstall, it writes `chrome/peekafoxy-status.json` again; close Firefox first, or delete that file after closing it.

## Roadmap

Planned work is tracked in the GitHub Project [Peek-a-Foxy](https://github.com/users/paodelonga/projects/22), and contributions are welcome.

Known limits that you may run into today:

- Hands-on testing on Windows (the UAC prompt, a Firefox update, per-user installs, the real title bar and window dragging, AltGr layouts) and a first run on a real Mac are still open; see [Requirements](#requirements) and [Windows notes](#windows-notes).
- Tiling window managers and context menus: some tiling WMs steal the pointer when a context menu opens, so the tab bar may close while the menu is open.
- A revealed bar pushes the page down instead of opening over it, which reflows the page on every animation frame.
- The bookmarks bar can close when a bookmark is pressed and held or dragged, seen on at least one setup (Linux, tiling window manager). The automated tests send synthetic drag events and do not reproduce it. Reports are welcome, with your Firefox build, desktop or window manager, and display server (X11 or Wayland).

## About the name

**Peek-a-Foxy** is a pun on *peek-a-boo*, the game where something hides and then pops back out with a cheerful "found you!". That is what the bars do: they hide, and peek back out 👀 when you hover over their strip.

> And when I picked the name I was listening to "Peek-A-Boo", and [AT THAT EXACT MOMENT](https://youtu.be/6uJf2IT2Zh8?t=59) my bar disappeared and came back, giving me a little scare 😅

👀 And there are a few easter eggs hiding around, including in the settings page.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow, commit style and how to run the tests. Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through the [security policy](SECURITY.md).

## License and credits

[MIT](LICENSE). Built on [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) by MrOtherGuy, which is MIT-licensed and not redistributed here.
