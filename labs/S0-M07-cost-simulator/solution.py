#!/usr/bin/env python3
"""S0-M07 Solution：80 行级纯 Python 批处理成本模拟器标准参考实现。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import pathlib

LAB_DIR = pathlib.Path(__file__).resolve().parent
FIXTURE_PATH = LAB_DIR / "fixtures" / "pricing_scenarios.json"


@dataclass(frozen=True)
class ModelPricing:
  name: str
  input_per_1m: float
  cached_input_per_1m: float
  output_per_1m: float
  cache_min_prefix_tokens: int = 1024
  batch_discount_factor: float = 0.5
  stack_batch_on_cache: bool = False


@dataclass(frozen=True)
class WorkloadSpec:
  task_count: int = 2000
  prefix_tokens: int = 1200
  variable_input_tokens: int = 250
  output_tokens: int = 300
  compact_output_ratio: float = 0.5


@dataclass(frozen=True)
class StrategyQuote:
  strategy_id: str
  label: str
  cache_triggered: bool
  input_cost_usd: float
  output_cost_usd: float
  cache_savings_usd: float
  total_cost_usd: float


def load_scenarios() -> dict:
  return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def simulate_all_strategies(workload: WorkloadSpec, pricing: ModelPricing) -> list[StrategyQuote]:
  """对比 A(全价实时) / B(精简输出) / C(前缀缓存) / D(前缀缓存+Batch半价) 四种策略账单。"""
  n = workload.task_count
  prefix_m = (n * workload.prefix_tokens) / 1_000_000.0
  var_in_m = (n * workload.variable_input_tokens) / 1_000_000.0
  full_out_m = (n * workload.output_tokens) / 1_000_000.0
  compact_out_m = full_out_m * workload.compact_output_ratio
  cache_hit = workload.prefix_tokens >= pricing.cache_min_prefix_tokens

  a_in = (prefix_m + var_in_m) * pricing.input_per_1m
  a_out = full_out_m * pricing.output_per_1m
  b_out = compact_out_m * pricing.output_per_1m

  c_prefix_rate = pricing.cached_input_per_1m if cache_hit else pricing.input_per_1m
  c_in = prefix_m * c_prefix_rate + var_in_m * pricing.input_per_1m
  c_save = prefix_m * (pricing.input_per_1m - c_prefix_rate) if cache_hit else 0.0

  batch_in_rate = pricing.input_per_1m * pricing.batch_discount_factor
  batch_out_rate = pricing.output_per_1m * pricing.batch_discount_factor
  if cache_hit:
    d_prefix_rate = (
        pricing.cached_input_per_1m * pricing.batch_discount_factor
        if pricing.stack_batch_on_cache
        else min(pricing.cached_input_per_1m, batch_in_rate)
    )
    d_save = prefix_m * max(0.0, batch_in_rate - d_prefix_rate)
  else:
    d_prefix_rate = batch_in_rate
    d_save = 0.0
  d_in = prefix_m * d_prefix_rate + var_in_m * batch_in_rate
  d_out = full_out_m * batch_out_rate

  return [
      StrategyQuote("A_realtime_full", "策略A：实时全价基线", False, round(a_in, 6), round(a_out, 6), 0.0, round(a_in + a_out, 6)),
      StrategyQuote("B_compact_output", "策略B：精简输出与思考", False, round(a_in, 6), round(b_out, 6), 0.0, round(a_in + b_out, 6)),
      StrategyQuote("C_prefix_cache", "策略C：前缀缓存实时调用", cache_hit, round(c_in, 6), round(a_out, 6), round(c_save, 6), round(c_in + a_out, 6)),
      StrategyQuote("D_cache_plus_batch", "策略D：前缀缓存 + Batch 异步半价", cache_hit, round(d_in, 6), round(d_out, 6), round(d_save, 6), round(d_in + d_out, 6)),
  ]


def find_best_quote(quotes: list[StrategyQuote]) -> StrategyQuote:
  return min(quotes, key=lambda q: q.total_cost_usd)


def render_markdown_comparison(
    workload: WorkloadSpec,
    pricing: ModelPricing,
    quotes: list[StrategyQuote] | None = None,
) -> str:
  """输出包含输入费用、输出费用、缓存节省额与总账单的完整 Markdown 对比表。"""
  items = quotes if quotes is not None else simulate_all_strategies(workload, pricing)
  best = find_best_quote(items)
  lines = [
      f"### 模型 `{pricing.name}`（任务数={workload.task_count}, 前缀={workload.prefix_tokens}, 输出={workload.output_tokens}）",
      "| 策略 | 缓存触发 | 输入费用 | 输出费用 | 缓存节省额 | 总账单 |",
      "| --- | --- | --- | --- | --- | --- |",
  ]
  for q in items:
    flag = "是" if q.cache_triggered else "否"
    lines.append(
        f"| {q.label} | {flag} | ${q.input_cost_usd:.4f} | ${q.output_cost_usd:.4f} | ${q.cache_savings_usd:.4f} | ${q.total_cost_usd:.4f} |"
    )
  lines.append(f"\n> 最省钱方案：**{best.label}**（总账单 `${best.total_cost_usd:.4f}`）")
  return "\n".join(lines)


if __name__ == "__main__":
  raw = load_scenarios()
  models = [ModelPricing(**m) for m in raw["models"]]
  by_id = {
      w["scenario_id"]: WorkloadSpec(
          task_count=w["task_count"],
          prefix_tokens=w["prefix_tokens"],
          variable_input_tokens=w["variable_input_tokens"],
          output_tokens=w["output_tokens"],
          compact_output_ratio=w["compact_output_ratio"],
      )
      for w in raw["workloads"]
  }
  for sid in ("under_threshold_800", "cached_verbose_1200", "cached_compact_80"):
    for mp in models:
      print(render_markdown_comparison(by_id[sid], mp))
      print()
