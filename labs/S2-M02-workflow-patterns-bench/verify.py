#!/usr/bin/env python3
"""S2-M02 自动化验收脚本：验证 10 样本五模式同题基准测、路由降本、并行投票与硬上限防死循环。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file  # noqa: E402

EXPECTED_MODES = ("single_prompt", "prompt_chain", "routing", "parallel_vote", "evaluator_loop")


def _load_target_module(module_path: pathlib.Path) -> Any:
  spec = importlib.util.spec_from_file_location("s2_m02_target", module_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块: {module_path}")
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S2-M02", "四种工作流模式同题 10 样本基准测")
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  tickets = json.loads((LAB_DIR / "fixtures" / "tickets_10.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module(mod_path)
    bench = mod.run_benchmark(tickets)
    md_table = mod.format_benchmark_markdown(bench)
  except Exception as exc:  # noqa: BLE001
    v.check(
        "10 样本基准框架与五组模式运行无异常",
        False,
        f"运行 {mod_path.name} 时抛出异常：{exc}。请保持 run_benchmark 与 format_benchmark_markdown 接口契约完整。",
    )
    return v.finish()

  modes = bench.get("modes", {})

  # 验收项 1：单提示基线与四种工作流模式均跑完同一批 10 条样本并产出完整对比表
  all_modes_present = all(
      m in modes
      and modes[m].get("sample_count") == 10
      and modes[m].get("llm_calls", 0) >= 10
      and modes[m].get("total_tokens", 0) > 0
      and modes[m].get("sim_latency_ms", 0) > 0
      and f"`{m}`" in md_table
      for m in EXPECTED_MODES
  )
  v.check(
      "单提示基线与四种工作流模式同题 10 样本跑通并产出完整计费/耗时对比表",
      all_modes_present,
      "请确保 single_prompt / prompt_chain / routing / parallel_vote / evaluator_loop 全部跑满 10 条样本并记录调用次数、Tokens、耗时与费用。",
  )

  # 验收项 2：难度路由显著降低平均成本与延迟，且模糊件走澄清兜底不瞎编
  base_stats = modes.get("single_prompt", {})
  route_stats = modes.get("routing", {})
  route_details = route_stats.get("details", [])
  route_labels = {str(d.get("route", "")) for d in route_details}
  ambiguous_details = [d for d in route_details if d.get("ticket_id") in ("T08", "T09", "T10")]

  routing_ok = (
      float(route_stats.get("cost_usd", 999.0)) < float(base_stats.get("cost_usd", 0.0)) * 0.75
      and float(route_stats.get("sim_latency_ms", 99999.0)) < float(base_stats.get("sim_latency_ms", 0.0)) * 0.75
      and {"simple_faq", "complex_complaint"} <= route_labels
      and bool(route_labels & {"ambiguous_edge", "other_fallback"})
      and len(ambiguous_details) == 3
      and all(bool(d.get("passed")) for d in ambiguous_details)
  )
  v.check(
      f"难度路由降本提速且模糊件安全澄清（routing 费用=${route_stats.get('cost_usd', 0):.4f} vs 基线=${base_stats.get('cost_usd', 0):.4f}）",
      routing_ok,
      "请在 run_routing 中将简单咨询分流至 mini 模型、复杂长投诉分流至 pro 模型，并将 T08-T10 模糊件路由至追问澄清兜底分支（严禁臆测已后台改完数据）。",
  )

  # 验收项 3：并行分段（5 并发上限）与三视角退款承诺投票（majority_vote vs any_hit 策略对比）
  par_stats = modes.get("parallel_vote", {})
  par_details = par_stats.get("details", [])
  complex_par = [d for d in par_details if d.get("ticket_id") in ("T05", "T06", "T07")]
  any_hit_cnt = sum(1 for d in par_details if d.get("any_hit"))
  majority_cnt = sum(1 for d in par_details if d.get("majority_vote"))

  parallel_ok = (
      len(complex_par) == 3
      and all(int(d.get("max_workers_configured", 0)) == 5 for d in complex_par)
      and all(int(d.get("segments_processed", 0)) >= 3 for d in complex_par)
      and all(isinstance(d.get("votes"), dict) and len(d["votes"]) == 3 for d in complex_par)
      and any_hit_cnt > majority_cnt
      and float(par_stats.get("quality_pass_rate", 0.0)) >= 0.90
  )
  v.check(
      f"长投诉 5 并发分段汇总与三视角投票审校对比（any_hit={any_hit_cnt}次 vs majority_vote={majority_cnt}次）",
      parallel_ok,
      "请在 run_parallel_vote 中按段落使用 ThreadPoolExecutor(max_workers=5) 并发提炼长投诉，并用 3 个独立审校视角统计 votes / majority_vote / any_hit 差异。",
  )

  # 验收项 4：苛刻必败样本下重试与评估循环严格受限于 2-3 轮上限（零死循环）且标准合格率提升
  try:
    chain_cap_res = mod.run_prompt_chain(
        tickets[4],
        mod.BenchmarkTracker(),
        max_retries=8,
        force_gate_fail=True,
    )
    eval_cap_res = mod.run_evaluator_loop(
        tickets[4],
        mod.BenchmarkTracker(),
        max_rounds=9,
        strict_rubric={"impossible_token": "__IMPOSSIBLE_RUBRIC_NEVER_MATCH__"},
    )
    chain_attempts = int(chain_cap_res.get("attempts_used", 99))
    eval_rounds = int(eval_cap_res.get("rounds_used", 99))
  except Exception as exc:  # noqa: BLE001
    chain_attempts = 99
    eval_rounds = 99
    print(f"  [警告] 循环上限测试捕获异常: {exc}")

  eval_pass_rate = float(modes.get("evaluator_loop", {}).get("quality_pass_rate", 0.0))
  base_pass_rate = float(base_stats.get("quality_pass_rate", 0.0))
  loop_cap_ok = (
      1 <= chain_attempts <= 3
      and 1 <= eval_rounds <= 3
      and eval_pass_rate >= 0.90
      and eval_pass_rate > base_pass_rate
  )
  v.check(
      f"苛刻样本有界循环防死循环（链尝试={chain_attempts}次，评估轮次={eval_rounds}轮，评估合格率={eval_pass_rate:.0%}）",
      loop_cap_ok,
      f"当前苛刻样本下提示词链尝试 {chain_attempts} 次（要求 <=3）、评估循环跑了 {eval_rounds} 轮（要求硬编码上限 <=3），或评估合格率（{eval_pass_rate:.0%}）未显著优于单提示基线（{base_pass_rate:.0%}）。",
  )

  if all_modes_present and routing_ok and parallel_ok and loop_cap_ok:
    print("\n📊 10 样本五模式实测对照表：")
    print(md_table)

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
