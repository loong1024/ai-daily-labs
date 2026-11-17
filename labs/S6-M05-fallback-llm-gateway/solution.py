#!/usr/bin/env python3
"""统一大模型网关封装（Solution 标准参考实现）。

生产环境可将 `default_transport` 直接替换为 `litellm.completion`；
本实现内置零依赖可插拔传输层与 `shared.aid_lab.chat_complete` 桥接，支持毫秒级确定性压测验收。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import pathlib
import random
import sys
import threading
import time
from typing import Any, Callable, Iterator

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


class ProviderError(Exception):
  """上游供应商调用异常（携带 HTTP 状态码或超时标识）。"""

  def __init__(self, status_code: int, message: str = "", error_type: str = "") -> None:
    super().__init__(f"HTTP {status_code}: {message}")
    self.status_code = status_code
    self.error_type = error_type or f"http_{status_code}"


class StreamInterruptedError(Exception):
  """流式调用在已向客户端输出部分 chunk 后断流，禁止静默从头拼接。"""


class BudgetExceededError(Exception):
  """单日累计费用触达硬上限，暂停非关键任务。"""


TransportFn = Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
StreamTransportFn = Callable[[str, list[dict[str, str]], dict[str, Any]], Iterator[str]]

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
  if isinstance(exc, TimeoutError):
    return True
  if isinstance(exc, ProviderError):
    return exc.status_code in RETRYABLE_STATUS_CODES or exc.error_type == "timeout"
  return False


class LLMGateway:
  """统一网关：按任务路由 + 确定性缓存 + 指数退避重试 + 熔断切备用 + 流式首包边界 + 并发 + 日预算封顶。"""

  def __init__(
      self,
      config: dict[str, Any],
      transport: TransportFn | None = None,
      stream_transport: StreamTransportFn | None = None,
  ) -> None:
    self.config = config
    self.transport = transport or self._default_transport
    self.stream_transport = stream_transport
    self.daily_spend_usd: float = 0.0
    self.logs: list[dict[str, Any]] = []
    self.alerts: list[str] = []

    self._cache: dict[str, dict[str, Any]] = {}
    self._lock = threading.Lock()
    self._consecutive_failures: dict[str, int] = {}
    self._circuit_open_until: dict[str, float] = {}

  def _default_transport(
      self, model_name: str, messages: list[dict[str, str]], opts: dict[str, Any]
  ) -> dict[str, Any]:
    text = chat_complete(
        messages,
        mock_fn=lambda msgs: f"[{model_name}] OK: {msgs[-1].get('content', '')[:32]}",
    )
    return {
        "content": text,
        "input_tokens": int(opts.get("est_in_tokens", 200)),
        "output_tokens": int(opts.get("est_out_tokens", 60)),
        "simulated_latency_ms": self._model_meta(model_name)["simulated_latency_ms"],
    }

  def _model_meta(self, model_name: str) -> dict[str, Any]:
    for meta in self.config["models"].values():
      if meta["name"] == model_name:
        return meta
    return {"name": model_name, "input_cost_per_1k": 0.001, "output_cost_per_1k": 0.002, "simulated_latency_ms": 300}

  def _calc_cost(self, model_name: str, in_tokens: int, out_tokens: int) -> float:
    meta = self._model_meta(model_name)
    return round(
        (in_tokens / 1000.0) * meta["input_cost_per_1k"]
        + (out_tokens / 1000.0) * meta["output_cost_per_1k"],
        6,
    )

  def _make_cache_key(
      self,
      model_name: str,
      prompt_version: str,
      messages: list[dict[str, str]],
      user_id: str | None,
  ) -> str:
    canonical = json.dumps(
        {
            "model": model_name,
            "prompt_version": prompt_version,
            "user_id": user_id or "",
            "messages": messages,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

  def _is_circuit_open(self, model_name: str) -> bool:
    with self._lock:
      until = self._circuit_open_until.get(model_name, 0.0)
      if until > time.monotonic():
        return True
      if model_name in self._circuit_open_until:
        self._circuit_open_until.pop(model_name, None)
        self._consecutive_failures[model_name] = 0
      return False

  def _record_success(self, model_name: str) -> None:
    with self._lock:
      self._consecutive_failures[model_name] = 0
      self._circuit_open_until.pop(model_name, None)

  def _record_failure(self, model_name: str) -> bool:
    """记录一次上游失败；若触发熔断阈值则返回 True。"""
    rel = self.config["reliability"]
    threshold = int(rel.get("circuit_failure_threshold", 3))
    cooldown = float(rel.get("circuit_cooldown_sec", 30.0))
    with self._lock:
      cnt = self._consecutive_failures.get(model_name, 0) + 1
      self._consecutive_failures[model_name] = cnt
      if cnt >= threshold:
        self._circuit_open_until[model_name] = time.monotonic() + cooldown
        return True
      return False

  def _select_route_and_check_budget(self, task: str) -> tuple[str, dict[str, Any], str]:
    task_cfg = self.config["tasks"].get(
        task, {"tier": "large", "cacheable": False, "critical": False}
    )
    tier = task_cfg.get("tier", "large")
    is_critical = bool(task_cfg.get("critical", False))
    budget_cfg = self.config["budget"]
    soft_limit = float(budget_cfg["soft_limit_usd"])
    hard_limit = float(budget_cfg["hard_limit_usd"])

    with self._lock:
      current_spend = self.daily_spend_usd

    budget_action = "normal"
    if current_spend >= hard_limit and not is_critical:
      alert_msg = f"[BUDGET_HARD_STOP] task={task} 暂停：当日累计 ${current_spend:.4f} 已达硬上限 ${hard_limit:.4f}"
      with self._lock:
        self.alerts.append(alert_msg)
      raise BudgetExceededError(alert_msg)

    if current_spend >= soft_limit and not is_critical and tier == "large":
      tier = "small"
      budget_action = "downgraded_to_small"
      with self._lock:
        self.alerts.append(
            f"[BUDGET_SOFT_DOWNGRADE] task={task} 自动降级为 small（当前累计 ${current_spend:.4f} >= 软上限 ${soft_limit:.4f}）"
        )

    primary_model = self.config["models"][tier]["name"]
    return primary_model, task_cfg, budget_action

  def _append_log(self, entry: dict[str, Any]) -> None:
    with self._lock:
      self.logs.append(entry)

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
    """统一网关调用入口。"""
    t0 = time.perf_counter()
    try:
      primary_model, task_cfg, budget_action = self._select_route_and_check_budget(task)
    except BudgetExceededError:
      self._append_log({
          "task": task,
          "model": "blocked",
          "prompt_version": prompt_version,
          "input_tokens": 0,
          "output_tokens": 0,
          "cost_usd": 0.0,
          "latency_ms": 1.0,
          "cache_hit": False,
          "retries": 0,
          "error_type": "budget_hard_limit",
          "budget_action": "hard_blocked",
      })
      raise

    cache_allowed = bool(task_cfg.get("cacheable", False)) and not no_cache
    cache_key = (
        self._make_cache_key(primary_model, prompt_version, messages, user_id)
        if cache_allowed
        else ""
    )
    if cache_allowed:
      with self._lock:
        cached = self._cache.get(cache_key)
      if cached is not None:
        self._append_log({
            "task": task,
            "model": cached["model"],
            "prompt_version": prompt_version,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": 2.0,
            "cache_hit": True,
            "retries": 0,
            "error_type": None,
            "budget_action": budget_action,
        })
        return {
            "content": cached["content"],
            "model": cached["model"],
            "cache_hit": True,
            "cost_usd": 0.0,
            "retries": 0,
            "latency_ms": 2.0,
            "budget_action": budget_action,
        }

    rel = self.config["reliability"]
    max_retries = int(rel.get("max_retries", 2))
    base_backoff = float(rel.get("base_backoff_sec", 0.002))
    fallback_model = self.config["models"]["fallback"]["name"]

    retries_used = 0
    last_error_type: str | None = None
    circuit_short_circuit = False

    candidate_chain: list[tuple[str, int]] = []
    if self._is_circuit_open(primary_model) and primary_model != fallback_model:
      circuit_short_circuit = True
      candidate_chain.append((fallback_model, max_retries))
    else:
      candidate_chain.append((primary_model, max_retries))
      if fallback_model != primary_model:
        candidate_chain.append((fallback_model, 1))

    sim_extra_latency_ms = 0.0
    for idx, (model_name, model_retries) in enumerate(candidate_chain):
      max_attempts = 1 + model_retries
      for attempt in range(max_attempts):
        try:
          resp = self.transport(model_name, messages, opts)
          self._record_success(model_name)
          in_tok = int(resp.get("input_tokens", opts.get("est_in_tokens", 200)))
          out_tok = int(resp.get("output_tokens", opts.get("est_out_tokens", 60)))
          cost = self._calc_cost(model_name, in_tok, out_tok)

          with self._lock:
            self.daily_spend_usd = round(self.daily_spend_usd + cost, 6)
            if cache_allowed:
              self._cache[cache_key] = {
                  "content": resp.get("content", ""),
                  "model": model_name,
              }

          measured_ms = (time.perf_counter() - t0) * 1000.0
          sim_ms = float(
              resp.get(
                  "simulated_latency_ms",
                  self._model_meta(model_name)["simulated_latency_ms"],
              )
          ) + sim_extra_latency_ms
          effective_latency_ms = round(max(measured_ms, sim_ms), 2)

          self._append_log({
              "task": task,
              "model": model_name,
              "prompt_version": prompt_version,
              "input_tokens": in_tok,
              "output_tokens": out_tok,
              "cost_usd": cost,
              "latency_ms": effective_latency_ms,
              "cache_hit": False,
              "retries": retries_used,
              "circuit_short_circuit": circuit_short_circuit,
              "error_type": last_error_type,
              "budget_action": budget_action,
          })
          return {
              "content": resp.get("content", ""),
              "model": model_name,
              "cache_hit": False,
              "cost_usd": cost,
              "retries": retries_used,
              "circuit_short_circuit": circuit_short_circuit,
              "latency_ms": effective_latency_ms,
              "budget_action": budget_action,
          }
        except Exception as exc:
          last_error_type = (
              exc.error_type if isinstance(exc, ProviderError) else type(exc).__name__
          )
          if not _is_retryable(exc):
            self._append_log({
                "task": task,
                "model": model_name,
                "prompt_version": prompt_version,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "cache_hit": False,
                "retries": retries_used,
                "error_type": last_error_type,
                "budget_action": budget_action,
            })
            raise

          sim_extra_latency_ms += 120.0
          tripped = self._record_failure(model_name)
          if tripped and idx == 0 and len(candidate_chain) > 1:
            break
          if attempt + 1 < max_attempts:
            retries_used += 1
            sleep_sec = base_backoff * (2**attempt) * random.uniform(0.8, 1.2)
            time.sleep(sleep_sec)

    raise ProviderError(503, f"主备模型均不可用（last_error={last_error_type}）", last_error_type or "exhausted")

  def llm_stream(
      self,
      task: str,
      messages: list[dict[str, str]],
      **opts: Any,
  ) -> Iterator[str]:
    """流式透传调用：仅在未发出首个 chunk 前允许切备用模型重试；半截断流抛出 StreamInterruptedError。"""
    if self.stream_transport is None:
      raise RuntimeError("未配置 stream_transport")

    primary_model, _, _ = self._select_route_and_check_budget(task)
    fallback_model = self.config["models"]["fallback"]["name"]

    models_to_try = (
        [fallback_model]
        if (self._is_circuit_open(primary_model) and primary_model != fallback_model)
        else [primary_model, fallback_model]
    )

    for idx, model_name in enumerate(models_to_try):
      emitted_chunks = 0
      try:
        for chunk in self.stream_transport(model_name, messages, opts):
          emitted_chunks += 1
          yield chunk
        self._record_success(model_name)
        return
      except Exception as exc:
        if emitted_chunks > 0:
          raise StreamInterruptedError(
              f"模型 {model_name} 在已发出 {emitted_chunks} 个 chunk 后断流，禁止重头拼接：{exc}"
          ) from exc
        self._record_failure(model_name)
        if not _is_retryable(exc) or idx + 1 >= len(models_to_try):
          raise

  def batch_concurrent_calls(
      self, calls: list[dict[str, Any]], max_workers: int = 4
  ) -> list[dict[str, Any]]:
    """使用线程池并发执行多路独立子请求，总耗时逼近最慢单路。"""
    if not calls:
      return []
    workers = max(1, min(max_workers, len(calls)))

    def _invoke(item: dict[str, Any]) -> dict[str, Any]:
      return self.llm_call(
          item["task"],
          item["messages"],
          prompt_version=item.get("prompt_version", "v1"),
          user_id=item.get("user_id"),
          no_cache=bool(item.get("no_cache", False)),
          **item.get("opts", {}),
      )

    with ThreadPoolExecutor(max_workers=workers) as pool:
      return list(pool.map(_invoke, calls))


def _p95(values: list[float]) -> float:
  if not values:
    return 0.0
  ordered = sorted(values)
  return float(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)])


def run_replay_benchmark(
    replay_items: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
  """在同一批 50 条混合重放集上对比“裸调主模型”与“开启统一网关”的效果。"""
  bench_cfg = json.loads(json.dumps(config))
  bench_cfg["budget"]["soft_limit_usd"] = 10.0
  bench_cfg["budget"]["hard_limit_usd"] = 20.0

  large_meta = bench_cfg["models"]["large"]
  large_name = large_meta["name"]

  naive_ok = 0
  naive_cost = 0.0
  naive_latencies: list[float] = []
  for item in replay_items:
    fault = item.get("fault")
    if fault in ("429_once", "503_primary"):
      naive_latencies.append(950.0)
      continue
    naive_ok += 1
    in_t = int(item["est_in_tokens"])
    out_t = int(item["est_out_tokens"])
    cost = (in_t / 1000.0) * large_meta["input_cost_per_1k"] + (out_t / 1000.0) * large_meta["output_cost_per_1k"]
    naive_cost += cost
    naive_latencies.append(float(large_meta["simulated_latency_ms"]))

  seen_429: set[str] = set()

  def _replay_transport(
      model_name: str, messages: list[dict[str, str]], opts: dict[str, Any]
  ) -> dict[str, Any]:
    fault = opts.get("fault")
    req_id = str(opts.get("req_id", ""))
    if fault == "429_once" and req_id not in seen_429:
      seen_429.add(req_id)
      raise ProviderError(429, "Rate limit exceeded", "rate_limit_429")
    if fault == "503_primary" and model_name == large_name:
      raise ProviderError(503, "Primary model overloaded", "overloaded_503")

    meta = next(
        (m for m in bench_cfg["models"].values() if m["name"] == model_name),
        large_meta,
    )
    return {
        "content": f"[{model_name}] handled {messages[-1]['content'][:20]}",
        "input_tokens": int(opts.get("est_in_tokens", 200)),
        "output_tokens": int(opts.get("est_out_tokens", 60)),
        "simulated_latency_ms": float(meta["simulated_latency_ms"]),
    }

  gw = LLMGateway(bench_cfg, transport=_replay_transport)
  gw_ok = 0
  gw_latencies: list[float] = []
  for item in replay_items:
    try:
      res = gw.llm_call(
          item["task"],
          item["messages"],
          prompt_version=item["prompt_version"],
          req_id=item["req_id"],
          fault=item["fault"],
          est_in_tokens=item["est_in_tokens"],
          est_out_tokens=item["est_out_tokens"],
      )
      gw_ok += 1
      gw_latencies.append(float(res.get("latency_ms", 0.0)))
    except Exception:
      gw_latencies.append(1500.0)

  total_n = len(replay_items)
  gw_cost = round(gw.daily_spend_usd, 6)
  naive_cost = round(naive_cost, 6)
  saving_ratio = round((naive_cost - gw_cost) / naive_cost, 4) if naive_cost > 0 else 0.0
  cache_hits = sum(1 for row in gw.logs if row.get("cache_hit"))

  return {
      "total_requests": total_n,
      "naive": {
          "success_rate": round(naive_ok / total_n, 4),
          "total_cost_usd": naive_cost,
          "p95_latency_ms": round(_p95(naive_latencies), 2),
      },
      "gateway": {
          "success_rate": round(gw_ok / total_n, 4),
          "total_cost_usd": gw_cost,
          "p95_latency_ms": round(_p95(gw_latencies), 2),
          "cache_hits": cache_hits,
      },
      "cost_saving_ratio": saving_ratio,
      "gateway_logs": gw.logs,
  }
