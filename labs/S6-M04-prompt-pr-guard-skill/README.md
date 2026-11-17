# S6-M04 · Agent 改提示词就乱提交？装 Skill 搭防退化闸门

> **所属章节**：Ch.7 评测优化与上线 · 评测驱动迭代（Evals）、性能优化与生产安全上线  
> **实验类型**：`skill`（即插即用 Agent Skill + Git 硬闸门配置包） | **专题**：`eval_ops` | **预计耗时**：60 分钟

## 1. 场景痛点与实验目标

用编码 Agent（Claude Code / Cursor / Windsurf）优化 AI 应用时，最怕以下三件事同时发生：
1. **改完顺手就提交**：让 Agent 润色一句系统提示词，它看着顺眼直接 `git commit`，上线才发现退款红线或防注入场景已经退化。
2. **平均分涨了掩盖高危翻车**：普通寒暄题多对了 2 道，总通过率从 80% 涨到 90%，但带 `critical` 标签的安全/合规核心用例从 `PASS` 掉成了 `FAIL`。
3. **覆盖旧版无快照可退**：既没留变更前后对比日志，也没保存上一版可用快照哈希，线上出故障想回滚都找不回昨天那版配置。

**本实验目标**：编写符合行业规范的 `llm-change-gate` Agent Skill（`SKILL.md`）与配套本地 Git `pre-commit` 硬卡点脚本（`gate.py`），实现**“总通过率不降 + Critical 高危用例一票否决 + 防删题作弊 + 结构化变更日志 + 1 分钟一键快照回滚”**完整闭环。

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `starter_skill.md` | **待完善 Skill 定义**：残缺的 `SKILL.md` 草稿，缺少标准 YAML 触发描述、`critical` 一票否决门槛与禁删评测题红线 |
| `starter_gate.py` | **待完善闸门脚本**：仅看总体通过率的朴素比较器（总分 80%→90% 时会漏放 `critical` 退化！），缺少回滚与完整变更日志 |
| `solution_skill.md` | **标准参考 Skill**：可直接放入 `.claude/skills/llm-change-gate/SKILL.md` 或项目技能目录的生产级规范文件 |
| `solution_gate.py` | **标准参考硬闸门**：完整实现逐条对比、`critical` 一票否决、防删题校验、`CHANGELOG-llm.md` 生成、一键回滚与 `pre-commit` 钩子输出 |
| `fixtures/eval_scenarios.json` | **回归演练套件**：内置 10 题 `baseline`（含 4 条 `critical` 高危用例）、`candidate_regressed`（总分升至 90% 但 `CRIT-02` 越权退款翻车）、`candidate_healthy`（全绿修复版）与 `snapshots` 版本快照清单 |
| `verify.py` | **自动化红蓝对抗验收脚本**：同时对 `SKILL.md` 规范性与 `gate.py` 拦截/日志/回滚能力进行实战检验 |

---

## 3. Vibe Coding 一键启动口令

将下面这句口令粘贴到编码 Agent 对话框即可开启结对演练：

```text
请阅读 @labs/S6-M04-prompt-pr-guard-skill/README.md 与 fixtures/，按 AGENTS.md 带我改进 starter 文件并运行 python3 labs/S6-M04-prompt-pr-guard-skill/verify.py 直至通过。
```

> **免代码平替方案**：若在 Dify / Coze 等平台编排应用，可在每次点击“发布更新”前，按 `solution_skill.md` 中的核对单先将旧版提示词另存为版本号快照，跑完固定 10 条核心题库且确认 `critical` 题零退化后再发布。

---

## 4. 建议实操步骤

1. **体验漏检事故**：运行 `python3 verify.py`，观察 `starter_gate.py` 为什么在面对 `candidate_regressed` 时错误放行（总分 90% ≥ 80%，却漏掉了高危用例 `CRIT-02` 翻车）。
2. **完善 `starter_skill.md`**：
   - 补齐顶部 YAML Frontmatter（`name: llm-change-gate` 与清晰的触发条件 `description`）；
   - 明确触发范围（`prompts/` 目录、模型标识/采样参数 `temperature`、检索切分与重排配置）；
   - 写明双层门槛（总通过率 ≥ 基线，且任何 `critical` 标签用例不得由 PASS 变 FAIL）与防作弊红线（严禁擅自修改或删除评测用例）。
3. **升级 `starter_gate.py` 硬卡点**：
   - 在 `evaluate_change()` 中增加用例完整性校验（拦截删题作弊）与 `critical` 退化一票否决；
   - 在 `format_changelog_entry()` 中输出含日期、改动意图、原因、前后通过率/Token/P95 延迟对比及一键回滚命令的 Markdown 记录；
   - 实现 `rollback_to_snapshot()` 与 `render_pre_commit_hook()`，确保本地 Git 提交前自动执行硬拦截，出事 1 分钟切回 `v1.2.0`。
4. **全绿闭环验收**：运行 `python3 verify.py` 确认全部红蓝测试通过。

---

## 5. 验收命令

```bash
# 验收当前改进进度（初始状态预期为 FAIL）
python3 labs/S6-M04-prompt-pr-guard-skill/verify.py

# 验收标准参考答案（预期 100% PASS）
python3 labs/S6-M04-prompt-pr-guard-skill/verify.py --solution
```
