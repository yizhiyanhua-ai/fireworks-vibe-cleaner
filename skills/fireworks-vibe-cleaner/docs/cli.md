# Manual installation and CLI guide

[Back to conversational usage](../README.md) · [简体中文](cli.zh.md)

If you use this Skill from Codex or Claude Code, start with the prompts in the README. The commands below are for manual installation, troubleshooting or direct CLI use.

## Install

Requires Python 3.11+, macOS or Linux. Mutation of source/quarantine files additionally requires `lsof`; project-bytecode validation requires Git. No runtime Python dependencies, daemon, or default network requests.

Install the v0.7.0 release:

```sh
git clone --branch v0.7.0 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

Direct script execution needs no package installation. For the shorter `fireworks-vibe-cleaner` command used below, optionally create a virtual environment and run `python -m pip install .`; alternatively replace that command with `python3 scripts/fireworks-vibe-cleaner.py`. During development, use a local checkout and omit the tag clone. Publication and live validation status are recorded in [release notes](releases/v0.7.0.md).

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

## Recommended first step: configure Jev

After installation, securely inject `TYPESAFE_API_KEY` using your secret manager or process environment. Do not paste it into chat or command history. Run `doctor` to check key presence; it makes no network request and does not prove authentication. You can explicitly choose rules-only mode and continue without a key. Actual advice calls need network/cost authorization.

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

Backup checks archived bytes against hashes. Keep the ZIP and its `.manifest.json` together. Extraction defaults to a 1 GiB byte cap (`extract --max-bytes`). It writes numbered copies into a new directory and checks hashes; it does not rebuild live harness state. **A valid backup is not evidence that a session can resume.** Sources remain untouched, so this increases storage use. Backups are unencrypted and restricted to the source volume; cross-volume moves and encryption are not implemented. Transcript source removal is a separate v0.2.0 flow below.

## Remove verified archived transcripts

This flow is separate from log/cache quarantine. It accepts only recognized old main transcripts with exact copies in existing backups; it never removes subagent/sidechain/fork/unknown-origin transcripts, tool results, checkpoints or assets. `archive-plan` reads and validates the archives; a manifest's success label is insufficient.

Use a fresh scan and keep ZIPs plus manifests in their private source-volume directory. Replace all uppercase placeholders and paths below. Repeat `--id` and `--archive` to select additional inputs. Plan expiry defaults to 3,600 seconds; `--ttl-seconds` must be 1–86,400.

```sh
fireworks-vibe-cleaner archive-plan --scan scan.json --id SESSION_CANDIDATE_ID --archive /absolute/path/to/private-backups/session.zip --state-dir /absolute/path/to/private-state --max-bytes 104857600 --ttl-seconds 3600 --output archive-plan.json
# Review the entire plan, its exact hash and history risk before approving.
fireworks-vibe-cleaner archive-apply --plan archive-plan.json --approve REVIEWED_PLAN_HASH --writers-stopped --acknowledge-history-risk
fireworks-vibe-cleaner archive-verify --state-dir /absolute/path/to/private-state --run RUN_ID
# Recovery, if needed; never overwrite an occupied original path.
fireworks-vibe-cleaner archive-restore --state-dir /absolute/path/to/private-state --run RUN_ID --writers-stopped
fireworks-vibe-cleaner archive-verify --state-dir /absolute/path/to/private-state --run RUN_ID
```

`archive-apply` removes selected originals directly after revalidation; it does not quarantine them or delete their archives. Do not pass either acknowledgement flag without the matching user confirmation and stopped writers. History entries may become unavailable because related files and indexes stay unchanged. `archive-restore` restores bytes to exact original paths, allowing a new inode, without updating indexes or proving native continuation. Preserve archives and the run journal. On interruption use `archive-verify`, resolve the specific state, and do not blindly replay removal. Logical bytes removed and observed volume free-space change are different measurements.

### Expired plans and a canary gate

When a plan expires but its exact scope should remain unchanged, a read-only refresh revalidates every source, archive and selected member byte. It refuses plans that already have a run journal or whose sources changed. Show and approve the new hash.

```sh
fireworks-vibe-cleaner archive-refresh --plan expired-plan.json --ttl-seconds 86400 --output refreshed-plan.json
```

For a larger cleanup, bind a one-file canary plan and a disjoint cleanup plan into one approval object. `archive-workflow-apply` enforces “remove canary → verify → restore original path → verify → remove cleanup originals → verify.” Cleanup never starts unless the canary is restored as a valid `source`. After interruption, inspect child journals with verify instead of replaying apply.

```sh
fireworks-vibe-cleaner archive-workflow-plan --canary-plan canary.json --cleanup-plan cleanup.json --output workflow.json
# Show both complete scopes, the workflow hash and risks in chat, then obtain approval of that hash.
fireworks-vibe-cleaner archive-workflow-apply --plan workflow.json --approve WORKFLOW_HASH --writers-stopped --acknowledge-history-risk
fireworks-vibe-cleaner archive-workflow-verify --state-dir /absolute/path/to/private-state --run WORKFLOW_HASH
```

Per-item verification JSON can be long for large runs. `archive-verify ... --summary` returns location counts, invalid-item count, logical bytes removed and recovery limits; omit `--summary` when individual rows are needed. The executor samples free space once per filesystem device and preserves negative deltas and timestamps. Observations may include other process writes and are not exclusive reclaim attribution.

## Recommended: fast Jev triage in your terminal

After a read-only `scan`, use an authorized Jev call:

```bash
fireworks-vibe-cleaner triage --scan scan.json --limit 40 --goal balanced --enable-network --format text --language en --output triage.json
```

Omit `--enable-network` for explicitly labeled local review. The default selects the largest 40 files in supported categories. Use `--limit 1..100`, or repeat `--id CANDIDATE_ID` for the complete explicitly selected set (up to 100). Goals are `balanced`, `reclaim-space`, and `preserve-history`.

The terminal shows every file, recommendation, reason, facts, alternatives and unknowns. Private JSON preserves Jev's original choice, confidence and local overrides. Below 0.5, original-preserving advice is tentative and cleanup preparation becomes review. `backup` retains originals; `prepare_removal` only recommends preparing a verified-backup-then-remove proposal; `prepare_cache_cleanup` only prepares quarantine and separately approved purge. This command creates no executable plan and reclaims zero bytes.

After scope selection, perform full hashes and protection/activity checks. Show every method, reason, impact, backup location and exact plan hash directly in chat, then obtain explicit human confirmation before execution. A Markdown link alone is insufficient. See [capability basis, limits and bounds](jev.md).

Existing-backup and recovery options (add to `triage`):

```bash
--archive /private/existing-backup.zip --verify-backup-bytes 16777216 --recovery-need unknown
```

Repeat `--archive` for existing copies. The default zero budget finds manifest references without checking bytes; the maximum 32 GiB budget counts source plus expanded selected-member bytes, not ZIP size, whole-archive verification or native resume. `--recovery-need archive-copy` is only for an explicit user requirement that file-copy recovery suffices; `native-resume` means original continuation is required. Both it and the default `unknown` close removal preparation. This preference never approves deletion. Batched activity checks run by default; `--skip-activity` leaves activity unknown. `verify_backup` recommends validating a matching copy, and `reuse_verified_backup` retains the original with its selected verified copy. Protected/current/linked/pinned/open objects bypass Jev. Missing supported index evidence stays unknown.

Purpose context: `purpose-template --scan scan.json --id ID --output purpose-notes.json` prepares a private, source-bound template; repeat IDs. Fill only the fixed role/continuation/origin fields after local review, then pass `--purpose-notes purpose-notes.json` to triage. Default structured sampling is at most 64 KiB per session; `--skip-purpose` disables it. `--advisor rules` is explicit offline advice. Stale annotations refuse before network calls. See [purpose workflow, annotation enums and measurement limits](purpose.md).

## Single-call Jev advice (compatibility command)

Supply `TYPESAFE_API_KEY` through your secret manager or process environment, never in command history or a report. Explicitly opt in:

```sh
fireworks-vibe-cleaner advise --scan scan.json --id CANDIDATE_ID --inspect-activity --enable-network --output advice.json
```

One invocation makes at most one TypeSafe API call for 1–20 selected candidates. It sends temporary candidate labels, category, size/age bands, rule eligibility, retention status, local-check status, activity snapshot and allowed actions. It does **not** send paths, filenames, original candidate IDs, session text, source code or free-text reasons. The payload cap is 16 KiB, response cap 64 KiB, network timeout 8 seconds; redirects and automatic retries are disabled.

Jev may suggest `keep`, `review`, `backup` or `delete`. `--inspect-activity` performs read-only local `lsof` checks. Delete is offered only for eligible old logs/rebuildable caches after local policy, retention and open-handle checks; sessions never receive a direct delete suggestion. A no-open-handles snapshot is not proof that writers have stopped. It cannot authorize deletion, change a plan or override a protection rule. Its confidence is not a probability of safe deletion. Missing credentials, HTTP errors or invalid responses fall back to rules-only mode. Calls may incur provider charges; a one-call cap is not a monetary budget guarantee. Live metadata-only calls succeeded on 2026-09-21 (Jev 1.13.0); see the [measured results in the README](../README.md#real-10-gib-validation-and-live-jev-comparison). Accuracy and superiority over rules remain unverified. Core cleanup does not depend on Jev availability.


The earlier live Jev measurements do not validate v0.2.0 delete recommendations. A [new live call](experiments/real-jev-v02.json) with the expanded action contract returned review for all 20 candidates; no deletion accuracy claim follows. Real-source cleanup requires approval of its exact plan.

## Codex history list

Use the separate [native history guide](history.md) for count/size pressure, reviewed archive and individual recovery. This promises zero disk reclaim.
