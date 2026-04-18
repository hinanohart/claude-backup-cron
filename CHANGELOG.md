# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Public API (types exported from `claude_backup_cron`, CLI subcommands,
config schema keys) follows SemVer. The internal subprocess wrapping of
`git` / `aws` / `age` / `crontab` is not considered API — their exit
codes and outputs are passed through as-is.

## [Unreleased]

## [0.1.2] — 2026-04-18

### Security

- **CRITICAL — plaintext tarball no longer lingers in `pack_dir`.**
  Prior flow left the unencrypted source tar sitting on disk
  indefinitely even when every destination had `encrypt_to` set,
  defeating the whole encryption guarantee. Backup now `_safe_unlink`s
  both the plaintext tar and the per-destination encrypted work copy
  after every destination has been dispatched.
- **`state_dir`, `pack_dir`, `work_dir` mode 0700** enforced on
  startup (existing dirs chmod-downgraded if they were permissive).
- **Tar symlink-escape blocked.** A directory symlink inside the
  source tree (e.g. `source/mem -> /etc`) was silently followed by
  `tarfile.add`, pulling `/etc/shadow` and friends into the backup
  even though each leaf file is a regular file. `_add_filter` now
  resolves each member's live path and refuses anything that escapes
  the source root. Matching check added to `hash_tree`.
- **Git destination branch-injection blocked.** A TOML-supplied
  `branch = "--mirror"` / `--delete main` / `refs/heads/*:refs/heads/*`
  would otherwise have turned `git push origin <branch>` into a
  destructive refspec. New `_SAFE_BRANCH_RE` rejects anything that
  isn't a plain ref name. `--` separator added before `dest.remote`
  in `git clone` and `git remote add`.
- **Cron-line injection blocked.** `scheduler.install`'s schedule
  argument is now validated against a strict regex for 5/6-field cron
  expressions or `@alias`. A schedule like `"* * * * *; rm -rf ~"`
  used to land verbatim in the crontab line.
- **`age` binary authentication.** `age_available()` now runs
  `age --version` and requires a recognised `v?MAJOR.MINOR` line with
  MAJOR ≥ 1. Prior check accepted any binary on PATH, so a
  user-writable `age` shim earlier on PATH could silently produce
  `.age` files that were actually plaintext.
- **`_AGE_RECIPIENT_RE`** accepts both X25519 (`age1…` bech32) and
  SSH public-key (`ssh-rsa` / `ssh-ed25519` / `ecdsa-sha2-…`)
  recipients. Restores support broken by earlier validation that
  only accepted X25519.
- **Subprocess stderr scrubbed** before any user-facing log /
  webhook. `_scrub` now redacts GitHub tokens (`ghp_` / `gho_` /
  `ghs_` / `ghr_` / `github_pat_`), AWS access key IDs, Slack
  tokens, `Authorization` / `Bearer` / `token` / `password` headers,
  and query-string `token=` / `key=` / `sig=`. `dispatch_s3`
  stderr is now also scrubbed (was bare previously).
- **Alerting scheme allowlist.** `alerting.post` refuses non-http(s)
  webhook URLs. A TOML-supplied `alert_webhook` pointing at a
  `file://` / `ftp://` URL previously turned the alerting path into a
  1-bit SSRF/LFI oracle.
- **`retain = true` (bool) rejected** explicitly.
  `isinstance(True, int)` is True in Python so a config typo used to
  silently mean `retain=1`.

### Privacy

- **Maintainer username slug removed from published example path.**
  The README, `examples/config.toml`, and the `config.py` module
  docstring previously showed `~/.claude/projects/-home-<slug>/memory`
  with the maintainer's local OS account name embedded (Claude Code
  derives the slug from `$HOME`). Replaced with
  `~/.claude/projects/-home-USER/memory`. `examples/config.toml`'s
  `encrypt_to = "age1abcdef…"` placeholder replaced with
  `age1YOUR_PUBLIC_RECIPIENT_HERE_RUN_age-keygen_TO_GENERATE` so
  it's obviously broken on copy.

### Governance

- `.github/CODEOWNERS` added.
- `release.yml` gains identity-leak grep gate that fails the job on
  the class of leak described above.

## [0.1.1] — 2026-04-18

### Changed

- `dispatch_git` now passes a bot identity
  (`-c user.name=claude-backup-cron -c user.email=<bot>@noreply.invalid`)
  so backups work in minimal cron / CI environments that have no
  `user.name` / `user.email` set globally.
- Skip the whole `test_scheduler` module on Windows (cron is POSIX-only
  and Task Scheduler is out of scope for v0.1).
- `test_cli` and `test_config` now use POSIX-style paths when writing
  TOML fixtures so Windows backslashes don't get interpreted as TOML
  escape sequences.
- `release.yml` now auto-creates a GitHub Release (with the built
  wheel + sdist attached) after the PyPI publish succeeds.

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
