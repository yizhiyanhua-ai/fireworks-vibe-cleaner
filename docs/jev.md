# Jev: fast decisions before expensive verification

Jev is the preferred decision stage after a local inventory. Enable it only with authorization for the disclosed metadata and provider cost; a missing key or failed call produces clearly labeled local review. Nothing in this stage authorizes cleanup.

## Why this shape fits Jev

TypeSafe documents three typed primitives: Choice, Score and Noul. Questions share a state and are evaluated independently in parallel. This project uses one narrow **Choice per candidate**, selecting an action with its supported reason code. Combining these in one option avoids an action and an independently chosen explanation disagreeing. Explanations shown to the user are fixed project text with observed local facts, not generated reasoning. See the official [introduction](https://docs.typesafe.ai/introduction) and [Choice contract](https://docs.typesafe.ai/primitives/choice).

Jev does not generate prose. Its documented weak areas include arithmetic, dates, indirect reasoning, irrelevant long inputs and adversarial content. Code therefore owns counts, bytes, retention, file identity and protection checks. Only compact allowlisted metadata leaves the machine, in English, without paths, names, session IDs, transcript text, code or user-supplied free text. The selected goal is one of `balanced`, `reclaim-space`, `preserve-history`. See the official [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) and [model reference](https://docs.typesafe.ai/models).

## Fast path and action boundaries

1. Reuse a recent scan. Recheck selected file identity, classification, keep rules and small recognized transcript headers locally. Read selected supported Codex index rows and incident edges in one read-only snapshot; collect batched open-handle observations. Positive current/pin/link/open protection bypasses Jev. A stale, missing or protected object does not acquire removal preparation eligibility.
2. Keep recovery need `unknown` unless explicitly supplied by the user. Accept existing archives with `--archive`; distinguish a manifest reference from fresh source/member byte verification within `--verify-backup-bytes` (default zero). Then ask Jev to recommend the next step. Batch 8 candidates per request, with up to 3 concurrent requests. An automatic selection considers the largest 40 files in supported categories by default; disclose that this is a subset. Explicit IDs cover the complete selected set, up to 100.
3. Show every file, recommendation, supporting facts, alternatives, impact and unknowns in the conversation or terminal. Review uncertainty instead of optimizing for a high deletion rate.
4. After the user selects a scope, check actual activity, index pin/lineage protection and full backup/source hashes. Create a separate executable plan; show it inline with all selected paths, methods, risks, backup locations and exact hash. Obtain explicit human approval before any movement or removal.

| Recommendation | Meaning | Disk effect in this phase |
| --- | --- | --- |
| `keep` | Retain the original | 0 |
| `review` | Missing information or low confidence; ask the human | 0 |
| `backup` | Create a backup, retaining the original | 0; creating an archive adds storage |
| `verify_backup` | Verify an existing matching backup before duplicating it | 0; advice only |
| `keep` with `reuse_verified_backup` | Retain the original and reuse the freshly verified selected copy | 0 |
| `prepare_removal` | Prepare a separate removal plan only after selected backup bytes verify, explicit archive-copy preference, old indexed use, unpinned/no-indexed-links/other-context facts and a no-open-handles snapshot | 0; later full plan verification and exact approval still required |
| `prepare_cache_cleanup` | Prepare quarantine for an eligible old log/rebuildable cache, with separately approved purge | 0; same-volume quarantine itself also reclaims 0 |

Preparation is conditional advice, never a statement that a file is safe to delete. A header alone does not establish complete format validity, absence of index relationships, stopped writers, backup recovery or future user value. Native history archival is a separate list-management operation with no promised disk reclaim. Backup and deletion remain separate decisions.

For partial failures, only the affected candidates fall back to local review. Each result keeps its provider status and source label. Choice probabilities and confidence are preserved in the private JSON. A confidence below 0.5 routes to review; this is a conservative product rule, not a domain-calibrated safety threshold. High confidence also needs the same verification and exact human approval. [Official confidence explanation](https://docs.typesafe.ai/confidence).

## Evidence bounds and recovery need

`--recovery-need unknown` is the default. `archive-copy` records an explicit need that file-copy recovery can satisfy, not deletion consent. `native-resume` requires application continuation; byte verification cannot establish it. Unknown or native-resume blocks transcript removal preparation. A known other-than-current thread may still have writers; no open handles is only a snapshot.

Backup checking accepts up to 64 explicitly supplied archives and 16 MiB of manifest metadata. The optional verification budget caps at 32 GiB and counts the source plus expanded selected member, usually twice the selected source size; metadata and compressed I/O are outside this logical budget. It checks identities, selected member bytes, SHA-256 and CRC, not the whole ZIP or native resume. Duplicate references, corrupt bytes and changed identities cannot become verified. A failed selected-member check does not mark other members verified. No match among supplied archives does not mean no backups exist elsewhere.

Index lookup is bounded to 100 selected files, recognized schemas and at most 1,000 incident edges with a query deadline. No indexed links is a scoped observation, not complete lineage proof. Missing schemas/rows, unsupported adapters, bad paths/times or failed checks leave unknown facts. The full-plan workflow remains necessary.

## Bounds and measurement

Each request is capped at 16 KiB and an 8-second transport timeout, with no redirect or automatic retry. Interrupting the run cancels queued requests; up to three requests already in flight may finish and incur charges. A run accepts at most 100 candidates, 13 requests and 208 KiB of request bodies. Call/token limits are not a guaranteed monetary cap. Provider version, measured wall time, usage, fallback status and unselected counts are reported.

The [v0.5 real evidence comparison](experiments/real-jev-evidence-2026-09-22.json) covered 14 files with 10 evidence combinations. Two repetitions produced 5 local keeps and 9 reviews in 1,459/1,405 ms, including 329 ms of fact collection. Recovery need was unknown, closing removal preparation. It did not demonstrate accurate backup/delete allocation or faster performance than the 1,060 ms baseline. The first attempt had one generic unavailable-or-invalid batch; failed attempts are retained.

The [real 33-file comparison](experiments/real-jev-triage-2026-09-22.json) used actual provider calls and source hashes. Serial and concurrent execution were measured once each; differences include network and provider variation, and the resulting recommendations differed. This is not an accuracy evaluation, a stable speedup guarantee or a real cleanup test. Full scan and archive verification time is outside the timed suggestion stage.

## 中文说明

Jev 是筛选建议的优先入口：本地代码先取事实，Jev 批量选择“动作＋理由”，然后直接把逐文件建议显示在聊天或终端里。它擅长简短、边界明确的分类判断。统计大小、比较日期、核验文件和备份都由代码完成。

“备份”保留原件；“验证已有备份”先检查已有副本，避免重复备份。只有所选备份字节验证通过，用户明确接受文件副本恢复，且置顶/关联/近期使用/当前会话/打开句柄等事实符合条件，才开放“准备移除方案”；执行仍须完整计划校验和人工确认。恢复需求默认未知，需要续聊时也不能用字节备份替代。两者不能合并成默认删除。元数据无法证明会话内容无用；年龄大、体积大、已归档都只是事实。未提供正文或用途证据时，不能宣称 Jev 理解了这些会话的价值。

默认先分析最大的 40 个候选；明确指定 ID 时最多 100 个，每批 8 个、最多 3 批并发。缺 Key、调用失败和低 confidence 都会明确标识，不隐藏成 Jev 的最终意见。0.5 阈值只是保守分流规则，任何 confidence 都不能替代人工确认。默认检查所选活动与索引；备份字节验证默认预算为零，可按需开启。只核验明确提供的归档与所选成员，完整计划校验仍在范围确认后进行。
