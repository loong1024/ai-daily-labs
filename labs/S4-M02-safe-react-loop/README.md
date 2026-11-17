# S4-M02：Agent 死循环烧钱还假装成功？手写最小安全闭环对照测

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **实验类型**：`idea` ｜ **专题**：`agent_mcp` ｜ **预计耗时**：90 分钟 ｜ **零代码友好**：否

---

## 一、场景需求与常见痛点

很多开发者第一次脱离重型黑盒框架手写自主 Agent（ReAct / Tool-Use 循环）去查本地笔记、做统计并写回待办时，往往在理想路径下看似跑通，一旦遇到边缘输出就酿成线上事故：

1. **嘴上成功、实际没落盘**：模型传入了错误字段或未经过宿主参数校验，或者宿主根本没写文件，模型却在最终回复里“自信宣布已写入待办”。
2. **一报错就崩或吞异常**：工具遇到文件不存在或参数类型错误时直接抛出未捕获异常导致进程崩溃，而不是把可操作的错误信息作为观察（Observation）喂回给模型自我纠错。
3. **死循环空转烧穿账单**：缺少最大步数、单步观察截断与重复调用签名熔断，模型卡在同一组参数上重试几十轮，瞬间耗尽 Token 预算。

**实验目标**：  
基于单文件白盒 Python 骨架与 `fixtures/notes/` 示例日记，补全 **JSON Schema 参数校验**、**异常转观察自愈**、**四道硬护栏（步数/预算上限、长观察 600 字截断、连续重复调用熔断、高危写操作前人工确认）** 以及 **`trace.jsonl` 全程轨迹落盘与回放**，并用 `--mock-fault` 确定性复现三类故障。

---

## 二、本目录资源说明

```text
labs/S4-M02-safe-react-loop/
├── README.md                         # 实验说明、四道护栏设计与 CLI 故障演练命令
├── fixtures/
│   ├── notes/
│   │   ├── 2026-W11-mon-wed.md       # 周一至周三日记（含 2 次运动记录 + 超 700 字会议纪要附录以测试截断护栏）
│   │   ├── 2026-W11-thu-sun.md       # 周四至周日日记（含 2 次运动记录，本周合计运动 4 次，距目标 5 次差 1 次）
│   │   └── todo.md                   # 待办清单文件（供 append_todo 写操作受控测试）
│   └── fault_scenarios.json          # 4 组确定性场景规格（none / bad_args / tool_err / loop）
├── starter.py                        # 起点半成品骨架（工具注册已备好，缺失参数校验、四道护栏与轨迹记录）
├── solution.py                       # 标准参考实现（完整安全闭环 + --mock-fault 故障桩 + JSONL 回放器）
└── verify.py                         # 自动化红绿验收脚本（在临时目录隔离测试，不污染仓库夹具）
```

---

## 三、Vibe Coding 一键启动口令

将下面口令直接粘贴给你的 AI 编程助手（Cursor / Claude Code / Windsurf 等）：

```text
请阅读 @labs/S4-M02-safe-react-loop/README.md 与 fixtures/ 测试素材，按根目录 AGENTS.md 结对教练协议带我一步步补全 starter.py 四道安全护栏，运行 verify.py 直到全部验收通过。
```

---

## 四、实操步骤指引

### 步骤 1：先跑基线验收，观察无护栏骨架的风险暴露
```bash
python3 labs/S4-M02-safe-react-loop/verify.py
```
你会发现未加护栏的 `starter.py` 存在以下风险：
- 未做 JSON Schema 参数校验，非法枚举与未知字段被直接放进工具；
- 工具抛出 `FileNotFoundError` 时未转为可恢复的错误观察文本；
- 超长日记原文未截断（超过 `MAX_CHARS_PER_OBS = 600`），且写操作 `append_todo` 前未触发人工确认回调；
- `--mock-fault loop` 连续重复调用同一工具时不会提前熔断，且没有生成可回放的 `trace.jsonl`。

> **免代码平替提示**：不写代码的同学，可用飞书多维表格自动化或 Dify/Coze 搭建“AI 决策 → 条件参数校验分支（失败退回重填）→ 循环计次器 <= 3 → 写入前人工审批节点 → 写执行日志表”五步流程图，手动输入错格式参数测试退回自愈。

### 步骤 2：补全消息主循环、参数校验与四道硬护栏
在 `starter.py` 中依次实现：
1. **`validate_tool_args(schema, args)`**：校验 `required` 必填项、`additionalProperties: False`、基础类型（`string`/`number`/`integer`/`array`）及 `enum` 枚举，校验失败时将清晰纠错提示作为工具结果回传给模型，不崩溃、不触发写入。
2. **工具异常捕获转观察**：调用工具函数时用 `try...except Exception` 捕获运行时异常（如读取不存在的笔记），返回 `ERROR [TOOL_EXCEPTION]: ...` 引导模型改调 `list_notes` 自我恢复。
3. **四道硬护栏**：
   - `MAX_STEPS = 8` 与累计 Token 上限硬约束；
   - `MAX_CHARS_PER_OBS = 600`：对超长工具输出截断至 `<= 600` 字符并附截断提示；
   - **重复调用熔断**：计算规范化调用签名 `tool_name + canonical_json(args)`，一旦连续出现相同调用签名（第 2 次重复）立即触发 `duplicate_call_circuit_breaker` 停机并输出已推进进展；
   - **高危写确认**：执行 `append_todo` 前调用 `confirm_fn(tool_name, args)`（命令行默认 `input()` 确认），若用户拒绝则取消落盘并如实告知模型。
4. **JSONL 轨迹落盘与回放**：每步将 `step`、`tool_name`、`call_signature`、`observation`、`elapsed_ms`、`cumulative_tokens` 写入 `trace.jsonl`，并在 `replay_trace(trace_path)` 中 100% 还原。

### 步骤 3：命令行对比运行正常模式、三类故障桩与轨迹回放
改好后（或使用 `solution.py`），可在终端直观运行四组对照实验：

```bash
# 1. 正常多步任务（查笔记统计本周运动次数 -> 确认后追加待办）
python3 labs/S4-M02-safe-react-loop/solution.py --mock-fault none --auto-approve

# 2. 故障演练：非法参数自愈 / 工具报错恢复 / 死循环重复熔断
python3 labs/S4-M02-safe-react-loop/solution.py --mock-fault bad_args --auto-approve
python3 labs/S4-M02-safe-react-loop/solution.py --mock-fault tool_err --auto-approve
python3 labs/S4-M02-safe-react-loop/solution.py --mock-fault loop

# 3. 100% 还原回放最近一次生成的 trace.jsonl
python3 labs/S4-M02-safe-react-loop/solution.py --replay /tmp/aid_s4m02_trace.jsonl
```

---

## 五、验收命令

```bash
# 检查当前 starter.py 修改进度
python3 verify.py

# 在仓库根目录运行
python3 labs/S4-M02-safe-react-loop/verify.py

# 验证标准参考实现 solution.py（应 100% 全绿通过）
python3 verify.py --solution
```
