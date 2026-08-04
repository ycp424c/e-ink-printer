# Security policy

## Supported version

Security fixes are made on the latest `main` branch. This project has not published stable
release branches yet.

## Reporting a vulnerability

Prefer the repository host's private vulnerability reporting feature. Do not open a public
Issue containing credentials, account balances, device identifiers, private logs, database
files, or a reproducible exploit against someone else's device.

Include only the minimum information needed to reproduce the issue:

- affected commit or version;
- affected provider or BLE command;
- expected and actual behavior;
- a redacted reproduction;
- whether a credential or device slot may already have been exposed or overwritten.

If a secret may have leaked, revoke or rotate it with the issuing service immediately; deleting
it from a Git commit is not sufficient. If a BLE device identifier leaked, remove it from logs
and attachments before sharing them.

## Credential boundary

- Project-local `.env` is ignored by Git.
- Codex and cc-switch credential stores are read-only fallbacks.
- Codex refresh tokens are neither exposed to providers nor refreshed by this project.
- Persistent refresh logs are redacted by default; detailed values require
  `--verbose-balances`.
- Device `sid` notifications are replaced with `<redacted>`.
