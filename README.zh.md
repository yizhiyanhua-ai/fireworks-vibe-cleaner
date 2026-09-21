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

Jev 仅可建议 `keep`、`review`、`backup`，无法批准删除、修改计划或绕过保护规则。置信度不代表安全删除概率。缺少 Key、HTTP 错误或非法响应均退回纯规则模式。调用可能产生服务商费用；一次调用上限不等于金额预算保证。2026-09-21 的真实元数据调用已成功（Jev 1.13.0），结果见下表；准确率及相对规则的收益仍未验证。核心清理不依赖 Jev 可用性。

## 真实 10 GiB 验证与 Jev 线上对比

**真实数据清理必须先经过人工确认，确认内容须包含具体范围和操作。** 本轮仅读取原件、创建私有归档并校验恢复字节，没有隔离、移动或删除任何原始文件。

实测日期：2026-09-21。选取 **564 个已有会话文件，共 10,932,021,589 字节（10.181 GiB）**；Codex 样本至少 7 天未修改，Claude 样本至少 1 天未修改。选择时检查了打开句柄，并冻结全文哈希。源目录盘点跳过 227 个边界，不能视为完整磁盘统计。

| 真实数据集 | 文件数 | 原始字节 | ZIP 字节 | 归档体积缩小 | 全量解压 / 最后原件哈希 |
| --- | ---: | ---: | ---: | ---: | --- |
| Codex 历史会话 | 560 | 9,932,261,559（9.250 GiB） | 5,447,045,764（5.073 GiB） | 45.16% | 全部一致 |
| Claude 历史会话 | 4 | 999,760,030（0.931 GiB） | 252,487,818（0.235 GiB） | 74.75% | 全部一致 |
| **总计** | **564** | **10.181 GiB** | **5.308 GiB** | **47.86%** | **564/564 一致** |

全部 **1,107,896 条非空 JSONL 记录**通过解析，非法行和超限行均为 0。所有归档都已全量流式解压并做 SHA-256 校验，没有覆盖正在使用的 harness 目录。原件与 ZIP 的逻辑大小差为 **4.873 GiB**；由于原件保留，**实际清理释放仍为 0 字节**，归档和保留的校验副本会增加占用，不能把这个差值当作磁盘回收承诺。过程中曾主动暂停一次，增加单条 JSONL 行长度上限 64 MiB（不等于进程总内存上限），之后复用 1 个完成的分卷续跑；耗时和卷空闲量变化仅对应续跑阶段，不作为冷启动性能基准。

| 原生历史读取检查（OS 沙箱禁止联网） | 真实结果 | 验收结论 |
| --- | --- | --- |
| Codex CLI 0.154.0，2 个归档样本 | 直接读取及分页接口均未返回非空历史 | **未通过验证**；不能声称会话恢复或续接成功 |
| Claude SDK 0.2.126，2 个样本 | 首轮按全库 UUID 查找选到了不同副本；两个 UUID 在源目录中均各有 2 份文件 | 全库查找存在歧义 |
| Claude，绑定到具体源文件 | 隔离的原件副本与恢复件分别读出 **87 条、63 条消息**，历史内容摘要一致 | 具体文件的原生读取通过；未验证整个原环境恢复或模型续接 |

| 纯规则与真实 Jev 对比 | 实际结果 |
| --- | --- |
| 纯规则处理 | 保留全部 564 份原件；清理须人工确认 |
| 线上样本与重复调用 | 从冻结数据集中抽取 20 个真实候选，3 次调用、60 次判断，**全部为 `review`**；三轮选项一致 |
| 实际模型及端到端耗时 | `jev-1.13.0`；1,286 / 2,010 / 3,170 ms，中位数 **2,010 ms** |
| 用量与费用 | 正式对比 10,398 输入 token；计入 3 个候选的连通性验证，共 **4 次真实调用、11,141 输入 token**，按[官方输入价格](https://docs.typesafe.ai/models)估算 **US$0.000467922**；未核验账单实扣金额 |
| 可支持的结论 | 真实结构化推理已验证；没有标注真值，不能声称准确率提升，也没有依据扩大删除范围 |

发送内容仅含类别、大小/年龄档位、规则结果和未知活跃状态，不含路径、文件名、原始 ID、会话正文、源码或凭据。模型的 `review` 和置信度都不能替代人工清理确认。

[10 GiB 脱敏记录](docs/experiments/real-10g-2026-09-21.json) · [真实 Jev 结果](docs/experiments/real-jev-2026-09-21.json) · [包含失败项的原生读取记录](docs/experiments/real-native-history-2026-09-21.json)。

复现工具位于当前 `main`（v0.1.1 发布早于本次验证）：[真实大样本验证](tools/large_real_validation.py)、[主动启用的 Jev 线上对比](tools/live_jev_validation.py)、[macOS 断网沙箱原生读取](tools/native_history_validation.py)。这些脚本会创建私有校验材料，始终保留原件；原生工具/SDK 是可选的本地依赖，不会自动安装。CI 不会运行访问真实用户数据或付费服务的检查。

较早的 214 MiB 实测及自定义日志误判修复，保留在[历史真实数据验证记录](docs/experiments/real-small-validation.zh.md)中。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
```

CI 已通过 Linux/macOS × Python 3.11/3.14 四组验证，覆盖安全与恢复测试、打包及干净安装，不需要模型凭据。实际证据以 workflow 与[版本说明](docs/releases/v0.1.1.md)为准，配置了 CI 不代表运行已通过。开发说明见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全边界见 [SECURITY.md](SECURITY.md)。MIT © 2026 Fireworks。
