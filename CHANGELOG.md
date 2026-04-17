# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Public API (types exported from `claude_backup_cron`, CLI subcommands,
config schema keys) follows SemVer. The internal subprocess wrapping of
`git` / `aws` / `age` / `crontab` is not considered API — their exit
codes and outputs are passed through as-is.

## [Unreleased]

## [0.1.0] — 2026-04-18

### Added

- Initial public release.
- `claude-backup-cron run` — idempotent scheduled backup with
  content-hash change detection.
- `claude-backup-cron show-config` — print the resolved config.
- `claude-backup-cron install-cron --schedule` / `uninstall-cron` —
  manage a single marked block in the user crontab.
- `claude-backup-cron version`.
- TOML config schema: `[global]`, `[[sources]]`, `[[destinations]]`
  with three destination kinds: `git`, `s3`, `local`.
- Optional age encryption per destination via `encrypt_to = "age1..."`.
- Webhook alerting on failure (Discord/Slack shape-compatible).
- Deterministic tarball output (mtime / uid / gid zeroed) — identical
  source trees produce identical backup bytes.
- Per-destination retry policy: one destination failing does not block
  the others.
- Dry-run (`--dry-run`) and JSON (`--json`) output modes.
- Typed Python library API (`py.typed`): `Config`, `SourceSpec`,
  `DestinationSpec`, `RunReport`, `StepResult`, `Artefact`, `Upload`,
  `load`, `run`.
- CI matrix: Python 3.10/3.11/3.12/3.13 × Linux/macOS/Windows.
- CodeQL analysis, Dependabot updates, Trusted Publishing to PyPI.

[Unreleased]: https://github.com/hinanohart/claude-backup-cron/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hinanohart/claude-backup-cron/releases/tag/v0.1.0
