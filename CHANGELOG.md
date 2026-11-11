# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a breaking change bumps the minor version).

Entries are detailed on purpose: one per user-visible change, saying what triggers it, what the default
is and what controls it, with a *Known issues* section for what is not covered.

## [Unreleased]

### Added

- **A new setting: how long the pointer must stay on an activation strip before its bar opens** (`peekafoxy.show.delay.ms`, 0 to 5000, default 100, so a pointer that only brushes past a strip no longer opens the bar; set it to 0 for the old behaviour). It applies to the hover strips only; shortcuts, flashes and popups still open the bars at once. In the CSS it is `--autohide-show-delay`.
- Something small is hiding in the settings page.
- **Windows support** (Windows 10/11, tested in CI on a real Windows runner and not yet by hand on a
  desktop; see the README's *Windows notes*):
  - **Profiles and Firefox are found.** Profiles in `%APPDATA%\Mozilla\Firefox` (falling back to the
    home folder); installations through the registry (HKLM and HKCU, the 64 and 32 bit views, every
    brand under `SOFTWARE\Mozilla`, `Install Directory`, `PathToExe`, `App Paths`), the usual
    `Program Files`, `Program Files (x86)` and local app data folders, and `PATH`. A folder only counts
    if it has both `omni.ja` and `firefox.exe`, so Thunderbird is never taken. `--firefox-dir` still
    works for portable copies.
  - **The Microsoft Store (MSIX) build is refused** like Snap and Flatpak, naming the kind of build.
  - **An administrator prompt (UAC) only for the loader.** Firefox's folder is read-only for a normal
    user, so when the direct copy is refused, `config.js` and `defaults\pref\config-prefs.js` are
    written by a short-lived elevated process; the rest of the command runs as you. An administrator
    who still cannot write gets an error instead of a second prompt; saying no to the prompt, a
    timeout or a failed copy each have a clear message. The elevated process is the Windows PowerShell
    of the system folder (found through `GetSystemDirectoryW`, never through `PATH`), started with
    `-NoProfile -NonInteractive -EncodedCommand`; the same route serves the standalone program and an
    installation with Python, so neither a Python installation nor the program itself runs elevated.
    Its script is generated with the Firefox folder, the two files and their SHA-256 values pinned in
    the package next to the fx-autoconfig commit (a network test compares them with the real files).
    It stops unless PowerShell is in its full language mode (`PAF-307`), the hashes match, the folder
    is a Firefox folder (`omni.ja`, `firefox.exe` and an `application.ini` saying Firefox) and no link,
    junction, short (8.3) name or substituted drive is on the way; then it writes each file aside and
    renames it into place, and it reports only through its exit code. It is refused when `FXAC_REPO` or
    `FXAC_COMMIT` override the pin, and Peek-a-Foxy asks Windows first whether the folder is the real
    place, so a path that the script would refuse does not show a prompt. Residual risk, stated in the
    README and in `SECURITY.md`: a program that already runs as you can still try to abuse the prompt
    through what Windows and .NET read from your own settings (for example environment variables that
    load a .NET profiler).
  - **Tab bar and the title bar Firefox draws itself.** On Windows (and on Linux with client-side
    decorations, and on macOS) Firefox sets `customtitlebar` and puts the window buttons and the drag
    area inside the tab bar. In that case the autohide hides only the tabs and keeps the window
    buttons and the drag area, so a slim row stays; with the native title bar nothing changes.
  - **Settings:** the shortcut hint is neutral plus a sentence for the system running Firefox, and a
    press with AltGr active (Portuguese ABNT2, German, Czech... report it as Ctrl+Alt) is neither
    recorded nor matched.
  - **Console:** output no longer crashes on a legacy code page (what cannot be shown is replaced and
    the fox only appears where it can), and in Git Bash, which does not look like a terminal to
    Python, the error explains `--yes` and `winpty`.
  - `windows-latest` joins the unit tests (Python 3.10 and 3.13), the headless-Firefox suite, the
    network tests and the weekly Firefox run, including a check of the real title bar layout.
  - **A guard on the length of the elevated command.** A command over 32,767 characters is refused
    with `PAF-306` and a hint before anything is started (the real command is about 12.7 thousand
    characters).
- **A standalone Windows program, an install script and package manifests (not published yet).** When
  a release is published, `.github/workflows/exe.yml` builds `peek-a-foxy.exe` with PyInstaller from a
  hash-pinned lock, checks it (its version, a registry lookup of Firefox, an install into a throwaway
  profile) and attaches it to the release with its SHA-256, `install.ps1` and filled-in Scoop and winget
  manifests; a separate job signs a build provenance attestation, which
  `gh attestation verify peek-a-foxy.exe -R paodelonga/peek-a-foxy` checks. `install.ps1`
  (`irm https://github.com/paodelonga/peek-a-foxy/releases/latest/download/install.ps1 | iex`)
  installs for the current user without administrator rights: it checks the download against its
  published SHA-256, copies the program to `%LOCALAPPDATA%\Programs\peek-a-foxy` and adds that folder
  to the user `PATH`, keeping the entries that use `%VARIABLES%` as they were. No release has these
  files yet, the program is not code-signed, and the manifests are templates that nothing has
  submitted to Scoop or winget; the README says so.
- **Every expected error has a code, a plain message and a "What to do" line** (`PAF-101` to `PAF-900`,
  listed in the README). `--verbose` (`-v`) adds the technical details. An unexpected error is a bug in
  Peek-a-Foxy: it ends with code `PAF-900`, exit code 70 and a pointer to the log, and a traceback never
  prints local variables. Exit codes are `0`, `1` (an expected failure, or you said no), `2` (a wrong
  option), `70` and `130` (Ctrl+C). Codes are never reused.
- **A local log** of every run (3 files of at most 5 MB, in the place each system keeps this kind of
  file, private to your account), with your home folder, user name, Firefox profile folder names,
  tokens and credentials hidden. `--log-file`, `--no-log` and `PEEK_A_FOXY_LOG=off|PATH` control it.
  If it cannot be written, one warning is shown and the command carries on. Nothing is sent anywhere.
- **`peek-a-foxy logs`** shows where the log is and what the last run did; `--open` opens its folder
  and `--clear` deletes it (after asking, or with `--yes`).
- **`peek-a-foxy doctor`**, a report of the program, of every Firefox installation, of the profiles
  and of what the script saw inside Firefox, with a code and a hint for every problem (`PAF-601` to
  `PAF-617`). It is a table in a terminal, Markdown otherwise (`--markdown`) or JSON (`--json`), and
  `--copy` puts it on the clipboard and `--save [PATH]` saves it without replacing a file (`PAF-403`).
  It changes none of your files. Every part of it that comes from a file is cleaned and limited, and a
  part that crashes becomes a warning instead of ending the report.
- **A status file, a health check and a Support group.** The script saves what it found in
  `chrome/peekafoxy-status.json` (schema 1) when Firefox starts and whenever something changes, with the
  last 50 events of the script. A health check looks for the elements, toolbar buttons, settings and
  shortcuts that Peek-a-Foxy depends on and names the change in Firefox that it suspects. The Peek a
  Foxy settings page has a **Support** group with a line that says whether the script is working in the
  window and a **Copy diagnostic info** button that needs no terminal (in English and Portuguese). The
  doctor reads the status file.
- **`--allow-unverified-loader`** lets `sudo` copy a loader chosen with `FXAC_REPO` or `FXAC_COMMIT`
  (see *Security*), and `--firefox-dir` must now be a Firefox folder: a folder without `omni.ja` (on
  Windows also `firefox.exe`) is refused with `PAF-109`.
- **The toolbar buttons look pressed** while the bar they belong to is hidden in their window.
- **A bar stays open while a popup that belongs to it is open** (the menu of one of its buttons, the
  list of all tabs, a bookmarks folder), however many popups are nested, and a window that a page opens
  as a popup never hides its navigation bar.
- **The settings page says when vertical tabs are on**, because Firefox then has no tab bar to hide and
  the tab bar options do nothing, and **warns when the shortcut you record is one that Firefox already
  uses**. Backspace or Delete in a shortcut field restores the default.
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
- **A one-time backup of the user's files.** The first time `install` or `uninstall` is about to change an existing `userChrome.css` or `user.js`, a copy is kept next to it as `<file>.peek-a-foxy.bak`; it is never replaced and `uninstall` never deletes it. It holds the file as it was when a version that makes backups first changed it, so it already has Peek-a-Foxy's lines if an earlier version, or an `install` that created the file, wrote them.
- **`uninstall` removes `chrome/peekafoxy-status.json` and its `.tmp` leftover**, and only warns if something else is at that name.
- **The weekly Firefox run also covers the ESR** (`latest-esr`), and every test job of the CI uploads a doctor report for its system and Python version.

### Changed

- **The default shortcuts changed.** The tab bar uses `Ctrl+Alt+Shift+T` on Linux, and on any system that
  is not Windows or macOS, because `Ctrl+Alt+T` opens a terminal on GNOME, Ubuntu and Linux Mint; Windows
  and macOS keep `Ctrl+Alt+T`. The navigation bar uses `Ctrl+Alt+Shift+U` everywhere, because
  `Ctrl+Alt+U` is Firefox's own shortcut for the Open Tabs sidebar. **If you never changed the shortcuts
  in 0.2.0 or earlier, your shortcuts change with this update.** A value that you set yourself is kept;
  to go back to the old ones, set `peekafoxy.tabs.shortcut` to `Ctrl+Alt+T` and
  `peekafoxy.urlbar.shortcut` to `Ctrl+Alt+U` in the settings page or in `about:config`.
- **The settings page and the toolbar buttons are reworded** in English and Portuguese so that they read
  naturally. The section is called **Peek a Foxy 🦊**, the buttons are **Auto-hide the tab bar** and
  **Auto-hide the navigation bar** (the Portuguese ones say "barra de navegação", not "barra de
  endereço"), reset buttons are **Restore default**, and the page and the buttons say "navigation bar"
  everywhere. Each shortcut field shows its instruction as a visible line, names its reset button after
  the field, and gives the focus back after a reset; a right-to-left Firefox no longer mirrors the English
  sentences. The **show the greeting again** button is gone; the one-time greeting on first run stays
  (set `peekafoxy.welcomed` to `false` to see it again).
- **The loader is fetched with `core.autocrlf=false` and `core.longpaths=true`**, read as UTF-8, and the
  checkout is removed even when git's object files are read-only. Git for Windows converts line
  endings by default, which handed Firefox a `config.js` with CRLF. A missing git on Windows points to
  Git for Windows and `winget`.
- **`git` gets a time limit of 120 seconds and never asks for a password**, and an offline run shows one
  failure instead of two attempts. A loader copy into a writable Firefox folder is written aside and
  renamed, so it appears whole or not at all. A loader that is already in place is left alone, so a run
  that has nothing to do no longer asks for `sudo` or for the administrator prompt.
- The step that installs the loader says "asks for administrator permission if needed" on Windows
  instead of "uses sudo if needed".
- The README no longer says the shortcuts will become configurable (they have been since 0.2.0).
- **The user files are replaced atomically.** The new content is written to a temporary file in the same folder and renamed over the old one, so a crash or a full disk cannot leave half a file; a symbolic link is followed to the real file and stays a link; permissions and owner are kept; a read-only file is respected; a change made by another program while the command works makes the edit start over from the new content; a file over 64 MiB is refused.
- **`user.js` and `userChrome.css` are read the way Firefox reads them.** A pref or an `@import` inside a `/* */` comment (or after `//` in `user.js`) does not count, in `install`, `uninstall` and `doctor`; an added line is never put inside a comment, and goes in front of one that is never closed. Each line keeps its own ending in a file that mixes LF and CRLF. A named pipe, a socket, a device or a folder behind either file (a link to `/dev/null`, for example) is refused with `PAF-402` before anything changes.
- **`doctor --profile` and `--firefox-dir` accept a folder that does not exist** (the report says `PAF-605` or `PAF-105` instead of the command ending with exit code 2), and `--save` takes a path that starts with `-`.
- **Typer and Rich have lower and upper bounds** (`typer>=0.16.0,<0.30`, `rich>=13.8,<16`): the lower ones are the oldest versions that pass the test suite, and a CI job runs the suite with exactly those. The CI also pins every action and pre-commit hook by commit, gives every job a time limit, cancels superseded pull request runs and tests Python 3.14.
- The script's `isNewTabPage` no longer rebuilds its list or imports its two modules on every new tab.
- **`uninstall` also removes the `chrome/JS` and `chrome/resources` folders once they are empty.** After the
  Peek-a-Foxy files are gone, each folder is removed with a single `rmdir`, so a folder that still holds
  anything (another script of yours, for example), a folder that is a link or a junction, and a folder that
  is missing or cannot be removed are all left as they are, quietly (the reason goes to the log). The plan
  shown by `uninstall` and `--dry-run` says so.
- **`logs` and `uninstall` have their own help for `--yes`, and `logs` for `--log-file`.** `logs --yes` says
  that it only answers the question of `--clear`, `uninstall --yes` no longer mentions the Firefox
  installation, which `uninstall` never looks at, and `logs --log-file` says that it names the log to look
  at. The help of `--install-completion` says that it covers bash, zsh and fish and sends PowerShell to
  `--show-completion`, and the help of `doctor` no longer breaks in the middle of a sentence in the list
  of commands.

### Fixed

- **A broken pipe stopped `install` and `uninstall` half way.** Rich turned it into `SystemExit(1)` inside a step, so `peek-a-foxy install --yes | head -1` left the profile half installed. Output that cannot be written (a closed pipe, a closed stream, a full disk) is now lost quietly, the work finishes, and no command prints a traceback or exits with 120.
- **Warnings broke `doctor --json` and `--markdown`.** Every warning now goes to the error output (stderr), so the report on the standard output can always be read by a program or pasted.
- **Redaction.** A home folder that is a drive root (`C:\`) no longer removes every `C:` from the text; file names of eight characters such as `autohide.uc.js` in a stack frame are no longer replaced by `<profile>` (the same exclusion as the Firefox side); a profile or user named `profile` or `user` no longer turns `<profile>` into `<<profile 1>>`, and redacting a text twice gives the same text. A home folder is replaced only as a whole folder name (`/home/al` no longer turns `/home/alice` into `~ice`, in the program and in the script), also in the spelling that a link resolves to (`/var/home/you`), ignoring case on macOS; the 8.3 short name of a Windows user, `NAME_TOKEN=...`, `password: ...`, JSON secrets and `Bearer ...` are hidden; the pattern for credentials in URLs no longer takes quadratic time (a 30 KB line in `profiles.ini` made `doctor` run for 13 seconds); a line break in a message cannot forge a log line; and a bug's traceback is shown once, redacted, under `--verbose`.
- **The message of `PAF-501` said that macOS works.** It now says that Peek-a-Foxy works on Linux and Windows
  and that it also knows where Firefox keeps its files on macOS, but that this has never been tried on a
  real Mac; the README says the same.
- **The log only goes to a log.** `PEEK_A_FOXY_LOG` or `--log-file` pointing at another kind of file (a `user.js`, a named pipe) is refused with a warning, and `logs --clear` deletes only files that are logs. The log file is created with mode `600` and its new folder with `700`. `~name` in `PEEK_A_FOXY_LOG`, `--log-file` or `--save` is a warning or a coded error, not "a bug".
- **The state of each bar did not come back with a restored session**, and a new window did not save its state until the first toggle: Firefox does not know a window to its SessionStore while it starts ("Window is not tracked"), and a restored window gets its saved values later. The script now applies the saved values when SessionStore knows the window and again whenever a window state is restored (`SSWindowStateReady`), and saves the state of a window that has none. One visible effect: in a restored window the bar may start in the default state and then move to the saved one a fraction of a second later.
- **A false error in every popup window** that a page opened (the script ran before the window had its browser and toolbox) is gone, and a window that closes while the script starts no longer ends up in the health registry.
- A `profiles.ini` with `IsRelative=` empty or with a value that is not a boolean, or with a NUL byte in a path, is `PAF-102` with a hint, and a missing home folder is `PAF-101`, instead of "this is a bug" (`PAF-900`, exit 70). `--profile` or `--firefox-dir` given as a link that loops is a usage error on every Python version.
- `doctor` no longer waits for ever on a named pipe called `user.js`, `userChrome.css`, `prefs.js` or the status file, and it reports the loader pin the way `install` would refuse it (`PAF-203` for a malformed `FXAC_COMMIT`, `PAF-207` or `PAF-305` for an override, by system).
- Adding the `@import` after a closing comment in a CRLF file without a final line break no longer leaves a lone CR, and running the edit twice changes nothing.
- Ctrl+C in the middle of a plan says how many steps had finished and that the running step was interrupted.
- The message "Firefox cannot run the script without them.run the script." is fixed; the texts that said `doctor` and `--dry-run` change nothing although they write the log now say so; error messages of an edit name `userChrome.css` and not its temporary file.
- A folder is refused as Flatpak only when its path has `/flatpak/app/` or `/flatpak/runtime/`; `/usr/lib64/firefox` is searched; the invisible direction marks U+200E, U+200F and U+061C are neutralised in reports.

### Security

- **The root copy of the loader on Linux and macOS is verified.** The bytes of `config.js` and `defaults/pref/config-prefs.js` are checked against the SHA-256 values pinned next to the fx-autoconfig commit and the very bytes that were checked go to `sudo` (`sudo install -m 644 /dev/stdin <destination>` on Linux, `sudo tee` and `sudo chmod` on macOS, which has not been run on a Mac): the file in the temporary checkout is not read a second time. With `FXAC_REPO` or `FXAC_COMMIT` the copy is refused (`PAF-207`) unless `--allow-unverified-loader` is given, and the log then records that the copy was made without verification.
- **`--firefox-dir` must be a Firefox folder** (`PAF-109`), so `--firefox-dir /usr/lib` can no longer make `sudo` write `/usr/lib/config.js`. A `chrome/utils` folder that is a symbolic link is refused (`PAF-404`) before anything is copied through it.
- **A named pipe, a socket, a device or a folder behind `userChrome.css` or `user.js` is never replaced**: the command stops with `PAF-402` before it changes anything.
- **`--install-completion` is refused for PowerShell.** Typer's installer first runs
  `Set-ExecutionPolicy Unrestricted -Scope CurrentUser`, which lets any script run, before it writes to the
  PowerShell profile, and it has no option to skip that. Peek-a-Foxy replaces that installer with a message
  that exits with code 1 and changes nothing; in PowerShell, run `peek-a-foxy --show-completion` and add what
  it prints to your PowerShell profile yourself. bash, zsh and fish are not affected.
- **CI.** Every action, including the third-party `browser-actions/setup-firefox`, and every pre-commit hook is pinned by its full commit hash with the version in a comment; no checkout keeps the token in `.git/config` (`persist-credentials: false`); the standalone program is built from a lock where every file is hashed (`pip install --require-hashes`), and the job that can sign the attestation is separate from the job that runs the build.

### Documentation

- The READMEs now introduce Peek-a-Foxy as a customization tool for Firefox, say that macOS has never been tried on a real Mac, and describe the PowerShell completion, the empty folders that `uninstall` removes and the help of `--yes` and `--log-file` in `uninstall` and `logs`.
- The READMEs, `CONTRIBUTING.md`, `SECURITY.md` and the issue forms now cover the diagnostics (`doctor`, `logs`, the log, the status file, the exit codes and a table of every `PAF-` code, in English and Portuguese), the new default shortcuts, the Windows install routes and the elevation model with its residual risk, and the release steps of the standalone program. The bug report form asks for the output of `peek-a-foxy doctor --copy`.
- The roadmap section points to the GitHub Project instead of listing items.
- The README says that the backup holds the file as it was when a version that makes backups first changed it, and that Firefox must be closed for `uninstall` to remove the status file for good.

### Known issues

- The administrator prompt, a Firefox update replacing its folder, Microsoft Store builds, per-user
  installs, the real title bar and window dragging, hover and menus, native drag, AltGr layouts, the
  consoles (cmd, PowerShell, Windows Terminal, Git Bash), antivirus and long paths have only been
  exercised on a headless CI runner, not by hand on a desktop.
- The elevated PowerShell script has been run with PowerShell 7 on Linux and in tests, but not yet on
  Windows PowerShell 5.1, which is what the administrator step starts. Not yet checked on Windows: how
  the script behaves under real Constrained Language Mode or AppLocker, whether an antivirus questions
  an `-EncodedCommand` start, `install.ps1` under Windows PowerShell 5.1, the PyInstaller build and its
  smoke test on a Windows runner, and the attestation job on a real release.
- With the title bar drawn by Firefox, a slim row with the window buttons stays when the tab bar is
  hidden; turn on Firefox's own title bar to collapse it fully.
- The runner image's Firefox already uses autoconfig (`mozilla.cfg`); the loader still worked there.
  Another `general.config.filename` set elsewhere is not detected.
- The standalone Windows program still needs Git for Windows, and it is not published yet: the program,
  the install script and the Scoop and winget manifests exist only as what a release will attach.
- A hard kill (power loss, `kill -9`) between the temporary file and the rename leaves a file named `<file>.<pid>.<random>.peek-a-foxy.tmp` next to the user's file. The user's file itself is never half written; the leftover can be deleted by hand.
- The edit replaces the file, so a hard link to `userChrome.css` is broken (the link becomes a separate file), and extended attributes, ACLs and the SELinux label of the old file are not copied to the new one.
- The step that checks for a change made by another program compares the content just before the rename; a change in the few microseconds between that check and the rename is still lost.
- When `install` creates `userChrome.css` (there was none) and `uninstall` is the first command to change it afterwards, the backup copy already holds Peek-a-Foxy's `@import` line.
- A pref that shares a line with another (`user_pref("a", 1); user_pref("b", 2);`) is seen only when it is the first on its line.
- The copy of `chrome/utils` is refused through a link, but the plain copy of the Peek-a-Foxy files into the profile still writes through a symbolic link at `chrome/` or `chrome/JS`, without a backup.
- `--install-completion` is Typer's installer for bash, zsh and fish: it edits the shell's startup file outside the atomic edits and the log. For PowerShell it is refused (see *Security*).
- On Windows, when the Firefox folder is writable by you but the direct copy still failed (a read-only `config.js`, a file held by an antivirus), a program of yours could in theory replace the `defaults` folder by a junction between the checks of the elevated script and its writes; what could be written is limited to the fixed content of the two pinned files.
- Windows is unverified for: the broken pipe handling (the errors Windows raises for a closed pipe differ) and an antivirus holding the file when the rename happens (the edit fails with `PAF-402`, safe to repeat).
- The settings-page check appears in the status file only after the Peek a Foxy settings page has been opened once in the current Firefox session.
- If Firefox is running when you run `uninstall`, it writes the status file again; close Firefox first, or delete the file after closing it.

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

[Unreleased]: https://github.com/paodelonga/peek-a-foxy/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/paodelonga/peek-a-foxy/releases/tag/v0.2.0
[0.1.0]: https://github.com/paodelonga/peek-a-foxy/releases/tag/v0.1.0
