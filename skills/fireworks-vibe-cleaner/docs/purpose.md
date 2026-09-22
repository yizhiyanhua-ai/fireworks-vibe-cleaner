# Purpose evidence / 用途证据

Tell the harness: “Inspect these candidates, reuse valid local purpose cards, and only read necessary snippets for unclear cases. Explain which tags are assistant judgments and which I confirmed. Send Jev only the fixed tags. Show the recommendation, reason and missing evidence in chat; wait for my exact-plan approval before cleanup.”

可以直接说：“检查这些候选，复用有效用途卡；拿不准的才读必要片段，说明判断来自助手还是我的确认。Jev 只接收固定标签。在对话里列出具体建议、理由和待补信息，清理等我确认具体方案。”

## Automatic observations / 自动观察

Default triage reads at most 64 KiB per selected supported session: the whole small file, or 32 KiB head plus 32 KiB tail. At most 100 candidates are accepted. Protected sources are not content-sampled. Unsupported, malformed, overlong and partial records do not prove absence of work. The report records coverage, byte counts and local source locators; no excerpts are persisted by this parser.

A recorded turn completion is not project completion. A pending plan remains an observed claim even if an unrelated later plan says completed. It blocks cleanup preparation but still permits original-preserving backup, verification or reuse. It does not prove that the project is active. A declared continuation need causes local keep. The current implementation recognizes Codex structured turn/plan events and a narrow Claude assistant `end_turn` marker; the real v0.6 cohort covered Codex only.

默认每个受支持会话最多读 64 KiB，最多 100 个候选。大文件只读首尾，保护对象不读取正文。回合结束、计划完成声明都不证明项目完成；未读到某项也不代表它不存在。观察到待办计划会阻止清理准备，但保留原件的操作仍可建议。解析器不保存正文摘录，也不执行记录中的指令。

## Optional local annotations / 可选本地标注

```bash
fireworks-vibe-cleaner purpose-template --scan scan.json --id CANDIDATE_ID --output purpose-notes.json
fireworks-vibe-cleaner triage --scan scan.json --id CANDIDATE_ID --purpose-notes purpose-notes.json --enable-network --output triage.json
```

Repeat `--id` for each selected candidate, up to 100. The template includes only available, unprotected candidates. Inspect the exact local source before filling an annotation. Preserve `id` and `source_binding`; edit only the closed fields below. No source title, excerpt or free-text rationale belongs in this file. The binding covers source identity and the sampled windows, not the semantics of the annotation or a whole-file hash. A changed source refuses the notes before any provider call; regenerate and review, never simply replace an old binding to make a stale judgment appear fresh.

| Field | Values |
| --- | --- |
| `role` | `unknown`, `knowledge-reference`, `implementation-history`, `delivery-record`, `diagnostic-history`, `generated-draft`, `deliverable` |
| `continuation` | `unknown`, `needed` |
| `origin` | `unreviewed`, `local-assistant`, `user` |

`local-assistant` is a fallible local harness judgment; it must not be marked `user`. Only actual user-supplied/confirmed judgments use `user`. `unknown` continuation never means “no need to continue.” Neither origin grants cleanup approval or changes recovery requirements. Only annotate when it can affect a useful recommendation; reuse still-valid cards to avoid repeated model work. Reading and labeling content takes additional time/cost outside the bounded parser and must be disclosed in benchmarks.

支持重复 `--id`。模板只列可读取、未受保护的候选。用途、续接需求、来源都是固定选项；助手根据片段判断就填 `local-assistant`，不能冒充用户确认。用途卡只绑定来源，不证明判断正确；过期卡必须重读、重判。只为有实际决策价值的歧义项补卡，不要为填满字段调用大模型。初次人工或助手判断的额外时间与成本必须单独说明。

## Decision and privacy boundaries / 建议与隐私

- `--advisor rules` runs the transparent local baseline with zero provider calls, even if `--enable-network` is also present. The default advisor remains Jev; without network authorization it reports local fallback.
- `--skip-purpose` disables automatic session-content sampling; missing evidence remains unknown. Do not use it or omit known keep notes to bypass a user's retention instruction.
- Unknown recovery need blocks removal preparation. It does not prevent verification/reuse of an existing copy. A new-backup suggestion with unknown purpose is held for purpose review unless the user explicitly chose `preserve-history`; raw Jev choice remains visible. Creating unexplained backups can increase storage.
- Below 0.5 confidence, original-preserving suggestions are tentative, not executed. Cleanup preparation goes to review. No confidence threshold proves deletion safety.
- All existing executor categories, full verification, writer checks and exact human approval gates remain unchanged. Assets and checkpoints still cannot enter source removal.
- Jev receives only rebuilt allowlisted enums/bools: no raw summaries, text, titles, code, paths, IDs, hashes or local locators. It does not see images/audio/video. This release does not enable summary transmission.

恢复需求未知会关闭移除准备；已有备份仍可核验或复用。用途不明时，Jev 提出的新增备份先转用途复核，除非用户明确要求保全历史；原始选择不会隐藏。低置信度的保留原件建议会标为暂定，清理准备仍转人工复核。素材与检查点没有新增移除权限。Jev 不接收正文、摘要或本地定位信息，也不会直接理解图片视频。

## Evaluating actual value / 怎样评估价值

Compare rules, metadata-only Jev and purpose-assisted Jev on the same real files. Freeze annotations before calls, retain raw choices and local overrides, and keep failures. Rule agreement and two matching repetitions are not accuracy. Local assistant labels are not user ground truth. Measure false removal recommendations against actual user labels when available; no such labels were supplied in the v0.6 experiment. Its final rules and Jev outputs matched on all 14 files, so model superiority was not demonstrated.

The provider adapter retains raw distributions. For two-decimal values it accepts only totals compatible with per-value rounding, capped at 0.025 total deviation, marks the tolerance, and never renormalizes. Invalid keys, ranges, choices or larger deviations still fail closed. The initial real failure recorded `probability-sum` but not the original numeric distribution; its exact cause remains unproven. A later diagnostic observed two-decimal outputs; successful final comparisons did not need this tolerance.
