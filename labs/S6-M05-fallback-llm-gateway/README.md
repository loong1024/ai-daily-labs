# S6-M05 · 模型报错账单飙？基于 LiteLLM 封装网关

> **所属章节**：Ch.7 评测优化与上线 · 评测驱动迭代（Evals）、性能优化与生产安全上线  
> **实验类型**：`idea`（白盒 Python 工程骨架包） | **专题**：`eval_ops` | **预计耗时**：180 分钟

## 1. 场景痛点与实验目标

业务流量一上来，到处散落的大模型 SDK 裸调用会迅速引爆三类生产事故：
1. **故障一崩到底，流式半截断流难处理**：上游接口偶发 `429` 限流或 `503` 过载，应用直接白屏报错；或者 `400` 参数写错还在盲目死循环重试；流式输出发了一半断流又直接重头拼接导致前端满屏乱码。
2. **所有请求全打最贵模型且串行排队**：简单意图分类、重复文档摘要全发给昂贵旗舰大模型，4 路独立子请求串行等待导致总延迟翻四倍。
3. **日账单失控无熔断闸门**：爬虫或异常循环半夜刷爆额度，缺少软上限自动降级小模型与硬上限暂停非核心功能的保护阀。

**本实验目标**：收敛统一的网关入口 `LLMGateway`（生产环境可直接对接 `litellm.completion`，本实验内置零依赖可插拔传输层开箱即测），补齐**任务分层路由、确定性结果缓存（排除实时任务）、可重试判定与连续失败熔断器、流式首包前无缝切备用、4 路并发提速、单日软/硬预算封顶及结构化日志**，并用 **50 条混合流量重放集**当场跑出省钱与高可用对比报表！

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `starter.py` | **待完善网关骨架**：把所有任务裸调发给最贵主模型，无缓存、无重试熔断、无流式首包边界保护、无并发与预算硬封顶 |
| `solution.py` | **标准参考实现**：零第三方硬依赖的高内聚网关封装（兼容 LiteLLM 调用范式）及 50 次重放压测对比器 |
| `fixtures/gateway_config.json` | **网关路由与预算配置**：定义 `small` / `large` / `fallback` 模型单价、各业务 `task` 路由档位、是否允许缓存、是否属于关键核心任务，以及软/硬日预算阈值 |
| `fixtures/replay_50.json` | **50 条真实混合流量重放集**：涵盖重复文档摘要、简单分类、合同审查、实时订单查询（禁缓存）及 `429`/`503` 故障注入请求 |
| `verify.py` | **自动化量化验收脚本**：验证连续 `503` 熔断与流式首包前兜底、缓存隔离与 4 路并发耗时、预算软降级/硬拦截，以及 50 次重放压测报表 |

---

## 3. Vibe Coding 一键启动口令

将下面这句口令粘贴到编码 Agent 对话框即可开启结对工程实战：

```text
请阅读 @labs/S6-M05-fallback-llm-gateway/README.md 与 fixtures/，按 AGENTS.md 带我改进 starter.py 并运行 python3 labs/S6-M05-fallback-llm-gateway/verify.py 直至通过。
```

> **免代码平替方案**：零代码场景可直接使用 OpenRouter 或 Cloudflare AI Gateway 等托管网关控制台，在网页端配置 Fallback 备用模型列表、确定性响应缓存与每日/每月消费硬上限告警。

---

## 4. 建议实操步骤

1. **运行红灯基线**：执行 `python3 verify.py`，查看朴素裸调 `starter.py` 在故障注入、并发延迟、预算红线和 50 条流量重放中的失败详情。
2. **实现任务分层路由与每日软/硬预算闸门**：
   - 读取 `fixtures/gateway_config.json` 中各 `task` 的 `tier`（`small` / `large`）、`cacheable` 与 `critical` 属性；
   - 累计当日账单 `daily_spend_usd`：超过 `soft_limit_usd` 时将非关键（`critical: false`）的大模型任务自动降级为 `small` 模型；超过 `hard_limit_usd` 时对非关键任务抛出 `BudgetExceededError` 并记录告警，同时保障 `critical: true` 核心任务继续可用。
3. **实现确定性缓存与实时任务豁免**：
   - 仅当任务配置 `cacheable: true` 且调用未传 `no_cache=True` 时，以 `model + prompt_version + user_id + messages` 的 SHA-256 作为缓存键；命中缓存时费用记为 `0`；`live_order_status` 等实时任务严禁走缓存。
4. **实现重试、熔断器、流式首包边界与并发提速**：
   - 仅对 `429`、`5xx`、`timeout` 做指数退避带随机抖动重试，遇到 `400` 立即失败不重试；
   - 主模型连续失败达到 `failure_threshold`（如 3 次）即打开熔断器，后续请求直接走 `fallback` 备用模型；
   - 流式调用 `llm_stream()`：**仅在未发出首个 chunk 前**允许切换至备用模型重试；若已发出至少 1 个 chunk 后中断，必须抛出 `StreamInterruptedError`，严禁重头拼接重复半截内容；
   - 使用 `ThreadPoolExecutor` 实现 `batch_concurrent_calls()` 4 路并发提速，并为每次调用写入完整结构化日志。
5. **跑通 50 条流量重放压测验收**：执行 `python3 verify.py` 直至全绿通过！

---

## 5. 验收命令

```bash
# 验收你当前改进的 starter.py（初始状态预期为 FAIL）
python3 labs/S6-M05-fallback-llm-gateway/verify.py

# 验收标准参考答案 solution.py（预期 100% PASS）
python3 labs/S6-M05-fallback-llm-gateway/verify.py --solution
```
