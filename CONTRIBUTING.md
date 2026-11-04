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

One logical change per commit.

## Releasing

Releases are cut from `main` by the maintainer:

1. On `devel/devel`: set the new `version` in `pyproject.toml` and move the `[Unreleased]` entries of
   `CHANGELOG.md` under the new version and date.
2. Open a pull request from `devel/devel` into `main` and merge it once CI is green.
3. Tag the merge commit `vX.Y.Z` (annotated: `git tag -a vX.Y.Z -m "vX.Y.Z"`) and push the tag.
4. Create the GitHub release from the tag, with the changelog entry as its notes.

The commit types decide the number: a `feat` is a minor bump, a `fix` a patch, and a `!` or a
`BREAKING CHANGE:` footer a major bump (a minor one while the version is below 1.0).

## Reporting problems and asking for things

Use the issue forms: bug reports ask for the details that matter here (Firefox build, desktop or
window manager, display server). Security problems go through the private advisory form instead; see
[SECURITY.md](SECURITY.md).

## Development setup

Python 3.10 or newer.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
peek-a-foxy --help
```

## Tests and lint

```bash
pytest                                  # unit, property-based and CLI tests; no network needed
pytest --cov --cov-report=term-missing  # with branch coverage (CI requires at least 90%)
pytest -m network                       # also clones the real fx-autoconfig at the pinned commit
pytest -m browser                       # drives a real headless Firefox (see below)
ruff check . && ruff format .           # lint and format
```

What the tests cover, and why:

- **The user's files** (`test_userfiles.py`, `test_properties.py`): CRLF and LF, missing final newline,
  BOM, odd Unicode separators, commented-out prefs, symlinked `userChrome.css`, `@charset`. These
  files belong to the user, so edits must be idempotent and must not touch other lines;
  [Hypothesis](https://hypothesis.readthedocs.io/) generates arbitrary file contents to check that.
- **Failure modes** (`test_robustness.py`): failed or missing `git`, failed `sudo`, read-only
  directories, invalid UTF-8, a half-installed state. A failure must be a clean error, never a
  traceback or a partly modified profile.
- **Environments** (`test_platform.py`, `test_profiles.py`): Linux and macOS paths (the platform is
  faked), several Firefox installations, odd `profiles.ini` files.
- **Interactive choices** (`test_cli.py`, `test_robustness.py`): profile and installation pickers,
  declining the confirmation, invalid numbers.

- **The script and the CSS in a real Firefox** (`tests/browser/`): a headless Firefox driven over
  Marionette, with the real fx-autoconfig loaded from a *copy* of your Firefox install (the loader has to
  be written into it) and a throwaway profile. They check what actually happens to the window: both
  buttons exist, shortcuts toggle only their own window, the bars collapse to the strip and open to
  their natural height without clipping, the bookmarks bar follows the navigation bar, a bar stays open while something is dragged out of it, the prefs are registered as booleans, Customize Toolbar and full screen are left alone, the greeting
  shows once and its button opens the song. They need network access and Firefox: point
  `PEEK_A_FOXY_FIREFOX` at its binary, or the first Firefox found is used.

The installer tests run against temporary profiles and a local stand-in for the fx-autoconfig repository,
so nothing touches your real Firefox. Hover itself can't be simulated in headless Firefox, so the tests
reveal the bars through the other reveal conditions (focus, `tabs-flash`); check hover by hand.

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
  comment in `chrome/JS/autohide.uc.js`).
- Keep `README.md` and `README.pt-BR.md` in sync.
