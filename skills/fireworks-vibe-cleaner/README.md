# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Use plain language in Codex or Claude Code to find out how much space your coding logs, conversations and caches take up, then decide what to do with them. Checks run locally by default; no additional model API setup is needed.

**You must approve the specific file list before cleanup. Moving files into quarantine also needs your approval; permanently deleting them needs a separate confirmation.**

## Use it from Codex or Claude Code

### 1. Ask your AI to install it

Paste this into the Codex or Claude Code session you use:

> Install fireworks-vibe-cleaner from https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner using the published v0.1.1 release. Put it in this tool's personal Skill directory, and don't overwrite an existing installation. Check the requirements and tell me whether it is ready to use. Don't clean up any files yet.

You need macOS or Linux and Python 3.11 or later. Your AI can check what is missing; if it cannot run the installation, follow the [manual installation guide](docs/cli.md#install). Once installed, ask your AI to use `fireworks-vibe-cleaner` by name.

### 2. Find out where the space is going

> Use fireworks-vibe-cleaner to check how much space Codex and Claude Code are using. Show me the main sources of disk usage, old logs or caches worth reviewing, and anything that must be kept. Show me the findings first; don't move or delete files.

It checks the two tools' data directories and lists their usage and cleanup candidates. To include a project, give it that project's path. It does not scan your whole disk by default, and it should tell you about directories it skipped or files it could not read.

### 3. Review the plan before approving cleanup

> Based on that scan, show me a specific cleanup plan: which files, how much space they take up, why they can be handled, what you will do with them, and whether I can undo it. Wait for me to approve this plan before acting.

Your AI must explain the scope and method first. A general request to “clean things up” does not approve deleting an unseen set of files. Your confirmation applies to that specific plan; changed files or scope require a new confirmation.

The supported cleanup flow first moves approved old logs or caches into a quarantine folder on the same disk. After checking the result, you can restore them or separately approve permanent deletion. **Moving files into quarantine does not free disk space.** Before cleanup, the relevant tools or project processes must stop writing to those files; your AI should explain what you need to do.

## Other things you can ask

| What you want | What to tell your AI |
| --- | --- |
| Check a project | “Use fireworks-vibe-cleaner to inspect this project: `<absolute project path>`. Just report disk usage for now; don't change files.” |
| Keep important files | “Keep logs from the last 30 days, and leave `<path to keep>` alone. Show me the remaining candidates first.” |
| Back up old conversations | “Find large older conversations and list what you would back up, including the extra space needed. Verify the backup contents and keep the originals.” |
| Undo a quarantine operation | “Restore the files from the quarantine operation I just approved. If a file already exists at its original path, don't overwrite it; tell me first.” |

Session backups use additional space, and the current version does not delete original conversations. Matching backup contents also does not prove that you can continue the conversation in Codex or Claude Code.

For optional advice from Jev on uncertain candidates, you can say:

> Ask Jev for a second opinion on these candidates. First explain what information would be sent and whether there is a charge, then wait for my approval to make the network call. Show me the advice; don't use it to clean up files automatically.

Jev is optional, requires a TypeSafe API key and may incur charges. It receives metadata such as file category, size and age bands, without paths, filenames, conversation text or code. Its advice never replaces your cleanup approval. You can inspect and clean supported files without Jev.

## What it can handle today

| Content | Current behavior |
| --- | --- |
| The tools' own older logs | Recognizes Codex `log/codex-tui.log`, `logs/codex-tui.log` and Claude `debug/` logs; keeps the last 30 days by default and lists older files as candidates |
| Python project caches | Only `__pycache__/*.pyc` with existing Git-tracked source; the cache itself must be ignored and untracked by Git |
| Conversations, tool results, checkpoints and generated files | Reports usage and can back up selected files; keeps the originals |
| Codex worktrees | Inspects and classifies them; does not automatically remove them |
| Source code, memories, credentials, databases and unrecognized content | Excluded from cleanup |

For full commands, requirements and recovery steps, see the [manual installation and CLI guide](docs/cli.md). See [compatibility](docs/compatibility.md) for supported scope. Local scan reports may contain private paths; keep them on your machine.

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

CI passed on Linux/macOS with Python 3.11/3.14, covering safety and recovery tests, packaging and clean installation without model credentials. See the workflow files and [release notes](docs/releases/v0.1.1.md) for actual evidence; a configured workflow is not a passing run. See [CONTRIBUTING.md](CONTRIBUTING.md) for development and [SECURITY.md](SECURITY.md) for the threat boundary. MIT © 2026 Fireworks.
