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

Jev may suggest `keep`, `review` or `backup`. It cannot authorize deletion, change a plan or override a protection rule. Its confidence is not a probability of safe deletion. Missing credentials, HTTP errors or invalid responses fall back to rules-only mode. Calls may incur provider charges; a one-call cap is not a monetary budget guarantee. Live endpoint and accuracy verification are pending; core cleanup does not depend on Jev availability.

## Real local validation

**Real data, 2026-09-21 · macOS 26.5.1 · arm64 · Python 3.14.6. Actual cleanup reclaimed 0 bytes.** This result does not demonstrate that v0.1 solves large session storage growth. No fixtures or mocked service responses were used for the measurements below.

| Measurement | Before | After / observed result |
| --- | ---: | --- |
| Real inventory | 49,064 files; 21,165,470,439 logical bytes (19.71 GiB) | Metadata-only scan; 225 symlink/dependency boundaries skipped; not a complete disk total |
| Session footprint | 2,615 files; 15,038,397,937 bytes (14.01 GiB) | Originals retained; session deletion and harness resume remain unsupported |
| Cleanup policy correction, identical snapshot | 8 custom-service logs incorrectly eligible; 196,608 allocated bytes | All 8 protected after narrowing the Codex filename allowlist; **0 eligible files** |
| Real Codex session backup (2 files) | 126,384,858 bytes (120.53 MiB) | ZIP 37,856,051 bytes (36.10 MiB), 70.05% smaller; 1978 ms |
| Real Claude session backup (2 files) | 98,252,538 bytes (93.70 MiB) | ZIP 21,852,674 bytes (20.84 MiB), 77.76% smaller; 1214 ms |
| Byte recovery | SHA-256 of each real source recorded privately | All 4 extracted copies matched; all 4 source hashes unchanged |
| Actual disk benefit | No approved eligible cleanup target after correction | **0 source bytes deleted; 0 cleanup bytes reclaimed**; retained ZIPs/manifests added 59,712,330 logical bytes (56.95 MiB) |
| Live Jev comparison | No inference request authorized for this run | **Not run**; no accuracy, latency or benefit claim based on a mock |

The four sessions were selected from stable files at least one day old, at most 64 MiB each, with no open handle at selection. Compression ratios apply to these samples only. Backup durations measure the backup operation, including its readback, and exclude initial hashing/extraction. Originals remain in place; smaller ZIPs are **not** reclaimed space. Observed volume free-space deltas were −38,461,440 bytes (Codex volume) and −21,991,424 bytes (Claude volume), including concurrent background writes; neither is attributed solely to the experiment. The extracted verification copies were removed; private archives and manifests remain local.

The real scan exposed a safety bug: arbitrary custom-service `.log` files in a Codex log directory were treated as harness logs. Current `main` restricts Codex cleanup to `log/codex-tui.log` and `logs/codex-tui.log`. Old plans are reclassified at execution and rejected when outside this allowlist. This result establishes a protection fix and byte-preserving backups; **real quarantine/purge and session resumption were not validated**.

[Sanitized real results](docs/experiments/real-local-2026-09-21.json) · [Real-data validation script](tools/real_validation.py). Public results contain aggregate sizes/counts/timings only; no usernames, paths, filenames, IDs, content hashes, transcripts or credentials. Raw inventories and backups must stay private.

```sh
python3 scripts/fireworks-vibe-cleaner.py scan --output artifacts/private-inventory.json
python3 tools/real_validation.py --inventory artifacts/private-inventory.json --output artifacts/real-results.json
```

Use a new output filename. The script creates private same-volume backups and temporary extraction copies; it never removes original sessions. This is a local opt-in operation, **not a CI job**. [Historical synthetic regression results](docs/experiments/synthetic-regression.md) remain available for safety mechanics and are not effectiveness evidence. CI continues to exercise fixtures without accessing personal data.

## Development and evidence

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
```

CI passed on Linux/macOS with Python 3.11/3.14, covering safety and recovery tests, packaging and clean installation without model credentials. See the workflow files and [release notes](docs/releases/v0.1.1.md) for actual evidence; a configured workflow is not a passing run. See [CONTRIBUTING.md](CONTRIBUTING.md) for development and [SECURITY.md](SECURITY.md) for the threat boundary. MIT © 2026 Fireworks.
