# Changelog

## 0.1.1 — 2026-09-21

- Real local validation found custom-service logs incorrectly eligible under Codex log directories. Restrict eligibility to the exact `codex-tui.log` basename directly under `log/` or `logs/`; existing plans are rechecked before execution.
- Add private real-session backup validation and publish sanitized real measurements, including zero bytes reclaimed. Separate synthetic regression evidence from actual effectiveness results.

## 0.1.0 — 2026-09-21

- Add a Python CLI and Codex/Claude Code Skill for bounded storage inspection.
- Add plan-hash-approved quarantine, verification, conflict-safe restoration and separately approved purge for old known logs and rebuildable Python bytecode.
- Protect session originals, checkpoints, assets, worktrees, source and unknown data from cleanup.
- Add same-volume byte-verified copies and extraction; harness resume is not verified.
- Add opt-in metadata-only Jev advice with rules-only fallback and no deletion authority.
- Add bilingual documentation, packaging and CI configuration.

See [release evidence and limits](docs/releases/v0.1.0.md). This entry does not establish a published release or passing remote CI.
