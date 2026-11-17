# S5-M03 · 拒绝AI一把梭改乱千行：Spec先行与小步TDD实验

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`prompt` ｜ **专题**：`vibe_coding` ｜ **预计耗时**：45 分钟

## 1. 场景痛点：为什么一句话需求会让 AI 改崩半个模块？

日常开发新功能时，如果只扔给 AI 一句模糊需求（例如：“给企业团队订阅写个算总价的函数，支持席位阶梯打折和优惠码”），往往会发生三件事：
1. **擅自脑补核心计费规则**：你想要的是类似个税的**分段超额累进计费**（前 10 席原价、超出部分打折），AI 却一把梭写成了全量跳档打折，买 11 席比买 10 席还便宜。
2. **没对齐“不做什么（Non-Goals）”**：AI 顺手硬编码了 `7.2` 美元汇率、自作主张加了 `tax_cents` 税费字段，甚至顺手把隔壁原本正常的 `normalize_account_slug` 改出了后缀破坏兼容性。
3. **测试滞后沦为摆设**：一次改完几百行再补一个只测正常路径的测试，异常优惠码与负数账单漏洞统统漏网。

本实验在单一主会话中带你完成：**模糊需求暴露坑点 → 生成并审计 7 节标准 `spec.md` → 对齐待确认问题 → 按小步 TDD（先红后绿）实现精准计费并剔除越界代码**。

---

## 2. 本目录资源清单

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、步骤指引与验收命令 |
| `fixtures/vague_requirement.json` | 原始一句话模糊需求、硬性技术约束，以及产品负责人对 3 个核心疑问的澄清答复 |
| `fixtures/bad_spec_stub.md` | 反面残缺规格样本（缺非目标、缺待确认问题、未给 Given-When-Then 用例） |
| `fixtures/clarified_io_cases.json` | 澄清锁死后的 11 组标准输入输出对照表与异常边界测试集 |
| `starter.py` | **待改进**：含残缺 Spec 生成器/审计器、“AI 一把梭”越界错误实现、被顺手改坏的邻近函数及单薄测试 |
| `solution.py` | 标准参考实现（调用 `shared.aid_lab.chat_complete` 支持真模型与离线确定性 Mock 双模运行） |
| `verify.py` | 红绿双重门禁验收脚本（零第三方依赖） |

---

## 3. Vibe Coding 一键启动口令

将下面口令粘贴到你的 Vibe Coding 工具（Cursor / Claude Code / Windsurf）中启动结对演练：

```text
阅读 @labs/S5-M03-spec-driven-tdd/README.md 与 fixtures/，先对齐规格再带我小步 TDD 改进 starter.py，运行 python3 labs/S5-M03-spec-driven-tdd/verify.py 直到全部通过。
```

---

## 4. 建议实操步骤

1. **观察“AI 一把梭”留下的坑点**：阅读 `starter.py` 与 `fixtures/vague_requirement.json`，运行 `python3 verify.py` 查看 4 项红灯报告。
2. **补齐 Spec 生成提示词与 7 节结构审计（`draft_spec_markdown` & `audit_spec_markdown`）**：
   - 确保生成的 `spec.md` 严格包含 7 节：**1. 目标**、**2. 非目标（Non-Goals）**、**3. 接口与输入输出样例对照表（Markdown 表格）**、**4. 边界情况与错误处理（≥5 条）**、**5. 验收标准（“给定…当…那么…”格式）**、**6. 任务拆分（显式标记 `须串行` 或 `可并行`）**、**7. 待确认问题（≥3 条并附候选方案，只出规格不写业务实现）**。
   - 在 `audit_spec_markdown` 中对上述要素做量化校验，能准确拦截 `fixtures/bad_spec_stub.md`。
3. **小步 TDD 推进（先写必败测试，再小步修正实现）**：
   - **小步 1（阶梯计费修正）**：在 `run_tdd_suite` 中先补充 12 席与 55 席的**分段超额累进**断言（1–10 席 `10000` 分/席，11–50 席 `8000` 分/席，51–500 席 `6000` 分/席），再修正 `quote_team_subscription`。
   - **小步 2（优惠码校验与零元封底）**：先补充优惠码大小写/空格归一化、未知优惠码抛 `ValueError`、大额券抵扣后最低应付 `0` 分（`discount_cents = min(subtotal_cents, coupon_value)`）的测试，再补齐实现。
   - **小步 3（席位合法性边界）**：拦截 `seats <= 0`、`seats > 500`、布尔值 `True/False` 或非整数输入，统一抛 `ValueError`。
   - **小步 4（非目标越界清理与 Diff 复核）**：拒绝非 `"CNY"` 币种（抛 `ValueError`），剔除规格外擅自塞入的 `tax_cents` / `vip_points` 字段，并还原被顺手改坏的既有函数 `normalize_account_slug`。

> **免代码平替方案**：产品或运营同学可在通用对话框套用本实验的 7 节 Spec 提示词，要求 AI 先输出“目标、3 条禁区、输入输出样例表、5 个待确认问题”，逐条拍板后再让其分步生成最终方案。

---

## 5. 验收命令

在仓库根目录执行：

```bash
# 检查当前 starter.py 进度（初始预期为红灯 exit 1）
python3 labs/S5-M03-spec-driven-tdd/verify.py

# 验证标准参考答案 solution.py（预期 4/4 全绿 exit 0）
python3 labs/S5-M03-spec-driven-tdd/verify.py --solution
```
