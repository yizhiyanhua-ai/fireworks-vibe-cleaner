# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

查看 Codex、Claude Code 产生的磁盘占用，审阅有明确范围的清理计划，再验证实际变化。同时提供 Agent Skill 和独立 Python CLI，默认离线，可选 Jev 辅助建议。

**v0.1 的清理范围有限：**仅处理超过保留期的已知 harness 日志，以及有 Git 跟踪源文件、被 Git 忽略且自身未跟踪的 Python 字节码。会话支持复制与字节校验，保留源文件。同盘隔离释放 **0 字节**；永久删除需要单独批准。

## 支持范围

| 对象 | v0.1 行为 |
| --- | --- |
| Codex `log/`、`logs/` 与 Claude `debug/` 中的普通日志文件 | 保留期检查 → 审阅计划 → 隔离 → 恢复或单独批准永久清理 |
| 项目 `__pycache__/*.pyc` | 要求源文件存在且被 Git 跟踪、缓存被忽略且未跟踪；执行前再次检查 |
| 会话记录、Claude 工具结果与恢复快照、生成资产 | 清点及按选定文件备份；校验字节、保留源文件；尚未验证 harness 会话恢复 |
| Codex worktree | 只读分类；不自动删除，不代管 Git 生命周期 |
| 源码、记忆、凭据、数据库、未知对象 | 禁止进入清理执行器 |

默认保留期为 30 天。扫描中的 eligible 只是初步候选，不代表删除授权。遍历不跟随子目录符号链接、不跨卷；依赖目录与 Git 内部目录会跳过并标明扫描不完整。本工具不提供整盘完整占用统计。

## 安装

需要 Python 3.11+，支持 macOS、Linux。修改源文件或隔离文件还需要 `lsof`；项目字节码检查需要 Git。无 Python 运行时第三方依赖，不启动常驻服务，默认不联网。

从固定标签安装：

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

直接运行脚本无需安装 Python 包。下文使用简短的 `fireworks-vibe-cleaner` 命令，可选择创建虚拟环境并执行 `python -m pip install .`；也可将该命令替换为 `python3 scripts/fireworks-vibe-cleaner.py`。开发期间使用本地 checkout，跳过标签克隆步骤。实际发布与实测状态见[版本说明](docs/releases/v0.1.0.md)。

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

备份会读回压缩包并核验哈希。ZIP 与旁边的 `.manifest.json` 必须一起保留。解包默认容量上限为 1 GiB（`extract --max-bytes`），只在新目录写入编号副本并校验哈希，不重建 harness 状态。**备份字节正确不代表会话可以恢复使用。**源文件不移除，因此备份会增加占用。备份未加密且限制在源文件所在卷；跨卷迁移、加密、会话删除均未实现。

## 可选 Jev 建议

通过密钥管理器或进程环境提供 `TYPESAFE_API_KEY`，不要写入命令历史或报告。使用以下参数显式启用联网：

```sh
fireworks-vibe-cleaner advise --scan scan.json --id CANDIDATE_ID --enable-network --output advice.json
```

每次执行最多调用一次 TypeSafe API，处理 1–20 个候选。仅发送临时候选编号、类别、大小/年龄区间、规则资格以及“活跃状态未知”；不发送路径、文件名、原始候选 ID、会话正文、源码或自由文本原因。请求上限 16 KiB、响应上限 64 KiB、网络超时 8 秒；禁止重定向，不自动重试。

Jev 仅可建议 `keep`、`review`、`backup`，无法批准删除、修改计划或绕过保护规则。置信度不代表安全删除概率。缺少 Key、HTTP 错误或非法响应均退回纯规则模式。调用可能产生服务商费用；一次调用上限不等于金额预算保证。线上接口与准确性仍待验证；核心清理不依赖 Jev 可用性。

## 本地实验

运行环境：**2026-09-21 · macOS 26.5.1 · arm64 · Python 3.14.6**。全部使用独立临时目录中的合成文件，7 组实验通过，未修改真实用户文件，也未发送模型 API 请求。这些是本地实测，与 CI 矩阵结果分开记录。

| 实验 | 测试条件 | 实际结果 | 结论 |
| --- | --- | --- | --- |
| 扫描与保护 | 10 个文件：2 份旧日志、8 个受保护/近期/手动保留对象 | 仅识别出 2 个清理候选；8 个保留对象哈希均未变化 | 通过 |
| 隔离与恢复 | 2 个文件，共 8 MiB | 8 MiB 全部保留在同卷隔离区；恢复后两份内容哈希一致 | 通过 |
| 批准后永久清理 | 为同一批 8 MiB 文件重新生成并批准计划 | 删除逻辑字节 8,388,608；卷空闲量实测增加 **4,157,440 字节（3.965 MiB）**；8 个保留对象未变化 | 通过 |
| 计划后文件变化 | 执行前修改候选文件 | 返回码 2，拒绝执行并保留变化后的源文件 | 通过 |
| 恢复冲突 | 原路径已有新内容 | 返回码 2，新内容与隔离区原件均保留 | 通过 |
| 会话字节备份 | 复制并解出一份合成会话记录 | 原文件保留，解出内容哈希一致；**未测试 harness 续接** | 通过 |
| Jev 服务失败 | 离线传输模拟 HTTP 503 | 1 次模拟调用、0 次联网，退回规则模式；请求不含私人路径 | 通过 |

增加 Python 优化模式保护后，第二次运行的 7 组实验也全部通过：删除逻辑字节 8,388,608，卷空闲量观测差值为 **+5,976,064 字节（+5.699 MiB）**。两次记录均保留，未挑选较高的回收值。隔离行验证的是字节保留，没有声称实测磁盘空闲量恰好变化 0。

卷空闲量差值是观测值，不代表删除的 8 MiB 全部立即可用；文件系统记账与其他进程写入会影响它。备份实验验证的是选定文件的字节，Jev 实验验证的是故障处理，分别不等于会话可续接、真实推理准确性已验证。

[首次脱敏记录](docs/experiments/local-2026-09-21.json) · [最终脱敏记录](docs/experiments/local-2026-09-21-final.json) · [复现实验脚本](tools/local_experiments.py)。公开结果仅保留实验标签、系统/运行时版本、计数、字节数和布尔值，不含用户名、绝对路径、会话 ID、凭据、会话正文或源码内容。

```sh
python3 tools/local_experiments.py --output artifacts/local-experiments.json
```

实验脚本和 Logo 随当前 `main` 分支提供；初始 `v0.1.0` 标签早于此次文档更新。复现本节请使用 `main` checkout。

每次运行使用新的输出文件名；脚本拒绝覆盖既有证据，退出时清理临时样本。CI 也会运行这组实验，并将脱敏报告保存为 workflow artifacts。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
```

CI 已通过 Linux/macOS × Python 3.11/3.14 四组验证，覆盖安全与恢复测试、打包及干净安装，不需要模型凭据。实际证据以 workflow 与[版本说明](docs/releases/v0.1.0.md)为准，配置了 CI 不代表运行已通过。开发说明见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全边界见 [SECURITY.md](SECURITY.md)。MIT © 2026 Fireworks。
