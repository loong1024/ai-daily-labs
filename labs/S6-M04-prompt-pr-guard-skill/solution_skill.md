---
name: llm-change-gate
description: 在修改 Prompt 文件、模型标识、采样参数或检索配置时使用。先运行评测集并与基线逐条对比，再写变更日志；出现退化时停止并向用户报告，不得直接提交。
---

# LLM 变更上线闸门（llm-change-gate）

## 何时使用
- 修改了 `prompts/` 目录下的任何提示词或模板文件
- 修改了模型标识（`model`）、`temperature`、`top_p` 等采样参数
- 修改了检索配置（文档切分大小、检索条数 `top_k`、重排模型或阈值）

## 项目约定
- 评测命令：`python3 solution_gate.py --baseline evals/baseline.json --candidate evals/latest.json`（在真实项目中可先执行 `npx promptfoo eval -o evals/latest.json`）
- 基线结果：`evals/baseline.json`（本实验对应 `fixtures/eval_scenarios.json` 中的 `baseline`）
- 快照索引：`evals/snapshots.json`（保存每次可上线版本的 `prompt_sha256` 与模型配置指针）
- 变更日志：`CHANGELOG-llm.md`
- **通过门槛（双硬卡点）**：
  1. 评测集用例 ID 与基线完全对齐（缺失任何基线用例视为违规删题，直接判 `FAIL`）；
  2. 总体通过率不低于基线（`candidate_pass_rate >= baseline_pass_rate`），**且任何带 `critical` 标签的高危用例都不得由通过变为失败（一票否决）**。

## 执行步骤
1. 用 `git diff` 列出本次涉及的 Prompt、模型参数与检索配置变更，用一句话写明改动意图与原因。
2. 运行评测命令生成本次候选结果 JSON，并保存当前版本快照。
3. 与基线 `baseline.json` 逐条对比，列出：
   - 由通过变失败的退化用例（重点高亮 `critical` 标签用例）
   - 由失败变通过的改进用例
   - 总体通过率变化、平均 Token 消耗变化与 P95 延迟变化
4. 门禁裁决：
   - **满足门槛（`PASS`）**：在 `CHANGELOG-llm.md` 追加一条结构化记录（含日期、版本号、改动内容与原因、评测前后指标对比、一键回滚命令），然后才允许执行 `git commit`。
   - **不满足门槛（`FAIL`）**：立即停止，**严禁提交**；向用户报告退化用例及其输出差异，并给出 1–2 个具体修复方向。
5. **防作弊红线**：绝对不要为了通过评测而擅自修改、弱化或删除评测用例；如果认为某条评测用例本身有误，必须单独向用户说明理由并等待人工确认。

## 生产级双保险：Git Pre-commit 硬卡点
为防止 Agent 偶发漏调本 Skill，应在 `.git/hooks/pre-commit` 中挂载 `gate.py` 检查脚本：一旦暂存区包含 `prompts/` 或模型配置文件改动，自动比对评测结果与 `baseline.json`，返回 `FAIL` 时直接以非零状态码阻断本地提交。

## 输出格式
- **结论**：`PASS` 或 `FAIL`
- **指标对比表**：总体通过率、`critical` 用例通过数、平均 Token、P95 延迟
- **退化用例清单**（如有，附退化原因摘要）
- **已写入的变更日志条目与一键回滚命令**（`PASS` 时）
