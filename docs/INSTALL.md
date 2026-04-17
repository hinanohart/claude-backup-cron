# Installing claude-backup-cron

## 1. Install the package

### Via pipx (recommended)

```bash
pipx install claude-backup-cron
```

`pipx` puts `claude-backup-cron` on your `PATH` regardless of which
shell the cron job uses — important because cron runs with a very
minimal environment.

### Via pip in a venv

```bash
python3 -m venv ~/.local/venvs/claude-backup-cron
~/.local/venvs/claude-backup-cron/bin/pip install claude-backup-cron
```

Cron will need the absolute path to the binary; use
`~/.local/venvs/claude-backup-cron/bin/claude-backup-cron` in the cron
line, or `install-cron` will try to auto-detect from the active PATH.

## 2. Install external binaries as needed

The tool shells out to a small set of standard binaries. Install only
what matches the destinations you're going to use:

| Binary    | Needed for                                   | Install                                           |
|-----------|----------------------------------------------|---------------------------------------------------|
| `git`     | `kind = "git"` destinations                  | usually already installed                         |
| `aws`     | `kind = "s3"` destinations                   | https://aws.amazon.com/cli/                       |
| `age`     | any destination with `encrypt_to = "..."`    | https://age-encryption.org/ (apt/brew/scoop)      |
| `crontab` | `install-cron` / `uninstall-cron` subcommand | ships with every POSIX system; nothing to install |

If a destination references a binary you haven't installed, the tool
reports the failure through the same per-destination error channel as
any other upload error — it won't crash the whole run.

## 3. Set up encryption (strongly recommended for remote destinations)

Generate an age key pair:

```bash
age-keygen -o ~/.config/age/claude-backup.key
# prints: Public key: age1abcdef...
```

Keep the **identity file** (`~/.config/age/claude-backup.key`) in a
location that is not one of your backup sources — otherwise the backup
contains its own decryption key. Reasonable options:

* A password manager attachment.
* An encrypted offline USB stick.
* A second machine you trust.

Add the public key (`age1...`) to `encrypt_to` on each destination
where plaintext on the wire is unacceptable.

## 4. Write a config

Copy [`examples/config.toml`](../examples/config.toml) to
`~/.config/claude-backup-cron/config.toml` and edit. Check it parses:

```bash
claude-backup-cron show-config
```

## 5. Do a dry-run, then a real run

```bash
claude-backup-cron run --dry-run   # no uploads; confirms packaging works
claude-backup-cron run             # first real backup
```

## 6. Schedule it

```bash
claude-backup-cron install-cron --schedule "0 3 * * *"   # daily 03:00
```

Re-running `install-cron` replaces the previous block (marked by a
`# claude-backup-cron managed entry` comment). Use `uninstall-cron` to
remove it entirely.

Log output lands in
`$XDG_STATE_HOME/claude-backup-cron/cron.log` (or
`~/.local/state/claude-backup-cron/cron.log`). Tail it to see how
yesterday's run went:

```bash
tail -n 50 ~/.local/state/claude-backup-cron/cron.log
```

## Troubleshooting

### `command not found` from cron

Cron ignores your shell's PATH. Either pass `--binary=/full/path` to
`install-cron`, or export `PATH` at the top of your crontab:

```cron
PATH=/usr/local/bin:/usr/bin:/bin:/home/you/.local/bin
```

### Git destination works by hand but fails from cron

Cron jobs run without your SSH agent. For git destinations over SSH,
either:

* Use a deploy key with no passphrase stored in a file that only the
  user account can read, and configure `~/.ssh/config` to use it for
  the backup remote; or
* Use an HTTPS remote with a credential helper that caches long-lived
  tokens.

### S3 destination fails with `Unable to locate credentials`

Same issue — the AWS SDK's default credential resolution chain looks
at environment variables, `~/.aws/credentials`, and EC2/ECS metadata.
Either set `AWS_PROFILE=xxx` in your crontab header, or use a profile
whose credentials live in the default config file.

### Encrypt set but `age` missing

The destination fails (correctly — we refuse to silently fall back to
plaintext). Install `age` and try again, or remove the `encrypt_to`
line if you genuinely want plaintext on this destination.
