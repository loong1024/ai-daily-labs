# S5-M05 进阶选修：基于模板补全只读本地笔记MCP并排坑

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **预计耗时**：80 分钟 | **实验类型**：工程实战与排坑 (`github`)

## 1. 场景痛点

将本地笔记或知识库接入多个 AI 客户端时，常见的三大工程失误是：

1. **选型过度设计**：个人一次性汇总或单客户端简单任务，明明写个本地 CLI 脚本或 Skill 就能解决，却盲目从零手写整套 MCP 服务。
2. **Stdio 协议被 `print` 搞崩 & 上下文被长文撑爆**：在 `stdio` 模式下随手用 `print()` 打调试日志污染 `stdout`，瞬间破坏 JSON-RPC 帧解析；或者返回未截断的数千字长笔记撑爆上下文窗口。
3. **读写混杂与描述含糊**：未严格限制只读边界（混入删除/写入接口）、硬编码个人目录路径，且工具描述含糊不清，导致大模型频频选错工具。

本实验带你先落地“三层技术选型决策树”，再在最小 MCP 模板上补全**纯只读、环境变量驱动、`stderr` 日志隔离、游标分页与字符硬截断**的本地笔记服务，并完成自然语言选工具联调。

## 2. 目录文件说明

- `starter.py`：含典型线上隐患的本地笔记 MCP 模板（存在盲目自建选型、暴露危险 `delete_note`、硬编码路径、`stdout` 调试日志污染、无分页与长文未截断等问题）。
- `solution.py`：完整高水准只读笔记 MCP 参考实现（支持 `OPENAI_API_KEY` / `OLLAMA_MODEL` / 离线确定性 Mock 三模自适应工具路由）。
- `fixtures/notes_corpus.json`：10 篇真实感工程与排障 Markdown 笔记样本（含超长架构复盘笔记，专门压测 100 字摘要与 400 字正文硬截断）。
- `fixtures/scenarios.json`：6 个技术选型判定场景与 4 条自然语言提问样本。
- `verify.py`：5 维自动化红绿验收脚本。

## 3. Vibe Coding 一键开练口令

```text
请阅读 @labs/S5-M05-readonly-notes-mcp/README.md 与 fixtures/，按 AGENTS.md 协议带我补全 starter.py，运行 python3 labs/S5-M05-readonly-notes-mcp/verify.py 直至验收通过。
```

## 4. 动手步骤指引

1. **第一步 · 技术选型自检（15 分钟）**：完善 `recommend_integration_mode(scenario)`，按决策树准确分流：
   - 非多客户端或低频一次性任务 → `cli_or_skill`（本地脚本 / Skill）
   - 多客户端高频复用且现成插件即可满足、无定制规则 → `off_the_shelf_mcp`（直接装成熟只读 MCP）
   - 多客户端高频复用且需定制过滤/分页/脱敏截断 → `custom_readonly_mcp`（自建只读 MCP）
2. **第二步 · 只读边界与环境变量解耦（15 分钟）**：移除 `starter.py` 中的 `delete_note` 写入接口，确保仅暴露 `search_notes`、`get_note`、`list_tags` 三个只读工具；笔记目录统一从环境变量 `NOTES_DIR` 读取，严禁硬编码个人本地路径。
3. **第三步 · 修复 `stdout` 污染（15 分钟）**：在 `dispatch_stdio_line` 中将所有调试日志改写到 `sys.stderr`，确保 `sys.stdout` 只输出纯净的单行 JSON-RPC 报文。
4. **第四步 · 实现游标分页与字符上限防爆（20 分钟）**：
   - `search_notes(query="", tag=None, limit=5, cursor=None)`：校验 `1 <= limit <= 10`，只返回 `id`、`title`、`updated_at`、`tags` 与 **不超过 100 字符**的 `summary`，并附带 `next_cursor`。
   - `get_note(note_id, offset=0, max_chars=300)`：强制单次硬上限 `MAX_NOTE_CHARS = 400`；超出时截断并返回 `truncated=True`、`next_offset` 与续读指引；遇到不存在的 `note_id` 返回引导先调用 `search_notes` 的友好报错。
5. **第五步 · 打磨工具描述并通过自然语言选工具联调（15 分钟）**：在工具描述中写清“做什么、何时用、不能做什么”，完善 `route_natural_language_query`，验证仅用自然语言提问即可准确命中对应只读工具与参数。

> **免代码平替方案**：无需跨多端定制规则的用户，优先安装官方只读文件系统插件并仅挂载单个公开笔记文件夹，避免重复造轮子。

## 5. 验收命令

```bash
# 检查当前 starter.py 进度（初始预期为 FAIL）
python3 labs/S5-M05-readonly-notes-mcp/verify.py

# 验证标准参考答案 solution.py（预期 5/5 全绿 PASS）
python3 labs/S5-M05-readonly-notes-mcp/verify.py --solution
```
