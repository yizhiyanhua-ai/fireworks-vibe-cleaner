# 手动安装与命令行指南

[返回自然语言用法](../README.zh.md) · [English](cli.md)

如果你在 Codex 或 Claude Code 里使用这个 Skill，可以直接按 README 的示例说出需求。下面的命令供手动安装、排查问题或直接使用 CLI 时参考。

## 安装

需要 Python 3.11+，支持 macOS、Linux。修改源文件或隔离文件还需要 `lsof`；项目字节码检查需要 Git。无 Python 运行时第三方依赖，不启动常驻服务，默认不联网。

安装 v0.7.0 发布版：

```sh
git clone --branch v0.7.0 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

直接运行脚本无需安装 Python 包。下文使用简短的 `fireworks-vibe-cleaner` 命令，可选择创建虚拟环境并执行 `python -m pip install .`；也可将该命令替换为 `python3 scripts/fireworks-vibe-cleaner.py`。开发期间使用本地 checkout，跳过标签克隆步骤。实际发布与实测状态见[版本说明](releases/v0.7.0.md)。

安装 Skill 时先生成目录，再复制到使用的 harness。以下命令拒绝覆盖已有安装：

```sh
python3 tools/build_skill.py
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
test ! -e "${CODEX_HOME:-$HOME/.codex}/skills/fireworks-vibe-cleaner" && cp -R skills/fireworks-vibe-cleaner "${CODEX_HOME:-$HOME/.codex}/skills/"
# 或安装到 Claude Code：
mkdir -p "$HOME/.claude/skills"
test ! -e "$HOME/.claude/skills/fireworks-vibe-cleaner" && cp -R skills/fireworks-vibe-cleaner "$HOME/.claude/skills/"
```

Skill 自带 Python 启动脚本。让 harness 使用 `fireworks-vibe-cleaner` 查看空间、提出清理范围；修改源文件前必须取得具体计划的批准。

## 推荐先配置 Jev

安装后通过密钥管理器或进程环境安全注入 `TYPESAFE_API_KEY`，不要粘贴到聊天或命令历史。运行 `doctor` 可检查 Key 是否存在；它不联网，也不证明鉴权成功。你也可明确选择纯规则模式，不配 Key 继续使用。实际建议调用需要联网和费用授权。

## 先检查，再审阅与执行

```sh
fireworks-vibe-cleaner scan --output scan.json
fireworks-vibe-cleaner report --scan scan.json
# 项目根需要显式指定；可重复 --root。
fireworks-vibe-cleaner scan --root project=/absolute/path/to/project --output project-scan.json
```

默认根遵循 `CODEX_HOME` 和 `CLAUDE_CONFIG_DIR`。使用 `--keep '*/important.log'` 保留匹配文件。扫描报告含本地路径，请私下保存。增长比较需要相同根下两次完整扫描：`report --scan later.json --previous earlier.json`。

以下为命令模板：将 `CANDIDATE_ID`、`REVIEWED_PLAN_HASH`、`RUN_ID` 和路径替换为审阅后的实际值。状态目录必须与待处理文件同卷、位于其来源目录之外，权限为 `0700`；CLI 新建状态目录时使用该权限。计划有效期为一小时。

```sh
fireworks-vibe-cleaner plan --scan scan.json --id CANDIDATE_ID   --state-dir /absolute/path/to/private-state --max-bytes 104857600 --output plan.json
# 阅读完整 plan.json，明确批准范围与哈希。
# 停止相关 harness / 项目写入进程后，才可使用此确认参数。
fireworks-vibe-cleaner apply --plan plan.json --approve REVIEWED_PLAN_HASH --writers-stopped
fireworks-vibe-cleaner verify --state-dir /absolute/path/to/private-state --run RUN_ID
```

`apply` 检查批准哈希、有效期、字节上限、文件身份、内容哈希、本地策略和打开句柄，记录事务日志并把文件移入同盘隔离区。`--writers-stopped` 表示操作者确认停止写入，工具不会替你关闭进程。`lsof` 报错或结果不确定时拒绝操作。仍需防范并发写入，请勿清理正在运行的 harness。

验证后选择恢复，或单独批准永久删除：

```sh
fireworks-vibe-cleaner restore --state-dir /absolute/path/to/private-state --run RUN_ID --writers-stopped
# 永久删除需要独立授权，工具无法撤销。
fireworks-vibe-cleaner purge --state-dir /absolute/path/to/private-state --run RUN_ID   --approve purge:RUN_ID --writers-stopped
```

恢复时原路径被占用会拒绝覆盖。操作中断后先运行 `verify`，保留日志与恢复文件，按报告处理；不要重放 `apply`。已恢复的 run 无法再 purge。隔离区默认逻辑容量上限为 1 GiB，可用 `apply --state-cap-bytes` 设置。永久清理分别报告删除的逻辑字节与卷空闲空间实际差值；快照、共享块和其他进程写入都会影响差值。

## 会话备份

```sh
mkdir -m 700 /absolute/path/to/new-private-backups
fireworks-vibe-cleaner backup --scan scan.json --id SESSION_CANDIDATE_ID   --output /absolute/path/to/new-private-backups/session.zip --max-bytes 104857600
fireworks-vibe-cleaner extract --archive /absolute/path/to/new-private-backups/session.zip   --destination /absolute/path/to/new-extraction-directory
```

备份会读回压缩包并核验哈希。ZIP 与旁边的 `.manifest.json` 必须一起保留。解包默认容量上限为 1 GiB（`extract --max-bytes`），只在新目录写入编号副本并校验哈希，不重建 harness 状态。**备份字节正确不代表会话可以恢复使用。**源文件不移除，因此备份会增加占用。备份未加密且限制在源文件所在卷；跨卷迁移和加密尚未实现。移除会话原件使用下方独立的 v0.2.0 流程。

## 移除已经验证归档的会话原件

此流程与日志/缓存隔离相互独立，只接受已有精确备份、超过保留期且能够识别的主会话记录。子代理、sidechain、fork、未知来源会话、工具结果、检查点和资产不移除。`archive-plan` 会实际读取并校验归档，不能只信任 manifest 中的成功标记。

使用新扫描，ZIP 和 manifest 保存在源文件所在卷的私有目录。将下方大写占位符和路径替换成实际值；可重复 `--id` 与 `--archive`。计划默认有效期 3,600 秒，`--ttl-seconds` 可设为 1–86,400。

```sh
fireworks-vibe-cleaner archive-plan --scan scan.json --id SESSION_CANDIDATE_ID --archive /absolute/path/to/private-backups/session.zip --state-dir /absolute/path/to/private-state --max-bytes 104857600 --ttl-seconds 3600 --output archive-plan.json
# 阅读完整计划、精确哈希与历史风险后，再批准。
fireworks-vibe-cleaner archive-apply --plan archive-plan.json --approve REVIEWED_PLAN_HASH --writers-stopped --acknowledge-history-risk
fireworks-vibe-cleaner archive-verify --state-dir /absolute/path/to/private-state --run RUN_ID
# 如需恢复，拒绝覆盖原路径已有文件。
fireworks-vibe-cleaner archive-restore --state-dir /absolute/path/to/private-state --run RUN_ID --writers-stopped
fireworks-vibe-cleaner archive-verify --state-dir /absolute/path/to/private-state --run RUN_ID
```

`archive-apply` 重新校验后直接移除所选原件，不把它们移入隔离区，也不删除归档。没有相应用户确认、未停止写入时，不得添加这两个确认参数。关联文件与索引保留不变，历史条目可能无法使用。`archive-restore` 将精确字节恢复到原路径，允许新 inode，不更新索引，也不证明原生续聊成功。保留归档和事务日志；中断后先运行 `archive-verify`，按具体状态处理，不盲目重放删除。删除逻辑字节与卷空闲量实际变化需要分开报告。

### 计划过期与金丝雀门控

计划过期、但希望保持原范围时，用只读刷新重新校验全部源文件、归档文件和成员字节。它拒绝已经执行过的计划以及发生变化的来源；新哈希必须重新展示并确认。

```sh
fireworks-vibe-cleaner archive-refresh --plan expired-plan.json --ttl-seconds 86400 --output refreshed-plan.json
```

大批量清理可把一份单文件金丝雀计划和一份互不重叠的正式计划绑定为一个审批对象。`archive-workflow-apply` 固定执行“金丝雀移除 → 校验 → 原路径恢复 → 再校验 → 正式移除 → 校验”。金丝雀未恢复为有效 `source` 状态时，正式计划不会启动；中断后使用 verify 查看子运行，不要重放 apply。

```sh
fireworks-vibe-cleaner archive-workflow-plan --canary-plan canary.json --cleanup-plan cleanup.json --output workflow.json
# 在对话里展示两个完整范围、组合哈希与风险，取得该组合哈希的确认。
fireworks-vibe-cleaner archive-workflow-apply --plan workflow.json --approve WORKFLOW_HASH --writers-stopped --acknowledge-history-risk
fireworks-vibe-cleaner archive-workflow-verify --state-dir /absolute/path/to/private-state --run WORKFLOW_HASH
```

大量文件的逐项验证 JSON 可能很长。`archive-verify ... --summary` 返回位置计数、无效项数量、逻辑删除字节和恢复边界；需要定位异常时去掉 `--summary` 查看逐项结果。执行器按文件系统设备去重采样空间，保留负值并记录时间窗；观测值可能包含其他进程写入，不能当成独占释放量。

## 推荐：Jev 快速筛选，直接在终端看建议

先完成只读 `scan`，再使用已经授权的 Jev 调用：

```bash
fireworks-vibe-cleaner triage --scan scan.json --limit 40 --goal balanced --enable-network --format text --language zh --output triage.json
```

不联网时去掉 `--enable-network`，结果明确标为本地复核。默认只选支持类别中最大的 40 个候选；可以使用 `--limit 1..100`，或重复 `--id CANDIDATE_ID` 覆盖你选定的完整集合（最多 100 项）。目标可选 `balanced`（综合考虑）、`reclaim-space`（优先腾空间）、`preserve-history`（优先保留历史）。

终端直接显示每个文件、动作、理由、事实、备选方式和未知项；JSON 留在本地供复核。`backup` 保留原件，`prepare_removal` 只建议准备“验证备份后移除”的方案，`prepare_cache_cleanup` 只建议准备日志/缓存隔离与另行批准的销毁方案。这一步不生成可执行计划、没有回收空间。Jev 原始建议、本地覆盖和置信度均留有记录；低于 0.5 的保留原件建议标为暂定，清理准备转人工复核。

范围确定后再做完整哈希和保护/活跃检查；在聊天中显示完整清单、每项方法及原因、影响、备份位置、计划 hash，经人工明确确认才进入后面的执行命令。只给 MD 链接不够。[能力依据、调用上限与限制](jev.md)。

已有备份和保留需求可直接加到 `triage`：

```bash
--archive /private/existing-backup.zip --verify-backup-bytes 16777216 --recovery-need unknown
```

`--archive` 可重复；默认验证预算为零，只识别备份清单引用。预算上限 32 GiB，累计原件与所选成员解压后的字节，不按 ZIP 大小计，也不代表整个归档或原生续聊验证通过。用户明确说文件副本足够时才用 `--recovery-need archive-copy`；需要继续原对话用 `native-resume`，未说明则保持 `unknown`，后二者均关闭移除准备选项。这个偏好不批准删除。默认批量检查打开句柄，`--skip-activity` 会使活动状态未知。`verify_backup` 表示建议验证已有副本，`reuse_verified_backup` 表示保留原件并复用所选已验证副本。受保护、当前、关联、置顶或观察到打开句柄的对象直接本地保留；缺失索引证据保持未知。

用途信息：`purpose-template --scan scan.json --id ID --output purpose-notes.json` 生成绑定来源的私有模板，可重复 ID。本地查看后仅填写固定用途、续接需求和来源，再给 triage 加 `--purpose-notes purpose-notes.json`。默认每会话最多读取 64 KiB 结构信息，`--skip-purpose` 可关闭；`--advisor rules` 使用离线规则。过期标注会在联网前拒绝。[完整用途流程、固定选项与计时边界](purpose.md)。

## 单次 Jev 建议（兼容命令）

通过密钥管理器或进程环境提供 `TYPESAFE_API_KEY`，不要写入命令历史或报告。使用以下参数显式启用联网：

```sh
fireworks-vibe-cleaner advise --scan scan.json --id CANDIDATE_ID --inspect-activity --enable-network --output advice.json
```

每次执行最多调用一次 TypeSafe API，处理 1–20 个候选。仅发送临时候选编号、类别、大小/年龄区间、规则资格、保留期、本地检查状态、活跃快照与允许动作；不发送路径、文件名、原始候选 ID、会话正文、源码或自由文本原因。请求上限 16 KiB、响应上限 64 KiB、网络超时 8 秒；禁止重定向，不自动重试。

Jev 可建议 `keep`、`review`、`backup`、`delete`。`--inspect-activity` 执行只读本地 `lsof` 检查；只有通过本地策略、保留期与句柄检查的旧日志/可重建缓存，才提供 delete 建议，会话没有直接 delete 建议。句柄快照不代表写入已停止。Jev 无法批准删除、修改计划或绕过保护规则。置信度不代表安全删除概率。缺少 Key、HTTP 错误或非法响应均退回纯规则模式。调用可能产生服务商费用；一次调用上限不等于金额预算保证。2026-09-21 的真实元数据调用已成功（Jev 1.13.0），结果见 [README 实测部分](../README.zh.md#真实-10-gib-验证与-jev-线上对比)；准确率及相对规则的收益仍未验证。核心清理不依赖 Jev 可用性。


早期 Jev 实测使用旧选项集，不能证明 v0.2.0 删除建议的效果。[扩展选项后的真实调用](experiments/real-jev-v02.json)对 20 个候选全部返回 review，不能据此宣称删除准确率。真实原件清理仍需对具体计划取得人工批准。

## Codex 历史列表

数量与容量提示、确认后原生归档及逐个恢复，见[历史会话指南](history.zh.md)。原生归档预计回收 0 字节。
