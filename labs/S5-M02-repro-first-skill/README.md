# S5-M02 · AI修Bug总盲改？复现优先Skill与降噪脚本实战

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`skill` ｜ **专题**：`vibe_coding` ｜ **预计耗时**：75 分钟

## 1. 场景痛点：为什么 AI 修 Bug 经常越修越乱？

很多开发者在用 Cursor、Claude Code、Windsurf 排查线上报错时，常踩三个大坑：
1. **没拿到最小复现就盲改**：只贴一句“退款算错了”，AI 立刻连猜带蒙连改四五轮，把原本正常的无券订单逻辑也改坏了。
2. **排障规范塞满全局规则**：把几百行调试 SOP 常驻在全局 `AGENTS.md`，平时写新功能也要白白消耗大量开局上下文。
3. **测试日志刷爆上下文**：每次跑测试把几百行 `PASSED` 和 `DEBUG` 日志全塞回会话，真正关键的最后 15 行断言堆栈反而被淹没。

本实验带你用**渐进式加载的 `repro-first-debugging` Skill + 精简测试输出包装器 + 二振止损守卫**，跑通“先红（必败复现）→ 根因定位 → 最小修复（后绿）→ 连续卡住及时回滚”的完整工程闭环。

---

## 2. 本目录资源清单

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、步骤指引与验收命令 |
| `fixtures/buggy_billing.py` | 历史故障提交快照（只读基准，用于检验你的回归测试是否真的“修复前必败”） |
| `fixtures/repro_cases.json` | 完整故障工单、缺信息伪故障单、刷屏测试日志样本与 5 组止损演练场景 |
| `starter.md` | **待完善**：残缺的 `repro-first-debugging` 技能说明（缺禁区声明、缺先问机制与二振回滚） |
| `solution.md` | 标准参考 `SKILL.md`（可直接复制到 `.claude/skills/repro-first-debugging/SKILL.md` 或 `.agents/skills/`） |
| `starter.py` | **待完善**：含日志降噪函数、必败复现测试、最小修复实现与止损状态机骨架 |
| `solution.py` | 标准参考 Python 实现 |
| `verify.py` | 红绿双重门禁验收脚本（零第三方依赖） |

---

## 3. Vibe Coding 一键启动口令

将下面口令直接粘贴给你的 AI 编程助手（Cursor / Claude Code / Windsurf）：

```text
阅读 @labs/S5-M02-repro-first-skill/README.md 与 fixtures/，带我按步骤改进 starter.md 与 starter.py，并运行 python3 labs/S5-M02-repro-first-skill/verify.py 直到全绿。
```

---

## 4. 建议实操步骤

1. **阅读故障基准与反面表现**：查看 `fixtures/repro_cases.json` 中的 `bug_reports` 与 `fixtures/buggy_billing.py`，先运行一次 `python3 verify.py` 观察当前 4 项红灯提示。
2. **完善 `starter.md`（对应 `repro-first-debugging/SKILL.md`）**：
   - 补齐顶部 YAML Frontmatter：`name: repro-first-debugging`，并在 `description` 中明确**触发条件**（报错、测试失败、行为异常）与**负面禁区**（不用于开发新功能）。
   - 写清**开始前信息核对**（完整报错与堆栈、触发步骤、期望与实际行为、运行环境；缺一不可，缺项先向用户询问而非瞎猜）。
   - 写清**四步流程**（1. 复现最小失败测试 → 2. 1–3 个根因假设验证 → 3. 最小范围修复且不得擅自修改/删除/跳过既有测试 → 4. 回归测试全绿）。
   - 写清**停止条件**（同一问题连续 2 次修复无效立即停止并回滚汇报；涉及公共接口、数据库结构或新增依赖须先征得同意）与**汇报格式**（根因及证据、修改文件与原因、新增回归测试名称、测试命令与摘要）。
3. **实现精简测试包装器 `summarize_test_run`（`starter.py`）**：
   - 全部通过时只输出简短汇总（≤ 3 行，剔除 `DEBUG` 噪音）；
   - 存在失败时提取失败用例标识，并仅保留最后 `max_tail_lines` 行关键报错摘要（剔除刷屏的 `PASSED` 与 `DEBUG` 行）。
4. **验证“先红后绿”与二振止损（`starter.py`）**：
   - 在 `test_promo_refund_repro(calc_fn)` 中编写必败断言：验证 `fixtures/buggy_billing.py` 传入时必定触发 `AssertionError`，而在你修复后的 `calculate_prorated_refund` 上通过，并填写 `ROOT_CAUSE_SUMMARY`。
   - 补齐 `decide_debug_next_action(state)` 止损决策逻辑，覆盖缺信息追问、连续 2 次失败回滚汇报、高影响变更先请示等场景。
5. **挂载到真实客户端（拓展）**：
   - 原生支持 Skill 的工具：将完善后的 `starter.md` 复制到 `.claude/skills/repro-first-debugging/SKILL.md` 或 `.agents/skills/repro-first-debugging/SKILL.md`。
   - 免代码平替：把“先要报错截图/样例 → 给 2 个根因猜想 → 给最小验证动作，卡住 2 轮立即重开窗口”存为快捷提示词模板。

---

## 5. 验收命令

在仓库根目录执行：

```bash
# 检查当前 starter.md / starter.py 改进进度（初始预期为红灯 exit 1）
python3 labs/S5-M02-repro-first-skill/verify.py

# 验证标准参考答案 solution.md / solution.py（预期 4/4 全绿 exit 0）
python3 labs/S5-M02-repro-first-skill/verify.py --solution
```
