# S6-M08 模型日志算不清账？套 OTel 拆解延迟与缓存

> **所属章节**：Ch.7 评测优化与上线 · 评测驱动迭代（Evals）、性能优化与生产安全上线  
> **实验类型**：`doc`（OpenTelemetry GenAI 本地结构化日志与延迟/缓存对账） | **预计耗时**：45 分钟

## 1. 场景痛点与定位

项目初期不想部署重型可观测平台（本实验可作为 **S6-M02 全链路观测** 的轻量前置方案），但随手打的本地日志往往一团糟：
1. **首字延迟与总耗时混淆**：没开流式（`stream=True`）直接把整包返回耗时记成响应速度，分不清用户等第一个字花了多久（`ttft_ms`）还是生成长文花了多久（`total_ms`）。
2. **看不出缓存省了多少钱**：只记总输入字数，分不清多少 Token 命中了廉价的提示词前缀缓存（`cached_tokens`），算出来的账单虚高一倍。
3. **多步请求串不起账单**：一次用户提问先后调了「意图路由」和「知识库生成」两步，却没有共享同一个 `trace_id`，排障对账时根本拼不回同一次请求。

**实验目标**：套用 **OpenTelemetry GenAI 语义约定** 重构本地 JSONL 日志格式，开启流式采集真实 `ttft_ms`，用唯一 `trace_id` 串联多步请求账单，并用精炼统计模板量化「裁剪冗余上下文 + 固定缓存前缀」前后的 P50/P95 首字提速与缓存省钱效果。

---

## 2. 目录资源说明

- `fixtures/legacy_messy_logs.jsonl`：重构前的典型混乱日志样本（缺 `trace_id`、未开流式无 `ttft_ms`、无 `cached_tokens`），供对照诊断盲区。
- `fixtures/ab_stream_traces.jsonl`：重构后的 40 条标准多步流式 Span 日志（`v1_bloated_ctx` 冗余动态前缀 10 次请求 vs `v2_trimmed_cached` 精简上下文并固定静态前缀 10 次请求，每次请求含 `intent_router` + `rag_answer` 两步）。
- `starter.py`：存在典型观测缺陷的基线代码（`stream=False` 把总耗时当首字延迟、每步生成孤立 ID 断链、把缓存命中 Token 按全价重复计费、统计函数缺 P50/P95 与缓存占比）。
- `solution.py`：完整 OTel GenAI 规范日志采集器、单次请求对账器与 A/B 延迟缓存统计脚本。
- `verify.py`：自动化红绿验收脚本。

---

## 3. Vibe Coding 一键启动口令

将下面口令粘贴到 Cursor / Claude Code / Windsurf 中开启结对练习：

> 请阅读 @labs/S6-M08-otel-latency-cost/README.md 与 fixtures/，按 AGENTS.md 带我改进 starter.py 并跑通 python3 labs/S6-M08-otel-latency-cost/verify.py。

---

## 4. OTel GenAI 轻量 JSONL 五大核心字段 + 语义映射

每条调用日志（Span）统一输出单行 JSON，兼顾直观易读与日后无缝接入 OTel 平台：

```json
{
  "trace_id": "trc_v2_01",
  "span_id": "spn_v2_01_s1",
  "step_name": "intent_router",
  "prompt_version": "v2_trimmed_cached",
  "ttft_ms": 190.0,
  "total_ms": 450.0,
  "cached_tokens": 1152,
  "cost_usd": 0.000163,
  "gen_ai.system": "openai_compatible",
  "gen_ai.request.model": "gpt-4o-mini",
  "gen_ai.request.stream": true,
  "gen_ai.usage.input_tokens": 1500,
  "gen_ai.usage.output_tokens": 40,
  "gen_ai.usage.cached_tokens": 1152
}
```

> **缓存计费公式**：`uncached_input = max(0, input_tokens - cached_tokens)`，未命中部分按标准输入单价计费，`cached_tokens` 按模型缓存折扣单价计费（如 `gpt-4o-mini` 半价、`deepseek-chat` 约 2.6 折）。

---

## 5. 动手步骤与验收命令

1. **运行基线看盲区**：
   ```bash
   python3 labs/S6-M08-otel-latency-cost/verify.py
   ```
2. **修复流式 Span 记录与缓存计费 (`record_streaming_span` / `compute_span_cost`)**：要求 `stream=True` 时从首个非空流式分片到达时刻提取真实 `ttft_ms`（满足 `0 < ttft_ms < total_ms`），写入上述核心字段与 `gen_ai.*` 标准属性，并按折扣公式精确计算 `cost_usd`。
3. **打通多步 `trace_id` 串联与单笔对账 (`run_traced_workflow` / `reconstruct_trace_bill`)**：同一次用户请求的多步调用透传同一个 `trace_id`，支持按 `trace_id` 一键拼出完整步骤明细、首步 `ttft_ms`、总耗时与总花费。
4. **补全 P50/P95 延迟与缓存占比统计 (`summarize_ab_logs`)**：对 `fixtures/ab_stream_traces.jsonl` 按 `(prompt_version, model, step_name)` 与版本维度汇总 P50/P95 `ttft_ms`、`cached_tokens` 命中占比及精简上下文后的提速幅度。
5. **运行验收闭环**：
   ```bash
   # 验收你的当前修改
   python3 labs/S6-M08-otel-latency-cost/verify.py

   # 验证标准参考答案
   python3 labs/S6-M08-otel-latency-cost/verify.py --solution
   ```

> 💡 **免代码平替方案**：零代码阶段可在飞书表格/Excel 固定 6 列标准表头（`trace_id`、`prompt_version`、`model`、`ttft_ms`、`total_ms`、`cached_tokens`），每次调优前后各登记 10 条请求，用数据透视表直接对比均值与中位数。
