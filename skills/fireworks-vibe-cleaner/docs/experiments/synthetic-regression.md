# Synthetic regression evidence (historical)

These fixtures verify safety mechanics only. They do not establish real-user cleanup savings. Captured before the Codex log allowlist fix; current fixtures use the narrower allowlist.

## Local experiments

Run on **2026-09-21 · macOS 26.5.1 · arm64 · Python 3.14.6**, using only synthetic files in an isolated temporary directory. Seven experiments passed; no real user files were modified and no model API requests were sent. These are local observations, separate from the CI matrix.

| Experiment | Setup | Observed result | Status |
| --- | --- | --- | --- |
| Inventory and protection | 10 files: 2 old logs, 8 protected/recent/kept objects | Only 2 cleanup candidates; all 8 protected hashes unchanged | Pass |
| Quarantine and restore | 2 files, 8 MiB total | All 8 MiB remained in same-volume quarantine; both restored content hashes matched | Pass |
| Approved permanent purge | A new reviewed plan for the same 8 MiB | Deleted 8,388,608 logical bytes; observed volume free-space change **+4,157,440 bytes (3.965 MiB)**; 8 protected objects unchanged | Pass |
| File changes after planning | Modify a candidate before apply | Exit 2; changed source retained | Pass |
| Restore conflict | New content occupies the original path | Exit 2; new content and quarantined original both preserved | Pass |
| Session byte backup | Copy and extract one synthetic transcript | Original retained; extracted hash matches; harness resume **not tested** | Pass |
| Jev service failure | Inject HTTP 503 through an offline transport | One simulated transport call, 0 network calls; rules-only fallback; no private paths in the request | Pass |

A second run after adding the optimized-Python guard also passed all seven experiments: 8,388,608 logical bytes deleted, with an observed free-space delta of **+5,976,064 bytes (+5.699 MiB)**. Both runs are retained below; the quarantine row verifies byte preservation, not a measured zero disk-free delta.

The volume free-space delta is an observation, not a claim that all 8 MiB became immediately available: filesystem accounting and unrelated writes affect it. The backup experiment verifies selected bytes, not session resumption; the Jev experiment verifies failure handling, not live inference accuracy.

[First sanitized run](local-2026-09-21.json) · [Final sanitized run](local-2026-09-21-final.json) · [Reproduction script](../../tools/local_experiments.py). The public result contains only experiment labels, OS/runtime versions, counts, byte totals and booleans—no usernames, absolute paths, session IDs, credentials, transcripts or source contents.

```sh
python3 tools/local_experiments.py --output artifacts/local-experiments.json
```

The reproduction script and logo are available in the current `main` checkout; the original `v0.1.0` tag predates this documentation update. Use `main` to reproduce this section.

Choose a new output filename for each run. The script refuses to overwrite evidence and removes its temporary fixtures on exit. CI also runs these experiments and keeps sanitized reports as workflow artifacts.

