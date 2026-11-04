# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a breaking change bumps the minor version).

Entries are detailed on purpose: one per user-visible change, saying what triggers it, what the default
is and what controls it, with a *Known issues* section for what is not covered.

## [Unreleased]

### Added

- **Choose what opens the tab bar for a moment.** The Peek-a-Foxy section of Firefox's settings has a
  "Reveal the tab bar when" group with one switch for each trigger, all on by default (the behavior
  until now), applied to every open window at once: switching to another tab
  (`peekafoxy.tabs.reveal.switch`), opening a new tab with `Ctrl+T` or the `+` button
  (`peekafoxy.tabs.reveal.new`), and a tab that opens straight to an address, such as a link you click,
  a bookmark or a page opening a window (`peekafoxy.tabs.reveal.link`). The reveal time stays
  `peekafoxy.tabs.flash.ms`, and hovering the strip always opens the bar.
  - Firefox does not report how a tab was opened, so the two kinds of new tab are told apart by what the
    tab is about to load: the new-tab page, your home page or nothing counts as a tab you opened; any
    other address counts as a link. A bookmark opened in a new tab therefore follows the "link" switch.
  - A tab that is opened and selected fires two events; the "new tab" or "link" switch decides, so
    turning one off is not undone by the tab switch that comes with it.

## [0.2.0] - 2026-11-04

The settings page and the first review round: a Peek-a-Foxy section in Firefox's settings, a safer and
more honest `peek-a-foxy` command, a stricter loader fetch, and a weekly run against new Firefox
versions. **After updating, run `peek-a-foxy install` again and restart Firefox:** the settings page
needs a pref that the installer now sets.

### Added

- **A Peek-a-Foxy section in Firefox's settings** (`about:preferences#peekafoxy`, added by the new
  script `JS/autohide-prefs.uc.js`). It sets, for every open window at once and without a restart:
  - whether new windows start with the tab bar and the navigation bar hidden (windows that are already
    open keep their own state);
  - the hover strip height (1 to 40 px, default 8), the opening animation (0 to 2000 ms, default 120),
    the delay before a bar closes (0 to 5000 ms, default 300) and how long the tab bar stays open after a
    tab switch or a new tab (0 to 10000 ms, default 1500);
  - the shortcut of each bar: click the field and press the new one. A shortcut is a letter, a digit or
    F1 to F12 with Ctrl, Alt, Shift or Meta, and needs at least one of Ctrl, Alt or Meta; the two bars
    cannot share one; some keys are refused with a message. This also answers the `Ctrl+Alt+T` clash
    with the terminal launcher on GNOME, Ubuntu and Linux Mint: the default is unchanged, and it can now
    be changed;
  - a button to show the greeting again, and a **Reset** button on every number and shortcut.
  The page is in English or Brazilian Portuguese, following Firefox's language. Out-of-range numbers
  are refused with a message (and clamped if a pref is edited in `about:config`); an invalid shortcut
  in a pref falls back to the default.
- **Six new prefs**, all real prefs listed in `about:config` with their type and none written to disk
  until changed: `peekafoxy.strip.px`, `peekafoxy.show.ms`, `peekafoxy.hide.delay.ms`,
  `peekafoxy.tabs.flash.ms`, `peekafoxy.tabs.shortcut` and `peekafoxy.urlbar.shortcut`.
- **It fails soft.** The page hooks into three places of Firefox's own settings page (the category list,
  the pane container and the category registry). If a Firefox update changes any of them, the script
  adds nothing, undoes anything it had added, and names what is missing in the Browser Console
  (filter for `peekafoxy settings`). The prefs keep working in `about:config`.
- A new shared module, `resources/peekafoxy.sys.mjs`, holds the prefs, their limits, the shortcut
  format and all texts for both scripts.
- The closing panel of `install` points to the new settings.

- **A closing panel that tells the truth.** After `peek-a-foxy install` the panel now depends on what
  happened: with `--skip-loader` it says the loader was not installed and that the script only runs if
  fx-autoconfig is already set up in that Firefox; when another `config.js` was found in Firefox's
  install directory and kept (as before, with a warning), it says that too. Only a complete install
  says "Done".
- **A failed install says what it left behind.** When a step fails, the error is followed by how many
  steps had finished and which, that the failed step may have changed part of its files, and that
  running the same command again is safe because every step can be repeated. If nothing had finished,
  it says so.
