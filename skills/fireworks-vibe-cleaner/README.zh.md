# fireworks-vibe-cleaner

<p align="center"><img src="assets/logo-spark-sweep.png" width="192" height="192" alt="Fireworks Vibe Cleaner — Spark Sweep logo"></p>

[English](README.md) | [简体中文](README.zh.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[![CI](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

查看 Codex、Claude Code 产生的磁盘占用，审阅有明确范围的清理计划，再验证实际变化。同时提供 Agent Skill 和独立 Python CLI，默认离线，可选 Jev 辅助建议。

**v0.1 的清理范围有限：**仅处理超过保留期的已知 harness 日志，以及有 Git 跟踪源文件、被 Git 忽略且自身未跟踪的 Python 字节码。会话支持复制与字节校验，保留源文件。同盘隔离释放 **0 字节**；永久删除需要单独批准。

## 支持范围

| 对象 | v0.1 行为 |
| --- | --- |
| Codex `log/codex-tui.log`、`logs/codex-tui.log` 与 Claude `debug/` 日志 | 保留期检查 → 审阅计划 → 隔离 → 恢复或单独批准永久清理 |
| 项目 `__pycache__/*.pyc` | 要求源文件存在且被 Git 跟踪、缓存被忽略且未跟踪；执行前再次检查 |
| 会话记录、Claude 工具结果与恢复快照、生成资产 | 清点及按选定文件备份；校验字节、保留源文件；尚未验证 harness 会话恢复 |
| Codex worktree | 只读分类；不自动删除，不代管 Git 生命周期 |
| 源码、记忆、凭据、数据库、未知对象 | 禁止进入清理执行器 |

默认保留期为 30 天。扫描中的 eligible 只是初步候选，不代表删除授权。遍历不跟随子目录符号链接、不跨卷；依赖目录与 Git 内部目录会跳过并标明扫描不完整。本工具不提供整盘完整占用统计。

## 安装

需要 Python 3.11+，支持 macOS、Linux。修改源文件或隔离文件还需要 `lsof`；项目字节码检查需要 Git。无 Python 运行时第三方依赖，不启动常驻服务，默认不联网。

从固定标签安装：

```sh
git clone --branch v0.1.1 --depth 1 https://github.com/yizhiyanhua-ai/fireworks-vibe-cleaner.git
cd fireworks-vibe-cleaner
python3 scripts/fireworks-vibe-cleaner.py doctor
```

直接运行脚本无需安装 Python 包。下文使用简短的 `fireworks-vibe-cleaner` 命令，可选择创建虚拟环境并执行 `python -m pip install .`；也可将该命令替换为 `python3 scripts/fireworks-vibe-cleaner.py`。开发期间使用本地 checkout，跳过标签克隆步骤。实际发布与实测状态见[版本说明](docs/releases/v0.1.1.md)。

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

## 真实本机验证

**真实数据，2026-09-21 · macOS 26.5.1 · arm64 · Python 3.14.6。实际清理释放 0 字节。** 这次结果尚不能证明 v0.1 能解决大体积 session 占用问题。下表没有使用合成文件或模拟服务响应。

| 指标 | 处理前 | 处理后 / 真实观测 |
| --- | ---: | --- |
| 真实目录盘点 | 49,064 个文件；逻辑大小 21,165,470,439 字节（19.71 GiB） | 只读元数据扫描；跳过 225 个符号链接/依赖目录边界，不是完整磁盘统计 |
| Session 占用 | 2,615 个文件；15,038,397,937 字节（14.01 GiB） | 原件保留；尚不支持删除 session，也未验证 harness 续接 |
| 同一份真实快照上的规则修正 | 8 份自定义服务日志被误选，分配空间共 196,608 字节 | 收紧 Codex 文件名白名单后全部受保护；**可清理候选变为 0** |
| 真实 Codex 会话备份（2 份） | 126,384,858 字节（120.53 MiB） | ZIP 37,856,051 字节（36.10 MiB），缩小 70.05%；耗时 1978 ms |
| 真实 Claude 会话备份（2 份） | 98,252,538 字节（93.70 MiB） | ZIP 21,852,674 字节（20.84 MiB），缩小 77.76%；耗时 1214 ms |
| 字节恢复校验 | 私下记录真实源文件 SHA-256 | 4 份解包内容全部匹配；4 份源文件前后哈希全部未变 |
| 实际空间收益 | 修正规则后没有可执行的清理候选 | **源文件删除 0 字节；清理释放 0 字节**；保留 ZIP/manifest 新增逻辑占用 59,712,330 字节（56.95 MiB） |
| Jev 线上效果对比 | 本轮推理调用尚未获得授权 | **未运行**；不以模拟响应声称准确性、速度或收益 |

样本选择条件为：至少一天前的稳定会话文件、每份不超过 64 MiB、选择时无打开句柄。压缩比只适用于这 4 份样本。备份耗时包含备份过程的回读，未包含前置哈希与解包。原件仍保留，ZIP 变小**不等于释放空间**。两个卷的空闲量观测差值分别为 −38,461,440 字节（Codex 所在卷）和 −21,991,424 字节（Claude 所在卷），包含同期后台写入，不能全部归因于本次验证。用于校验的解包副本已移除，私有归档与 manifest 留在本机。

真实盘点发现了一处安全问题：旧规则会把 Codex 日志目录中的自定义服务 `.log` 也当作 harness 日志。当前 `main` 将 Codex 清理范围收紧到 `log/codex-tui.log` 和 `logs/codex-tui.log`；执行阶段会重新分类并拒绝白名单外的旧计划。这次验证确认了保护规则修复与备份字节完整性；**尚未验证真实隔离/永久清理，也未验证 session 续接**。

[真实脱敏结果](docs/experiments/real-local-2026-09-21.json) · [真实数据验证脚本](tools/real_validation.py)。公开结果仅包含聚合计数、体积与耗时，不含用户名、路径、文件名、ID、内容哈希、会话正文或凭据。原始盘点、归档与 manifest 均应保留在本机私有目录。

```sh
python3 scripts/fireworks-vibe-cleaner.py scan --output artifacts/private-inventory.json
python3 tools/real_validation.py --inventory artifacts/private-inventory.json --output artifacts/real-results.json
```

每次使用新的输出文件名。脚本会创建同卷私有备份与临时解包副本，始终保留原始 session；这是用户主动运行的本地验证，**不会在 CI 中访问个人目录**。[历史合成回归测试](docs/experiments/synthetic-regression.md) 仅作安全机制证据，不作真实清理效果证据；CI 继续用隔离样本运行回归测试。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
```

CI 已通过 Linux/macOS × Python 3.11/3.14 四组验证，覆盖安全与恢复测试、打包及干净安装，不需要模型凭据。实际证据以 workflow 与[版本说明](docs/releases/v0.1.1.md)为准，配置了 CI 不代表运行已通过。开发说明见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全边界见 [SECURITY.md](SECURITY.md)。MIT © 2026 Fireworks。
