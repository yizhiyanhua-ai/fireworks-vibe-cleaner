---
name: fireworks-vibe-cleaner
description: Inspect Codex and Claude Code disk growth, prepare bounded cleanup plans, quarantine and restore approved old logs or rebuildable bytecode, and obtain optional privacy-minimized Jev advice. Use when the user asks to investigate or clean harness-generated storage.
---

# Fireworks Vibe Cleaner

Use the bundled CLI as the sole cleanup implementation. Resolve this Skill's directory and run `python3 <skill-dir>/scripts/fireworks-vibe-cleaner.py`. Python 3.11+ and macOS/Linux are required. See README.md or README.zh.md for command templates and limits.

## Workflow

1. Run `doctor`, then `scan --output <private-new-file>`. Default roots honor `CODEX_HOME` and `CLAUDE_CONFIG_DIR`. Add `--root project=<absolute-path>` only for user-selected projects. Never scan `/` or the entire HOME. Apply user keep rules through `--keep`.
2. Read scan completeness/errors and `report --scan <file>`. Explain logical size, allocated size, preliminary eligibility and actual reclaim as distinct measurements. Skipped directories mean incomplete coverage. A single snapshot cannot establish growth.
3. Select a narrow set of candidate IDs. Create `plan --scan <file> --id <id> --state-dir <private-same-volume-dir> --max-bytes <cap> --output <new-plan-file>`. Inspect the full plan and present exact paths, method, total bytes, state directory, expiry and hash to the user.
4. Obtain explicit approval for that exact scope/hash before applying. Existing valid exact-plan authorization suffices; broad requests to inspect or clean do not approve an unseen plan. Stop only processes the user has authorized you to stop; otherwise ask the user to stop relevant writers. `--writers-stopped` is an acknowledgement, never evidence by itself. Do not fabricate it.
5. Run `apply --plan <file> --approve <reviewed-hash> --writers-stopped`, then `verify --state-dir <dir> --run <run-id>`. Apply performs additional identity/content/policy and `lsof` checks. Preserve journals and recovery files on any failure. Do not replay an existing run.
6. Use `restore --state-dir <dir> --run <id> --writers-stopped` to recover. If permanent deletion is requested, obtain separate approval for the run and invoke `purge --state-dir <dir> --run <id> --approve purge:<id> --writers-stopped`. Verify again and report observed results.

## Hard boundaries

- Only recognized old regular logs and Git-ignored, untracked Python bytecode with tracked source can enter cleanup. Never expand scope via shell deletion, directory-name guesses or model output.
- Sessions, checkpoints, assets, worktrees, source, credentials, databases, memories and unknown objects are not cleanup targets. Worktrees require the harness/Git lifecycle outside this Skill.
- Same-volume quarantine releases zero bytes. Purge is irreversible. Report observed volume free-space change separately from deleted logical size; neither is a universal reclaim guarantee.
- Backup/extract check selected bytes only, retain source files and do not prove harness resume. Keep ZIP and manifest together, local and private. Cross-volume backup, encryption and session deletion are unavailable.
- Never bypass a refusal, missing `lsof`, active writer, occupied restore path or changed file. After an interruption, verify and preserve evidence before resolving the specific state.
- Reports, manifests and journals contain local paths and may contain sensitive metadata. Do not upload or commit them.

## Jev: optional advice only

Only use `advise --scan <file> --id <id> --enable-network --output <new-file>` after user authorization to send the documented metadata to TypeSafe and any applicable cost authorization. Use securely injected `TYPESAFE_API_KEY`; do not print or persist it. One call supports up to 20 candidates, with no automatic retries. No raw paths, filenames, transcript/code content or original IDs leave the machine.

Advice is limited to keep/review/backup, cannot alter a plan, and never authorizes deletion. Confidence is not deletion safety. Missing credentials or service failure leave rules-only operation available. Do not install or modify the user's separate `jev` CLI. Do not claim live provider verification unless current evidence supports it.
