# Security

## Current measures (Phase 1)

- **Untrusted files:** the `.vmap` reader enforces size, entry-count and depth limits,
  validates structure and never extracts archive entries to disk (see FILE_FORMAT.md).
  Theme files are data-only JSON with strict whitelisting of keys and values.
- **No code from documents:** documents and themes cannot run code. Plugins (Phase 9)
  will be opt-in and clearly marked as executable code.
- **Secrets:** Phase 1 stores no credentials. When AI providers arrive (Phase 7), API keys
  will go into the OS keychain (`keyring`) and never into the settings database, files or logs.
- **Logging:** logs record errors and file paths, never document contents, passwords or keys.
- **Atomic saves:** failed writes never corrupt existing documents.
- **Clipboard:** pasted data is size-limited and validated before use.

## Planned

Encrypted and password-protected workbooks, encrypted backups and signed release builds.

## Reporting a vulnerability

Please report privately to the maintainers (add a security contact address here before
the first public release) rather than opening a public issue.
