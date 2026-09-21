# Security

## Reporting

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/security/advisories/new) when available. If that channel is unavailable, open an issue asking for a private reporting channel without exploit details, secrets or personal data. Never attach a real session transcript or unredacted inventory. Security support initially targets the latest released version.

## Trust boundary

This is a local, user-invoked tool, not a sandbox against an adversary controlling your account, repository or filesystem. Stop relevant writers before mutation. File identity/content checks, no-follow operations, private state storage, open-handle checks and per-state locking reduce mistakes; they cannot prove the absence of concurrent changes across every filesystem and process.

Only a narrow local policy permits cleanup. Explicit plan-hash approval binds the reviewed scope; permanent purge has a separate approval token. The tokens are operator acknowledgements, not authentication or cryptographic signatures against a malicious local user. Keep plans, journals and state private and do not edit them to bypass a refusal.

Session deletion, cross-volume moves and encrypted backups are not implemented. A byte-verified snapshot is not a complete harness restore point. Backups retain originals, may contain private content, and must stay on a private same-volume directory. Reports and manifests contain paths. Do not publish them.

## Optional provider

Jev is opt-in and receives allowlisted metadata only. It never receives file contents or paths, and cannot authorize deletion. Key injection uses `TYPESAFE_API_KEY`. Provider errors are sanitized, redirects are rejected, and malformed replies fall back to rules-only behavior. Metadata still reveals coarse usage patterns; obtain consent before enabling network access. A call-count cap does not enforce a currency budget.

## Recovery

On interruption, preserve the entire state directory and run `verify`. Do not manually delete journals or replay `apply`. Restore refuses to overwrite a newly occupied path. Purged data cannot be restored by this tool. Independent backups and filesystem snapshots may have different retention and reclaim behavior.
