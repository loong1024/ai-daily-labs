#!/usr/bin/env python3
"""统一大模型网关封装（Starter 朴素基线版 —— 含多处工程隐患待改进）。"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterator


class ProviderError(Exception):
  """模拟上游模型供应商报错（如 400 / 429 / 503 / timeout）。"""

  def __init__(self, status_code: int, message: str = "") -> None:
    super().__init__(f"HTTP {status_code}: {message}")
    self.status_code = status_code


class StreamInterruptedError(Exception):
  """流式响应在已发出部分 chunk 后中断（严禁静默从头重拼）。"""


class BudgetExceededError(Exception):
  """触发单日预算硬封顶拦截非核心任务。"""


TransportFn = Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
StreamTransportFn = Callable[[str, list[dict[str, str]], dict[str, Any]], Iterator[str]]


class LLMGateway:
  """统一网关入口（Starter 版：全量直连最贵主模型，缺路由/缓存/熔断/并发/预算控制）。"""

  def __init__(
      self,
      config: dict[str, Any],
      transport: TransportFn | None = None,
      stream_transport: StreamTransportFn | None = None,
  ) -> None:
    self.config = config
    self.transport = transport
    self.stream_transport = stream_transport
    self.daily_spend_usd: float = 0.0
    self.logs: list[dict[str, Any]] = []
    self.alerts: list[str] = []

  def _calc_cost(self, model_name: str, in_tokens: int, out_tokens: int) -> float:
    for m in self.config["models"].values():
      if m["name"] == model_name:
        return round(
            (in_tokens / 1000.0) * m["input_cost_per_1k"]
            + (out_tokens / 1000.0) * m["output_cost_per_1k"],
            6,
        )
    return 0.0

  def llm_call(
      self,
      task: str,
      messages: list[dict[str, str]],
      *,
      prompt_version: str = "v1",
      user_id: str | None = None,
      no_cache: bool = False,
      **opts: Any,
  ) -> dict[str, Any]:
    """统一非流式调用入口。

    TODO 改进清单：
    1. 路由与预算：按 task 配置选择 small/large 模型；超过软上限将非关键任务降级 small，超过硬上限拦截非关键任务并记告警。
    2. 缓存：对 cacheable=True 任务用 SHA-256(model + prompt_version + user_id + messages) 缓存结果；实时任务（cacheable=False）禁止缓存。
    3. 可靠性：仅对 429/5xx/timeout 指数退避重试（跳过 400）；连续失败达阈值触发熔断器直接切 fallback 备用模型。
    4. 结构化日志：完整记录 task、model、prompt_version、input_tokens、output_tokens、cost_usd、latency_ms、cache_hit、retries、error_type。
    """
    del prompt_version, user_id, no_cache
    large_model = self.config["models"]["large"]["name"]
    if self.transport is None:
      raise RuntimeError("未提供 transport")
    resp = self.transport(large_model, messages, opts)
    in_tok = int(resp.get("input_tokens", 200))
    out_tok = int(resp.get("output_tokens", 60))
    cost = self._calc_cost(large_model, in_tok, out_tok)
    self.daily_spend_usd = round(self.daily_spend_usd + cost, 6)
    self.logs.append({"task": task, "model": large_model, "cost_usd": cost})
    return {
        "content": resp.get("content", ""),
        "model": large_model,
        "cache_hit": False,
        "cost_usd": cost,
        "retries": 0,
    }

  def llm_stream(
      self,
      task: str,
      messages: list[dict[str, str]],
      **opts: Any,
  ) -> Iterator[str]:
    """流式输出入口。

    TODO：仅当主模型在发出首个 chunk 之前报错时，自动切换至 fallback 模型兜底；
    若已经发出 >= 1 个 chunk 后中断，必须抛出 StreamInterruptedError，绝不能重头再发一遍。
    """
    del task
    large_model = self.config["models"]["large"]["name"]
    if self.stream_transport is None:
      raise RuntimeError("未提供 stream_transport")
    for chunk in self.stream_transport(large_model, messages, opts):
      yield chunk

  def batch_concurrent_calls(
      self, calls: list[dict[str, Any]], max_workers: int = 4
  ) -> list[dict[str, Any]]:
    """批量独立子请求执行（TODO：改为 ThreadPoolExecutor 并发执行以降低整体延迟）。"""
    del max_workers
    results: list[dict[str, Any]] = []
    for item in calls:
      results.append(
          self.llm_call(
              item["task"],
              item["messages"],
              prompt_version=item.get("prompt_version", "v1"),
              **item.get("opts", {}),
          )
      )
    return results


def _p95(values: list[float]) -> float:
  if not values:
    return 0.0
  ordered = sorted(values)
  return float(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)])


def run_replay_benchmark(
    replay_items: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
  """在 50 条混合重放流量上对比裸调与当前网关效果。"""
  gw = LLMGateway(config)
  del gw
  return {
      "total_requests": len(replay_items),
      "naive": {"success_rate": 0.0, "total_cost_usd": 0.0, "p95_latency_ms": 0.0},
      "gateway": {"success_rate": 0.0, "total_cost_usd": 0.0, "p95_latency_ms": 0.0},
      "cost_saving_ratio": 0.0,
  }
