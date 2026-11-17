#!/usr/bin/env python3
"""S6-M05 实验验收脚本：验证统一大模型网关的容错熔断、流式边界、缓存并发与日预算封顶。"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import sys
import time
from typing import Any, Iterator

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_gateway_module(path: pathlib.Path):
  spec = importlib.util.spec_from_file_location("aid_gateway_mod", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载网关模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S6-M05", "模型报错账单飙？基于 LiteLLM 封装网关")

  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  try:
    gw_mod = _load_gateway_module(mod_path)
    base_cfg = json.loads((LAB_DIR / "fixtures" / "gateway_config.json").read_text(encoding="utf-8"))
    replay_50 = json.loads((LAB_DIR / "fixtures" / "replay_50.json").read_text(encoding="utf-8"))
  except Exception as exc:
    v.check("加载网关代码与压测配置", False, f"加载失败：{exc}")
    return v.finish()

  rel_ok = False
  rel_hint = ""
  try:
    cfg1 = copy.deepcopy(base_cfg)
    large_name = cfg1["models"]["large"]["name"]
    fallback_name = cfg1["models"]["fallback"]["name"]
    call_counts = {"primary": 0, "fallback": 0, "bad_400": 0}

    def _fault_transport(
        model_name: str, messages: list[dict[str, str]], opts: dict[str, Any]
    ) -> dict[str, Any]:
      mode = opts.get("mode", "503_primary")
      if mode == "400_bad_request":
        call_counts["bad_400"] += 1
        raise gw_mod.ProviderError(400, "Invalid message format")
      if model_name == large_name:
        call_counts["primary"] += 1
        raise gw_mod.ProviderError(503, "Service unavailable")
      call_counts["fallback"] += 1
      return {"content": f"fallback:{messages[-1]['content']}", "input_tokens": 120, "output_tokens": 40}

    def _stream_transport(
        model_name: str, _messages: list[dict[str, str]], opts: dict[str, Any]
    ) -> Iterator[str]:
      smode = opts.get("smode", "pre_first_chunk_503")
      if smode == "pre_first_chunk_503":
        if model_name == large_name:
          raise gw_mod.ProviderError(503, "Pre-chunk 503")
        yield "备用流式-"
        yield "完整响应"
      elif smode == "mid_stream_drop":
        yield "半截已输出内容-"
        raise gw_mod.ProviderError(503, "Connection reset mid-stream")

    gw1 = gw_mod.LLMGateway(cfg1, transport=_fault_transport, stream_transport=_stream_transport)

    got_400 = False
    try:
      gw1.llm_call("contract_audit", [{"role": "user", "content": "bad"}], mode="400_bad_request")
    except gw_mod.ProviderError as exc:
      got_400 = exc.status_code == 400
    no_400_retry = got_400 and call_counts["bad_400"] == 1

    r1 = gw1.llm_call("contract_audit", [{"role": "user", "content": "q1"}], no_cache=True)
    primary_calls_after_r1 = call_counts["primary"]
    r2 = gw1.llm_call("contract_audit", [{"role": "user", "content": "q2"}], no_cache=True)
    circuit_worked = (
        r1["model"] == fallback_name
        and r2["model"] == fallback_name
        and call_counts["primary"] == primary_calls_after_r1
    )

    gw_stream = gw_mod.LLMGateway(cfg1, transport=_fault_transport, stream_transport=_stream_transport)
    pre_chunk_text = "".join(
        gw_stream.llm_stream("contract_audit", [{"role": "user", "content": "s1"}], smode="pre_first_chunk_503")
    )
    mid_stream_caught = False
    try:
      list(gw_stream.llm_stream("contract_audit", [{"role": "user", "content": "s2"}], smode="mid_stream_drop"))
    except gw_mod.StreamInterruptedError:
      mid_stream_caught = True

    rel_ok = (
        no_400_retry
        and circuit_worked
        and pre_chunk_text == "备用流式-完整响应"
        and mid_stream_caught
    )
    if not rel_ok:
      rel_hint = (
          f"400不重试={no_400_retry}(calls={call_counts['bad_400']})，"
          f"熔断切备用={circuit_worked}(primary_calls={primary_calls_after_r1}->{call_counts['primary']})，"
          f"流式首包前兜底='{pre_chunk_text}'，流式半截保护={mid_stream_caught}。"
          "请实现 429/5xx 重试（跳过 400）、连续失败熔断器，以及流式首包前切备用、首包后断流抛 StreamInterruptedError。"
      )
  except Exception as exc:
    rel_hint = f"容错与流式测试未通过：{exc}"

  v.check(
      "连续 503 触发熔断自动切备用（跳过 400），且流式严守“首包前切换、半截断流报错”边界",
      rel_ok,
      rel_hint,
  )

  perf_ok = False
  perf_hint = ""
  try:
    cfg2 = copy.deepcopy(base_cfg)
    backend_hits = {"count": 0}

    def _slow_transport(
        model_name: str, messages: list[dict[str, str]], opts: dict[str, Any]
    ) -> dict[str, Any]:
      backend_hits["count"] += 1
      if opts.get("sleep_sec"):
        time.sleep(float(opts["sleep_sec"]))
      return {
          "content": f"{model_name}:{backend_hits['count']}:{messages[-1]['content']}",
          "input_tokens": 150,
          "output_tokens": 50,
      }

    gw2 = gw_mod.LLMGateway(cfg2, transport=_slow_transport)
    msg_doc = [{"role": "user", "content": "固定白皮书摘要请求"}]
    first_doc = gw2.llm_call("doc_summary", msg_doc, prompt_version="v1")
    second_doc = gw2.llm_call("doc_summary", msg_doc, prompt_version="v1")
    v2_doc = gw2.llm_call("doc_summary", msg_doc, prompt_version="v2")

    msg_live = [{"role": "user", "content": "查询订单 ORD-1001 实时位置"}]
    live_1 = gw2.llm_call("live_order_status", msg_live, prompt_version="v1")
    live_2 = gw2.llm_call("live_order_status", msg_live, prompt_version="v1")

    cache_valid = (
        first_doc["cache_hit"] is False
        and second_doc["cache_hit"] is True
        and second_doc["cost_usd"] == 0.0
        and second_doc["content"] == first_doc["content"]
        and v2_doc["cache_hit"] is False
        and live_1["cache_hit"] is False
        and live_2["cache_hit"] is False
        and live_1["content"] != live_2["content"]
    )

    sub_calls = [
        {
            "task": "intent_classify",
            "messages": [{"role": "user", "content": f"并发子任务-{i}"}],
            "opts": {"sleep_sec": 0.06},
        }
        for i in range(4)
    ]
    t_start = time.perf_counter()
    batch_out = gw2.batch_concurrent_calls(sub_calls, max_workers=4)
    elapsed_sec = time.perf_counter() - t_start
    concurrent_valid = len(batch_out) == 4 and elapsed_sec < 0.16

    perf_ok = cache_valid and concurrent_valid
    if not perf_ok:
      perf_hint = (
          f"缓存校验={cache_valid}（second_hit={second_doc.get('cache_hit')}，live_2_hit={live_2.get('cache_hit')}），"
          f"4路耗时={elapsed_sec*1000:.1f}ms（需 < 160ms，串行为 ~240ms）。"
          "请以 model+prompt_version+user_id+messages 哈希缓存确定性任务（跳过 cacheable=False 任务），并用 ThreadPoolExecutor 实现并发。"
      )
  except Exception as exc:
    perf_hint = f"缓存与并发测试异常：{exc}"

  v.check(
      "确定性请求精准命中缓存（跳过实时任务），且 4 路并发总耗时接近单路而非四路相加",
      perf_ok,
      perf_hint,
  )

  budget_ok = False
  budget_hint = ""
  try:
    cfg3 = copy.deepcopy(base_cfg)
    cfg3["budget"]["soft_limit_usd"] = 0.005
    cfg3["budget"]["hard_limit_usd"] = 0.010
    small_name = cfg3["models"]["small"]["name"]
    large_name = cfg3["models"]["large"]["name"]

    def _fast_transport(
        model_name: str, _messages: list[dict[str, str]], _opts: dict[str, Any]
    ) -> dict[str, Any]:
      return {"content": f"ok:{model_name}", "input_tokens": 600, "output_tokens": 300}

    gw3 = gw_mod.LLMGateway(cfg3, transport=_fast_transport)
    c_small = gw3.llm_call("intent_classify", [{"role": "user", "content": "查物流"}], no_cache=True)
    c_large = gw3.llm_call("doc_summary", [{"role": "user", "content": "文档A"}], no_cache=True)
    c_downgraded = gw3.llm_call("doc_summary", [{"role": "user", "content": "文档B"}], no_cache=True)
    gw3.daily_spend_usd = 0.012
    non_crit_blocked = False
    try:
      gw3.llm_call("doc_summary", [{"role": "user", "content": "文档C"}], no_cache=True)
    except gw_mod.BudgetExceededError:
      non_crit_blocked = True
    crit_allowed = gw3.llm_call("contract_audit", [{"role": "user", "content": "核心合同审查"}], no_cache=True)

    budget_ok = (
        c_small["model"] == small_name
        and c_large["model"] == large_name
        and c_downgraded["model"] == small_name
        and non_crit_blocked
        and crit_allowed["model"] == large_name
        and len(gw3.alerts) >= 2
    )
    if not budget_ok:
      budget_hint = (
          f"small路由={c_small['model']}，首单large={c_large['model']}，"
          f"超软上限降级={c_downgraded['model']}，超硬上限拦截非核心={non_crit_blocked}，告警数={len(gw3.alerts)}。"
          "请按 task 配置选择 small/large，超软上限将非关键任务降级 small，超硬上限抛 BudgetExceededError 暂停非核心任务并写入 alerts。"
      )
  except Exception as exc:
    budget_hint = f"路由与预算门禁测试异常：{exc}"

  v.check(
      "按任务自动路由大小模型，触达软/硬日预算红线时准确执行降级与非核心任务封顶告警",
      budget_ok,
      budget_hint,
  )

  bench_ok = False
  bench_hint = ""
  try:
    report = gw_mod.run_replay_benchmark(replay_50, base_cfg)
    gw_stats = report.get("gateway", {})
    naive_stats = report.get("naive", {})
    logs = report.get("gateway_logs", [])
    required_log_fields = {
        "task",
        "model",
        "prompt_version",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "latency_ms",
        "cache_hit",
        "retries",
        "error_type",
    }
    logs_complete = len(logs) == 50 and all(required_log_fields.issubset(row.keys()) for row in logs)
    bench_ok = (
        report.get("total_requests") == 50
        and gw_stats.get("success_rate", 0.0) == 1.0
        and naive_stats.get("success_rate", 1.0) < 0.90
        and report.get("cost_saving_ratio", 0.0) >= 0.45
        and gw_stats.get("p95_latency_ms", 9999.0) < naive_stats.get("p95_latency_ms", 0.0)
        and logs_complete
    )
    if not bench_ok:
      bench_hint = (
          f"50条重放结果：裸调成功率={naive_stats.get('success_rate')} vs 网关成功率={gw_stats.get('success_rate')}，"
          f"省钱比例={report.get('cost_saving_ratio')}（需 >= 0.45），"
          f"P95延迟={naive_stats.get('p95_latency_ms')}ms -> {gw_stats.get('p95_latency_ms')}ms，"
          f"结构化日志完备={logs_complete}。"
          "请完善 run_replay_benchmark 与每次调用的 10 个核心结构化日志字段。"
      )
  except Exception as exc:
    bench_hint = f"50 条流量重放压测异常：{exc}"

  v.check(
      "50 次混合流量重放压测：容错成功率升至 100%、总费用下降 ≥ 45%、P95 延迟降低且结构化日志齐全",
      bench_ok,
      bench_hint,
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
