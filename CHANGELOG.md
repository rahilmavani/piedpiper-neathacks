# Changelog

All notable changes to `culprit-cli` are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Contributor docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and pull request
  templates, and a CI workflow that runs the test suite.

## [0.1.1] - 2026-10-12

### Added
- `culprit help`, and bare `culprit`, print the commands in the order you use them.
  `culprit help <command>` shows that command's options.

### Changed
- Help text no longer refers to internal spec sections.
- The neatlogs SDK logs warnings only, so its INFO lines no longer end up in `culprit comment` or
  `culprit export-costs` output. Set `NEATLOGS_LOG_LEVEL` to change this.

### Fixed
- A setting blanked in the shell (for example `NEATLOGS_API_KEY=`) now stays blank instead of being
  refilled from the repo's `.env` or the saved setup.

## [0.1.0] - 2026-10-11

First release on PyPI, under the Apache License 2.0.

### Added
- `culprit run` and `culprit resume`: a noise-aware bisect with a Fisher regression gate, 95% Wilson
  decisions with resampling, skipping of commits that won't install, staged and reused baselines,
  budget caps, and retries for temporary API errors.
- `culprit localise` and `culprit fix`: the responsible hunks by revert search, and a minimal fix
  verified on the full and held-out suites.
- `culprit report`, `culprit comment`, `culprit export-costs` and `culprit verify-trace`.
- `culprit ci`, `culprit drift` and `culprit audit`.
- `culprit init`: keys saved once per user, and a repo's eval module and suite.
- Optional tracing with neatlogs and intent from Entire checkpoints.

[Unreleased]: https://github.com/rahilmavani/piedpiper-neathacks/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/rahilmavani/piedpiper-neathacks/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rahilmavani/piedpiper-neathacks/releases/tag/v0.1.0
