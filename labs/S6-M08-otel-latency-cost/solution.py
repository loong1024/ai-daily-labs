#!/usr/bin/env python3
"""S6-M08 套用 OTel GenAI 拆解首字延迟与缓存账单（Solution 标准参考实现）。"""

from __future__ import annotations

from collections import defaultdict
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

PRICE_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "deepseek-chat": {"input": 0.27, "cached_input": 0.07, "output": 1.10},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
}


def percentile(values: list[float], pct: float) -> float:
  """计算排序序列的线性插值分位数（P50 / P95）。"""
  if not values:
    return 0.0
  ordered = sorted(float(v) for v in values)
  if len(ordered) == 1:
    return round(ordered[0], 2)
  pos = (len(ordered) - 1) * (pct / 100.0)
  lo = int(pos)
  hi = min(lo + 1, len(ordered) - 1)
  frac = pos - lo
  return round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac, 2)


def compute_span_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
  """区分未命中全价输入与命中前缀缓存折扣输入，精确计算单步美元成本。"""
  rate = PRICE_PER_1M.get(model, PRICE_PER_1M["gpt-4o-mini"])
  safe_cached = max(0, min(int(cached_tokens), int(input_tokens)))
  uncached_input = max(0, int(input_tokens) - safe_cached)
  cost = (
      uncached_input * rate["input"]
      + safe_cached * rate["cached_input"]
      + max(0, int(output_tokens)) * rate["output"]
  ) / 1_000_000
  return round(cost, 6)


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
  """按 OpenTelemetry GenAI 语义约定构造流式 Span JSONL 对象。"""
  if not stream:
    raise ValueError("采集真实首字延迟 ttft_ms 必须开启流式调用 (stream=True)。")
  if not chunk_timestamps_ms:
    raise ValueError("chunk_timestamps_ms 不能为空。")

  ttft_ms = round(float(chunk_timestamps_ms[0]), 2)
  total_ms = round(float(chunk_timestamps_ms[-1]), 2)
  if ttft_ms <= 0 or total_ms < ttft_ms:
    raise ValueError(f"非法流式时间戳：ttft_ms={ttft_ms}, total_ms={total_ms}")

  safe_cached = max(0, min(int(cached_tokens), int(input_tokens)))
  cost_usd = compute_span_cost(model, input_tokens, output_tokens, safe_cached)

  return {
      "trace_id": trace_id,
      "span_id": f"spn_{uuid.uuid4().hex[:8]}",
      "step_name": step_name,
      "prompt_version": prompt_version,
      "ttft_ms": ttft_ms,
      "total_ms": total_ms,
      "cached_tokens": safe_cached,
      "cost_usd": cost_usd,
      "input_preview": input_preview,
      "output_preview": output_preview,
      "gen_ai.system": "openai_compatible",
      "gen_ai.request.model": model,
      "gen_ai.request.stream": True,
      "gen_ai.usage.input_tokens": int(input_tokens),
      "gen_ai.usage.output_tokens": int(output_tokens),
      "gen_ai.usage.cached_tokens": safe_cached,
  }