- **Toolbar button names and tooltips follow Firefox's language**, like the greeting already did:
  Portuguese (`pt`, `pt-BR`, `pt-PT`, ...) gets **Ocultar abas automaticamente** and **Ocultar barra de
  endereço automaticamente** with Portuguese tooltips; every other language keeps the English texts.
  The buttons are created once per Firefox session, by the first window, so they follow the language
  Firefox started with.
- **A weekly run of the browser tests** against the current Firefox release and the Beta
  (`.github/workflows/firefox-weekly.yml`, also startable by hand), so a Firefox change that breaks the
  script is noticed before users notice it.
- `CONTRIBUTING.md` explains how to move to a newer pinned fx-autoconfig commit.

### Changed

- **`install` also sets `userChromeJS.persistent_domcontent_callback` in `user.js`.** fx-autoconfig only
  runs scripts in the browser window unless this is set, and the settings page lives in a tab. It is
  read when Firefox starts, so restart Firefox, and run `peek-a-foxy install` again after updating to
  get the settings page. `uninstall` leaves it, like the stylesheets pref, because other scripts may
  use it. `uninstall` now removes the two new files (`JS/autohide-prefs.uc.js` and
  `resources/peekafoxy.sys.mjs`) and every `peekafoxy.*` line from `user.js`.
- **The stylesheet has two more variables**, `--autohide-show-duration` (0.12s) and
  `--autohide-hide-delay` (0.3s), which the settings set; `--autohide-show` and `--autohide-hide` are
  built from them. A value from the settings wins over the stylesheet's only while its pref has a user
  value, so edits to `autohide.css` keep working when nothing was changed in the settings. With
  `prefers-reduced-motion`, bars still open instantly and keep only the closing delay, whatever the
  settings say.
- **`install` and `uninstall` no longer apply anything without a terminal or `--yes`.** Before, with
  stdin or stdout not a terminal (a pipe, cron, CI) and no `--yes`, the confirmation was silently
  skipped and the changes were applied. Now the command shows the plan and stops with an error that
  names `--yes`. With `--yes`, and with `--dry-run`, nothing changes.
- **The `--yes` help** now says everything it skips: the confirmation, the profile picker and the
  Firefox installation picker (an unclear choice is an error instead).
- **The loader is fetched, not cloned.** Only the pinned commit is downloaded (`git fetch --depth 1`),
  without the repository's history, and then checked against the pinned hash as before. If a server
  refuses to serve a single commit, it falls back to a full clone.
- `FXAC_COMMIT` (a test override) must be a full 40-digit hash; a branch, a tag, an abbreviated hash or
  anything starting with `-` is refused with a clear error, even for `--dry-run`. The repository and the
  commit are passed to git after `--`, so they can never be read as git options.

### Fixed

- **Paths and git messages that look like Rich markup** (a profile directory called `[bold red]p` or
  `[/x]`, for example) were garbled in the plan, the pickers, warnings and errors, and `[/x]` crashed
  the command with a `MarkupError`. All user text is now printed as typed.
- Tests: `test_dragging_a_bookmark_keeps_the_bookmarks_bar_open` could fail at random when Firefox
  focused the URL bar of the new window (which correctly keeps the bars open); the test helper now waits
  for the window to finish starting and takes the focus off the URL bar.
- Tests: the failing-`sudo` test failed earlier than it meant to (on an unrelated step), so it did not
  exercise `sudo`; it now makes Firefox's directory read-only and covers both a refused and a missing
  `sudo`.
- A stale comment in the installer claimed the script treats a missing pref as "off"; the script
  registers the defaults itself.

### Documentation

- The README's CSS example now shows the real defaults (8 px strip, 0.3 s hide delay; it said 12 px and
  0.6 s) and all six variables (`--autohide-nav-height` and `--autohide-bookmarks-height` were missing),
  in English and Portuguese. A test compares the example with `autohide.css`.
- Both READMEs say that `Ctrl+Alt+T` opens a terminal on GNOME, Ubuntu and Linux Mint and never reaches
  Firefox there, and point to the toolbar button.

### Internal

- Browser tests for the settings page (the category and its navigation, every control, live effect in
  several windows, shortcuts and their refusals, both languages, and a Firefox whose page changed), for
  the shortcut format and the texts, and for the installer's new files and prefs.
- Terminal output moved to `ui.py`; every user-supplied string goes through it as plain text.
- New tests: odd paths everywhere user text is shown, no-terminal behavior, the closing panel, partial
  failures, loader sources and shallow fetches (including against the real GitHub), the pref names and
  shortcuts shared by Python and the script, the localized button texts in a real Firefox, and the
  workflow files. Branch coverage went from 96% to 100%.

