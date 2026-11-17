#!/usr/bin/env python3
"""S0-M07 Starter：千条反馈与长文批处理成本模拟器。

请根据 README.md 中的四种策略公式修复下方 TODO 逻辑，运行 python3 verify.py 验收。
"""

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
  """计算 A/B/C/D 四种批处理策略在给定任务规模与模型单价下的精确账单。"""
  n = workload.task_count
  prefix_m = (n * workload.prefix_tokens) / 1_000_000.0
  var_in_m = (n * workload.variable_input_tokens) / 1_000_000.0
  full_out_m = (n * workload.output_tokens) / 1_000_000.0

  # TODO 1: 修复输出计费单价错误（此处误把高价 output_per_1m 按 input_per_1m 计算了！）
  a_in = (prefix_m + var_in_m) * pricing.input_per_1m
  a_out = full_out_m * pricing.input_per_1m

  # TODO 2: 实现策略 B（按 compact_output_ratio 压缩输出长度并按 output_per_1m 计费）

  # TODO 3: 加入 prefix_tokens >= pricing.cache_min_prefix_tokens (默认 1024) 的缓存门槛判断！
  # 当前基线错误地无条件按缓存折扣价计算，导致 800 token 前缀误判省钱。
  c_in = prefix_m * pricing.cached_input_per_1m + var_in_m * pricing.input_per_1m
  c_out = full_out_m * pricing.output_per_1m
  c_save = prefix_m * (pricing.input_per_1m - pricing.cached_input_per_1m)

  # TODO 4: 实现策略 D（前缀缓存 + Batch API 异步折扣通道，支持 stack_batch_on_cache 参数化叠加规则）
  return [
      StrategyQuote(
          "A_realtime_full",
          "策略A：实时全价基线",
          False,
          round(a_in, 6),
          round(a_out, 6),
          0.0,
          round(a_in + a_out, 6),
      ),
      StrategyQuote(
          "C_prefix_cache",
          "策略C：前缀缓存实时调用",
          True,
          round(c_in, 6),
          round(c_out, 6),
          round(c_save, 6),
          round(c_in + c_out, 6),
      ),
  ]


def find_best_quote(quotes: list[StrategyQuote]) -> StrategyQuote:
  return min(quotes, key=lambda q: q.total_cost_usd)


def render_markdown_comparison(
    workload: WorkloadSpec,
    pricing: ModelPricing,
    quotes: list[StrategyQuote] | None = None,
) -> str:
  """渲染包含输入费用、输出费用、缓存节省额与总账单的 Markdown 对比表。"""
  # TODO 5: 补全包含「策略 | 缓存触发 | 输入费用 | 输出费用 | 缓存节省 | 总账单」六列的完整 Markdown 表格
  items = quotes if quotes is not None else simulate_all_strategies(workload, pricing)
  lines = [f"### 模型 `{pricing.name}` 账单简表", "| 策略 | 总账单 |", "| --- | --- |"]
  for q in items:
    lines.append(f"| {q.label} | ${q.total_cost_usd:.4f} |")
  return "\n".join(lines)


if __name__ == "__main__":
  print("当前为 starter.py 基线版，请运行 python3 verify.py 查看待修复清单。")