def run_traced_workflow(
    user_query: str,
    prompt_version: str = "v2_trimmed_cached",
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
  """执行两步流式请求（意图路由 -> 知识库生成），全链路透传唯一 trace_id。"""
  shared_trace_id = trace_id or f"trc_{uuid.uuid4().hex[:10]}"

  router_out = chat_complete(
      [{"role": "user", "content": f"路由分类：{user_query}"}],
      mock_fn=lambda _m: '{"intent": "billing_faq"}',
      response_json=True,
  )
  answer_out = chat_complete(
      [{"role": "user", "content": f"根据路由 {router_out} 回答：{user_query}"}],
      mock_fn=lambda _m: "您好，您可以在控制台「费用中心-账单导出」下载按 trace_id 聚合的消耗明细。",
  )

  is_trimmed = prompt_version == "v2_trimmed_cached"
  span_router = record_streaming_span(
      trace_id=shared_trace_id,
      step_name="intent_router",
      prompt_version=prompt_version,
      model="gpt-4o-mini",
      stream=True,
      chunk_timestamps_ms=[195.0, 310.0, 445.0] if is_trimmed else [780.0, 990.0, 1220.0],
      input_tokens=1500 if is_trimmed else 5800,
      output_tokens=40,
      cached_tokens=1152 if is_trimmed else 256,
      input_preview=user_query,
      output_preview=router_out,
  )
  span_answer = record_streaming_span(
      trace_id=shared_trace_id,
      step_name="rag_answer",
      prompt_version=prompt_version,
      model="deepseek-chat",
      stream=True,
      chunk_timestamps_ms=[225.0, 520.0, 840.0] if is_trimmed else [870.0, 1450.0, 1950.0],
      input_tokens=2100 if is_trimmed else 6600,
      output_tokens=240,
      cached_tokens=1408 if is_trimmed else 256,
      input_preview=router_out,
      output_preview=answer_out,
  )
  return [span_router, span_answer]


def reconstruct_trace_bill(spans: list[dict[str, Any]], trace_id: str) -> dict[str, Any]:
  """凭唯一 trace_id 串起单次请求所有步骤的输入输出、首字延迟、总耗时与完整花费账单。"""
  matched = [s for s in spans if s.get("trace_id") == trace_id]
  if not matched:
    return {
        "trace_id": trace_id,
        "step_count": 0,
        "steps": [],
        "first_ttft_ms": 0.0,
        "total_ms": 0.0,
        "total_input_tokens": 0,
        "total_cached_tokens": 0,
        "total_cost_usd": 0.0,
    }

  total_in = sum(int(s.get("gen_ai.usage.input_tokens", 0)) for s in matched)
  total_cached = sum(int(s.get("cached_tokens", s.get("gen_ai.usage.cached_tokens", 0))) for s in matched)
  total_ms = sum(float(s.get("total_ms", 0.0)) for s in matched)
  total_cost = sum(float(s.get("cost_usd", 0.0)) for s in matched)

  return {
      "trace_id": trace_id,
      "step_count": len(matched),
      "steps": matched,
      "first_ttft_ms": round(float(matched[0].get("ttft_ms", 0.0)), 2),
      "total_ms": round(total_ms, 2),
      "total_input_tokens": total_in,
      "total_cached_tokens": total_cached,
      "total_cost_usd": round(total_cost, 6),
  }


def load_jsonl_spans(path: pathlib.Path | None = None) -> list[dict[str, Any]]:
  """读取本地 JSONL Span 日志文件。"""
  target = path or (LAB_DIR / "fixtures" / "ab_stream_traces.jsonl")
  return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def _calc_group_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
  ttfts = [float(x["ttft_ms"]) for x in items]
  totals = [float(x["total_ms"]) for x in items]
  in_toks = sum(int(x.get("gen_ai.usage.input_tokens", 0)) for x in items)
  cached_toks = sum(int(x.get("cached_tokens", x.get("gen_ai.usage.cached_tokens", 0))) for x in items)
  cost_sum = sum(float(x.get("cost_usd", 0.0)) for x in items)
  return {
      "count": len(items),
      "p50_ttft_ms": percentile(ttfts, 50),
      "p95_ttft_ms": percentile(ttfts, 95),
      "p50_total_ms": percentile(totals, 50),
      "p95_total_ms": percentile(totals, 95),
      "cache_hit_ratio": round(cached_toks / in_toks, 4) if in_toks else 0.0,
      "total_cost_usd": round(cost_sum, 6),
  }


def summarize_ab_logs(spans: list[dict[str, Any]]) -> dict[str, Any]:
  """20 行核心统计逻辑：按版本及 (版本, 模型, 步骤) 汇总 P50/P95 延迟、缓存命中率与提速降本幅度。"""
  by_ver_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
  by_ms_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

  for s in spans:
    ver = str(s.get("prompt_version") or "unknown")
    model = str(s.get("gen_ai.request.model") or "unknown")
    step = str(s.get("step_name") or "unknown")
    by_ver_buckets[ver].append(s)
    by_ms_buckets[f"{ver}|{model}|{step}"].append(s)

  by_version = {k: _calc_group_stats(v) for k, v in sorted(by_ver_buckets.items())}
  by_model_step = {k: _calc_group_stats(v) for k, v in sorted(by_ms_buckets.items())}

  v1 = by_version.get("v1_bloated_ctx", {})
  v2 = by_version.get("v2_trimmed_cached", {})
  v1_p50 = float(v1.get("p50_ttft_ms") or 0.0)
  v2_p50 = float(v2.get("p50_ttft_ms") or 0.0)
  v1_cost = float(v1.get("total_cost_usd") or 0.0)
  v2_cost = float(v2.get("total_cost_usd") or 0.0)

  comparison = {
      "ttft_speedup_pct": round((v1_p50 - v2_p50) / v1_p50 * 100.0, 2) if v1_p50 else 0.0,
      "cost_saving_pct": round((v1_cost - v2_cost) / v1_cost * 100.0, 2) if v1_cost else 0.0,
  }
  return {
      "by_version": by_version,
      "by_model_step": by_model_step,
      "comparison": comparison,
  }


def format_ab_report(summary: dict[str, Any]) -> str:
  """打印按模型/步骤分组的 P50/P95 延迟、cached_tokens 命中率及上下文精简前后对比表。"""
  lines = [
      "=== OTel GenAI 本地日志对账：按版本 × 模型 × 步骤分组统计 ===",
      f"{'版本 | 模型 | 步骤':<46} | {'P50 TTFT':<10} | {'P95 TTFT':<10} | {'P50 Total':<10} | {'缓存命中率':<10} | {'花费($)':<10}",
      "-" * 112,
  ]
  for key, st in summary.get("by_model_step", {}).items():
    lines.append(
        f"{key:<46} | "
        f"{st['p50_ttft_ms']:>7.1f} ms | "
        f"{st['p95_ttft_ms']:>7.1f} ms | "
        f"{st['p50_total_ms']:>7.1f} ms | "
        f"{st['cache_hit_ratio']*100:>8.1f}% | "
        f"${st['total_cost_usd']:.6f}"
    )

  comp = summary.get("comparison", {})
  v1 = summary.get("by_version", {}).get("v1_bloated_ctx", {})
  v2 = summary.get("by_version", {}).get("v2_trimmed_cached", {})
  lines.extend([
      "-" * 112,
      (
          f"版本汇总对比：v1_bloated_ctx (P50 TTFT={v1.get('p50_ttft_ms', 0):.1f}ms, 缓存率={v1.get('cache_hit_ratio', 0)*100:.1f}%) "
          f"-> v2_trimmed_cached (P50 TTFT={v2.get('p50_ttft_ms', 0):.1f}ms, 缓存率={v2.get('cache_hit_ratio', 0)*100:.1f}%)"
      ),
      (
          f"调优收益：精简冗余上下文并固定缓存前缀后，首字延迟 P50 提速 {comp.get('ttft_speedup_pct', 0):.1f}%，"
          f"总花费降低 {comp.get('cost_saving_pct', 0):.1f}%。"
      ),
  ])
  return "\n".join(lines)


if __name__ == "__main__":
  spans = load_jsonl_spans()
  bill = reconstruct_trace_bill(spans, "trc_v2_01")
  print(f"单笔请求对账示例 trace_id={bill['trace_id']}: 共 {bill['step_count']} 步, 首字={bill['first_ttft_ms']}ms, 总耗时={bill['total_ms']}ms, 总花费=${bill['total_cost_usd']:.6f}\n")
  print(format_ab_report(summarize_ab_logs(spans)))
