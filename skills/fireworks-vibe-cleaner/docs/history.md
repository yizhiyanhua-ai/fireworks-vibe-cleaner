# Codex history pressure and native archive

Use natural language in your harness: “Check my Codex history. If total or individual session size exceeds 3 GiB, or unarchived count exceeds 200, show what you recommend. Keep recent, pinned, current and explicitly retained sessions. Show an overview in chat and link the full plan before asking me to confirm.”

`history-audit` is read-only. It measures the whole recognized index, including archived files for the total byte count; it does not replicate the UI's project filters. It reads bounded metadata headers, not complete conversation bodies. Incomplete file coverage means known byte totals are a lower bound. This is an on-demand check, not a scheduled cleanup service.

| Option | Default | Meaning |
| --- | ---: | --- |
| `--total-bytes` | 3221225472 | Trigger above 3 GiB in readable indexed files |
| `--single-bytes` | 3221225472 | Trigger above 3 GiB in one readable file |
| `--count-limit` | 200 | Trigger above 200 unarchived indexed threads |
| `--keep-recent` | 100 | Keep the newest 100 unarchived threads |
| `--min-age-days` | 30 | Keep threads/files updated in the last 30 days |
| `--keep-thread` | repeatable | Explicitly protect an ID; current `CODEX_THREAD_ID` is also retained |

Pinned threads are always protected. Identify the current thread explicitly when the harness does not provide `CODEX_THREAD_ID`. All thresholds generate recommendations only. Native planning refuses any incomplete audit; inspect missing/unsafe records and lineage conflicts rather than silently repairing the database. A preliminary candidate count is not an executable plan.

```sh
fireworks-vibe-cleaner history-audit --codex-home /absolute/codex-home --output history-audit.json
fireworks-vibe-cleaner history-plan --audit history-audit.json --id ROOT_THREAD_ID --state-dir /absolute/private-state --output history-plan.json
# Review the overview, complete plan and hash; obtain exact approval and stop all writers.
fireworks-vibe-cleaner history-apply --plan history-plan.json --approve REVIEWED_HASH --writers-stopped
fireworks-vibe-cleaner history-verify --state-dir /absolute/private-state --run RUN_ID
# Review and approve recovery separately.
fireworks-vibe-cleaner history-restore --state-dir /absolute/private-state --run RUN_ID --approve unarchive:RUN_ID --writers-stopped
fireworks-vibe-cleaner history-verify --state-dir /absolute/private-state --run RUN_ID
```

Paths and uppercase values above are placeholders. Repeat `--id` to select top-level threads, and `--keep-thread` when auditing for additional retained IDs. Plans expire after one hour; `history-plan --ttl-seconds` permits at most 86400 seconds. State must be private and outside CODEX_HOME. `--codex` can select the canonical native Mach-O executable; unrecognized script launchers are refused. Initial native writes require **macOS and codex-cli 0.154.0**; read-only audit supports recognized schemas on macOS/Linux.

Before approval, show triggered thresholds, counts, measured bytes and unknown coverage, protected threads, every selected root and all affected descendants, method, **zero expected disk reclaim**, risks and recovery limits in chat. Then link the complete private plan and its exact hash. An approval flag is an acknowledgement, not proof that the operator approved: a harness must obtain that approval from the human. Stop relevant writers; `notLoaded` in the isolated server does not prove other processes are idle.

The native archive API cascades through spawned descendants. Any protected descendant blocks the selected root, even if already archived. The cleaner checks the entire tree against both the read-only index and paginated native APIs, binds source SHA-256/identities, and journals intent before native effects. It never directly edits the index or moves transcripts. Native API startup may maintain its index and read CODEX_HOME configuration; the OS sandbox denies network, execution of other program paths and writes outside CODEX_HOME/private runtime HOME. It is not a restriction on all file reads.

Native unarchive affects one thread per call. Recovery processes every changed ID individually, leaving originally archived descendants archived. It restores paths, content and archive membership; Codex deliberately updates file mtime and index update times. Verify interrupted runs before recovery; changed lineage, occupied destinations or content conflicts require manual inspection. Never replay apply or widen a recovery scope automatically. Native UI rendering and conversation continuation are unverified.

Native archive promises **0 reclaimed bytes**. For disk recovery, use the separate verified-ZIP `archive-plan` / `archive-apply` workflow, with its own exact approval and history-risk acknowledgement. Approval to organize a history list does not approve deleting original transcripts. Jev advice does not bypass any gate.
