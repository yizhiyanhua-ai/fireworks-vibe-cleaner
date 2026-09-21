# Changelog

## 0.3.0 — 2026-09-21

- Add configurable Codex history count, total size and individual size pressure audits. Default triggers: more than 200 unarchived threads or 3 GiB. Never trigger automatic cleanup.
- Add exact-approved native history archive and individual unarchive over a fully checked descendant tree; preserve pinned/current/recent/explicitly kept threads.
- Refuse incomplete index/file/lineage audits, unrecognized runtimes, destination conflicts and changed plans. Initial native writes require macOS and Codex 0.154.0 with OS execution, write and network restrictions.
- Require an inline overview before the complete plan link. Native archive promises zero disk reclaim; source removal remains separately approved.
- Publish sanitized real read-only audit and isolated actual-Codex synthetic workflow evidence. Real history archival and native continuation remain unverified.

## 0.2.0 — 2026-09-21

- Add verified-archive plans and separately approved removal of recognized old main transcripts, with byte/path restoration and explicit history-risk acknowledgement. No index repair or native continuation claim.
- Keep linked/unknown-origin transcripts, tool results, checkpoints and assets out of source removal.
- Recommend Jev setup early, retain rules-only fallback, and add dynamic keep/review/backup/delete advice with local checks and no execution authority.
- Add `advise --inspect-activity`, per-candidate response validation and privacy-preserving local evidence.
- 63 local tests passed, including the black-box CLI archive roundtrip and interrupted read-only recovery. One new real Jev call returned review for all 20 candidates; real-original cleanup awaits exact human approval.

### Historical measurements retained in this release


- Validate 564 real session files (10.181 GiB) into 5.308 GiB of archives, with complete stream restore and final source hashes matching. No original cleanup occurred.
- Add actual Jev metadata-only comparison: three repeated 20-candidate calls plus a connectivity canary. Preserve native-reader failures and distinguish them from byte recovery.
- Add optional bounded real-data, live-provider and network-isolated native-reading tools; keep all original cleanup behind explicit human confirmation.

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

See [v0.2.0 release evidence and limits](docs/releases/v0.2.0.md). Historical entries do not establish passing CI for this commit; consult its actual workflow run.
