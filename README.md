# firefox-autohide

Auto-hides Firefox's horizontal tab bar and navigation bar (urlbar), **per window**.

- The tab bar collapses to a thin hover strip above the URL bar (hovering the URL bar does not reveal it).
- It slides open when the cursor is on the strip, briefly on every tab switch (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) and when a new tab opens (links, background tabs), and while a tab context menu is open.
- The navigation bar (urlbar, buttons, extensions) can be hidden too. It is revealed by its own hover strip, whenever the urlbar gets focus (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`), and while its dropdown or a toolbar popup is open. Off by default.
- Toggles act **on the current window only** and the state is saved with the session:
  - tabs: toolbar button or `Ctrl+Alt+T`
  - urlbar: `Ctrl+Alt+U` (no button, since it would live in the bar that gets hidden)

Tested on Firefox Developer Edition on Linux. Requires a Firefox with CSS `:has()` (121+).

## How it works

| File | Role |
| --- | --- |
| `chrome/autohide.css` | Collapses/reveals `#TabsToolbar` and `#nav-bar`, keyed on the `autohide-tabs` / `autohide-urlbar` attributes of the window root. |
| `chrome/JS/autohide.uc.js` | Sets those attributes per window, handles the button, the shortcuts and the tab-switch flash. |
| [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) | Loader that lets Firefox run `*.uc.js` scripts. Fetched by the installer, pinned to a commit. |

Pure CSS cannot detect tab switches or toggle per window, hence the script. Firefox only runs such scripts through an
autoconfig file in its install directory, which needs root and may be replaced by package updates.

## Install (Linux)

```bash
git clone <this repo> && cd firefox-autohide
./install.sh            # default profile, auto-detected Firefox dir
```

Options: `--profile DIR`, `--firefox-dir DIR`, `--skip-loader` (profile files only), `--dry-run`, `--uninstall`.

The installer:
1. copies the CSS and script into `<profile>/chrome/`, and adds one `@import` line at the top of your `userChrome.css` (your own rules stay untouched);
2. sets `toolkit.legacyUserProfileCustomizations.stylesheets` and `userchrome.tabs.autohide` in `user.js`;
3. clones fx-autoconfig at a pinned commit (verified), copies `chrome/utils/` into the profile, and installs `config.js` and
   `defaults/pref/config-prefs.js` into the Firefox dir, using `sudo` only if that dir isn't writable.

Then close **all** Firefox windows and start it again. If the button or shortcut is missing, clear the startup cache from `about:support`.
Add **Tabs autohide** from *Customize Toolbar*.

After a Firefox package update, re-run `./install.sh` if the loader disappears.

## Settings

- `userchrome.tabs.autohide` (default `true`) and `userchrome.urlbar.autohide` (default `false`), in about:config: initial state for windows without a saved one. Existing windows keep their own state. The installer never overwrites them once set.
- Strip and bar heights are in `chrome/autohide.css`.

## Known limitations

- Linux only for now. macOS/Windows need different profile and install paths in `install.sh`.
- Some tiling window managers steal the pointer when a context menu opens, so the "stay open during context menu" rule may not help there.
- The loader executes arbitrary scripts from the profile's `chrome/JS`; only install scripts you trust.

## Uninstall

```bash
./install.sh --uninstall
```

Removes this project's files and prefs. It leaves `chrome/utils` and the loader in the Firefox dir, since other scripts may use them.

## License

MIT, see `LICENSE`. fx-autoconfig is MIT-licensed by its author and is not redistributed here.
