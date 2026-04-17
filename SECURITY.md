# Security policy

## Reporting a vulnerability

Please report security issues privately by email to
**`hinanohart@gmail.com`** with the subject prefix
`[claude-backup-cron security]`.

I aim to acknowledge within 72 hours and to ship a fix (or publish an
advisory explaining the trade-off) within 14 days for high-severity
issues.

## What counts as security-relevant

* **Silent encryption downgrade.** If a destination has `encrypt_to`
  set but the tool uploads plaintext for any reason, that's a hard
  bug — the whole point of the option is that it never silently
  regresses. Report privately.
* **Credential leakage via logs or alerts.** If any subprocess stderr
  that might contain a token (AWS keys, SSH prompts, etc.) ends up in
  the alerting webhook payload or the state directory's log files,
  that's in scope.
* **Command injection in the subprocess wrappers.** Every call site
  uses a fixed argv (no shell), but config-supplied values end up as
  argv elements. A destination spec with an unusual value that breaks
  out of argv semantics is a bug.
* **Supply-chain concerns** with the packaging (signed releases,
  Trusted Publishing configuration, CI token scope, etc.).

## What is not in scope

* Root-level compromise of the host. If the attacker can read the age
  identity file and the config, they can already decrypt the backup —
  that's the threat model, not a vulnerability.
* Alerting webhook being publicly reachable. The webhook URL is
  considered a secret by the user; if they share it, that's their
  choice.
* Cron itself. If the user's crontab is compromised, this tool isn't
  the bottleneck.

## Disclosure

Coordinated disclosure preferred. Once a fix is released, a short
advisory is added to [CHANGELOG.md](CHANGELOG.md) crediting the reporter
(unless they prefer to remain anonymous).
