#!/usr/bin/env python3
"""S6-M08 套用 OTel GenAI 拆解首字延迟与缓存账单（Starter 基线版 —— 含典型日志与计费盲区，待重构）。"""

from __future__ import annotations

import json
import pathlib
import sys
import uuid
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

# 每百万 Token 美元单价表（含提示词前缀缓存命中折扣价 cached_input）
PRICE_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "deepseek-chat": {"input": 0.27, "cached_input": 0.07, "output": 1.10},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
}


def compute_span_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
  """计算单步调用美元花费。

  TODO(S6-M08): 当前把全部 input_tokens 按全价计费，忽略了 cached_tokens 的缓存折扣价！
  正确逻辑：uncached_input = max(0, input_tokens - cached_tokens)，分别乘以 input 与 cached_input 单价。
  """
  _ = cached_tokens
  rate = PRICE_PER_1M.get(model, PRICE_PER_1M["gpt-4o-mini"])
  return round((input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000, 6)


def record_streaming_span(
    *,
    trace_id: str,
    step_name: str,
    prompt_version: str,
    model: str,
    stream: bool,
    chunk_timestamps_ms: list[float],
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    input_preview: str = "",
    output_preview: str = "",
) -> dict[str, Any]:
  """构造符合 OTel GenAI 语义约定的结构化 JSONL 日志记录。

  TODO(S6-M08):
  1. 当前未区分首字到达时刻 chunk_timestamps_ms[0] 与完成时刻 chunk_timestamps_ms[-1]，把 total_ms 直接填成了 ttft_ms！
     且未校验 stream=True（未开启流式时无法采集真实首字延迟）。
  2. 补齐五个核心字段（trace_id, prompt_version, ttft_ms, total_ms, cached_tokens）及 OTel GenAI 标准属性：
     gen_ai.system / gen_ai.request.model / gen_ai.request.stream / gen_ai.usage.input_tokens /
     gen_ai.usage.output_tokens / gen_ai.usage.cached_tokens / cost_usd。
  """
  total_ms = round(chunk_timestamps_ms[-1], 2) if chunk_timestamps_ms else 0.0
  return {
      "trace_id": trace_id,
      "step_name": step_name,
      "prompt_version": prompt_version,
      "stream": stream,
      "ttft_ms": total_ms,  # 缺陷：误把总耗时当作首字延迟
      "total_ms": total_ms,
      "cost_usd": compute_span_cost(model, input_tokens, output_tokens, cached_tokens),
      "input_preview": input_preview,
      "output_preview": output_preview,
  }


def run_traced_workflow(
    user_query: str,
    prompt_version: str = "v2_trimmed_cached",
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
  """执行一次两步流式工作流（intent_router -> rag_answer）并返回两步的 Span 列表。

  TODO(S6-M08): 当前每一步都各自随机生成了不同 ID 且硬编码 stream=False，导致多步请求无法串联、也测不出真实 ttft_ms！
  请确保同一次请求的两步共享同一个 trace_id，并开启 stream=True。
  """
  _ = trace_id
  router_out = chat_complete(
      [{"role": "user", "content": f"路由分类：{user_query}"}],
      mock_fn=lambda _m: '{"intent": "billing_faq"}',
  )
  answer_out = chat_complete(
      [{"role": "user", "content": f"回答问题：{user_query}"}],
      mock_fn=lambda _m: "您好，账单明细可在控制台导出。",
  )

  span1 = record_streaming_span(
      trace_id=f"step_{uuid.uuid4().hex[:8]}",  # 缺陷：每步各自生成新 ID，无法串联
      step_name="intent_router",
      prompt_version=prompt_version,
      model="gpt-4o-mini",
      stream=False,  # 缺陷：未开启流式
      chunk_timestamps_ms=[195.0, 310.0, 445.0],
      input_tokens=1500,
      output_tokens=40,
      cached_tokens=1152,
      input_preview=user_query,
      output_preview=router_out,
  )
  span2 = record_streaming_span(
      trace_id=f"step_{uuid.uuid4().hex[:8]}",
      step_name="rag_answer",
      prompt_version=prompt_version,
      model="deepseek-chat",
      stream=False,
      chunk_timestamps_ms=[225.0, 520.0, 840.0],
      input_tokens=2100,
      output_tokens=240,
      cached_tokens=1408,
      input_preview=router_out,
      output_preview=answer_out,
  )
  return [span1, span2]


def reconstruct_trace_bill(spans: list[dict[str, Any]], trace_id: str) -> dict[str, Any]:
  """按唯一 trace_id 串联同一次多步请求的输入输出、首步 ttft_ms、总耗时与总花费。

  TODO(S6-M08): 筛选匹配 trace_id 的所有步骤，汇总 step_count、first_ttft_ms、total_ms、total_cached_tokens 与 total_cost_usd。
  """
  matched = [s for s in spans if s.get("trace_id") == trace_id]
  return {"trace_id": trace_id, "step_count": len(matched), "steps": matched}


def load_jsonl_spans(path: pathlib.Path | None = None) -> list[dict[str, Any]]:
  """加载 JSONL 格式的 Span 日志文件。"""
  target = path or (LAB_DIR / "fixtures" / "ab_stream_traces.jsonl")
  return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize_ab_logs(spans: list[dict[str, Any]]) -> dict[str, Any]:
  """解析日志并统计按版本及 (版本, 模型, 步骤) 分组的 P50/P95 首字延迟与缓存命中占比。

  TODO(S6-M08): 当前只算了一个笼统的平均总耗时，请补齐：
  - by_version: 每个 prompt_version 的 p50_ttft_ms, p95_ttft_ms, p50_total_ms, p95_total_ms, cache_hit_ratio, total_cost_usd
  - by_model_step: 按 (prompt_version, model, step_name) 分组的上述统计项
  - comparison: v2_trimmed_cached 相对 v1_bloated_ctx 的 ttft_speedup_pct 与 cost_saving_pct
  """
  avg_total = sum(float(s.get("total_ms", 0.0)) for s in spans) / max(1, len(spans))
  return {"avg_total_ms": round(avg_total, 2)}


def format_ab_report(summary: dict[str, Any]) -> str:
  """TODO(S6-M08): 打印包含 P50/P95 首字延迟、cached_tokens 命中率与精简上下文提速结论的对账表。"""
  return json.dumps(summary, ensure_ascii=False)


if __name__ == "__main__":
  logs = load_jsonl_spans()
  print(format_ab_report(summarize_ab_logs(logs)))
