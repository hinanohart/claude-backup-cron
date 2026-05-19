# claude-backup-cron

Scheduled, encrypted backups for small-but-high-value directories —
Claude Code's `memory/` folder in particular, but anything the shape
would fit.

> **Disclaimer:** This is an **independent third-party tool**. It is **not affiliated with, endorsed by, or sponsored by Anthropic**. "Claude" and "Claude Code" are trademarks of Anthropic and are used here nominatively to identify the directory layout this tool happens to back up.

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

The default `memory-backup.sh` approach that ships in many Claude Code
setups works well for single-machine, single-destination use — but it
intentionally does not cover multi-destination failover, encryption,
content-hash change detection, or structured failure reporting. This
package adds those features for higher-reliability deployments where
the operator is not watching the cron logs every day: strict typing,
deterministic artefacts, structured failures, audit-friendly CLI.

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
path = "~/.claude/projects/-home-USER/memory"
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

## Verification (sigstore)

Releases from **v_next_** (released after 2026-05-16) include a sigstore keyless signature bundle
(`.sigstore` per artifact) attached to the GitHub Release.

### Verify a PyPI install

```bash
pip download <pkg-name>==<version> --no-deps -d ./verify
python -m sigstore verify github \
    --cert-identity 'https://github.com/hinanohart/claude-backup-cron/.github/workflows/release.yml@refs/tags/v<version>' \
    --cert-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ./verify/*.whl ./verify/*.tar.gz
```

The corresponding `.sigstore` bundles can be downloaded from the GitHub Release page.

### Historic releases (pre-2026-05-16)

Earlier releases were published without sigstore bundles. Re-installing those versions
provides no cryptographic provenance — pin to a current release if assurance matters.

## License

MIT. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## Why not just `age + cron + git push` in a shell script?

Fair question, and it's the first thing anyone with a 50-line backup
shell script will reach for. The honest answer is that nine of the
eight CVE-class fixes that landed in v0.1.2 were **not** about
cleverness — they were about cases the shell version was getting
silently wrong:

- **Token redaction in destination logs.** When `git push` to a
  private remote fails, its stderr contains the URL + auth token if
  the remote was configured with one. Four token shapes are stripped
  from any captured output before it reaches the alerting webhook
  or the local error log.
- **Branch-name injection.** A user-controlled `dest.git.branch`
  string could be `main; rm -rf $HOME` if the shell variant
  interpolated it into a `git push` command line. The `_SAFE_BRANCH_RE`
  whitelist refuses anything outside `[A-Za-z0-9._/-]`.
- **Symlink-escape on tar.** `tarfile.open` follows symlinks by
  default; a symlink pointing outside the source dir would let the
  archive include unrelated files. Each member's resolved path is
  re-checked against the source root with `Path.is_relative_to`.
- **Cron-expression injection.** `_CRON_EXPRESSION_RE` rejects any
  `crontab` entry that doesn't parse as a 5-field schedule, so a
  hostile config file can't sneak `* * * * *` followed by a backslash
  newline into the user's crontab.
- **`age` binary impostor.** `age --version` is parsed and matched
  against an expected prefix before any encryption pipeline runs.
  A `PATH`-collision dropping a shim would otherwise produce
  ciphertext readable by the attacker.
- **Webhook scheme allow-list.** Discord/Slack alerting URLs are
  passed through `_ALLOWED_SCHEMES` (`https://` only), so a
  redirected config can't smuggle `file://` or `gopher://` reads
  out via the webhook channel.
- **Atomic private-dir creation.** The state dir is `mkdir`'d with
  mode `0o700` in one syscall, not `mkdir` + `chmod`, so there is no
  window where the dir exists with default umask permissions.

Could you write all of that in shell? Yes — but every one of them is
an easy thing to forget, and every one of them is a place where a
secret leaves the trust boundary. The Python package exists so the
checks live in one place with tests, not so it is "fancier" than a
script. If your threat model genuinely doesn't include any of those
attack paths, a shell script is the right answer.

The 2026-05-09 audit explicitly considered consolidating this back
into a thin shell variant and rejected it on the grounds above. That
record is preserved in the failure museum so the next audit doesn't
have to re-derive it.
