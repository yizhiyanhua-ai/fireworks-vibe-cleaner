# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Understand disk growth from Codex and Claude Code, review a bounded cleanup plan, and verify what actually changed. An Agent Skill and a standalone Python CLI, offline by default, with optional Jev advice.

**v0.1 is deliberately narrow:** cleanup covers old, recognized harness logs and Git-ignored Python bytecode with tracked source. Sessions can be copied and checked, but their originals are retained. Quarantine on the same volume releases **zero bytes**; permanent deletion is a separate approved action.

## What it handles

| Data | v0.1 behavior |
| --- | --- |
| Codex `log/`, `logs/` and Claude `debug/` regular logs | Retention check → reviewed plan → quarantine → restore or separately approved purge |
| Project `__pycache__/*.pyc` | Requires existing tracked source and an ignored, untracked cache file; checked again before execution |
| Session transcripts, Claude tool results and checkpoints, generated assets | Inventory and selected byte-verified backup; source retained; harness resume unverified |
| Codex worktrees | Read-only classification; no automatic removal or Git lifecycle management |
| Source, memories, credentials, databases, unknown objects | Protected from cleanup |

Default retention is 30 days. Scan eligibility is preliminary, not permission to delete. Traversal does not follow child symlinks or cross volumes; dependencies and Git internals are pruned and disclosed as incomplete coverage. This is not a whole-disk usage analyzer.

## Install

Requires Python 3.11+, macOS or Linux. Mutation of source/quarantine files additionally requires `lsof`; project-bytecode validation requires Git. No runtime Python dependencies, daemon, or default network requests.

Install the tagged source:

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

Direct script execution needs no package installation. For the shorter `fireworks-vibe-cleaner` command used below, optionally create a virtual environment and run `python -m pip install .`; alternatively replace that command with `python3 scripts/fireworks-vibe-cleaner.py`. During development, use a local checkout and omit the tag clone. Publication and live validation status are recorded in [release notes](docs/releases/v0.1.0.md).

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

Jev may suggest `keep`, `review` or `backup`. It cannot authorize deletion, change a plan or override a protection rule. Its confidence is not a probability of safe deletion. Missing credentials, HTTP errors or invalid responses fall back to rules-only mode. Calls may incur provider charges; a one-call cap is not a monetary budget guarantee. Live endpoint and accuracy verification are pending; core cleanup does not depend on Jev availability.

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

[First sanitized run](docs/experiments/local-2026-09-21.json) · [Final sanitized run](docs/experiments/local-2026-09-21-final.json) · [Reproduction script](tools/local_experiments.py). The public result contains only experiment labels, OS/runtime versions, counts, byte totals and booleans—no usernames, absolute paths, session IDs, credentials, transcripts or source contents.

```sh
python3 tools/local_experiments.py --output artifacts/local-experiments.json
```

The reproduction script and logo are available in the current `main` checkout; the original `v0.1.0` tag predates this documentation update. Use `main` to reproduce this section.

Choose a new output filename for each run. The script refuses to overwrite evidence and removes its temporary fixtures on exit. CI also runs these experiments and keeps sanitized reports as workflow artifacts.

## Development and evidence

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
```

CI passed on Linux/macOS with Python 3.11/3.14, covering safety and recovery tests, packaging and clean installation without model credentials. See the workflow files and [release notes](docs/releases/v0.1.0.md) for actual evidence; a configured workflow is not a passing run. See [CONTRIBUTING.md](CONTRIBUTING.md) for development and [SECURITY.md](SECURITY.md) for the threat boundary. MIT © 2026 Fireworks.
