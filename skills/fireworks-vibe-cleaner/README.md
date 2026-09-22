# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Use plain language in Codex or Claude Code to inspect coding logs, conversations and caches, ask Jev for handling suggestions, and approve a concrete plan before any cleanup. Recommended setup starts with Jev; local rules-only use remains available.

**Cleanup requires human approval of the specific plan.** v0.2.0 can verify existing archives, remove approved old main transcripts and restore their original paths. Byte restoration does not establish native conversation continuation.

## Use it from Codex or Claude Code

### 1. Install, then configure Jev

> Install fireworks-vibe-cleaner v0.5.0 from https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner into this tool's personal Skill directory. Do not overwrite an existing installation or clean any files. Then help me configure Jev securely.

You need macOS/Linux and Python 3.11+. See the [manual installation guide](docs/cli.md#install). Jev uses `TYPESAFE_API_KEY`, injected through a secret manager or process environment; never paste the key into chat, a report or command history. `doctor` checks whether a key is present, not whether authentication or inference succeeds.

> Explain Jev's metadata and possible charges before making a network call. If I choose rules-only mode, continue locally without a key.

**Configure Jev first, then let it help review fresh local evidence.** The cleaner checks selected Codex index protection and relationships, open file handles, and any existing backups you supply. Protected objects stay local and are retained. Jev receives only closed metadata choices, without paths, titles, transcripts or code; a failed call is labeled local review.

Say what you need to keep: “I need to continue these conversations” or “A verified file copy is enough for these selected sessions.” If you have not decided, the recovery need remains unknown and removal preparation is unavailable. A found backup and a verified backup are different: the cleaner can check selected bytes within a read budget before suggesting reuse. Your recovery preference never approves deletion.

Jev makes a narrow action/reason choice; code does the arithmetic and verification. Eight candidates per batch and up to three concurrent batches keep requests bounded. Metadata cannot establish a conversation's future value. See [evidence, choices and limits](docs/jev.md).

### 2. Inspect and ask for recommendations

> Use fireworks-vibe-cleaner to inspect Codex and Claude Code storage. Show the main sources of usage and what must be kept. If I have authorized the call, use Jev for fast triage. Show every selected file, recommendation, reason, backup/removal alternatives, expected impact and unknowns directly in chat. Give suggestions first, then fully verify my selected scope. Do not move or delete anything.

Project roots are opt-in. Scans do not cover the whole disk; skipped directories and unreadable files must be disclosed. Unknown activity, protected objects and credentials never acquire deletion authority from model output.

### 3. Approve the exact plan

> Show the exact files, method, bytes, recovery limits and plan hash. Wait for my approval of that plan. If it involves archived conversations, also explain that history may become unavailable and restoring file bytes does not prove I can continue the conversation.

There are two separate cleanup paths:

- **Old logs/caches:** approve quarantine, verify it, then restore or separately approve permanent purge. Same-volume quarantine releases **zero bytes**.
- **Already-backed-up main transcripts:** `archive-plan` validates existing archives and selected source bytes. Only after exact-plan approval, stopped writers and explicit history-risk acknowledgement does `archive-apply` remove the selected original transcript files while retaining the archives. Related files and harness indexes are unchanged.

A broad cleanup request does not approve unseen files. Stop relevant writers before mutation; `--writers-stopped` records an acknowledgement, not a process-stopping action. Changed scope or source requires a new plan.

## When Codex history becomes too large

> Use fireworks-vibe-cleaner to check my Codex history. If indexed sessions exceed 3 GiB in total, one session exceeds 3 GiB, or the unarchived count exceeds 200, show me a suggested cleanup scope. Keep the newest 100 sessions, everything updated in the last 30 days, pinned sessions, the current thread and my explicit keep list. Give me an overview in chat before linking the full plan. Wait for my approval of the exact scope.

These configurable thresholds trigger **advice only**, never automatic archiving or deletion. `history-audit` reads Codex's canonical index through read-only SQLite access and checks known pin/lineage fields and bounded transcript headers. Counts cover the index, not the exact list currently displayed under UI filters. Byte totals count readable indexed files and are a lower bound when files cannot be checked; incomplete coverage is disclosed.

Before asking for approval, show the triggered thresholds, indexed/unarchived counts, measured bytes and missing coverage, protected counts, proposed roots **and every affected descendant**, intended operation, recovery limits and expected disk reclaim. Then link the complete plan and give its hash. A link alone is not a reviewable overview.

**Native archive changes history visibility; expected disk reclaim is 0 bytes.** The supported Codex 0.154.0 archive API cascades to descendants, so the reviewed scope includes the entire descendant tree. Unarchive affects one thread at a time; recovery must unarchive every affected ID. The tool uses native APIs, without directly writing the index or manually moving transcript files.

Read-only auditing supports macOS/Linux with a recognized schema. Native history writes initially require macOS with OS-enforced network denial; unsupported native versions or unrecognized pin/lineage state refuse mutation. Preserve current/pinned/keep-protected descendants: a root cannot bypass their protection.

To recover actual storage, use the separate verified-ZIP and explicitly approved original-removal workflow. Approval to change history visibility does not authorize deleting transcript originals.

The initial native canary used isolated synthetic root/child/grandchild sessions with the installed Codex binary; transcript content SHA-256 values remained unchanged. It is evidence about API behavior in that test, not archiving of real user history or proof of native conversation continuation.

Incomplete index, file or lineage coverage blocks executable native plans while still allowing pressure reports. Native unarchive updates Codex timestamps and file mtime; recovery verifies paths, content and archive state, not original timestamps.

## Other things you can ask

| What you want | What to tell your AI |
| --- | --- |
| Inspect a project | “Inspect `<absolute project path>`; report usage without changing files.” |
| Preserve important data | “Keep the last 30 days and `<path to keep>`; show remaining candidates.” |
| Back up conversations | “Back up selected old conversations, verify bytes and retain originals.” |
| Remove already archived originals | “Prepare an archive-removal plan for these main transcripts. Verify the existing backups, show the exact scope and history risk, and wait for my confirmation.” |
| Recover archived originals | “Restore the approved archive-removal run to its exact original paths. Do not overwrite existing files or claim conversation continuation.” |
| Undo quarantine | “Restore the approved log/cache quarantine; report conflicts without overwriting.” |

`archive-restore` restores exact bytes at original paths; a new inode is expected. It does not rebuild indexes or restore complete harness state. Preserve archives, manifests and the run journal. Backup-only operations retain originals and consume additional storage.

## Supported scope

| Content | Current behavior |
| --- | --- |
| Codex `log/codex-tui.log`, `logs/codex-tui.log`; Claude `debug/` logs | Old recognized regular files may use approved quarantine and separate purge |
| Codex native history | Read-only pressure audit; complete-audit and exact-approved native archive/unarchive; macOS Codex 0.154.0; zero disk reclaim |
| Python `__pycache__/*.pyc` | Requires existing Git-tracked source; cache ignored and untracked |
| Recognized old main transcripts | Backup first; separate archive plan, exact approval and history-risk acknowledgement before removal |
| Subagent, sidechain, fork or unknown-origin transcripts; tool results, checkpoints and assets | No source removal; backup-only where supported |
| Worktrees, source, memories, credentials, databases, unknown objects | No automatic deletion |

See the [CLI guide](docs/cli.md), [compatibility](docs/compatibility.md) and [v0.2.0 evidence record](docs/releases/v0.2.0.md). Keep local reports and recovery data private.

## v0.5.0: real evidence and decision comparison

On 2026-09-22 we checked **14 existing files, 404,874,193 logical bytes**, with 10 distinct evidence combinations. These included old/recent/current and related sessions, protected files and assets. Local evidence took **329 ms** (index/policy 16, activity 287, backup 24); no full inventory scan is included.

| Observation | Measured result |
| --- | --- |
| v0.4.0 on the same selected files | 1,060 ms; 2 removal-preparation suggestions, 12 reviews |
| v0.5 evidence, two frozen-input repetitions | **1,459 / 1,405 ms** including fact collection; both 5 local keeps, 9 reviews |
| Existing backup evidence | 2 selected source/member byte checks passed; 1 manifest-only match deferred by budget; 6 had no match in supplied archives; 5 were not checked |
| Local protection | 5 objects bypassed Jev; this is local policy, not model judgment |
| Raw Jev choices in each repetition | 8 reviews; 1 verify-existing-backup choice at confidence 0.44, routed to review by the local 0.5 rule |
| Observed consistency | 9/9 raw choices and 14/14 final actions matched across the two repetitions |
| User recovery need | Unknown; removal-preparation choices stayed closed |
| Source stability / actual reclaim | 9/9 checked source hashes matched; 5 protected/dynamic files were not hashed; **0 bytes reclaimed** |

The 16 MiB logical verification budget covered 9,776,540 bytes of source plus expanded selected-member reads. It did not verify whole ZIPs or native conversation resume. Selection and additional before/after hashes are outside the timed stage. Pinned threads and eligible old logs/caches were not covered by this real sample.

**This validates evidence collection and stricter gates, not accurate backup-versus-delete judgment.** New runs were slower than this baseline. Removing the old baseline's two preparation suggestions follows stricter evidence/recovery requirements, not proven model improvement. Two repeats do not establish a general consistency rate.

The initial attempt had one `unavailable-or-invalid` batch; its old generic status did not record whether transport or validation caused it. One frozen diagnostic and the subsequent full comparison succeeded. Across all attempts: 11 calls, 10 accepted responses, 20,159 known input tokens; known input cost is estimated at US$0.000846678 using the [official price](https://docs.typesafe.ai/models), excluding unknown usage of the failed call. Billing was not verified. [All sanitized results, including the failure](docs/experiments/real-jev-evidence-2026-09-22.json) · [Reproduction tool](tools/live_evidence_validation.py).

## v0.4.0: real Jev triage latency comparison

On 2026-09-22, the same **33 existing old main transcripts, 1,049,047,931 bytes (about 1.05 GB)** were evaluated with serial and concurrent real provider calls. No provider responses were mocked; full source hashes matched before and after.

| Observation | Serial (1 in flight) | Concurrent (up to 3 in flight) |
| --- | ---: | ---: |
| Candidates / actual API calls | 33 / 5 | 33 / 5 |
| Fresh local fact checks | 7 ms | 8 ms |
| Provider wall time | 10,063 ms | 3,453 ms |
| Total suggestion-stage time | **10,070 ms** | **3,461 ms** |
| Raw Jev choices | 33 prepare-removal | 31 prepare-removal, 2 review |
| Recommendations after low-confidence routing | 33 review | 5 prepare-removal, 28 review |
| Actual deletions / reclaimed space | **0 / 0 bytes** | **0 / 0 bytes** |

Concurrent elapsed time was about **66% lower in this comparison**. Timings cover fresh identity/retention/header checks and real inference, reusing an existing selected inventory. Full scans, archive verification and benchmark-only before/after source hashes are excluded. The two runs used 25,628 input tokens, estimated at US$0.001076376 using the [official rate](https://docs.typesafe.ai/models); billing was not verified.

All 33 files had identical metadata in the provider packet; different choices did not establish file-specific understanding. Recommendations differed between runs; low confidence routes to review under a product rule. This sample has no labeled ground truth and establishes neither deletion accuracy nor a repeatable speedup. No real cleanup occurred. Removal preparation still needs recovery-needs review, verified backups, protection checks and explicit approval of the final plan. [Sanitized results](docs/experiments/real-jev-triage-2026-09-22.json) · [Reproduction tool](tools/live_triage_validation.py).

## v0.3.0 history checks

Two different checks ran on 2026-09-21; the native API check used isolated synthetic transcripts.

| Check | Observed result |
| --- | --- |
| Real Codex index, read-only | 3,947 threads; 2,862 unarchived, 1,085 archived |
| Known indexed file sizes | 10,884,095,473 bytes (10.137 GiB); largest 0.989 GiB |
| Default alerts | Total size and unarchived count triggered; single-file size did not |
| Incomplete audit | 2,027 missing/unsafe file records, 25 unresolved edges, 884 lineage issues; executable planning refused (exit 2) |
| Actual native API, synthetic data | 3 related threads archived, individually restored and verified; all 4 original paths/content hashes matched afterward |
| Approval safeguards | Wrong hash, missing stopped-writer acknowledgement, wrong recovery approval and replay all refused |
| Real history changed / disk reclaimed | 0 threads / 0 bytes |

[Real read-only evidence](docs/experiments/real-codex-history-v03-2026-09-21.json), [isolated native evidence](docs/experiments/synthetic-native-archive-v03-2026-09-21.json), and [full workflow](docs/history.md). Counts describe that snapshot; coverage gaps overlap and do not prove missing data. No real-user native archival, UI performance benefit or conversation continuation is claimed.

## v0.2.0 workflow validation

On 2026-09-21, the published v0.2.0 was checked against existing local files with real Jev calls. No synthetic files or artificial file aging were used for this run.

| Check | Result |
| --- | --- |
| Archived removal, original-path restore, approval refusals, interrupted/read-only recovery | 63 local tests passed using isolated test data |
| Fresh real inventory | 49,810 files; 231 skipped boundaries. The scan is incomplete and is not whole-disk accounting. |
| Existing sources and archives reverified | 189 transcripts, 6,282,966,045 bytes (5.851 GiB); 9 existing archives, 4.188 GiB. Full source SHA-256, full archive SHA-256 and decompressed selected-member bytes all matched. |
| Refusal checks using a real plan | Wrong plan hash, missing stopped-writer attestation and missing history-risk acknowledgement all refused execution; no deletion transaction was created. |
| Fresh live Jev calls | 20 existing files: 7 transcripts, 3 logs, 3 Python caches, 3 protected files, 2 checkpoints and 2 assets. Two calls, 40 decisions, all `review`. |
| Jev latency and usage | 1,761 / 1,821 ms; 9,374 input tokens. Estimated US$0.000393708 at the [official rate](https://docs.typesafe.ai/models); billed cost was not verified. |
| New real-source cleanup | Awaiting exact human approval; not executed, with 0 bytes of verified reclaim. The hash checks above were read-only. |

No old log/cache files in this scope met the 30-day retention and local eligibility checks, so **none of the 20 candidates offered `delete`; live delete recommendations were not validated**. Eleven candidates allowed `backup`; the remaining nine allowed only `keep/review`. Jev chose review for all of them. Two matching runs establish observed choice consistency for this sample, with no labeled ground truth or evidence of accuracy gains over rules. Only allowlisted metadata was sent, without paths, filenames, transcripts or code.

[Fresh read-only evidence](docs/experiments/real-session-preflight-v02-2026-09-21.json) · [Fresh sanitized Jev evidence](docs/experiments/real-jev-mixed-v02-2026-09-21.json) · [Earlier single-call check](docs/experiments/real-jev-v02.json). Real-original removal and original-path restoration still require approval of the exact list; file recovery does not establish native conversation continuation.

## Real 10 GiB validation and live Jev comparison

The following historical backup measurements predate v0.2.0 archive removal and its expanded Jev choices. They do not validate those new capabilities.

**Cleanup of real user data always requires explicit human confirmation of the concrete scope.** This run only read originals, created private archives and verified recovery bytes. No original was quarantined, moved or deleted.

Measured on 2026-09-21: **564 existing session files, 10,932,021,589 bytes (10.181 GiB)**. Codex samples were at least 7 days old; Claude samples at least 1 day old. Selection checked open handles and froze full-file hashes. The source inventory skipped 227 boundaries and is not a whole-disk inventory.

| Real dataset | Files | Original bytes | ZIP bytes | Archive size reduction | Full stream restore / final source hash |
| --- | ---: | ---: | ---: | ---: | --- |
| Codex historical sessions | 560 | 9,932,261,559 (9.250 GiB) | 5,447,045,764 (5.073 GiB) | 45.16% | All matched |
| Claude historical sessions | 4 | 999,760,030 (0.931 GiB) | 252,487,818 (0.235 GiB) | 74.75% | All matched |
| **Total** | **564** | **10.181 GiB** | **5.308 GiB** | **47.86%** | **564/564 matched** |

All **1,107,896 nonblank JSONL records** passed parsing, with zero malformed or over-limit lines. Every archive was fully decompressed through SHA-256 verification; this was streamed verification, not restoration over live harness directories. The logical difference between originals and ZIPs is **4.873 GiB**. **Actual cleanup reclaimed 0 bytes** because originals remain; archives and retained validation copies consume additional space. This difference is not a promised filesystem reclaim amount. The run was paused once to add a 64 MiB JSONL line-length limit (not a process memory cap), then resumed using one completed shard; its timings/free-space observations are scoped to that resumed invocation, not a cold-start performance benchmark.

| Native history check, network denied by OS sandbox | Actual result | Acceptance |
| --- | --- | --- |
| Codex CLI 0.154.0, 2 archived samples | Eager and paginated read APIs did not produce nonempty history | **Not validated**; do not claim session restoration or continuation |
| Claude SDK 0.2.126, 2 samples | Global UUID lookup initially selected different duplicates; each UUID had 2 files in the original namespace | Global lookup was ambiguous |
| Claude, baseline bound to the exact source file | Isolated source copies and restored files matched **87** and **63** messages, including canonical history digests | Exact-file native reading passed; full environment restoration/continuation unverified |

| Rule-only baseline vs live Jev | Observed result |
| --- | --- |
| Rule-only behavior | Retain all 564 originals; cleanup requires human confirmation |
| Live sample and repetition | 20 real candidates selected from the frozen dataset; 3 calls, 60 decisions, **all `review`**; same choices across all repetitions |
| Actual provider and round-trip latency | `jev-1.13.0`; 1,286 / 2,010 / 3,170 ms; median **2,010 ms** |
| Usage and cost | Comparison: 10,398 input tokens. Including the 3-candidate connectivity canary: **4 live calls, 11,141 input tokens**, estimated **US$0.000467922** at the [official input price](https://docs.typesafe.ai/models); billing-statement amount not verified |
| Interpretation | Live structured inference is verified; no labeled ground truth or evidence that Jev improves cleanup accuracy or permits broader deletion |

Only category, size/age bands, rule eligibility and unknown active-state metadata were sent. No path, filename, original ID, transcript, code or credential was included in model state. A model's `review` or confidence never replaces human cleanup approval.

[10 GiB sanitized measurements](docs/experiments/real-10g-2026-09-21.json) · [Live Jev results](docs/experiments/real-jev-2026-09-21.json) · [Native-read findings, including failures](docs/experiments/real-native-history-2026-09-21.json).

Reproduction tools are available in current `main` (the v0.1.1 release predates this validation): [large real-data validation](tools/large_real_validation.py), [opt-in live Jev comparison](tools/live_jev_validation.py), and [macOS network-isolated native reader](tools/native_history_validation.py). They create private artifacts and never remove originals. Native tools/SDK are optional local dependencies, not automatic installs. These real-data or paid-provider checks never run in CI.

The earlier 214 MiB validation and custom-log safety finding are preserved in [historical real-data evidence](docs/experiments/real-small-validation.md).

## Development and evidence

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
```

Local tests cover the CLI workflow, native history boundaries and interrupted recovery. CI runs on macOS/Linux with Python 3.11/3.14; check the [actual workflow results](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml). See [release notes](docs/releases/v0.5.0.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). MIT © 2026 Fireworks.
