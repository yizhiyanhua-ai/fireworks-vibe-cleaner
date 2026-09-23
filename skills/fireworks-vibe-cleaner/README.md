# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

fireworks-vibe-cleaner is a **Skill plus CLI**. Tell Codex or Claude Code what you need in plain language; the Skill inspects and explains, while the CLI performs deterministic scans, verification, execution and recovery. Real cleanup starts only after you see and approve the exact list, method, impact and plan hash.

## Start with three prompts

### 1. Install it and preferably configure Jev

> Install fireworks-vibe-cleaner from https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner. Check requirements and any existing installation; do not overwrite it or clean files. Then explain how to configure Jev securely. If I skip configuration, start with local rules.

Requires macOS/Linux and Python 3.11+. See the [CLI guide](docs/cli.md) for manual installation. Jev receives fixed metadata to help triage; it does not receive paths, titles, transcripts or code. Disclose data scope and possible charges before a network call, and never paste an API key into chat or command history.

### 2. Review the list and state what must be kept

> Check how much storage Codex and Claude Code use. Show candidates, recommendations, reasons, alternatives, expected impact and unknowns directly in chat. Leave active, linked, explicitly kept and unclear content alone. Show findings before deleting anything.

Say “I need to continue these conversations” for important sessions. If file-copy recovery is enough, say which sessions only need a verified archive. Unclear requirements stay unknown. Jev, local rules and assistant purpose judgments provide advice; none can approve cleanup for you.

### 3. Approve this specific operation

> Show the exact files, method, backup location, expected reclaim, recovery limits and plan hash, then link the full plan. Wait for my approval and report actual results afterward.

Relevant writers must stop first. If an unchanged plan expires, `archive-refresh` revalidates the same sources and archive bindings and creates a new hash, which still needs approval. For larger cleanup, use `archive-workflow-*`: the CLI removes and restores one canary file and verifies its original path and bytes before it can start the cleanup plan.

## What do backup, archive and cleanup change?

| Operation | Originals and disk space |
| --- | --- |
| Backup | Create or reuse a copy and retain originals; a new copy consumes space |
| Codex history archive | Change history-list visibility; expected reclaim is 0 bytes |
| Log/cache quarantine | Move files to same-volume recovery storage; quarantine itself frees no space, and purge needs separate approval |
| Remove backed-up transcript originals | Verify archives first, then remove only approved originals; bytes can be restored, but native continuation remains unverified |

## Real execution evidence

On 2026-09-23, one real operation completed after approval of its exact scope:

| Check | Actual result |
| --- | --- |
| Recovery canary | One 2,036,098-byte original was removed, verified, restored and verified again; the original remained at the end |
| Cleanup | 188 originals totaling 6,280,929,947 logical bytes (about 5.850 GiB) were removed; 188/188 were valid `archive-only` items and 9 archives were retained |
| Volume observations | The executor window increased by 5,173,981,184 bytes; an external `df` window increased by 5,198,995,456 bytes (about 4.842 GiB). The windows differ and may include unrelated writes and filesystem accounting |
| Excluded scope | 375 reviewed but unselected objects did not enter the cleanup plan; databases, indexes, related files, source, Skills and credentials were outside the mutation scope |
| Concurrent Jev check | Two runs over 14 real candidates returned review for all 28 decisions; no accuracy advantage over local rules was shown, and model output did not authorize cleanup |
| Still unverified | Native conversation continuation and original-path restoration of all 188 removed files; the real restore exercise covered only the one canary |

[Sanitized execution evidence](docs/experiments/real-approved-cleanup-2026-09-23.json). Logical bytes removed, volume movement and recovery coverage are separate measurements; they do not establish that every removed session was restored.

## When Codex history gets large

> Check my Codex history. If total size exceeds 3 GiB, one session exceeds 3 GiB, or the unarchived count exceeds 200, show a recommendation. Keep the newest 100, the last 30 days, pinned/current sessions and my explicit keep list. Give me an overview before the full plan and wait for approval.

