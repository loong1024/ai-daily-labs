#!/usr/bin/env python3
from __future__ import annotations
import pathlib, sys
LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

import importlib.util
import json
from types import ModuleType


def _load_target_module() -> ModuleType:
  path = target_file(LAB_DIR, "starter.py", "solution.py")
  mod_name = f"s0_m07_{path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块文件：{path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def _approx(a: float, b: float, tol: float = 1e-5) -> bool:
  return abs(float(a) - float(b)) <= tol


def main() -> int:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S0-M07", "千条反馈和长文怎么跑最省？80 行 Python 成本模拟器")
  fixture = json.loads((LAB_DIR / "fixtures" / "pricing_scenarios.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module()
    models = {m["name"]: mod.ModelPricing(**m) for m in fixture["models"]}
    workloads = {
        w["scenario_id"]: mod.WorkloadSpec(
            task_count=w["task_count"],
            prefix_tokens=w["prefix_tokens"],
            variable_input_tokens=w["variable_input_tokens"],
            output_tokens=w["output_tokens"],
            compact_output_ratio=w["compact_output_ratio"],
        )
        for w in fixture["workloads"]
    }
  except Exception as exc:
    v.check("加载成本模拟器模块与配置", False, f"模块加载或 dataclass 初始化失败（{exc}）。")
    return v.finish()

  pro_model = models["pro_reasoning_model"]
  flash_model = models["economy_flash_model"]

  # 验收项 1：2000 条任务四种策略（A/B/C/D）完整账单与手算结果核对
  try:
    quotes_1200 = mod.simulate_all_strategies(workloads["cached_verbose_1200"], pro_model)
    by_sid = {q.strategy_id: q for q in quotes_1200}
    has_four = {"A_realtime_full", "B_compact_output", "C_prefix_cache", "D_cache_plus_batch"}.issubset(by_sid)

    math_ok = (
        has_four
        and _approx(by_sid["A_realtime_full"].input_cost_usd, 5.80)
        and _approx(by_sid["A_realtime_full"].output_cost_usd, 4.80)
        and _approx(by_sid["A_realtime_full"].total_cost_usd, 10.60)
        and _approx(by_sid["B_compact_output"].input_cost_usd, 5.80)
        and _approx(by_sid["B_compact_output"].output_cost_usd, 2.40)
        and _approx(by_sid["B_compact_output"].total_cost_usd, 8.20)
        and _approx(by_sid["C_prefix_cache"].input_cost_usd, 1.48)
        and _approx(by_sid["C_prefix_cache"].output_cost_usd, 4.80)
        and _approx(by_sid["C_prefix_cache"].cache_savings_usd, 4.32)
        and _approx(by_sid["C_prefix_cache"].total_cost_usd, 6.28)
        and _approx(by_sid["D_cache_plus_batch"].input_cost_usd, 0.98)
        and _approx(by_sid["D_cache_plus_batch"].output_cost_usd, 2.40)
        and _approx(by_sid["D_cache_plus_batch"].cache_savings_usd, 1.92)
        and _approx(by_sid["D_cache_plus_batch"].total_cost_usd, 3.38)
    )
    v.check(
        "2000 条任务四策略（A/B/C/D）输入费、输出费、缓存节省额与总账单手算核验",
        bool(math_ok),
        "请完善 simulate_all_strategies：确保返回 A_realtime_full / B_compact_output / C_prefix_cache / D_cache_plus_batch 四项报价，"
        "修复输出按 output_per_1m 计费，并核对 2000 条 × 前缀 1200 场景总账单分别为 $10.60 / $8.20 / $6.28 / $3.38。",
    )
  except Exception as exc:
    v.check(
        "2000 条任务四策略（A/B/C/D）输入费、输出费、缓存节省额与总账单手算核验",
        False,
        f"执行 simulate_all_strategies 出错（{exc}），请检查 StrategyQuote 字段。",
    )

  # 验收项 2：>= 1024 token 前缀缓存门槛严格判断（800 / 1023 不触发，1024 / 1200 触发）
  try:
    q_800 = {q.strategy_id: q for q in mod.simulate_all_strategies(workloads["under_threshold_800"], pro_model)}
    q_1023 = {q.strategy_id: q for q in mod.simulate_all_strategies(workloads["just_below_boundary_1023"], pro_model)}
    q_1024 = {q.strategy_id: q for q in mod.simulate_all_strategies(workloads["exact_boundary_1024"], pro_model)}

    threshold_ok = (
        "C_prefix_cache" in q_800
        and "D_cache_plus_batch" in q_800
        and q_800["C_prefix_cache"].cache_triggered is False
        and _approx(q_800["C_prefix_cache"].cache_savings_usd, 0.0)
        and _approx(q_800["C_prefix_cache"].total_cost_usd, q_800["A_realtime_full"].total_cost_usd)
        and q_800["D_cache_plus_batch"].cache_triggered is False
        and _approx(q_800["D_cache_plus_batch"].cache_savings_usd, 0.0)
        and _approx(q_800["D_cache_plus_batch"].total_cost_usd, 4.50)
        and q_1023["C_prefix_cache"].cache_triggered is False
        and _approx(q_1023["C_prefix_cache"].cache_savings_usd, 0.0)
        and q_1024["C_prefix_cache"].cache_triggered is True
        and q_1024["C_prefix_cache"].cache_savings_usd > 0.0
    )
    v.check(
        "前缀缓存 >= 1024 Token 触发门槛校验（800 与 1023 不误享折扣，1024 正式触发）",
        bool(threshold_ok),
        "请加入 workload.prefix_tokens >= pricing.cache_min_prefix_tokens 判断：低于 1024（如 800 或 1023）时 "
        "cache_triggered 必须为 False、cache_savings_usd 为 0.0，且策略 C 费用等于策略 A 原价。",
    )
  except Exception as exc:
    v.check(
        "前缀缓存 >= 1024 Token 触发门槛校验（800 与 1023 不误享折扣，1024 正式触发）",
        False,
        f"边界门槛校验出错（{exc}），请检查缓存门槛分支逻辑。",
    )

  # 验收项 3：输出（含思考）长度压缩（300 -> 80）与双档模型单价/叠加规则联动验证
  try:
    pro_compact = {q.strategy_id: q for q in mod.simulate_all_strategies(workloads["cached_compact_80"], pro_model)}
    flash_compact = {q.strategy_id: q for q in mod.simulate_all_strategies(workloads["cached_compact_80"], flash_model)}

    sensitivity_ok = (
        "D_cache_plus_batch" in pro_compact
        and "D_cache_plus_batch" in flash_compact
        and _approx(pro_compact["A_realtime_full"].output_cost_usd, 1.28)
        and _approx(pro_compact["D_cache_plus_batch"].total_cost_usd, 1.62)
        and _approx(flash_compact["D_cache_plus_batch"].input_cost_usd, 0.074)
        and _approx(flash_compact["D_cache_plus_batch"].output_cost_usd, 0.064)
        and _approx(flash_compact["D_cache_plus_batch"].total_cost_usd, 0.138)
    )
    v.check(
        "输出（含思考）长度压缩(300->80)与双档模型单价/Batch 叠加参数联动核验",
        bool(sensitivity_ok),
        "请核验输出长度与 stack_batch_on_cache 参数联动：输出压到 80 token 后 pro 模型策略 D 应降至 $1.62；"
        "开启 stack_batch_on_cache=True 的 economy_flash_model 策略 D 应精确为输入 $0.074 + 输出 $0.064 = $0.138。",
    )
  except Exception as exc:
    v.check(
        "输出（含思考）长度压缩(300->80)与双档模型单价/Batch 叠加参数联动核验",
        False,
        f"参数敏感度联动校验出错（{exc}），请检查 stack_batch_on_cache 与 output_tokens 计算公式。",
    )

  # 验收项 4：Markdown 账单对比表渲染与最优方案定位
  try:
    md_text = mod.render_markdown_comparison(workloads["cached_compact_80"], pro_model)
    best_q = mod.find_best_quote(mod.simulate_all_strategies(workloads["cached_compact_80"], pro_model))
    md_ok = (
        all(col in md_text for col in ("输入费用", "输出费用", "缓存节省", "总账单"))
        and all(lbl in md_text for lbl in ("策略A", "策略B", "策略C", "策略D"))
        and best_q.strategy_id == "D_cache_plus_batch"
        and "1.6200" in md_text
    )
    v.check(
        "渲染包含输入费、输出费、缓存节省额与总账单四维明细的 Markdown 对比表",
        bool(md_ok),
        "请完善 render_markdown_comparison：确保表格同时列出策略 A/B/C/D 及「输入费用、输出费用、缓存节省额、总账单」完整列。",
    )
  except Exception as exc:
    v.check(
        "渲染包含输入费、输出费、缓存节省额与总账单四维明细的 Markdown 对比表",
        False,
        f"渲染 Markdown 对比表出错（{exc}），请检查 render_markdown_comparison 实现。",
    )

  return v.finish()


if __name__ == "__main__":
  main()
