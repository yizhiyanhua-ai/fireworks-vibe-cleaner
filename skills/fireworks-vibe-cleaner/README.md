# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Understand disk growth from Codex and Claude Code, review a bounded cleanup plan, and verify what actually changed. An Agent Skill and a standalone Python CLI, offline by default, with optional Jev advice.

**v0.1 is deliberately narrow:** cleanup covers old, recognized harness logs and Git-ignored Python bytecode with tracked source. Sessions can be copied and checked, but their originals are retained. Quarantine on the same volume releases **zero bytes**; permanent deletion is a separate approved action.

## What it handles

| Data | v0.1 behavior |
| --- | --- |
| Codex `log/codex-tui.log`, `logs/codex-tui.log` and Claude `debug/` logs | Retention check → reviewed plan → quarantine → restore or separately approved purge |
| Project `__pycache__/*.pyc` | Requires existing tracked source and an ignored, untracked cache file; checked again before execution |
| Session transcripts, Claude tool results and checkpoints, generated assets | Inventory and selected byte-verified backup; source retained; harness resume unverified |
| Codex worktrees | Read-only classification; no automatic removal or Git lifecycle management |
| Source, memories, credentials, databases, unknown objects | Protected from cleanup |

Default retention is 30 days. Scan eligibility is preliminary, not permission to delete. Traversal does not follow child symlinks or cross volumes; dependencies and Git internals are pruned and disclosed as incomplete coverage. This is not a whole-disk usage analyzer.

## Install

Requires Python 3.11+, macOS or Linux. Mutation of source/quarantine files additionally requires `lsof`; project-bytecode validation requires Git. No runtime Python dependencies, daemon, or default network requests.

Install the tagged source:

```sh
git clone --branch v0.1.1 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

Direct script execution needs no package installation. For the shorter `fireworks-vibe-cleaner` command used below, optionally create a virtual environment and run `python -m pip install .`; alternatively replace that command with `python3 scripts/fireworks-vibe-cleaner.py`. During development, use a local checkout and omit the tag clone. Publication and live validation status are recorded in [release notes](docs/releases/v0.1.1.md).

To install the Skill, generate the bundle and copy it to the harness you use. These commands intentionally refuse to overwrite an existing installation:

```sh
python3 tools/build_skill.py
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
test ! -e "${CODEX_HOME:-$HOME/.codex}/skills/fireworks-vibe-cleaner" && cp -R skills/fireworks-vibe-cleaner "${CODEX_HOME:-$HOME/.codex}/skills/"
# Alternatively, for Claude Code:
mkdir -p "$HOME/.claude/skills"
test ! -e "$HOME/.claude/skills/fireworks-vibe-cleaner" && cp -R skills/fireworks-vibe-cleaner "$HOME/.claude/skills/"
```

The copied Skill includes its Python launcher. Ask your harness to use `fireworks-vibe-cleaner` to inspect space and propose a cleanup scope. It must obtain approval for the exact plan before modifying source files.

## Inspect, review, then act

```sh
fireworks-vibe-cleaner scan --output scan.json
fireworks-vibe-cleaner report --scan scan.json
# Explicit project roots are opt-in; repeat --root to select multiple roots.
fireworks-vibe-cleaner scan --root project=/absolute/path/to/project --output project-scan.json
```

Default roots respect `CODEX_HOME` and `CLAUDE_CONFIG_DIR`. `--keep '*/important.log'` protects matching files. Reports contain local paths: keep them private. Growth comparison requires two complete scans of identical roots: `report --scan later.json --previous earlier.json`.

The commands below are templates: replace `CANDIDATE_ID`, `REVIEWED_PLAN_HASH`, `RUN_ID` and paths with values you have inspected. Keep the state directory on the same volume as the selected files, outside their source directories, and private (mode `0700`). The CLI creates a new state directory with that mode. A plan expires after one hour.

```sh
fireworks-vibe-cleaner plan --scan scan.json --id CANDIDATE_ID   --state-dir /absolute/path/to/private-state --max-bytes 104857600 --output plan.json
# Read all of plan.json; explicitly approve that scope and hash.
# Stop the relevant harness/project writers before acknowledging this flag.
fireworks-vibe-cleaner apply --plan plan.json --approve REVIEWED_PLAN_HASH --writers-stopped
fireworks-vibe-cleaner verify --state-dir /absolute/path/to/private-state --run RUN_ID
```

`apply` checks the approval hash, expiry, byte cap, file identity, content hash, local policy and open handles. It records a journal and moves approved files into same-volume quarantine. `--writers-stopped` is your acknowledgement, not a command that stops processes. `lsof` failures or inconclusive results refuse the operation. Concurrent writers remain a risk; do not clean a running harness.

Choose recovery **or** permanent deletion after verification:

```sh
fireworks-vibe-cleaner restore --state-dir /absolute/path/to/private-state --run RUN_ID --writers-stopped
# Separate explicit approval is required; this cannot be undone by the cleaner.
fireworks-vibe-cleaner purge --state-dir /absolute/path/to/private-state --run RUN_ID   --approve purge:RUN_ID --writers-stopped
```

Restore refuses to overwrite an occupied source path. After an interruption, run `verify`, preserve the journal and recovery files, and resolve the reported state; do not replay `apply`. A restored run cannot be purged. Quarantine defaults to a 1 GiB logical capacity limit (`apply --state-cap-bytes`). Purge reports deleted logical bytes and observed volume free-space change separately; snapshots, shared blocks and unrelated writes affect the latter.

## Session copies

```sh
mkdir -m 700 /absolute/path/to/new-private-backups
fireworks-vibe-cleaner backup --scan scan.json --id SESSION_CANDIDATE_ID   --output /absolute/path/to/new-private-backups/session.zip --max-bytes 104857600
fireworks-vibe-cleaner extract --archive /absolute/path/to/new-private-backups/session.zip   --destination /absolute/path/to/new-extraction-directory
```

Backup checks archived bytes against hashes. Keep the ZIP and its `.manifest.json` together. Extraction defaults to a 1 GiB byte cap (`extract --max-bytes`). It writes numbered copies into a new directory and checks hashes; it does not rebuild live harness state. **A valid backup is not evidence that a session can resume.** Sources remain untouched, so this increases storage use. Backups are unencrypted and restricted to the source volume; cross-volume moves, encryption and session deletion are not implemented.

## Optional Jev advice

Supply `TYPESAFE_API_KEY` through your secret manager or process environment, never in command history or a report. Explicitly opt in:

```sh
fireworks-vibe-cleaner advise --scan scan.json --id CANDIDATE_ID --enable-network --output advice.json
```

One invocation makes at most one TypeSafe API call for 1–20 selected candidates. It sends temporary candidate labels, category, size/age bands, rule eligibility and unknown activity status. It does **not** send paths, filenames, original candidate IDs, session text, source code or free-text reasons. The payload cap is 16 KiB, response cap 64 KiB, network timeout 8 seconds; redirects and automatic retries are disabled.

Jev may suggest `keep`, `review` or `backup`. It cannot authorize deletion, change a plan or override a protection rule. Its confidence is not a probability of safe deletion. Missing credentials, HTTP errors or invalid responses fall back to rules-only mode. Calls may incur provider charges; a one-call cap is not a monetary budget guarantee. Live metadata-only calls succeeded on 2026-09-21 (Jev 1.13.0); measured results are below. Accuracy and superiority over rules remain unverified. Core cleanup does not depend on Jev availability.

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
