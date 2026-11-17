# S1-M02 · JSON 总报错还瞎猜？用 Instructor 锁死结构化抽取

> **所属章节**：Ch.3 长文档与结构化 API · 长报告精读、模型 API 调用与批量表格抽取  
> **实验类型**：`github` | **专题**：`doc_data` | **预计耗时**：60 分钟

---

## 1. 场景痛点与实验目标

做财务发票记账、表单录入或报销工单归档时，手搓“请只输出 JSON”往往面临三大顽疾：
1. **多吐一句客套话即崩盘**：模型顺手加上 `"好的，抽取结果如下："` 或代码块包裹，直接炸崩下游裸 `json.loads()`。
2. **先填金额再强行圆谎**：模型若先输出 `amount` 结论字段，遇到邮件里同时出现“原价/预算上限/实付合计”时极易抓错首个数字，随后在说明字段里强行自圆其说。
3. **脏数据无拦截直通入库**：OCR 把日期识别成 `2099-12-01` 或把冲红负数 `-300.00` 当成正数发票金额，缺少字段校验与错误回传重试闭环，入库后只能人工擦屁股。

**本实验目标**：
借鉴 **Instructor + Pydantic** 核心工程范式（零外部依赖即可在本地直接运行验证，同时完全兼容真实 `instructor` 接口），实现：
- **强类型 Schema + 依据前置（`evidence` 置于 `amount` 之前）**；
- **业务规则校验器（拦截未来日期、非正数金额、非法币种）+ `max_retries=2` 自动带错重试修正链路**；
- **20 份含雷样本全量实测**，产出“依据前置 vs 结论前置”准确率对比表与假阳性样本复盘。

> 💡 **免代码平替思路**：在网页对话框中给出带枚举说明的表格模板，强制要求 AI 先填“原文依据原句”列再填“最终金额/日期”列，最后用表格条件格式筛查负数或超期异常值。

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `fixtures/invoices.json` | 20 份真实感邮件/报销单样本（含 12 份常规中英文票据、4 份折扣/押金多数字干扰样本、2 份故意埋雷的未来日期 `INV-17` 与冲红负数 `INV-18`、2 份报价单/报销上限假阳性剖析样本） |
| `starter.py` | **起点半成品代码**：字段将 `amount` 放在最前且缺 `evidence`、缺正数金额与日期上限校验、业务层直接裸调 `json.loads` 且无错误回传重试 |
| `solution.py` | **标准参考实现**：强类型 `Invoice` Schema（`evidence` 前置 + 字段校验器）、`max_retries=2` 错误回传自愈循环、准确率对照与假阳性审计器 |
| `verify.py` | 自动化验收脚本（验证 20 份样本强类型入库、埋雷样本重试自愈日志、依据前置准确率优势及零裸 `json.loads`） |

---

## 3. Vibe Coding 一键启动口令

将下面这段话直接复制发送给你的 AI 编程助手（Cursor / Claude Code / Windsurf）：

```text
请阅读 @labs/S1-M02-json-schema-extract/README.md 与 fixtures/，带我一步步改进 starter.py 并运行 python3 labs/S1-M02-json-schema-extract/verify.py 直到全部通过。
```

---

## 4. 动手步骤指引

1. **运行基线观察报错率**：
   执行 `python3 labs/S1-M02-json-schema-extract/verify.py`，查看 `starter.py` 在带寒暄包裹样本与埋雷样本上的崩溃及漏拦提示。
2. **锁死 `Invoice` 强类型 Schema 并前置 `evidence`**：
   在 `Invoice` 模型中将 `evidence: str`（摘录含金额、币种、真实开票日期的原文句子）放在第一个字段，随后定义 `amount: float`、`currency`（限定 `"CNY"` / `"USD"`）、`issue_date`（`YYYY-MM-DD`）与 `vendor`，并统一通过 `Invoice.model_validate_json(...)` 替代业务层裸 `json.loads`。
3. **加装业务规则校验器与 `max_retries=2` 回传重试**：
   在校验逻辑中拦截 `amount <= 0` 与 `issue_date > reference_today`（开票日期晚于今天）。当抛出 `ValueError` 时，将具体错误原因追加回对话消息列表自动重试（最多重试 2 次），保存每次尝试的状态日志。
4. **实测“依据前置 vs 结论前置”与复盘假阳性**：
   完善 `compare_evidence_order(samples)`，统计 `evidence_first=True` 与 `evidence_first=False` 在 20 份样本上的字段全对率，并输出“格式合法但易抽错语义”的典型假阳性案例成因。
   *(注：若在真实项目中连接在线模型，可在 `.env` 配置 API Key；测试示例请勿写真实密钥，可用 `FAKE_TEST_KEY_DO_NOT_USE_12345` 占位。)*

---

## 5. 量化验收命令

```bash
# 检查你当前修改的 starter.py 进度
python3 labs/S1-M02-json-schema-extract/verify.py

# 验证标准参考实现（期望 100% 全绿通过）
python3 labs/S1-M02-json-schema-extract/verify.py --solution
```
