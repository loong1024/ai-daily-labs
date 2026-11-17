# S5-M07 · 主窗口被源码搜爆变笨？只读侦察子会话降噪对照实验

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`skill` | **预计耗时**：40 分钟 | **专题**：`vibe_coding`

## 1. 场景痛点：为什么主会话一边翻源码一边改代码最容易失忆翻车？

接手陌生中大型代码库追查跨模块调用链时，很多开发者习惯在同一个主对话窗口里让 AI 一路盲搜、读文件、试错、改代码：

1. **检索噪音挤爆主上下文**：连搜七八轮无关文件与历史报错后，上万 Token 的无关源码把主会话迅速塞满，触发上下文自动压缩（Compaction），连最初要改的约束都忘了。
2. **口头写“别改代码”根本拦不住**：仅在提示词里写一句“先看别改”，没有工具级的只读权限白名单（`allowed-tools`），AI 看到顺眼的报错常常顺手就把业务文件改坏了。
3. **缺少量化对照与逐行核验**：侦察返回一大坨未核实的函数名和飘移的行号，或者没做对照组 vs 实验组数据记录，做完也说不清到底省了多少上下文、准不准。

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验任务书、双窗/子会话降噪方法论与验收指南 |
| `fixtures/mini_repo/api/orders_router.py` | 模拟陌生代码库入口路由层（退款请求解析与路由入口） |
| `fixtures/mini_repo/services/refund_service.py` | 领域服务层（含退款幂等编排与夜间对账批处理下游耦合方） |
| `fixtures/mini_repo/models/ledger_entry.py` | 账本存储模型、冲正持久化仓储层与内建幂等冒烟自检函数 |
| `fixtures/session_traces.json` | 对照组（主会话盲搜）与实验组（只读子会话侦察）的真实会话遥测记录 |
| `starter.md` | **待改进起点**：残缺版 `codebase-scout` Skill 规范 + 超长失真侦察摘要 + 未填对照表 |
| `solution.md` | **标准参考实现**：可直接装入 `.claude/skills/` 或 `.agents/skills/` 的标准只读侦察 Skill + 经逐行核验的 ≤30 行坐标摘要 + 完整对照表 |
| `verify.py` | 红绿闭环量化验收脚本（自动打开 `fixtures/mini_repo/` 逐行核验每个文件名、符号与行号！） |

---

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴进 Cursor / Claude Code / Windsurf / Codespaces 对话框即可启动结对闯关：

```text
请阅读 @labs/S5-M07-subagent-context/README.md 及 fixtures/，按结对教练协议带我改进 starter.md，运行 python3 labs/S5-M07-subagent-context/verify.py 直到全部通过。
```

---

## 4. 40 分钟实操步骤指引

### Step 1：查看基线缺陷与会话遥测记录（5 分钟）
先阅读 `fixtures/session_traces.json` 中对照组与实验组的上下文消耗差异，再运行验收脚本观察 `starter.md` 当前触发的 4 项问题：

```bash
python3 labs/S5-M07-subagent-context/verify.py
```

### Step 2：补齐工具级只读权限硬约束（10 分钟）
修改 `starter.md` 顶部的 YAML Frontmatter：
- `name` 固定为 `codebase-scout`；
- `description` 写清正向触发时机（陌生/大型仓库梳理跨模块调用链、符号引用、测试病灶定位）**以及负向边界**（如“不要用于已知精确单文件的小型直接编辑”）；
- 配置工具级只读白名单 `allowed-tools: [Read, Grep, Glob]`（严禁放行 `Write`、`Edit`、`MultiEdit`、`Bash` 等写/执行工具！），并声明 `max-output-lines: 30`。

### Step 3：对 `fixtures/mini_repo/` 执行真实只读侦察并输出 ≤30 行坐标摘要（15 分钟）
只读打开 `fixtures/mini_repo/` 下的 3 个跨层模块文件，修正 `starter.md` 中的 ```` ```scout-brief ```` 代码块：
- **严格控制在 30 行以内**，严禁大段粘贴源码；
- 包含三大契约板块：`[核心调用链]`、`[现有约定与测试参考]`、`[潜在耦合与禁区]`；
- 每个坐标按 `path/to/file.py:L行号 (`符号名`)` 格式书写，确保每一个文件路径、行号与函数/类名在 `fixtures/mini_repo/` 中 **100% 真实存在且精确对应**；
- **零猜测原则**：针对任务询问但源码中并不存在的“异步网关回调重试队列”，必须明确标注 `未确认`，删掉 `starter.md` 里臆造的 `auto_retry_webhook` 函数名！

### Step 4：填完主会话降噪对照实验记录表（10 分钟）
根据 `fixtures/session_traces.json` 的实测遥测数据，补全 `starter.md` 底部的 `## 对照实验记录表`，清晰对比对照组与实验组在**对话轮数、主会话注入 Token 数（上下文占比）、坐标核验准确率、后续修改轮数**上的差异。

---

## 5. 免代码平替方案（双窗资料提炼法）

非程序员处理十几份长报告、政策汇编或访谈纪要时，完全照搬同一套隔离架构：
1. **侦察窗 A（只读提炼窗）**：专门投喂原始长文档，规定它只允许输出**不超过 1 页、每条必带《文件名 + 页码/章节号》的索引摘要**，没见到的数字一律标“未确认”。
2. **主写作窗 B（干净成稿窗）**：只把这 1 页核验过的带页码摘要贴进全新的窗口 B 撰写正式方案，彻底告别“长文聊了十轮后张冠李戴编数据”。

---

## 6. 量化验收命令

```bash
# 验收当前 starter.md 改进进度（自动逐行打开 mini_repo 核对行号与符号真伪）
python3 labs/S5-M07-subagent-context/verify.py

# 验证标准参考答案 solution.md（全部 4 项指标 100% 通过，返回退出码 0）
python3 labs/S5-M07-subagent-context/verify.py --solution
```
