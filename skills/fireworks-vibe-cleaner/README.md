# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Use plain language in Codex or Claude Code to inspect coding logs, conversations and caches, ask Jev for handling suggestions, and approve a concrete plan before any cleanup. Recommended setup starts with Jev; local rules-only use remains available.

**Cleanup requires human approval of the specific plan.** v0.2.0 can verify existing archives, remove approved old main transcripts and restore their original paths. Byte restoration does not establish native conversation continuation.

## Use it from Codex or Claude Code

### 1. Install, then configure Jev

> Install fireworks-vibe-cleaner v0.2.0 from https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner into this tool's personal Skill directory. Do not overwrite an existing installation or clean any files. Then help me configure Jev securely.

You need macOS/Linux and Python 3.11+. See the [manual installation guide](docs/cli.md#install). Jev uses `TYPESAFE_API_KEY`, injected through a secret manager or process environment; never paste the key into chat, a report or command history. `doctor` checks whether a key is present, not whether authentication or inference succeeds.

> Explain Jev's metadata and possible charges before making a network call. If I choose rules-only mode, continue locally without a key.

Jev is recommended for suggestions, but network calls still require authorization. It receives coarse metadata, not paths, filenames, conversation text or code. Its choices are **keep, review, backup or delete**; delete is offered only for locally checked old logs/rebuildable caches with a clear open-handle snapshot. This snapshot does not prove writers have stopped. Jev cannot approve or execute deletion. Missing credentials and provider failures fall back to local rules.

### 2. Inspect and ask for recommendations

> Use fireworks-vibe-cleaner to inspect Codex and Claude Code storage. Show the main sources of usage and what must be kept. For selected candidates, check local activity and, if I've authorized the call, ask Jev whether to back up, keep, review or consider deleting them. Show me the results before moving or deleting anything.

Project roots are opt-in. Scans do not cover the whole disk; skipped directories and unreadable files must be disclosed. Unknown activity, protected objects and credentials never acquire deletion authority from model output.

### 3. Approve the exact plan

> Show the exact files, method, bytes, recovery limits and plan hash. Wait for my approval of that plan. If it involves archived conversations, also explain that history may become unavailable and restoring file bytes does not prove I can continue the conversation.

There are two separate cleanup paths:

- **Old logs/caches:** approve quarantine, verify it, then restore or separately approve permanent purge. Same-volume quarantine releases **zero bytes**.
- **Already-backed-up main transcripts:** `archive-plan` validates existing archives and selected source bytes. Only after exact-plan approval, stopped writers and explicit history-risk acknowledgement does `archive-apply` remove the selected original transcript files while retaining the archives. Related files and harness indexes are unchanged.

A broad cleanup request does not approve unseen files. Stop relevant writers before mutation; `--writers-stopped` records an acknowledgement, not a process-stopping action. Changed scope or source requires a new plan.

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

| Content | v0.2.0 behavior |
| --- | --- |
| Codex `log/codex-tui.log`, `logs/codex-tui.log`; Claude `debug/` logs | Old recognized regular files may use approved quarantine and separate purge |
| Python `__pycache__/*.pyc` | Requires existing Git-tracked source; cache ignored and untracked |
| Recognized old main transcripts | Backup first; separate archive plan, exact approval and history-risk acknowledgement before removal |
| Subagent, sidechain, fork or unknown-origin transcripts; tool results, checkpoints and assets | No source removal; backup-only where supported |
| Worktrees, source, memories, credentials, databases, unknown objects | No automatic deletion |

See the [CLI guide](docs/cli.md), [compatibility](docs/compatibility.md) and [v0.2.0 evidence record](docs/releases/v0.2.0.md). Keep local reports and recovery data private.

The following measurements predate v0.2.0 archive removal and its expanded Jev choices. They do not validate these new capabilities.

## v0.2.0 workflow validation

| Check | Result |
| --- | --- |
| Archived removal, original-path restore, approval refusals, interrupted/read-only recovery | 63 local tests passed using isolated test data |
| Live Jev with the expanded action contract | 1 call, 20 real candidates, all `review`; 4,936 input tokens, 2,620 ms |
| New real-source cleanup | Awaiting approval of the exact file list; not executed. Test-fixture deletion is not real-user space recovery. |

[Sanitized live Jev record](docs/experiments/real-jev-v02.json). No accuracy or advantage over rules is established.

## Real 10 GiB validation and live Jev comparison

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

All 63 local tests passed, covering the CLI workflow and interrupted recovery. CI runs on macOS/Linux with Python 3.11/3.14; check the [actual workflow results](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml). See [release notes](docs/releases/v0.2.0.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). MIT © 2026 Fireworks.