### Known issues

- The settings page was built and tested against the settings page of Firefox 157 (the one with the
  `moz-page-nav` category list). An older layout is not supported and gets no section (the console says
  what is missing); the prefs still work in `about:config`.
- The settings page is not found by the search box at the top of Firefox's settings.
- The toolbar buttons are created once per Firefox session, by the first window, so their names follow
  the language Firefox started with; their tooltips follow the shortcuts live.

## [0.1.0] - 2026-11-04

The first public release.

### Added

#### Autohide for the tab bar

- The tab bar collapses to a thin hover strip (8 px, `--autohide-strip`) and opens to its **natural
  height**, so nothing is clipped.
- It opens when the cursor is on the strip. Hovering the URL bar does **not** reveal it.
- It opens briefly (1.5 s) on every tab switch (`Ctrl+Tab`, `Ctrl+PageUp/PageDown`, clicking a tab, ...)
  and whenever a tab is opened, including links opened in a background tab.
- It stays open while keyboard focus is inside it, while a tab is being dragged, and while a tab's
  context menu is open.

#### Autohide for the navigation bar

- The navigation bar (URL bar, navigation buttons, extension buttons) collapses to its own 8 px hover
  strip.
- It opens when the cursor is on the strip, whenever the URL bar gets focus (`Ctrl+L`, `Ctrl+K`, `F6`,
  `Alt+D`), while the URL bar's dropdown is open, while a toolbar popup (an extension's, for example) is
  open, and while the bookmarks bar below it is hovered.
- **The bookmarks bar hides and shows together with the navigation bar**, as one group. A bookmarks bar
  that you turned off in Firefox stays off.

#### Behavior shared by both bars

- **Opt-in:** both autohides start off. Nothing changes in the browser until you turn one on.
- **Per window:** every window has its own state, saved with the session, so it survives a restart and a
  session restore. New windows start from the preferences below.
- **Toggles:** `Ctrl+Alt+T` (tab bar) and `Ctrl+Alt+U` (navigation bar), and a toolbar button for each
  (**Tabs autohide**, **Urlbar autohide**) that you add from *Customize Toolbar*. The navigation bar's
  button lives in the bar it hides, so reveal the bar with its strip to click it; the shortcut works at
  any time.
- **Dragging:** a bar stays open while something is dragged out of it (a tab, a bookmark, a toolbar
  button). Firefox does not update hover during a drag, so the script records the source bar on the
  window and the CSS keeps it open until the drag ends. See *Known issues* for bookmarks.
- **Out of the way:** Customize Toolbar and full screen are left to Firefox; the bars are fully visible
  there.
- **Animation:** a bar opens in 0.12 s and closes in 0.2 s after a 0.3 s delay, so it does not flicker
  when the cursor drifts off. `prefers-reduced-motion` is honored: it opens instantly, keeping only the
  delay before closing.
- **Firefox's own look is kept:** a bar is only collapsed while it is not revealed, so its padding and
  borders come back untouched when it opens.
- **Tunable in CSS:** the strip size, the open heights and the timings are variables at the top of
  `autohide.css` (`--autohide-strip`, `--autohide-tabs-height`, `--autohide-nav-height`,
  `--autohide-bookmarks-height`, `--autohide-show`, `--autohide-hide`).

#### Preferences

- `peekafoxy.tabs.autohide` and `peekafoxy.urlbar.autohide` (default `false`): the initial state of
  windows that have no saved state. Existing windows keep their own.
- `peekafoxy.welcomed` (default `false`): set to `true` after the one-time greeting; set it back to see
  it again.
- The script registers the three as boolean defaults every time it loads, so `about:config` lists them
  with the right type and a toggle, and nobody has to create them by hand. Nothing is written to
  `user.js` or `prefs.js` until you change a value, and your changes stick across restarts.

#### One-time greeting

- The first time the script runs in a profile, Firefox shows a notification, so you can tell it loaded:
  "Instaalleeeeed PEEK A BOO!!! >.<" in English, or "Instaalaadoooo PEEK A BOO!!! >.<" when Firefox's
  language is Portuguese (`pt`, `pt-BR`, `pt-PT`, ...). Its **Peek-a-boo!** button opens the song the
  name is a nod to.

#### The `peek-a-foxy` command

- `peek-a-foxy install` and `peek-a-foxy uninstall`.
- **It shows a plan first** (a numbered list of every change), asks for confirmation, and only then
  applies it. `--dry-run` shows the plan and stops; `--yes` skips the questions.
