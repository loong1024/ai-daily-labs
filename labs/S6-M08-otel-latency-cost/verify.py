#!/usr/bin/env python3
"""S6-M08 自动化红绿验收脚本。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_target_module() -> ModuleType:
  path = target_file(LAB_DIR, "starter.py", "solution.py")
  spec = importlib.util.spec_from_file_location("s6_m08_target", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S6-M08", "模型日志算不清账？套 OTel 拆解延迟与缓存")

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块加载", False, f"导入目标文件失败：{exc}")
    return v.finish()

  # 验收项 1：OTel GenAI 标准字段与流式真实首字延迟（stream=True 且 0 < ttft_ms < total_ms）
  try:
    span = mod.record_streaming_span(
        trace_id="trc_unit_01",
        step_name="intent_router",
        prompt_version="v2_trimmed_cached",
        model="gpt-4o-mini",
        stream=True,
        chunk_timestamps_ms=[188.5, 290.0, 460.0],
        input_tokens=1500,
        output_tokens=40,
        cached_tokens=1152,
        input_preview="查账单",
        output_preview='{"intent":"billing"}',
    )
    required_keys = {
        "trace_id",
        "prompt_version",
        "ttft_ms",
        "total_ms",
        "cached_tokens",
        "gen_ai.request.model",
        "gen_ai.request.stream",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    }
    check1_ok = (
        required_keys.issubset(set(span.keys()))
        and span.get("gen_ai.request.stream") is True
        and abs(float(span["ttft_ms"]) - 188.5) < 1e-2
        and abs(float(span["total_ms"]) - 460.0) < 1e-2
        and float(span["ttft_ms"]) < float(span["total_ms"])
        and int(span["cached_tokens"]) == 1152
    )
    v.check(
        "OTel GenAI 标准字段与流式首字延迟采集（stream=True，准确区分 ttft_ms 与 total_ms）",
        check1_ok,
        "请在 record_streaming_span 中校验 stream=True，取 chunk_timestamps_ms[0] 为 ttft_ms、[-1] 为 total_ms，并写入五个核心字段与 gen_ai.* 标准属性。",
    )
  except Exception as exc:
    v.check(
        "OTel GenAI 标准字段与流式首字延迟采集（stream=True，准确区分 ttft_ms 与 total_ms）",
        False,
        f"record_streaming_span 执行异常：{exc}",
    )

  # 验收项 2：多步请求统一 trace_id 串联对账与缓存折扣成本核算
  try:
    # deepseek-chat: input=$0.27/1M, cached=$0.07/1M, output=$1.10/1M
    # input=2100, cached=1408 => uncached=692 => (692*0.27 + 1408*0.07 + 240*1.10)/1e6 = 0.0005494 -> 0.000549
    cost_cached = mod.compute_span_cost("deepseek-chat", 2100, 240, cached_tokens=1408)
    cost_no_cache = mod.compute_span_cost("deepseek-chat", 2100, 240, cached_tokens=0)

    wf_spans = mod.run_traced_workflow("如何导出月度发票？", prompt_version="v2_trimmed_cached", trace_id="trc_demo_99")
    trace_ids = {s.get("trace_id") for s in wf_spans}
    bill = mod.reconstruct_trace_bill(wf_spans, "trc_demo_99")

    check2_ok = (
        abs(cost_cached - 0.000549) < 2e-6
        and cost_cached < cost_no_cache * 0.70
        and len(wf_spans) == 2
        and trace_ids == {"trc_demo_99"}
        and all(s.get("gen_ai.request.stream") is True and float(s["ttft_ms"]) < float(s["total_ms"]) for s in wf_spans)
        and bill.get("step_count") == 2
        and float(bill.get("first_ttft_ms", 0.0)) > 0
        and float(bill.get("total_ms", 0.0)) > float(bill.get("first_ttft_ms", 0.0))
        and float(bill.get("total_cost_usd", 0.0)) > 0
    )
    v.check(
        "多步调用唯一 trace_id 串联与缓存折扣计费（单次请求拼出完整账单，cached_tokens 享折扣价）",
        check2_ok,
        "请在 compute_span_cost 中用 input_tokens - cached_tokens 计算未命中全价部分；在 run_traced_workflow 中透传同一 trace_id 并开启 stream=True；完善 reconstruct_trace_bill 聚合账单。",
    )
  except Exception as exc:
    v.check(
        "多步调用唯一 trace_id 串联与缓存折扣计费（单次请求拼出完整账单，cached_tokens 享折扣价）",
        False,
        f"多步串联与成本核算异常：{exc}",
    )

  # 验收项 3：按模型与步骤分组统计 P50/P95 延迟与 cached_tokens 占比
  summary = None
  try:
    fixture_spans = mod.load_jsonl_spans()
    summary = mod.summarize_ab_logs(fixture_spans)
    by_ms = summary.get("by_model_step") or {}
    expected_groups = {
        "v1_bloated_ctx|gpt-4o-mini|intent_router",
        "v1_bloated_ctx|deepseek-chat|rag_answer",
        "v2_trimmed_cached|gpt-4o-mini|intent_router",
        "v2_trimmed_cached|deepseek-chat|rag_answer",
    }
    g_v2_rag = by_ms.get("v2_trimmed_cached|deepseek-chat|rag_answer") or {}
    check3_ok = (
        len(fixture_spans) == 40
        and expected_groups.issubset(set(by_ms.keys()))
        and 220.0 <= float(g_v2_rag.get("p50_ttft_ms", 0.0)) <= 265.0
        and float(g_v2_rag.get("p95_ttft_ms", 0.0)) > float(g_v2_rag.get("p50_ttft_ms", 0.0))
        and abs(float(g_v2_rag.get("cache_hit_ratio", 0.0)) - (1408 / 2100)) < 0.02
    )
    v.check(
        "按模型与步骤分组计算 P50/P95 首字延迟及缓存命中占比（解析 40 条流式 Span 日志）",
        check3_ok,
        "请在 summarize_ab_logs 中按 f'{prompt_version}|{model}|{step_name}' 分组计算 p50_ttft_ms、p95_ttft_ms 与 cache_hit_ratio。",
    )
  except Exception as exc:
    v.check(
        "按模型与步骤分组计算 P50/P95 首字延迟及缓存命中占比（解析 40 条流式 Span 日志）",
        False,
        f"summarize_ab_logs 分组统计异常：{exc}",
    )

  # 验收项 4：对比精简上下文前后的首字提速效果与可读报告输出
  try:
    if summary is None:
      summary = mod.summarize_ab_logs(mod.load_jsonl_spans())
    by_ver = summary.get("by_version") or {}
    v1 = by_ver.get("v1_bloated_ctx") or {}
    v2 = by_ver.get("v2_trimmed_cached") or {}
    comp = summary.get("comparison") or {}
    report = str(mod.format_ab_report(summary))

    speedup_pct = float(comp.get("ttft_speedup_pct", 0.0))
    cost_saving_pct = float(comp.get("cost_saving_pct", 0.0))

    check4_ok = (
        float(v1.get("p50_ttft_ms", 0.0)) > 750.0
        and float(v2.get("p50_ttft_ms", 9999.0)) < 280.0
        and float(v1.get("cache_hit_ratio", 1.0)) < 0.10
        and float(v2.get("cache_hit_ratio", 0.0)) > 0.65
        and speedup_pct > 60.0
        and cost_saving_pct > 65.0
        and "P50" in report
        and "P95" in report
        and "%" in report
    )
    v.check(
        "上下文裁剪前后对比报告（量化验证 P50 首字提速 > 60%、缓存率跃升至 > 65%、总花费下降 > 65%）",
        check4_ok,
        "请在 summarize_ab_logs 与 format_ab_report 中汇总 v1_bloated_ctx 与 v2_trimmed_cached 的 P50/P95、缓存率、ttft_speedup_pct 与 cost_saving_pct 并格式化打印。",
    )
  except Exception as exc:
    v.check(
        "上下文裁剪前后对比报告（量化验证 P50 首字提速 > 60%、缓存率跃升至 > 65%、总花费下降 > 65%）",
        False,
        f"版本对比报告异常：{exc}",
    )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
