# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a breaking change bumps the minor version).

## [Unreleased]

## [0.1.0] - 2026-11-04

### Added

- Per-window autohide for Firefox's tab bar and navigation bar, with a hover strip, the shortcuts
  `Ctrl+Alt+T` / `Ctrl+Alt+U`, and a toolbar button for each.
- The bookmarks bar hides and shows together with the navigation bar.
- A one-time greeting notification, in English or Brazilian Portuguese.
- The `peek-a-foxy` command: `install` and `uninstall`, with a reviewable plan, `--dry-run`, an
  interactive profile and Firefox picker, `-h`, and shell completion.
- Tests for the installer (including odd user files and failure modes) and for the script and CSS in a
  real headless Firefox.

### Known issues

- The bookmarks bar can still close when a bookmark is pressed and held or dragged, on at least one
  setup (Linux, tiling window manager). See the roadmap in the README.

[Unreleased]: https://github.com/paodelonga/peek-a-foxy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/paodelonga/peek-a-foxy/releases/tag/v0.1.0
