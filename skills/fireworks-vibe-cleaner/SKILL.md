---
name: fireworks-vibe-cleaner
description: Inspect Codex and Claude Code disk growth, prepare bounded cleanup plans, quarantine and restore approved old logs or rebuildable bytecode, remove explicitly approved main transcripts only after verified archival, and obtain privacy-minimized Jev advice. Use when the user asks to investigate or clean harness-generated storage.
---

# Fireworks Vibe Cleaner

Use the bundled CLI as the sole cleanup implementation. Resolve this Skill's directory and run `python3 <skill-dir>/scripts/fireworks-vibe-cleaner.py`. Python 3.11+ and macOS/Linux are required. See README.md or README.zh.md for command templates and limits.

## Workflow

1. Recommend secure Jev setup first via injected `TYPESAFE_API_KEY`; never ask for a key in chat. `doctor` reports presence only, not successful inference. Respect a rules-only choice. Network/cost authorization is separate. Run `doctor`, then `scan --output <private-new-file>`. Default roots honor `CODEX_HOME` and `CLAUDE_CONFIG_DIR`. Add `--root project=<absolute-path>` only for user-selected projects. Never scan `/` or the entire HOME. Apply user keep rules through `--keep`.
2. Read scan completeness/errors and `report --scan <file>`. Explain logical size, allocated size, preliminary eligibility and actual reclaim as distinct measurements. Skipped directories mean incomplete coverage. A single snapshot cannot establish growth.
3. With network/cost authorization, use `advise --scan <file> --id <id> --inspect-activity --enable-network --output <new-file>` before proposing a plan. Local rules remain available without a key. Advice never authorizes actions. Select a narrow set of candidate IDs. Create `plan --scan <file> --id <id> --state-dir <private-same-volume-dir> --max-bytes <cap> --output <new-plan-file>`. Inspect the full plan. First summarize the selected scope, method, bytes, exclusions, recovery limits and expected reclaim in chat; then link the complete plan with paths, state directory, expiry and exact hash.
4. Obtain explicit approval for that exact scope/hash before applying. Existing valid exact-plan authorization suffices; broad requests to inspect or clean do not approve an unseen plan. Stop only processes the user has authorized you to stop; otherwise ask the user to stop relevant writers. `--writers-stopped` is an acknowledgement, never evidence by itself. Do not fabricate it.
5. Run `apply --plan <file> --approve <reviewed-hash> --writers-stopped`, then `verify --state-dir <dir> --run <run-id>`. Apply performs additional identity/content/policy and `lsof` checks. Preserve journals and recovery files on any failure. Do not replay an existing run.
6. Use `restore --state-dir <dir> --run <id> --writers-stopped` to recover. If permanent deletion is requested, obtain separate approval for the run and invoke `purge --state-dir <dir> --run <id> --approve purge:<id> --writers-stopped`. Verify again and report observed results.

## Hard boundaries

- Only recognized old regular logs and Git-ignored, untracked Python bytecode with tracked source can enter the log/cache quarantine executor. Codex allows only `log/codex-tui.log` and `logs/codex-tui.log`; custom-service logs are protected. Never expand scope via shell deletion, directory-name guesses or model output.
- Only recognized main transcripts may use the separate verified-archive flow below. Subagent/sidechain/fork/unknown-origin transcripts, tool results, checkpoints, assets, worktrees, source, credentials, databases, memories and unknown objects cannot enter source removal. Worktrees require the harness/Git lifecycle outside this Skill.
- Same-volume quarantine releases zero bytes. Purge is irreversible. Report observed volume free-space change separately from deleted logical size; neither is a universal reclaim guarantee.
- Backup/extract check selected bytes only, retain source files and do not prove harness resume. Keep ZIP and manifest together, local and private. Cross-volume backup and encryption are unavailable. Transcript removal requires the separate archive flow below.
- Never bypass a refusal, missing `lsof`, active writer, occupied restore path or changed file. After an interruption, verify and preserve evidence before resolving the specific state.
- Reports, manifests and journals contain local paths and may contain sensitive metadata. Do not upload or commit them.

## Explicitly approved archived-transcript removal

Start with existing `backup` archives and manifests; backup itself retains originals. Use `archive-plan --scan <fresh-scan> --id <id> --archive <zip> --state-dir <private-dir> --max-bytes <cap> --ttl-seconds <1..86400> --output <new-plan>`; repeat IDs/archives as needed. It validates archive bytes and selected main-transcript content. First show the selected files/counts, byte total, retained backups, expected reclaim, risk and recovery limits in chat; then link the complete plan with every path, archive, expiry and exact hash for review.

Obtain exact-plan approval and explicit history-risk acknowledgement. Existing matching authorization suffices; never infer either from successful backups or Jev output. Stop relevant writers, then run `archive-apply --plan <plan> --approve <hash> --writers-stopped --acknowledge-history-risk`. This directly removes selected originals and retains archives. Run `archive-verify --state-dir <dir> --run <id>`.