- **It never guesses.** With several profiles, or several Firefox installations (release and Developer
  Edition, for example), it asks which one to use. With `--yes`, an ambiguous choice is an error and you
  pass `--profile` or `--firefox-dir`.
- `--skip-loader` installs only the profile files and leaves Firefox's install directory alone.
- `-h` works like `--help` on every command, and `--version` prints the version.
- **Shell completion** for bash, zsh and fish (`--install-completion`): commands, options, the profiles
  from `profiles.ini` for `--profile`, and the detected Firefox installations for `--firefox-dir`.
- **What it changes:**
  - copies `autohide.css` and `autohide.uc.js` into the profile's `chrome` folder;
  - adds one `@import` line at the top of your `userChrome.css` (or after a leading `@charset`), and
    leaves your own rules untouched;
  - sets `toolkit.legacyUserProfileCustomizations.stylesheets` in `user.js`, the only line it writes
    there;
  - installs the [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) loader that lets Firefox
    run the script: its `utils` folder in the profile and `config.js` plus
    `defaults/pref/config-prefs.js` in Firefox's install directory, using `sudo` only if that directory
    is not writable by you.
- **The loader is pinned and verified.** It is cloned at one fixed commit (`dfdab56`), and the install
  stops if the checkout does not match. The download is the first step, so a network failure leaves your
  profile untouched. A different `config.js` that is already in place is never overwritten: the installer
  warns and skips the loader.
- **Your files are handled with care:** LF or CRLF line endings, a missing final newline and a UTF-8
  byte-order mark are preserved; a symlinked `userChrome.css` stays a symlink; a file that is not valid
  UTF-8 stops the install, with a clear message, before anything is changed. Running it again changes
  nothing.
- Errors and warnings never break a path across lines, so it can be copied back.
- Pref names used by pre-release builds (`userchrome.tabs.autohide`, `userchrome.urlbar.autohide`) are
  migrated: a deliberate "on" is kept under the new name, and the old lines are removed.
- Snap and Flatpak builds of Firefox are refused with an explanation: their install directory is
  read-only.

#### Quality

- 104 unit tests (pytest and Hypothesis), covering odd user files, failure modes, several Firefox
  installations, interactive choices and the Linux and macOS paths, with 96% branch coverage (CI
  requires 90%).
- 19 tests that drive a **real headless Firefox** with the real fx-autoconfig: both buttons exist,
  shortcuts toggle only their own window, the bars collapse to the strip and open to their natural
  height, the bookmarks bar follows the navigation bar, the prefs are registered as booleans, dragging,
  Customize Toolbar, full screen and the greeting (shown once, and its button opens the song).
- A test that checks the pinned fx-autoconfig commit still exists upstream and has the files that are
  installed.
- CI on Linux and macOS (Python 3.10 and 3.13), `mypy --strict`, `ruff`, `pre-commit`, and a check that
  every commit message of a pull request follows Conventional Commits.

#### Project

- A Code of Conduct (Contributor Covenant 2.1), a security policy with private vulnerability reporting,
  issue forms for bug reports, feature requests and questions, a pull request template, Dependabot, a
  release notes template and a `CONTRIBUTING.md` that documents the branch workflow and the release
  steps.
- The README is available in English and Brazilian Portuguese. The other documents (`CONTRIBUTING.md`,
  the Code of Conduct, the security policy and this changelog) are in English.

### Known issues

- **The bookmarks bar can still close when a bookmark is pressed and held, or dragged**, on at least one
  setup (Linux, tiling window manager). The automated tests send synthetic drag events and do not
  reproduce it, so it needs reports from other environments. See the roadmap in the README.
- **Context menus on tiling window managers:** some of them take the pointer when a context menu opens,
  so the tab bar may close while the menu is open.
- **Hover and real drags** cannot be simulated in a headless browser, so the automated tests reveal the
  bars through focus and the tab-switch reveal, not through the mouse. Those paths are checked by hand.
- **Platforms:** Linux is the supported one. The installer has code paths for macOS, covered by tests that
  pass explicit paths on macOS CI, but it has never been run on a real Mac, and its automatic detection
  of the profile and of Firefox is not exercised there. Windows is not supported.
- **Snap and Flatpak** builds of Firefox are not supported.

[Unreleased]: https://github.com/paodelonga/peek-a-foxy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/paodelonga/peek-a-foxy/releases/tag/v0.1.0
