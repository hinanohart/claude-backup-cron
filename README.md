# claude-backup-cron

Scheduled, encrypted backups for small-but-high-value directories —
Claude Code's `memory/` folder in particular, but anything the shape
would fit.

## What it does

* Tars each configured source directory into a deterministic artefact.
* Skips the run entirely if nothing has changed since last time
  (content hash, not mtime — mtime lies).
* Optionally encrypts the artefact with [age](https://age-encryption.org/)
  before it ever reaches a destination.
* Fans out to one or more destinations — a private git remote, an S3
  bucket, a spare local drive — with independent success/failure per
  destination.
* On any failure, posts a short message to an optional webhook
  (Discord/Slack shape).
* Installs itself as a cron job with a one-liner.

Zero runtime dependencies on Python 3.11+; `tomli` backport on 3.10.
External binaries (`git`, `aws`, `age`, `crontab`) are invoked only
when the corresponding feature is actually used.

## Why

The existing `memory-backup.sh` that ships in many Claude Code setups
is ~20 lines of bash: great for one machine, brittle in practice —
silent on failure, no encryption, single destination, no change
detection. This package is the "I want it to keep working while I'm
not watching" version: strict typing, deterministic artefacts,
structured failures, audit-friendly CLI.

## Install

```bash
pipx install claude-backup-cron
```

Or in a venv:

```bash
python3 -m venv ~/.local/venvs/claude-backup-cron
~/.local/venvs/claude-backup-cron/bin/pip install claude-backup-cron
```

See [`docs/INSTALL.md`](docs/INSTALL.md) for setup on each destination
kind (git remote, S3 bucket, local path).

## Configure

Default config location: `~/.config/claude-backup-cron/config.toml`.
Override with `$CLAUDE_BACKUP_CRON_CONFIG`.

Minimal example:

```toml
[global]
alert_webhook = "https://discord.com/api/webhooks/..."

[[sources]]
id = "claude-memory"
path = "~/.claude/projects/-workspace/memory"
exclude = [".git/*", "*.swp"]

[[destinations]]
id = "offsite-git"
kind = "git"
remote = "git@github.com:me/claude-memory-backup.git"
branch = "main"
encrypt_to = "age1abc..."   # omit to upload plaintext
```

Verify it parses:

```bash
claude-backup-cron show-config
```

A fuller example covering all three destination kinds lives in
[`examples/config.toml`](examples/config.toml).

## Run

```bash
claude-backup-cron run              # do the thing
claude-backup-cron run --dry-run    # package sources but don't upload
claude-backup-cron run --json       # machine-readable report on stdout
```

Exit codes:

| Code | Meaning                                                      |
|------|--------------------------------------------------------------|
| 0    | All steps succeeded (or nothing to do).                      |
| 2    | At least one source→destination step failed. Others may have succeeded. |
| 3    | Config or encryption setup error — nothing was uploaded.     |

## Schedule

```bash
claude-backup-cron install-cron --schedule "0 3 * * *"   # daily 03:00
claude-backup-cron uninstall-cron
```

The installer manages a single block in your user crontab, marked
with `# claude-backup-cron managed entry`. Re-running `install-cron`
replaces the previous block in place.

## Encryption

Set `encrypt_to = "age1..."` on a destination. The artefact is piped
through `age --recipient <...>` before upload. We refuse to fall back
to plaintext on encryption failure — that's exactly the degradation
you don't want in a backup tool.

To decrypt later:

```bash
age --decrypt -i ~/.ssh/my-age-key claude-memory-abc123.tar.age \
  | tar -xvf -
```

## Library API

```python
from claude_backup_cron import load, run

config = load()
report = run(config, dry_run=False)
if not report.ok:
    for failure in report.failed:
        print(failure.source_id, "→", failure.destination_id, failure.message)
```

All public types are frozen dataclasses (`Config`, `SourceSpec`,
`DestinationSpec`, `RunReport`, `StepResult`, `Artefact`, `Upload`).
Typed Python (`py.typed`); passes `mypy --strict`.

## Design commitments

* **Never silently downgrade encryption.** If `encrypt_to` is set and
  `age` is missing, the destination fails — it does not upload
  plaintext.
* **Independent destination failures.** A dead S3 bucket must not
  prevent the git push that follows.
* **Deterministic artefacts.** The same tree produces the same tarball
  bytes (mtime/uid/gid zeroed) so destinations can no-op when nothing
  has changed.
* **Zero telemetry.** No phone-home, no metrics. A backup tool that
  beacons is a backup tool that will be firewalled off.

## Picking a destination kind

Quick rule of thumb:

| Kind    | Good for                                             | Avoid when                                          |
|---------|------------------------------------------------------|-----------------------------------------------------|
| `git`   | Small sources (< ~100 MB), full version history matters | The source is large and churns; every run adds a blob to `.git/objects` that is never deleted. |
| `s3`    | Offsite durability with a lifecycle rule for rotation | You don't have (or don't want) an AWS-shaped account. |
| `local` | Spare drive, second machine on LAN, bounded retention (`retain = N`) | You need the backup to survive the laptop being stolen. |

Mix and match — having one `git` destination for history and one
`local` destination for recent rollback is a common shape.

## Threat model & non-goals

* **In scope**: accidental data loss (mistaken `rm`, disk failure, lost
  laptop, revoked cloud account). The remote copies let you rebuild.
* **Out of scope**: targeted attack by someone with root on the host.
  If the attacker can read your config and your age identity file,
  they can already read your unencrypted source — this is a backup
  tool, not a sealing room.
* **Out of scope**: real-time sync. The minimum meaningful schedule is
  whatever cron runs; continuous replication is a different product.

See [`SECURITY.md`](SECURITY.md) for the vulnerability reporting
process.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