Recovery uses `archive-restore --state-dir <dir> --run <id> --writers-stopped`, then archive-verify. It restores exact bytes at original paths with new inodes allowed, refuses occupied paths, and does not edit indexes. Explain before approval that related state stays unchanged, history may disappear, and native conversation continuation is unverified. Preserve archives/manifests/journals on any failure. Do not blindly replay an interrupted removal.

## Jev: optional advice only

Only use `advise --scan <file> --id <id> --enable-network --output <new-file>` after user authorization to send the documented metadata to TypeSafe and any applicable cost authorization. Use securely injected `TYPESAFE_API_KEY`; do not print or persist it. One call supports up to 20 candidates, with no automatic retries. No raw paths, filenames, transcript/code content or original IDs leave the machine.

Advice is limited to keep/review/backup/delete; delete is offered only for locally checked old logs/rebuildable caches with retention met and a no-open-handles snapshot. Sessions never receive direct delete advice. A snapshot does not prove stopped writers. Advice cannot alter a plan, and never authorizes deletion. Confidence is not deletion safety. Missing credentials or service failure leave rules-only operation available. Do not install or modify the user's separate `jev` CLI. Do not claim live provider verification unless current evidence supports it.

## Explicitly requested real-data validation

Use `tools/large_real_validation.py` only when the user requests a bounded real-session archive benchmark. It retains originals and writes private same-volume archives; full recovery bytes are verified as a stream. `tools/live_jev_validation.py` is separately opt-in and requires network/cost authorization. The optional macOS `tools/native_history_validation.py` denies network access and checks history parsing, never continuation.

Keep all original cleanup behind explicit human confirmation of the concrete scope and action. Validation authorization, successful hashes, compression ratios and model confidence do not approve quarantine, movement or deletion. Preserve and report failed native-reader checks. Never publish raw inventories, paths, manifests, session IDs or content. Archives and verification copies add storage until an independently approved cleanup occurs.

## Codex history pressure: overview before approval

Use `history-audit --codex-home <root> --output <private-new-audit>` for index-based inspection. Defaults are total readable indexed bytes > 3 GiB, any session > 3 GiB, or unarchived index count > 200. Configure through `--total-bytes`, `--single-bytes`, `--count-limit`; retain the latest 100 threads and the last 30 days through `--keep-recent`/`--min-age-days`, plus pinned/current threads and repeated `--keep-thread <id>` values. Ensure the current thread is known (the audit uses `CODEX_THREAD_ID` when available); supply its ID explicitly or stop native planning if it cannot be established. Do not infer the current thread from latest modification time.

A threshold breach produces suggestions only. Explain that counts are index-wide, not the exact UI-filtered list. Readable-file byte totals can be a lower bound; disclose incomplete files and lineage. Unknown pin/lineage/version information must not be converted into permission to mutate. Read-only audit is macOS/Linux for recognized schemas; native writes require supported Codex and macOS OS-enforced network denial.

For eligible selections, prepare `history-plan --audit <file> --id <root-id> --state-dir <private-dir> --codex <executable> --output <new-plan>` (repeat `--id`). Codex 0.154.0 native archive cascades to descendants, so freeze and review the entire affected descendant scope; never archive a root that would bypass protection on a descendant.

**Before linking the full plan or asking for approval, summarize in chat:** triggered thresholds; indexed/unarchived counts; measured bytes and unknown coverage; protected counts; selected roots and total affected descendants; native archive operation; expected disk reclaim of zero; recovery limitations. Then provide the plan link and exact hash. A bare artifact link is insufficient.

Only after exact-scope/hash approval and stopped-writer acknowledgement use `history-apply --plan <file> --approve <hash> --writers-stopped`, followed by `history-verify --state-dir <dir> --run <run>`. Use the official native API; never write SQLite or move transcript files directly. Stop on isolation/version/protection refusal.

Recovery requires approval for the exact unarchive scope: `history-restore --state-dir <dir> --run <run> --approve unarchive:<run> --writers-stopped`, then history-verify. Native unarchive affects one ID at a time: restore each affected ID, and report any partial recovery instead of claiming the whole tree recovered. Native API state restoration does not establish UI rendering or conversation continuation.

Native archive is a history-list operation with no promised disk reclaim. Storage recovery requires existing verified ZIP backups and the separate archive-plan/archive-apply workflow, with its own exact authorization and history-risk acknowledgement. Never reuse history-archive approval as source-deletion approval. Synthetic native canaries and unchanged transcript SHA-256 do not prove real-user archiving or authorize it.

Incomplete audit coverage blocks native planning and execution. Never auto-repair the index to bypass this gate. Native unarchive intentionally updates file mtime and Codex update times. The native runtime can read the reviewed CODEX_HOME configuration; OS restrictions deny network, execution of other programs and writes outside that home and the private runtime home. Do not call this an OS read-isolation boundary.
