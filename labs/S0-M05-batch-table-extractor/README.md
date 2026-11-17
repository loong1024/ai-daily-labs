# S0-M05 · 手工复制粘贴太慢？60 分钟写个批量抽表小脚本

> **所属章节**：Ch.3 长文档与结构化 API · 长报告精读、模型 API 调用与批量表格抽取  
> **预计耗时**：60 分钟 ｜ **实验类型**：白盒 Python 工程骨架包

## 1. 场景痛点

当你要处理几十到几百条客户反馈、工单记录或调研问卷时，继续停留在网页聊天框复制粘贴会遇到三大瓶颈：

1. **手工搬运易漏行错位**：15–200 条反馈来回复制粘贴，不仅手酸，还经常漏行、错列，或者导出的 CSV 用 Excel 打开中文全变乱码。
2. **一遇限流或脏格式就整批崩盘**：并发或连续请求触发 `429 Rate Limit`、偶发模型把 JSON 包在 ```` ```json ```` 代码块里甚至返回一段解释文字，朴素脚本没做异常区分与容错兜底，跑到第 12 条直接抛异常前功尽弃。
3. **Token 花销是笔糊涂账**：既没有试跑前几条预估总预算，也没有累加每次响应里的 `usage.prompt_tokens / completion_tokens`，跑完不敢放大到上千条生产数据。

## 2. 目录文件说明

- `README.md`：实验任务书、模块契约与验收命令说明
- `fixtures/customer_feedback_15.csv`：15 条真实感 SaaS 客户反馈语料（覆盖账单异常、移动端闪退、功能诉求、好评致谢、账号权限及含英文逗号/引号的 CSV 转义边界样本）
- `starter.py`：起点半成品脚本（含硬编码占位密钥、无 401/429 重试区分、缺少 Markdown 代码块剥离与 JSON 容错、未汇总 Token 账单、导出 CSV 缺少 `utf-8-sig` BOM）
- `solution.py`：零第三方依赖的完整标准实现（支持环境变量安全读取、401 立即阻断、429 指数退避 + `Retry-After` 遵循、前 5 条试跑预算预估、JSON 容错记错不中断、精确 Token 对账与 Excel 无乱码 `utf-8-sig` CSV 导出）
- `verify.py`：红绿双重门禁验收脚本（内置 401/429 故障注入桩与账单对账断言）

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴到 Cursor / Claude Code / Windsurf 即可开始结对改造：

```text
请阅读 @labs/S0-M05-batch-table-extractor/README.md 与 fixtures/，按 AGENTS.md 带我完善 starter.py，运行 python3 labs/S0-M05-batch-table-extractor/verify.py 直至通过。
```

> **免代码平替**：如果暂时不写代码、只需要一次性处理 10–20 条反馈，可把文本合并粘贴到网页 AI 对话框，要求它“按 `反馈ID | 情绪 | 分类 | 紧急度 | 一句话摘要` 整理成可直接粘贴进 Excel 的制表符表格”一次出表。

## 4. 实操步骤指引

### 步骤 1：环境变量鉴权（严禁硬编码 API Key）

修改 `starter.py` 中的 `load_config_from_env`：
- 删除源码中的硬编码测试密钥常量，改为只从 `os.environ.get("OPENAI_API_KEY", "").strip()` 读取密钥（永远不要把任何真实密钥写进代码或提交记录；本地测试假密钥请统一用 `FAKE_TEST_KEY_DO_NOT_USE_12345` 占位格式）。
- 若未配置密钥且未显式开启离线演示回退，抛出 `AuthConfigError` 并给出包含 `401` 排查提示的清晰报错。

### 步骤 2：区分 401 鉴权错误与 429 限流指数退避重试

完善 `call_with_retry`：
- 捕获 `ApiHttpError`：当 `status_code == 401` 时**绝不盲目重试**，立即抛出 `AuthConfigError` 提醒检查环境变量密钥。
- 当 `status_code in {429, 500, 502, 503, 504}` 时，最多重试 `config.max_retries` 次；若异常带有 `retry_after` 秒数则优先遵循 `retry_after`，否则按 `config.base_backoff_sec * (2 ** attempt)` 指数退避调用 `sleep_fn(delay)` 后重试。

### 步骤 3：JSON 代码块剥离与单条解析容错兜底

完善 `parse_extraction_json`：
- 若模型返回了 ```` ```json ... ``` ```` 代码围栏，先剥离围栏再做 `json.loads`。
- 校验必填字段 `("sentiment", "category", "urgency", "summary")` 均存在且非空；若遇到非法 JSON 或缺字段，**不要抛异常中断全批**，返回 `(None, 错误原因字符串)` 供主循环记录 `status="parse_error"` 后继续处理后续样本。

### 步骤 4：前 5 条试跑估算、Token 账单精确累加与 UTF-8-SIG 导出

完善 `estimate_pilot_budget` 与 `run_batch_pipeline`：
- 遍历全部 15 条反馈，即使某条返回文本 JSON 解析失败，只要 API 已成功响应，仍需将其 `usage.prompt_tokens` 与 `usage.completion_tokens` 计入实付账单！
- 在完成前 5 条（或不足 5 条时的全部样本）后调用 `estimate_pilot_budget` 计算单条平均输入/输出 Token 与全批预估总费用。
- 使用 `encoding="utf-8-sig"`（带 UTF-8 BOM 头）导出结果 CSV，确保 Windows / macOS Excel 双击直接打开无乱码。

## 5. 验收命令

```bash
# 1) 检查当前 starter.py 进度（默认未修改时返回红灯改进提示，退出码 1）
python3 labs/S0-M05-batch-table-extractor/verify.py

# 2) 验证标准参考答案 solution.py（全部验收项 100% 通过，退出码 0）
python3 labs/S0-M05-batch-table-extractor/verify.py --solution
```
