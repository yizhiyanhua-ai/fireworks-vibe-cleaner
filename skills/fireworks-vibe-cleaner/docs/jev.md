# Jev: fast decisions before expensive verification

Jev is the preferred decision stage after a local inventory. Enable it only with authorization for the disclosed metadata and provider cost; a missing key or failed call produces clearly labeled local review. Nothing in this stage authorizes cleanup.

## Why this shape fits Jev

TypeSafe documents three typed primitives: Choice, Score and Noul. Questions share a state and are evaluated independently in parallel. This project uses one narrow **Choice per candidate**, selecting an action with its supported reason code. Combining these in one option avoids an action and an independently chosen explanation disagreeing. Explanations shown to the user are fixed project text with observed local facts, not generated reasoning. See the official [introduction](https://docs.typesafe.ai/introduction) and [Choice contract](https://docs.typesafe.ai/primitives/choice).

Jev does not generate prose. Its documented weak areas include arithmetic, dates, indirect reasoning, irrelevant long inputs and adversarial content. Code therefore owns counts, bytes, retention, file identity and protection checks. Only compact allowlisted metadata leaves the machine, in English, without paths, names, session IDs, transcript text, code or user-supplied free text. The selected goal is one of `balanced`, `reclaim-space`, `preserve-history`. See the official [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) and [model reference](https://docs.typesafe.ai/models).

## Fast path and action boundaries

1. Reuse a recent scan. Recheck selected file identity, classification, keep rules and small recognized transcript headers locally. A stale, missing or protected object does not acquire removal preparation eligibility.
2. Ask Jev to recommend the next step. Batch 8 candidates per request, with up to 3 concurrent requests. An automatic selection considers the largest 40 files in supported categories by default; disclose that this is a subset. Explicit IDs cover the complete selected set, up to 100.
3. Show every file, recommendation, supporting facts, alternatives, impact and unknowns in the conversation or terminal. Review uncertainty instead of optimizing for a high deletion rate.
4. After the user selects a scope, check actual activity, index pin/lineage protection and full backup/source hashes. Create a separate executable plan; show it inline with all selected paths, methods, risks, backup locations and exact hash. Obtain explicit human approval before any movement or removal.

| Recommendation | Meaning | Disk effect in this phase |
| --- | --- | --- |
| `keep` | Retain the original | 0 |
| `review` | Missing information or low confidence; ask the human | 0 |
| `backup` | Create or reuse a verified backup, retaining the original | 0; creating an archive adds storage |
| `prepare_removal` | Prepare a proposal to verify/create a backup, then remove an old recognized main transcript if separately approved | 0; no archive is verified and no source is removed by triage |
| `prepare_cache_cleanup` | Prepare quarantine for an eligible old log/rebuildable cache, with separately approved purge | 0; same-volume quarantine itself also reclaims 0 |

Preparation is conditional advice, never a statement that a file is safe to delete. A header alone does not establish complete format validity, absence of index relationships, stopped writers, backup recovery or future user value. Native history archival is a separate list-management operation with no promised disk reclaim. Backup and deletion remain separate decisions.

For partial failures, only the affected candidates fall back to local review. Each result keeps its provider status and source label. Choice probabilities and confidence are preserved in the private JSON. A confidence below 0.5 routes to review; this is a conservative product rule, not a domain-calibrated safety threshold. High confidence also needs the same verification and exact human approval. [Official confidence explanation](https://docs.typesafe.ai/confidence).

## Bounds and measurement

Each request is capped at 16 KiB and an 8-second transport timeout, with no redirect or automatic retry. Interrupting the run cancels queued requests; up to three requests already in flight may finish and incur charges. A run accepts at most 100 candidates, 13 requests and 208 KiB of request bodies. Call/token limits are not a guaranteed monetary cap. Provider version, measured wall time, usage, fallback status and unselected counts are reported.

The [real 33-file comparison](experiments/real-jev-triage-2026-09-22.json) used actual provider calls and source hashes. Serial and concurrent execution were measured once each; differences include network and provider variation, and the resulting recommendations differed. This is not an accuracy evaluation, a stable speedup guarantee or a real cleanup test. Full scan and archive verification time is outside the timed suggestion stage.

## 中文说明

Jev 是筛选建议的优先入口：本地代码先取事实，Jev 批量选择“动作＋理由”，然后直接把逐文件建议显示在聊天或终端里。它擅长简短、边界明确的分类判断。统计大小、比较日期、核验文件和备份都由代码完成。

“备份”保留原件；“准备备份后移除方案”还需要核验备份、置顶/关联/活跃状态，并取得具体计划的人工确认。两者不能合并成默认删除。元数据无法证明会话内容无用；年龄大、体积大、已归档都只是事实。未提供正文或用途证据时，不能宣称 Jev 理解了这些会话的价值。

默认先分析最大的 40 个候选；明确指定 ID 时最多 100 个，每批 8 个、最多 3 批并发。缺 Key、调用失败和低 confidence 都会明确标识，不隐藏成 Jev 的最终意见。0.5 阈值只是保守分流规则，任何 confidence 都不能替代人工确认。完整校验放到范围确定后进行，这样先看到建议，不必等全部备份扫描结束。
