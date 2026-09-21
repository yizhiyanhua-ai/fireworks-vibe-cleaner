# Codex 历史会话检查与原生归档

直接对 Codex 说：“检查我的历史会话。如果总量或单个会话超过 3 GiB，或未归档数量超过 200，先告诉我哪些值得归档。保留最近、置顶、当前和我指定保留的会话。先在聊天里给概览，再附完整方案，等我确认后再执行。”

这是按需检查，不会安装定时清理任务。`history-audit` 只读整个已识别的索引；总容量也包括已经归档的文件，数量不等于 UI 当前按项目筛选的结果。只读取有长度上限的会话头部元数据，不读完整对话正文。文件覆盖不完整时，已计量字节只是下界。

| 参数 | 默认值 | 用途 |
| --- | ---: | --- |
| `--total-bytes` | 3221225472 | 可读取索引文件总量超过 3 GiB 时提示 |
| `--single-bytes` | 3221225472 | 单个可读取会话文件超过 3 GiB 时提示 |
| `--count-limit` | 200 | 未归档索引会话超过 200 个时提示 |
| `--keep-recent` | 100 | 保留最新 100 个未归档会话 |
| `--min-age-days` | 30 | 保留最近 30 天更新的会话与文件 |
| `--keep-thread` | 可重复 | 指定保留 ID；同时保留 `CODEX_THREAD_ID` 指向的当前会话 |

置顶会话始终保留。工具没有提供当前会话 ID 时，应显式指定，不能按更新时间猜测。阈值只触发建议。索引、文件或父子关系核对不完整时，拒绝生成可执行计划；初步候选数量不代表可以执行，也不会自动修复数据库。

```sh
fireworks-vibe-cleaner history-audit --codex-home /absolute/codex-home --output history-audit.json
fireworks-vibe-cleaner history-plan --audit history-audit.json --id ROOT_THREAD_ID --state-dir /absolute/private-state --output history-plan.json
# 展示聊天概览、完整方案和哈希；获得具体批准并停止相关写入。
fireworks-vibe-cleaner history-apply --plan history-plan.json --approve REVIEWED_HASH --writers-stopped
fireworks-vibe-cleaner history-verify --state-dir /absolute/private-state --run RUN_ID
# 单独展示恢复范围并获得批准。
fireworks-vibe-cleaner history-restore --state-dir /absolute/private-state --run RUN_ID --approve unarchive:RUN_ID --writers-stopped
fireworks-vibe-cleaner history-verify --state-dir /absolute/private-state --run RUN_ID
```

上面的路径和大写名称都是占位符。重复 `--id` 可选多个主会话；审计时重复 `--keep-thread` 可保留多个 ID。计划默认一小时过期，`history-plan --ttl-seconds` 上限为 86400 秒。状态目录必须私有且位于 CODEX_HOME 外。可用 `--codex` 指定原生 Mach-O 程序，无法可靠识别的脚本启动器会被拒绝。原生写操作首版仅支持 **macOS 和 codex-cli 0.154.0**；只读检查支持已识别 schema 的 macOS/Linux。

确认前，聊天里必须展示：触发条件、数量、已计量空间与遗漏范围、保留项、选中的主会话及全部受影响后代、处理方式、**预计释放 0 字节**、风险与恢复限制。随后附完整私有方案链接及精确哈希。命令参数不代表用户已经批准；使用此 Skill 的 Agent 必须先得到人工确认。还需停止相关写入，隔离 app-server 的 `notLoaded` 不能证明别的进程没有使用这些会话。

Codex 原生归档会连带处理后代。后代中任何置顶、当前或其他保留项都阻止归档父会话，包括已归档的受保护后代。工具将只读索引、分页原生 API、文件身份与内容 SHA-256 相互核对，操作前持久化日志，再调用原生接口；不会直接写数据库或手工移动会话文件。原生程序仍会读取 CODEX_HOME 配置并维护索引；OS 沙箱禁止联网、执行其他路径的程序、写入 CODEX_HOME 和私有运行目录以外的文件，不承诺隔离所有文件读取。

取消归档一次只处理一个 ID，恢复会逐个处理本轮改变的会话，原本已归档的后代仍保持归档。恢复核验覆盖原路径、内容和归档状态；Codex 会更新时间字段和文件 mtime，因此不承诺原始时间戳。中断后先核验再恢复；关联关系变化、路径被占用或内容冲突时停止并人工排查，不重放 apply 或自动扩大范围。UI 展示和原生续聊尚未验证。

整理历史列表预计回收 **0 字节**。腾磁盘空间仍走独立的已校验 ZIP 备份与 `archive-plan` / `archive-apply` 原件移除流程，需要单独确认具体范围和历史风险。归档历史的批准不能用于删除原件，Jev 建议也不能绕过这些条件。
