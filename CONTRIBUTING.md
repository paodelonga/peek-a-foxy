# Contributing

Thanks for helping out. The workflow is small on purpose.

## Branches

| Branch | Purpose |
| --- | --- |
| `main` | Stable. Only receives merges from `devel/devel`. Releases are tagged here (`vX.Y.Z`). |
| `devel/devel` | Development. Integrates finished work and is where CI must stay green. |
| `devel/<topic>` | One change each (`devel/urlbar-focus`, `devel/fix-installer-macos`, ...). Branch from `devel/devel`, merge back into it. |

```text
devel/<topic>  ──►  devel/devel  ──►  main
```

1. `git switch devel/devel && git switch -c devel/<topic>`
2. Commit, run the tests, push the branch and open a pull request into `devel/devel`.
3. When `devel/devel` is ready to release, open a pull request from `devel/devel` into `main` and tag the release.

Hotfixes for `main` follow the same path; they just go through `devel/devel` quickly.

## Commits

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) and releases follow [Semantic Versioning](https://semver.org/), so the commit types decide the next version:

```text
<type>(<optional scope>): <summary in the imperative, up to ~72 characters>

<optional body: why, not what; wrap at ~72 columns>
```

| Type | Use for | Version bump |
| --- | --- | --- |
| `feat` | a new feature | minor |
| `fix` | a bug fix | patch |
| `perf` | a performance improvement | patch |
| `refactor` | code change that neither fixes a bug nor adds a feature | none |
| `docs` | documentation only | none |
| `test` | adding or fixing tests | none |
| `ci` / `build` | CI configuration, build or install tooling | none |
| `style` | formatting only | none |
| `chore` | anything else that doesn't touch behavior | none |

A breaking change adds `!` after the type (`feat(css)!: ...`) or a `BREAKING CHANGE:` line in the body, and bumps the major version.

```text
feat(urlbar): reveal the navigation bar when the URL bar gets focus
fix(installer): do not overwrite an existing config.js
docs: add a Portuguese README
```

One logical change per commit. CI checks every commit message of a pull request with commitizen.

## Releasing

Releases are cut from `main` by the maintainer. The version lives in `pyproject.toml`, the notes in
`CHANGELOG.md` (written by hand, in the [Keep a Changelog](https://keepachangelog.com/) format), and
[commitizen](https://commitizen-tools.github.io/commitizen/) does the mechanical part.

1. On `devel/devel`, move the `[Unreleased]` entries of `CHANGELOG.md` under the new version and date,
   and commit that (`docs: changelog for X.Y.Z`).
2. Run `cz bump --dry-run` to see the version the commits since the last tag call for, then `cz bump`:
   it updates `pyproject.toml`, makes the commit `chore(release): X.Y.Z` and creates the annotated tag
   `vX.Y.Z`.
3. Open a pull request from `devel/devel` into `main` and merge it once CI is green, then push the tag
   (`git push origin vX.Y.Z`).
4. Create the GitHub release from the tag, with the changelog entry as its notes, and publish it.
5. Publishing the release starts `.github/workflows/exe.yml`, which builds the standalone Windows program
   and attaches it to the release (see below). Check that the release page then lists
   `peek-a-foxy.exe`, `peek-a-foxy.exe.sha256`, `install.ps1` and the four manifest files, and that
   `gh attestation verify peek-a-foxy.exe -R paodelonga/peek-a-foxy` succeeds for the downloaded program.

The commit types decide the number: a `feat` is a minor bump, a `fix` a patch, and a `!` or a
`BREAKING CHANGE:` footer a major bump (a minor one while the version is below 1.0).
The first release, `v0.1.0`, was made by hand with the same steps, since there was no earlier tag.

### The standalone Windows program

`exe.yml` runs on every pull request that touches `packaging/`, `src/`, `chrome/`, `pyproject.toml` or the
workflow itself (it builds and tests, and publishes nothing), and on a published release (it also
publishes). It has three jobs:

- **build** installs the pinned build tools from `packaging/requirements-build.txt` (a lock in which
  every file is hashed; regenerate it with the `uv pip compile` command in its first lines), builds
  `peek-a-foxy.exe` with PyInstaller, and smoke-tests it: `--version`, an unknown `--elevated-copy` option
  (a usage error, exit code 2), an `install` into a throwaway profile, and a Firefox registered in a
  temporary registry key that `doctor --json` must find and whose version must equal the one in
  `pyproject.toml`. It also checks that `install.ps1` parses.
- **attest** (only on a release) signs a build provenance statement for the program through Sigstore. It
  is a job of its own so that the token that can sign never sits beside the build, which runs
  third-party code.
- **publish** (only on a release, after the other two) fills the manifest templates of
  `packaging/templates` with the version and the hash (`packaging/render_manifests.py`) and attaches the
  program, its `.sha256`, `install.ps1` and the Scoop and winget manifests to the release.

Things to know when you make a release:

- The workflow does not compare the release tag with the version in `pyproject.toml` (the smoke test
  compares the program with `pyproject.toml`, not with the tag). `cz bump` writes both, so create the
  release from the tag it made and never tag by hand.
- The Scoop and winget manifests are only attached to the release as files. Submitting them to winget's
  community repository (`microsoft/winget-pkgs`) and to a Scoop bucket is a manual step that has not
  been done yet, so the READMEs say that neither route works.
- The program is not code-signed. Code signing (SignPath) is tracked in the GitHub Project.
- When you change what the program imports by name, add it to the `--hidden-import` list of the build
  (`tests/test_packaging.py` fails if a module that is imported by name is missing from it).

## Updating the pinned fx-autoconfig

The loader is fetched at one fixed commit (`DEFAULT_COMMIT` in `src/peek_a_foxy/loader.py`), never at a
branch or a tag, so what gets installed can't change under users. To move to a newer fx-autoconfig:

1. Read what changed upstream between the current commit and the new one
   (`https://github.com/MrOtherGuy/fx-autoconfig/compare/<old>...<new>`), paying attention to
   `program/config.js`, `program/defaults/pref/config-prefs.js` and `profile/chrome/utils/`: these are
   the files this project installs.
2. Put the new **full 40-digit hash** in `DEFAULT_COMMIT`. Abbreviated hashes, branches and tags are
   refused on purpose.
3. Put the SHA-256 values of `config.js` and `defaults/pref/config-prefs.js` at the new commit (with LF
   line endings) in `PINNED_SHA256` in `src/peek_a_foxy/elevate.py`. The copy into a folder that needs
   `sudo` or the administrator prompt checks the files against these values, so they must change
   together with the commit.
4. Run `pytest -m network` (the commit exists upstream, has the expected files, the pinned SHA-256 values
   match them, and GitHub serves it without its history) and `pytest -m browser` (the script still loads
   and works with it).
5. Update the short hash in the sample plan of `README.md` / `README.pt-BR.md` and add a `Changed` entry to
   `CHANGELOG.md`.

## Reporting problems and asking for things

Use the issue forms: bug reports ask for the details that matter here (Firefox build, desktop or
window manager, display server) and for the output of `peek-a-foxy doctor --copy`, which already holds
most of them. Security problems go through the private advisory form instead; see
[SECURITY.md](SECURITY.md).

## Development setup

Python 3.10 or newer. The runtime dependencies have a lower and an upper bound in `pyproject.toml`
(`typer>=0.16.0,<0.30`, `rich>=13.8,<16`): the lower ones are the oldest versions that pass the suite, and
the `lowest` job of `ci.yml` runs the suite with exactly those, so raise a lower bound only when you
need a newer feature, and move an upper bound only after the suite has run against the new release.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
peek-a-foxy --help
pre-commit install          # optional: runs ruff and checks your commit message on every commit
```

`pre-commit` runs the same checks as CI (whitespace, YAML, `ruff`, and the commit message format), so
problems show up before you push. `cz commit` asks for the type and the summary and writes a valid
message for you. Both are optional: CI is what enforces them.

## Tests and lint

```bash
pytest                                  # unit, property-based and CLI tests; no network needed
pytest --cov --cov-report=term-missing  # with branch coverage (CI requires at least 90%)
pytest -m network                       # also clones the real fx-autoconfig at the pinned commit
pytest -m browser                       # drives a real headless Firefox (see below)
ruff check . && ruff format .           # lint and format
```

The tests are written mainly for the unexpected, though not only: the default path has its tests too, but for every change ask what the strangest realistic input or state is and test that (NUL bytes, huge or empty files, links that loop, permission denied, a read-only or full disk, an unset home folder, a closed stdout, a hanging external tool, text that is not UTF-8, paths with newlines or spaces, concurrent runs, wrong JSON types, a clock that goes backwards). Prefer property-based tests (Hypothesis) where the input space is large, and say in a pull request which of your tests are adversarial and which only cover the default behaviour.

What the tests cover, and why:

- **The user's files** (`test_userfiles.py`, `test_properties.py`): CRLF and LF, missing final newline,
  BOM, odd Unicode separators, commented-out prefs, symlinked `userChrome.css`, `@charset`. These
  files belong to the user, so edits must be idempotent and must not touch other lines;
  [Hypothesis](https://hypothesis.readthedocs.io/) generates arbitrary file contents to check that.
- **What `uninstall` leaves behind** (`test_installer.py`): `chrome/JS` and `chrome/resources` are removed
  only when they are empty, so a folder that holds a file of the user's (hidden or oddly named ones
  too), a folder that is a link or a junction, one that the system refuses to remove, one that gets a file
  or vanishes between the check and the removal, and an empty `chrome/utils` are all left alone, and the
  uninstall goes on.
- **Failure modes** (`test_robustness.py`): failed or missing `git`, failed `sudo`, read-only
  directories, invalid UTF-8, a half-installed state. A failure must be a clean error, never a
  traceback or a partly modified profile.
- **Environments** (`test_platform.py`, `test_profiles.py`): Linux, macOS and Windows paths (the platform
  is faked), several Firefox installations, odd `profiles.ini` files.
- **Interactive choices** (`test_cli.py`, `test_robustness.py`): profile and installation pickers,
  declining the confirmation, invalid numbers.
- **The help texts and the shell completion** (`test_cli_help.py`, `test_completion_safety.py`): each
  option says what it does for its own command (`--yes` in `install`, `uninstall` and `logs`, `--log-file`
  in `logs`) and wraps like prose; `--install-completion` is refused for PowerShell without starting any
  program, because Typer's installer would set the execution policy to `Unrestricted`, and it still installs
  for bash, zsh and fish.

- **What the user reads** (`test_markup.py`, `test_reports.py`): paths and git output that look like Rich
  markup (`[/x]`, `[bold red]`) are printed as typed; the closing panel says what actually happened
  (`--skip-loader`, a loader that was already there); a failed step says which steps had finished.
- **The Python side and the script agree** (`test_contract.py`): the pref names, the shortcuts, the
  status file's name and schema, the issues link and the closing sentence of the report are compared with
  the ones in `chrome/resources/peekafoxy.sys.mjs`, and the README's CSS example with `autohide.css`, so
  renaming one side fails a test.
- **The documents** (`test_docs.py`): both READMEs have a table of every error code that equals the
  registry in `errors.py` (word for word in English; in Portuguese the codes, commands and links must match),
  the default shortcuts in them are the ones in the code, no text teaches `Ctrl+Alt+U` as a default, the
  Windows notes name the PowerShell route and not `python.exe`, and the two READMEs have the same
  structure. Change a hint in `errors.py` and the English table fails until you copy the new text.
- **Errors and the log** (`test_errors.py`, `test_cli_errors.py`, `test_logs.py`, `test_log_paths.py`,
  `test_redaction_edges.py`, `test_redaction_hostile.py`, `test_broken_pipe.py`): every code is
  registered once and used, each failure ends as a message with a code and a hint, the log is private and
  only goes to a log, and redaction hides the home folder, user name, profile names and secrets in every
  spelling they can have (and gives the same result when applied twice).
- **The doctor** (`test_doctor*.py`, `test_cli_doctor.py`, `test_status.py`): every check, every format,
  hostile files, links, sizes and permissions, a report that is saved, copied or cut off. The invariant is
  that whatever is on the disk, a report comes out and no check says `PAF-900`.
- **Administrator rights** (`test_loader_privilege.py`, `test_elevate.py`, `test_elevate_pwsh.py`): the
  copy through `sudo` (a fake `sudo` that is a real executable, so the bytes it receives are checked),
  and on Windows the generated PowerShell script and its command line (no folder name can change a
  character of the code), the length guard, and the real script run with PowerShell for every exit code. The PowerShell
  tests need `pwsh` (PowerShell 7) on Linux or macOS and are skipped without it; point
  `PEEK_A_FOXY_PWSH` at a `pwsh` that is not on `PATH`. Windows-only cases (junctions, short names, a
  substituted drive, a line of exactly the limit) run on a Windows runner.
- **Packaging** (`test_packaging.py`, `test_install_script.py`, `test_workflows.py`): the manifests filled
  from their templates, the build lock, the hidden imports, `install.ps1` run in a real PowerShell, and
  the workflow files (actions pinned by commit, read-only permissions, time limits).
- **The suite does not depend on your machine** (`test_isolation.py`): your git configuration, home
  folder and variables such as `FXAC_REPO` do not leak into a test.
- **The settings page** (`tests/browser/test_settings.py`, `test_settings_ui.py`,
  `test_shortcut_format.py`): the category and its navigation next to Firefox's own, each control and its
  refusals, the live effect in several windows, the shortcut format and the texts, the Portuguese page, and
  a Firefox whose page changed (the script must add nothing and say why). Firefox's own markup is the thing most likely to change under
  this page: if one of these fails after a Firefox update, read `requirements()` in
  `chrome/JS/autohide-prefs.uc.js` first.
- **The script and the CSS in a real Firefox** (`tests/browser/`): a headless Firefox driven over
  Marionette, with the real fx-autoconfig loaded from a *copy* of your Firefox install (the loader has to
  be written into it) and a throwaway profile. They check what actually happens to the window: both
  buttons exist, shortcuts toggle only their own window, the bars collapse to the strip and open to
  their natural height without clipping, the bookmarks bar follows the navigation bar, a bar stays open while something is dragged out of it, the prefs are registered as booleans, Customize Toolbar and full screen are left alone, the greeting
  shows once and its button opens the song. `test_pointer.py` and `test_real_keys.py` use a real pointer
  and real key presses (Marionette actions) instead of synthetic events, `test_popups.py` covers popups, and
  `test_diagnostics.py` covers the health check, the status file and the Support group against the Python
  reader. They need network access and Firefox: point `PEEK_A_FOXY_FIREFOX` at its binary, or the first
  Firefox found is used.

Firefox changes its own interface without notice, so the browser tests also run every week against
the current release, the Beta and the ESR, on Linux and Windows (`.github/workflows/firefox-weekly.yml`, or
start it by hand from the Actions tab). A red run there means the script or the CSS needs attention before
users notice.

The installer tests run against temporary profiles and a local stand-in for the fx-autoconfig repository,
so nothing touches your real Firefox. Most browser tests reveal the bars through an attribute, focus or a
popup, and the pointer and key tests above cover real hover and real shortcuts; a drag started by hand
(native drag and drop of a bookmark) is still not reproduced by any test, so check it by hand.

When you fix a bug, add the test that would have caught it.

## Style

- Python: type-annotated, formatted and linted with ruff (line length 100). Keep logic in small
  functions that take and return plain values, so it can be tested without Firefox; the CLI layer
  (`cli.py`) only asks, prints and calls into the rest.
- Installer changes are expressed as a *plan* of steps (`installer.py`), so `--dry-run`, the
  confirmation and the tests all see the same list of changes.
- CSS: sizes and timings go in the variables at the top of `chrome/autohide.css`. Each bar has a
  *collapsed* rule and a *revealed* rule that must stay exact opposites (see the comment at the top of
  the file); adding a way to reveal a bar means adding it to both.
- JavaScript: widget callbacks must not use anything from the window script's scope (see the
  comment in `chrome/JS/autohide.uc.js`). Prefs, limits, the shortcut format and every user-visible
  text live in `chrome/resources/peekafoxy.sys.mjs`, shared by both scripts; a new pref goes there and
  in `OWN_PREFS` (`userfiles.py`), and a test checks that the two lists agree.
- Keep `README.md` and `README.pt-BR.md` in sync, with the same structure and the same meaning on each
  line. A new error code goes in `src/peek_a_foxy/errors.py` (its `meaning` and `hint` are written for
  someone who has never opened a terminal) and in the table of both READMEs; a test compares the
  English table with the registry. The `CHANGELOG.md` entries under `[Unreleased]` are written as the
  change happens.
- In the Portuguese texts, technical terms and loanwords that the community uses in English (issue, log,
  commit, pull request, hover, loader, script, link, doctor) stay in English; words with a natural
  Portuguese equivalent (atalho, barra de ferramentas, favoritos, área de transferência, restaurar,
  pasta pessoal, nome de usuário) stay Portuguese.