Thresholds trigger advice only. Native history archive is expected to reclaim 0 bytes. Actual storage recovery uses the separate “verify ZIP → approve exact plan → restore canary → remove originals” flow. See the [history guide](docs/history.md).

## Supported and protected scope

| Content | Current behavior |
| --- | --- |
| Recognized Codex/Claude Code logs | Old files may use approved quarantine and separately approved purge |
| Codex native history | Read-only pressure audit; archive/recovery after complete audit and exact approval; expected reclaim 0 bytes |
| Python `__pycache__/*.pyc` | Only untracked cache with corresponding Git-tracked source |
| Recognized old main transcripts | Verify backup first, then exact-hash approval and canary-gated workflow |
| Subagent, sidechain, fork, unknown-origin, tool-result, checkpoint and asset files | No source removal; backup-only where supported |
| Worktrees, source, memories, credentials, databases and unknown objects | No automatic deletion |

See the [CLI guide](docs/cli.md), [Jev boundaries](docs/jev.md), [purpose evidence](docs/purpose.md), [compatibility](docs/compatibility.md) and [security policy](SECURITY.md). Keep local inventories, plans, archives and recovery journals private.

## v0.6.0: useful purpose evidence, with a rules comparison

The same **14 real files (404,874,193 bytes)** were evaluated using metadata and four locally prepared assistant purpose annotations. Two annotations conservatively identified possible continuation needs. These are fallible judgments from bounded text, not user labels or proof of project status. No text or semantic summary was sent to Jev.

| Final comparison | Rules + purpose | Jev, metadata only | Jev + purpose, repeat 1 / 2 |
| --- | ---: | ---: | ---: |
| Local evidence collection | 113 ms | 304 ms | 113 ms, reused for both |
| Provider / decision time | 0 ms rounded | 1,143 ms | 1,042 / 1,100 ms |
| Combined measured stage | **113 ms** | **1,447 ms** | **1,155 / 1,213 ms** |
| Real API calls | 0 | 2 | 1 / 1 |
| Local keeps / reuse verified copy | 7 / 1 | 5 / 2 | 7 / 1 in both |
| Verify existing copy / new backup suggestion | 1 / 1 | 1 / 0 | 1 / 1 in both |
| Needs purpose review | 4 | 6 | 4 in both |

Both purpose runs matched the rule baseline's final reason codes on **14/14** files. This is **not accuracy**, and no advantage over rules was demonstrated. The useful change is source-bound purpose evidence and clearer next steps. Two extra local keeps came from assistant continuation judgments, not Jev. Four raw Jev backup choices lacked purpose evidence and were routed to review locally. One original-preserving suggestion in each purpose run remained tentative; confidence is not deletion safety.

The experiment excludes the first local annotation work and extra source hashes from timing; annotation time/model cost was not measured. Thus 1.16 seconds is not the complete first-use workflow. Nine checked source hashes matched, five protected/dynamic files were not hashed, and **zero bytes were reclaimed**. No human action labels, real Claude transcripts, visual-media understanding or real cleanup were tested.

We retain the initial probability-sum rejection, a diagnostic call and the earlier run that suggested unnecessary new copies. Across all attempts: **11 real calls, 26,635 known input tokens**, estimated known input cost **US$0.00111867** at the [official price](https://docs.typesafe.ai/models); one failed call's usage and billing remain unverified. [Full sanitized evidence](docs/experiments/real-purpose-comparison-2026-09-22.json) · [Reproduction tool](tools/live_purpose_validation.py).

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

Local tests cover the CLI workflow, native history boundaries and interrupted recovery. CI runs on macOS/Linux with Python 3.11/3.14; check the [actual workflow results](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml). See [release notes](docs/releases/v0.7.0.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). MIT © 2026 Fireworks.
