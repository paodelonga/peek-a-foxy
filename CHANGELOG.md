# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a breaking change bumps the minor version).

Entries are detailed on purpose: one per user-visible change, saying what triggers it, what the default
is and what controls it, with a *Known issues* section for what is not covered.

## [Unreleased]

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
