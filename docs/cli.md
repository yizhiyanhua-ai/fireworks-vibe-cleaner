# Manual installation and CLI guide

[Back to conversational usage](../README.md) · [简体中文](cli.zh.md)

If you use this Skill from Codex or Claude Code, start with the prompts in the README. The commands below are for manual installation, troubleshooting or direct CLI use.

## Install

Requires Python 3.11+, macOS or Linux. Mutation of source/quarantine files additionally requires `lsof`; project-bytecode validation requires Git. No runtime Python dependencies, daemon, or default network requests.

Install the tagged source:

```sh
git clone --branch v0.1.1 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

Direct script execution needs no package installation. For the shorter `fireworks-vibe-cleaner` command used below, optionally create a virtual environment and run `python -m pip install .`; alternatively replace that command with `python3 scripts/fireworks-vibe-cleaner.py`. During development, use a local checkout and omit the tag clone. Publication and live validation status are recorded in [release notes](releases/v0.1.1.md).

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

Jev may suggest `keep`, `review` or `backup`. It cannot authorize deletion, change a plan or override a protection rule. Its confidence is not a probability of safe deletion. Missing credentials, HTTP errors or invalid responses fall back to rules-only mode. Calls may incur provider charges; a one-call cap is not a monetary budget guarantee. Live metadata-only calls succeeded on 2026-09-21 (Jev 1.13.0); see the [measured results in the README](../README.md#real-10-gib-validation-and-live-jev-comparison). Accuracy and superiority over rules remain unverified. Core cleanup does not depend on Jev availability.

