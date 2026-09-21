# Compatibility and limits

| Component | v0.2.0 contract |
| --- | --- |
| Runtime | Python 3.11+, macOS/Linux; Windows unsupported |
| Filesystem mutation | POSIX primitives, private owned state directory, stopped writers and `lsof`; same-volume regular single-link files only |
| Codex root | `CODEX_HOME`, otherwise `~/.codex`; explicit `--root codex=...` supported |
| Claude root | `CLAUDE_CONFIG_DIR`, otherwise `~/.claude`; explicit `--root claude=...` supported |
| Codex cleanup | Old `log/codex-tui.log` and `logs/codex-tui.log` only; custom-service logs protected |
| Claude cleanup | Old `.txt`/`.log` files below `debug/` only |
| Project cleanup | `__pycache__/*.pyc` with an existing tracked source, untracked cache and Git ignore rule |
| Recognized old main transcripts | Verified existing archive, exact plan approval, stopped writers and history-risk acknowledgement before source removal; exact-path byte recovery |
| Linked/unknown transcripts, tool results, checkpoints and assets | No source removal; selected backup where supported |
| Worktrees | Classification only; no Git integrity audit or automatic removal |
| Other harnesses, Docker, global package caches | No adapter or cleanup support |
| Jev | Four real metadata-only calls succeeded with Jev 1.13.0 on 2026-09-21; accuracy and superiority over rules remain unverified |
| Real-data validation helpers | Opt-in only; ~10 GiB archive/stream-restore benchmark retains originals and adds private artifacts |
| Native history readers | macOS network-denied sandbox; Claude exact-file samples passed; two Codex archived samples did not yield nonempty history; continuation unverified |

Adapters recognize narrow filesystem layouts; they do not claim comprehensive version-specific session compatibility. Unknown content remains protected. Recognition is intentionally narrow and does not establish complete application restoration. Native continuation is unverified; historical native-reader results do not validate the new removal flow.

A scan can be incomplete because of a file limit, permission errors, symlinks, volume boundaries or deliberately pruned dependencies/Git metadata. Its totals describe observed files, not all disk usage. Read `complete` and `errors` before interpretation. Plans revalidate each selected candidate; scan eligibility does not grant execution authority.

Backups are unencrypted file copies on the source volume. They do not capture all dependency graphs, attachments, application databases or external indexes required for harness resume. Main-transcript source removal is an independently approved flow that leaves indexes and related files untouched. Cross-volume archival is not implemented.

CI configuration and the actual tested matrix are separate evidence. Consult the workflow and [release notes](releases/v0.2.0.md) for run results. Filesystems with snapshots, compression, sparse allocation or shared blocks may show a volume free-space change different from deleted logical bytes.

Jev setup is recommended, with explicit rules-only fallback. Dynamic advice is keep/review/backup/delete; delete is only available for locally checked old logs/caches, never a model authorization. The four historical live calls used earlier options, so their results do not establish new delete-advice quality. v0.2.0 has 63 passing local tests. One new live call with the expanded contract returned review for all 20 candidates; see [the sanitized record](experiments/real-jev-v02.json). Real-original removal awaits exact human approval.
