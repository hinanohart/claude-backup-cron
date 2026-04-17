# Contributing to claude-backup-cron

Thanks for considering a contribution. The scope of this project is
deliberately narrow — keep a small set of directories safe, and do it
without silently regressing encryption. Every change should make that
harder to get wrong, not easier.

## Principles

1. **Never silently downgrade encryption.** If `encrypt_to` is set on a
   destination and encryption fails, we fail the destination. We do not
   fall back to plaintext. This is the single rule that would ruin the
   whole package if it slipped.
2. **Per-destination isolation.** A dead S3 endpoint must not block the
   git push that follows. If you're adding a new destination, keep its
   failure surface to itself.
3. **Deterministic artefacts.** The same tree should produce the same
   tarball bytes. Change-detection depends on it. Don't add timestamps,
   random padding, or anything else that drifts run-to-run.
4. **No mandatory network dependencies.** The tool runs on cron, often
   on laptops that are offline half the day. Broken network is an
   expected case; reaching out to a phone-home endpoint is not.
5. **Additive config schema.** Config keys don't change meaning across
   minor releases. New keys are optional with sensible defaults.

## Development

```bash
pip install -e '.[dev]'
pytest
ruff check src tests
ruff format --check src tests
mypy --strict src/claude_backup_cron
```

All four must pass locally. CI runs the same matrix across Python
3.10 / 3.11 / 3.12 / 3.13 on Linux, macOS, and Windows.

### Live-tool tests

A few tests assume external binaries are on PATH and skip gracefully
otherwise:

- `git` — used by the `git` destination tests.
- `age` / `age-keygen` — used by the encryption round-trip test.
- `crontab` — used by the scheduler tests via a tiny stub.

If you're adding a new backend that shells out to something, follow the
same `shutil.which(...) is None → pytest.skip(...)` pattern.

## Adding a destination kind

1. Open an issue first so the shape of the config schema can be agreed
   before code review.
2. Add a `dispatch_<name>(dest, upload)` function in
   `src/claude_backup_cron/destinations.py` returning a one-line status
   string or raising `DestinationError`.
3. Extend `_parse_destination` and `_VALID_DEST_KINDS` in `config.py`.
4. Wire it into `_dispatch` in `backup.py`.
5. Add both happy-path and failure-mode tests.
6. Update `README.md`, `docs/INSTALL.md`, and `CHANGELOG.md`.

## Reporting bugs

Open an issue with:

- The config section that reproduces it (scrub secrets — webhook URLs,
  bucket names, age recipients are fine to omit).
- The command line, exit code, and the last ~20 lines of stderr.
- `claude-backup-cron version`.
- Python version, OS, and whether you're running via cron or invoking
  `run` by hand.

## Code of conduct

See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Contact:
`hinanohart@gmail.com`.
