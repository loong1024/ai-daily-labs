# S2-M04：自动化脚本带病上线？给 AI 装上六维只读审查提示与靶子排雷

> **所属章节**：Ch.5 自动化 AI 工作流 · 确定性 AI 工作流编排与无人值守自动化  
> **实验类型**：`skill` | **零代码友好**：`True` | **专题**：`workflow` | **预计耗时**：45 分钟

---

## 1. 场景痛点与实验目标

把自动化工作流（n8n JSON、GitHub Actions YAML 或自研编排配置）投入生产运行前，手工排查常遇到三大痛点：

1. **肉眼扫配置易漏高危隐患**：几十行节点 JSON 里藏着硬编码密钥、无上限立即重试或缺少对外发送前的人工审批卡点，人眼极易滑过去。
2. **随口让 AI 检查标准漂移且二次泄密**：口头说一句“帮我检查一下”，AI 每次关注点不一，甚至会把配置文件里的明文密钥原封不动打印在审查报告里造成二次泄露！
3. **缺少带毒靶子验证提示词成色**：写完审查 Skill 后没有预设缺陷的靶子文件做红蓝盲测，不知道遇到真实漏洞时能不能 100% 拦住。

**实验目标**：
1. 将残缺的 `starter_skill.md` 升级为符合 Agent Skills 规范的 **六维只读可靠性审查技能（`workflow-reliability-review`）**，做到自然语言触发、按 `BLOCKER/WARN/NIT` 输出分级表格与结论、严守只读边界且 **全程脱敏遮罩明文密钥**。
2. 用该 Skill 对预埋 **3 处高危阻断漏洞** 的靶子文件做红队盲测排雷，再将 `starter_workflow.json` 修复为高可靠配置并通过蓝队复验清零高危阻断项！

> 💡 **免代码平替提示**：零基础同学也可直接把完善的 `solution_skill.md` 和 `fixtures/vulnerable_workflow.json` 一起粘贴进任意大模型网页对话框，仅输入一句“帮我检查这个工作流能不能上线”，即可秒出脱敏分级排雷报告。

---

## 2. 本目录文件说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、六维审查标准与验收指引 |
| `fixtures/vulnerable_workflow.json` | 预埋 3 处高危缺陷（硬编码测试密钥、无限无退避重试、对外群发无审批）的带毒靶子工作流 |
| `fixtures/audit_test_cases.json` | 触发盲测用例与禁止明文回显的敏感假凭证黑名单 |
| `starter_skill.md` | 待完善的审查技能文件（缺 YAML 触发头、缺六维细则、缺分级表与密钥脱敏约束） |
| `solution_skill.md` | 标准六维只读审查 `SKILL.md`（可直接放入 `.claude/skills/workflow-reliability-review/SKILL.md`） |
| `starter_workflow.json` | 待按审查报告整改的工作流配置（初始与带毒靶子一致） |
| `solution_workflow.json` | 修复全部高危阻断项与隐患后的可上线工作流标准配置 |
| `verify.py` | 红蓝双向验收脚本（测试 Skill 元数据规范、红队盲测抓洞、密钥零回显脱敏、蓝队修复复验） |

---

## 3. Vibe Coding 一键开练口令

将下面这段口令直接粘贴给 Cursor / Claude Code / Windsurf 等 AI 编程助手即可开启结对排雷：

```text
请阅读 @labs/S2-M04-workflow-audit-skill/README.md 与 fixtures/，按 AGENTS.md 结对教练协议带我完善审查 Skill 与靶子配置，运行 python3 verify.py 直至全部验收通过。
```

---

## 4. 实操步骤指引

1. **查看带毒靶子与基线失败报告**  
   直接运行 `python3 verify.py`，观察残缺的 `starter_skill.md` 为何漏检漏洞并在报告里直接泄露了假测试密钥原文。
2. **完善六维只读审查技能 `starter_skill.md`**  
   补齐标准 `SKILL.md` 结构：
   - **YAML Frontmatter**：包含 `name: workflow-reliability-review` 与触发场景 `description`（涵盖检查、评审、上线自动化流程等关键词）；
   - **六维审查清单**：完整覆盖 `触发器`、`数据流转`、`LLM 节点`、`错误处理`、`人工审批`、`密钥与成本` 六个维度；
   - **分级输出表与结论**：输出 `| 级别（BLOCKER/WARN/NIT） | 位置 | 问题 | 建议修复 |` Markdown 表格，末尾给出明确结论（`可上线` / `修复后上线` / `不可上线`）并列出必改 `BLOCKER`；
   - **硬性安全约束**：声明 **只读审查**（不改文件、不跑流程、不调外部 API），且 **发现明文密钥时只报告位置或打码遮罩，绝不在输出中复述密钥原文**。
3. **修复 `starter_workflow.json` 中的三处高危隐患**  
   对照排雷报告修复工作流配置：
   - 将明文 `api_key` 改为环境变量引用（如 `${MAIL_GATEWAY_API_KEY}`），补充日志脱敏与单次运行预算上限；
   - 将无限立即重试改为仅针对 `429`/`5xx`/`timeout` 的带抖动指数退避（最大 4 次），`400`/`401` 不重试，耗尽落入死信队列并告警；
   - 在对外群发邮件与发放补偿券前启用人工审批（`enabled: true`），设置超时默认中止（`timeout_policy: "abort"`）与一次性身份校验令牌（`one_time_token: true`），并补齐触发器时区、Webhook 幂等去重与 LLM `"其他"` 兜底。
4. **运行红蓝双向复验**  
   执行 `python3 verify.py`，确认红队盲测 100% 抓出 3 个漏洞且零明文泄密、蓝队修复后高危阻断项归零并转为 `可上线`！

---

## 5. 验收命令

在实验目录（`labs/S2-M04-workflow-audit-skill/`）下执行：

```bash
# 验收你当前完善的 starter_skill.md 与 starter_workflow.json
python3 verify.py

# 验证标准参考答案 solution_skill.md 与 solution_workflow.json
python3 verify.py --solution
```
