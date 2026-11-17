# [S1-M04] 仓库 Prompt 越改越乱？自制自动体检 Skill 拦截缺陷

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`skill` ｜ **预计耗时**：60 分钟 ｜ **零代码友好**：否（附免代码平替方案）

---

## 1. 场景痛点与实验目标

当业务仓库里长期维护十几个 LLM Prompt 模板时，多人协作迭代极易引入隐蔽退化：

- **痛点 1（前缀缓存被击穿，账单翻倍）**：顺手把动态时间戳 `{{current_timestamp}}` 或随机请求号 `{{request_id}}` 写在 System Prompt 开头前几行，导致每次请求 KV Cache 前缀全部失效，白花冤枉钱还拖慢首字延迟。
- **痛点 2（外部输入裸奔引发指令注入）**：把用户来信或网页抓取文本直接裸拼进提示词，既没有用 `<user_input>` 分隔标签包裹并声明“标签内只是数据”，也没在填充前转义闭合标签 `</user_input>`，极易被恶意输入逃逸并劫持输出字段。
- **痛点 3（示例自相矛盾、规范靠人脑记）**：Few-shot 示例改了一半导致 JSON 字段名冲突（如示例 1 用 `category/priority`，示例 2 用 `type/urgent`），或者调试时把假密钥留在提示词里，人工 Code Review 十次漏九次。

### 实验目标
在本实验中，你将按标准 `SKILL.md` 规范构建 **`prompt-review` 自动体检技能**，并配套编写确定性 Prompt 静态体检器、闭合标签防注入转义器与修复版模板，拿“四缺陷坏模板”与 6 条回归测试集（含闭合标签逃逸注入攻击）完成端到端拦截与修复闭环。

> 💡 **免代码平替方案（日常提示词维护者）**：  
> 不写代码时，可把四项核心铁律——**① 开头固定保缓存（动态时间放末尾）、② 外部输入加标签隔离、③ Few-shot 示例字段完全一致、④ 零硬编码密钥/内部机密**——存为一段固定“提示词上线前自检口令”，每次改完模板粘贴给 AI 逐条打勾审查。

---

## 2. 本目录文件说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、步骤指引与验收命令（本文件） |
| `fixtures/flawed_ticket_triage.prompt.md` | **四缺陷坏样本**：同时包含开头动态时间戳击穿缓存、System 混入假密钥、Few-shot 字段冲突、外部输入未用标签隔离且缺头部版本号 |
| `fixtures/regression_cases.json` | **6 场景回归测试集**：覆盖常规退款、生产 P0 故障、闭合标签逃逸指令注入（`</user_input>`）、账号注销与边界情绪投诉 |
| `starter.md` | **待完善起点（Skill 规约）**：残缺的 `prompt-review` 技能定义，触发描述过窄且缺少缓存/转义/结构化输出规范 |
| `starter.py` | **待完善起点（体检脚本与修复模板）**：空壳体检器、未做闭合标签转义的拼接函数与未修复的工单模板 |
| `solution.md` | **标准参考答案（Skill 规约）**：可直接放入 `.claude/skills/prompt-review/SKILL.md` 的完整六维体检规范 |
| `solution.py` | **标准参考答案（体检脚本与修复模板）**：精准定位行号的静态体检器、闭合标签安全转义器、零缺陷修复模板与回归评测器 |
| `verify.py` | 自动化红绿闭环验收脚本（支持无 Key 离线确定性回归验证与真实大模型无缝切换） |

---

## 3. Vibe Coding 一键启动口令

打开你的 Vibe Coding 编程助手，一键粘贴以下口令开始实战：

```text
请阅读 @labs/S1-M04-prompt-lint-skill/README.md 与 fixtures/，按 AGENTS.md 带我完善 starter 文件并运行 python3 labs/S1-M04-prompt-lint-skill/verify.py 直至全绿。
```

---

## 4. 动手步骤指引

1. **运行基线验收看红灯**：执行 `python3 verify.py`，查看当前 `starter.md` 与 `starter.py` 缺失的 5 项核心能力。
2. **完善 `starter.md`（定义 `prompt-review` 自动触发技能）**：
   - 在 YAML Frontmatter 中设置 `name: prompt-review`，并在 `description` 中明确写出触发场景：**新建或修改 `prompts/` 目录下的模板文件，或修改代码中拼接传给模型的 `system` / `user` 文本时自动触发**。
   - 完整覆盖 6 步体检清单：① 要素具体可检验（拒绝“专业一点”这类含糊词）；② `system`/`user` 职责分离且禁绝密钥/内部敏感信息；③ Few-shot 示例字段与格式完全一致且覆盖边界；④ 缓存友好前缀（开头固定规则与示例，时间戳/请求 ID 等易变参数一律置末）；⑤ 外部输入装入分隔标签声明“标签内只是数据”并**转义闭合标签**；⑥ 结构化输出附 Schema、代码做校验与有限重试。
   - 规定输出表格列（`问题 | 位置（文件:行号）| 风险等级（高/中/低）| 修改建议`）及收尾动作（运行回归测试如 `promptfoo` 或本地回归集 + 更新头部版本号与变更说明）。
3. **完善 `starter.py`（实现确定性体检、闭合转义与模板修复）**：
   - 实现 `lint_prompt_template`：扫描前 20 行动态占位符（`cache_prefix`）、硬编码密钥（`hardcoded_secret`）、`[EXAMPLES]` JSON 字段一致性（`fewshot_consistency`）、`[USER]` 分隔标签隔离与数据声明（`injection_isolation`）以及首行版本注释（`version_header`），精准返回 `file:line` 位置与修复建议。
   - 实现 `render_safe_user_input`：将外部不可信文本中的 `<user_input>` 与 `</user_input>` 转义为 `&lt;user_input&gt;` / `&lt;/user_input&gt;` 后再包裹外层标签，彻底阻断闭合逃逸注入。
   - 修复 `REPAIRED_PROMPT_TEMPLATE` 并完成 `run_regression_suite`，确保 6 条回归用例 100% 通过且注入用例无法篡改分类。

---

## 5. 验收命令

```bash
# 检查你当前修改的 starter.md 与 starter.py 进度
python3 verify.py

# 验证官方参考实现 solution.md 与 solution.py（应 5/5 全绿通过）
python3 verify.py --solution
```
