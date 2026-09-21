# Compatibility and limits

| Component | v0.1 contract |
| --- | --- |
| Runtime | Python 3.11+, macOS/Linux; Windows unsupported |
| Filesystem mutation | POSIX primitives, private owned state directory, stopped writers and `lsof`; same-volume regular single-link files only |
| Codex root | `CODEX_HOME`, otherwise `~/.codex`; explicit `--root codex=...` supported |
| Claude root | `CLAUDE_CONFIG_DIR`, otherwise `~/.claude`; explicit `--root claude=...` supported |
| Codex cleanup | Old `log/codex-tui.log` and `logs/codex-tui.log` only; custom-service logs protected |
| Claude cleanup | Old `.txt`/`.log` files below `debug/` only |
| Project cleanup | `__pycache__/*.pyc` with an existing tracked source, untracked cache and Git ignore rule |
| Sessions/checkpoints/assets | Selected file backup and hash-checked numbered extraction only; sources retained |
| Worktrees | Classification only; no Git integrity audit or automatic removal |
| Other harnesses, Docker, global package caches | No adapter or cleanup support |
| Jev | Four real metadata-only calls succeeded with Jev 1.13.0 on 2026-09-21; accuracy and superiority over rules remain unverified |
| Real-data validation helpers | Opt-in only; ~10 GiB archive/stream-restore benchmark retains originals and adds private artifacts |
| Native history readers | macOS network-denied sandbox; Claude exact-file samples passed; two Codex archived samples did not yield nonempty history; continuation unverified |

Adapters recognize narrow filesystem layouts; they do not claim comprehensive version-specific session compatibility. Unknown content remains protected. No supported harness version is declared safe for session deletion or session resume restoration.

A scan can be incomplete because of a file limit, permission errors, symlinks, volume boundaries or deliberately pruned dependencies/Git metadata. Its totals describe observed files, not all disk usage. Read `complete` and `errors` before interpretation. Plans revalidate each selected candidate; scan eligibility does not grant execution authority.

Backups are unencrypted file copies on the source volume. They do not capture all dependency graphs, attachments, application databases or external indexes required for harness resume. Source removal and cross-volume archival require future independent implementation and acceptance.

CI configuration and the actual tested matrix are separate evidence. Consult the workflow and [release notes](releases/v0.1.0.md) for run results. Filesystems with snapshots, compression, sparse allocation or shared blocks may show a volume free-space change different from deleted logical bytes.
