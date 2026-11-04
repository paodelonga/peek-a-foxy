# Security policy

## Supported versions

Peek-a-Foxy is pre-1.0. Only the latest release, and `main`, get security fixes.

## What this tool does that deserves care

- It installs a script that runs in Firefox's **privileged** browser context, through
  [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig). That is how every userChrome.js setup
  works, and it is by design: anything placed in the profile's `chrome/JS` folder runs with full
  browser privileges.
- It writes `config.js` and `defaults/pref/config-prefs.js` into Firefox's install directory, using
  `sudo` only when that directory is not writable by you. It never overwrites a different `config.js`.
- It downloads fx-autoconfig with `git`, at a pinned commit, and refuses to continue if the checked-out
  commit differs from the pinned one.

## What to report

Please report, for example:

- the installer writing or deleting files outside the profile and the Firefox install directory;
- a way to make the installer run unintended commands, or to install something other than the pinned
  fx-autoconfig commit;
- the script or the CSS exposing browser data, or loading remote code.

Not a vulnerability here: the fact that scripts in `chrome/JS` run with full privileges (see above), and
bugs in fx-autoconfig itself, which belong to [that project](https://github.com/MrOtherGuy/fx-autoconfig/issues).

## How to report

Use GitHub's private reporting: **Security > Report a vulnerability** on the repository page
(<https://github.com/paodelonga/peek-a-foxy/security/advisories/new>). Please do not open a public issue
for a vulnerability.

This is a small project maintained in spare time: reports are handled on a best-effort basis, with no
guaranteed response time.
