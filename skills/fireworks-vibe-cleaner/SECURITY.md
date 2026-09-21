# Security

## Reporting

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/security/advisories/new) when available. If that channel is unavailable, open an issue asking for a private reporting channel without exploit details, secrets or personal data. Never attach a real session transcript or unredacted inventory. Security support initially targets the latest released version.

## Trust boundary

This is a local, user-invoked tool, not a sandbox against an adversary controlling your account, repository or filesystem. Stop relevant writers before mutation. File identity/content checks, no-follow operations, private state storage, open-handle checks and per-state locking reduce mistakes; they cannot prove the absence of concurrent changes across every filesystem and process.

Only a narrow local policy permits cleanup. Explicit plan-hash approval binds the reviewed scope; permanent purge has a separate approval token. The tokens are operator acknowledgements, not authentication or cryptographic signatures against a malicious local user. Keep plans, journals and state private and do not edit them to bypass a refusal.

Cross-volume moves and encrypted backups are not implemented. v0.2.0 provides a separate, exact-plan-approved removal path for recognized old main transcripts whose archived bytes have been verified. It requires stopped writers and explicit history-risk acknowledgement; subagent/sidechain/fork/unknown-origin transcripts, tool results, checkpoints and assets remain excluded. A byte-verified snapshot is not a complete harness restore point. Backup commands retain originals; only a separate approved archive-removal command removes selected transcripts. Archives may contain private content, and must stay on a private same-volume directory. Reports and manifests contain paths. Do not publish them.

## Optional provider

Jev is opt-in and receives allowlisted metadata only. It never receives file contents or paths, and cannot authorize deletion. Key injection uses `TYPESAFE_API_KEY`. Provider errors are sanitized, redirects are rejected, and malformed replies fall back to rules-only behavior. Metadata still reveals coarse usage patterns; obtain consent before enabling network access. A call-count cap does not enforce a currency budget.

## Recovery

On interruption, preserve the entire state directory and run `verify`. Do not manually delete journals or replay `apply`. Restore refuses to overwrite a newly occupied path. Purged data cannot be restored by this tool. Independent backups and filesystem snapshots may have different retention and reclaim behavior.

Archive-removal recovery uses `archive-verify` and `archive-restore`, preserving exact bytes and original paths while permitting new inodes. It does not update harness indexes, restore every dependency or prove conversation continuation. Keep the verified archives and journal; occupied paths are never overwritten. Model recommendations, archive success and validation experiments do not authorize source deletion.

## Native Codex history

History pressure never triggers automatic archival. Native plans require complete index/file/lineage inspection and exact human approval of the descendant closure; pinned, recent, current and explicit keep rules apply to all descendants, including already archived ones. Target conflicts include dangling symlinks. The narrow RPC client permits no turn/start/resume. It binds the native Mach-O executable/version/hash and runs only on verified macOS/Codex 0.154.0 under OS restrictions: deny network, execute only the bound binary, write only CODEX_HOME and a private runtime home. Existing Codex configuration can still be read; this is not a general read sandbox. An unknown launcher, runtime, schema or closure refuses mutation.

Use history-verify and separately approved history-restore after interruption. Recovery unarchives only IDs with durable archive intent, checks bytes/paths/membership and permits documented native timestamp changes. The underlying API archives descendants but unarchives one ID at a time. Native archive promises zero disk reclaim and does not validate UI behavior or continuation. Stop all writers: a new server's notLoaded status is not global process evidence.
