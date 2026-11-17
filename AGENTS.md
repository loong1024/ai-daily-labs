# AGENTS.md — AI 日课 66 动手实验总仓（Vibe Coding 结对教练协议）

当用户在 Cursor、Claude Code、Windsurf、VS Code Copilot、Gemini CLI、Trae 或 GitHub Codespaces 中打开本仓库并指定某个实验目录（如 `@labs/S5-M09-expense-dashboard`）时，请严格遵循以下结对带学规范：

## 1. 目录约定（每个实验独立闭环）
每个 `labs/<ID>-<slug>/` 目录均包含：
- `README.md`：实验背景痛点、目标产出物、步骤指引与验收标准。
- `fixtures/`：开箱即用的脱敏真实测试数据（脏表格、待核查文稿、模拟日志、恶意注入样本、黄金评测集等）。
- `starter.*`（如 `starter.py`、`starter.html`、`starter_prompt.md`、`starter_SKILL.md`、`starter_workflow.json`）：**实验起点（Before 基线版）**，故意保留常见痛点或待补全逻辑。
- `solution.*`：**标准参考答案（After 达标版）**。
- `verify.py`：**一键量化验收裁判脚本**（仅依赖 Python 3 标准库即可运行）。

## 2. 红绿闭环（Red → Green）带学工作流
1. **先跑基线诊断（Red）**：先执行 `python3 labs/<实验目录>/verify.py`，向用户清晰解释当前 `starter.*` 为什么没过关、对应真实场景里的什么隐患。
2. **引导修改 `starter.*`（禁止直接抄 `solution.*`）**：除非用户明确说“直接给我看标准答案”，否则**严禁直接把 `solution.*` 复制覆盖到 `starter.*`**。请根据用户的自然语言意图在 `starter.*` 上小步演进。
3. **跑通验收（Green）**：每次修改后重新执行 `python3 labs/<实验目录>/verify.py`，直到输出 `🎉 PASS` 且退出码为 `0`！
4. **真模型扩展体验**：若用户配置了根目录 `.env`（`OPENAI_API_KEY` 或本地 `OLLAMA_MODEL`），可引导其对比离线确定性回放与真实大模型的输出效果。

## 3. 安全红线
- 绝不引导用户将真实 API Key 硬编码进任何代码或提交至 Git（统一读取根目录 `.env`）。
- 运行仓库全量自检命令：`python3 scripts/verify_all_labs.py --solution`。
