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
import os
from types import ModuleType


def _load_target_module() -> ModuleType:
  path = target_file(LAB_DIR, "starter.py", "solution.py")
  mod_name = f"s0_m02_{path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块文件：{path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> int:
  os.environ["AID_FORCE_MOCK"] = "1"
  os.environ.pop("AID_USE_LIVE_OLLAMA", None)
  _ = (chat_complete, use_solution)

  v = LabVerifier("S0-M02", "批量抽数老漂移？本地小模型采样与窗口对照实测")
  fixture = json.loads((LAB_DIR / "fixtures" / "expense_memos.json").read_text(encoding="utf-8"))
  memo_case = fixture["short_memos"][0]
  memo_text = memo_case["text"]
  expected_short = memo_case["expected"]

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("加载实验目标模块", False, f"导入模块失败（{exc}），请检查语法错误。")
    return v.finish()

  # 验收项 1：三档 temperature 波动率统计与 Seed 可复现性
  try:
    stab = mod.measure_sampling_stability(memo_text, temperatures=(0.0, 0.7, 1.2), runs_per_temp=5)
    runs_by_temp = stab.get("runs_by_temp", {})
    drift_by_temp = stab.get("drift_by_temp", {})
    has_all_runs = all(
        t in runs_by_temp and len(runs_by_temp[t]) == 5 for t in (0.0, 0.7, 1.2)
    )
    drift_ordered = (
        has_all_runs
        and drift_by_temp.get(0.0) == 0.0
        and 0.0 < float(drift_by_temp.get(0.7, 0.0)) <= float(drift_by_temp.get(1.2, 0.0))
    )
    parsed_ok = stab.get("temp_zero_parsed") == expected_short
    seed_ok = (
        stab.get("seed_reproducible") is True
        and len(stab.get("seed_42_outputs", [])) == 3
        and len(set(stab.get("seed_42_outputs", []))) == 1
        and stab["seed_42_outputs"][0] != stab.get("seed_99_output", "")
    )
    cloud_ok = bool(stab.get("cloud_temp_zero_output")) and json.loads(
        stab["cloud_temp_zero_output"]
    ) == expected_short
    v.check(
        "三档温度(0 / 0.7 / 1.2)各 5 次波动率统计、固定/更换 Seed 可复现性与云端稳态对照",
        bool(drift_ordered and parsed_ok and seed_ok and cloud_ok),
        "请完善 build_ollama_chat_payload 与 measure_sampling_stability：确保透传 temperature/seed/stop/num_ctx，"
        "记录三档温度各 5 次输出与波动率（0.0 零漂移、高温漂移递增），验证 seed=42 连跑 3 次一致且不同于 seed=99，并补充 chat_complete 云端温度=0 对照。",
    )
  except Exception as exc:
    v.check(
        "三档温度(0 / 0.7 / 1.2)各 5 次波动率统计、固定/更换 Seed 可复现性与云端稳态对照",
        False,
        f"执行 measure_sampling_stability 出错（{exc}），请检查返回字典结构与 JSON 解析逻辑。",
    )

  # 验收项 2：num_predict 截断复现与 stop 闭合符精准停止
  try:
    trunc_res = mod.diagnose_truncation_and_stop(memo_text)
    t_case = trunc_res.get("truncated_case", {})
    c_case = trunc_res.get("clean_stop_case", {})
    trunc_reproduced = (
        t_case.get("done_reason") == "length"
        and t_case.get("is_truncated") is True
        and t_case.get("json_valid") is False
    )
    stop_verified = (
        c_case.get("done_reason") == "stop"
        and c_case.get("is_truncated") is False
        and c_case.get("json_valid") is True
        and c_case.get("parsed_data") == expected_short
        and "备注" not in str(c_case.get("content", ""))
    )
    v.check(
        "num_predict 过小半途截断复现与 stop=['</JSON>'] 精准停止验证",
        bool(trunc_reproduced and stop_verified),
        "请完善 diagnose_truncation_and_stop：truncated_case 设 num_predict=10, stop=None 复现 length 截断；"
        "clean_stop_case 设 num_predict=160, stop=['</JSON>'] 在闭合标记前精准截停并解析出完整 JSON。",
    )
  except Exception as exc:
    v.check(
        "num_predict 过小半途截断复现与 stop=['</JSON>'] 精准停止验证",
        False,
        f"执行 diagnose_truncation_and_stop 出错（{exc}），请检查 options 中的 num_predict 与 stop 传递逻辑。",
    )

  # 验收项 3：默认 num_ctx=2048 超窗静默遗忘与扩容 num_ctx=4096 找回验证
  try:
    ctx_res = mod.diagnose_context_window_forgetting(fixture["long_meeting_memo"])
    expected_long = fixture["long_meeting_memo"]["expected"]
    small_forgot = (
        int(ctx_res.get("prompt_length", 0)) > 2048
        and ctx_res.get("header_forgotten_in_small_ctx") is True
        and ctx_res.get("small_ctx_data", {}).get("amount") is None
    )
    expanded_found = (
        ctx_res.get("header_recovered_in_expanded_ctx") is True
        and ctx_res.get("expanded_ctx_data") == expected_long
    )
    v.check(
        "长纪要超窗静默遗忘复现（num_ctx=2048）与扩容找回验证（num_ctx=4096）",
        bool(small_forgot and expanded_found),
        "请完善 build_ollama_chat_payload 的 options['num_ctx'] 透传及 diagnose_context_window_forgetting："
        "对比 num_ctx=2048（卷首 48500.00 元被截断遗忘）与 num_ctx=4096（完整找回立项日期、金额与苏州城市）。",
    )
  except Exception as exc:
    v.check(
        "长纪要超窗静默遗忘复现（num_ctx=2048）与扩容找回验证（num_ctx=4096）",
        False,
        f"执行 diagnose_context_window_forgetting 出错（{exc}），请检查 num_ctx 参数传递与 JSON 解析兜底。",
    )

  # 验收项 4：准确率、速度、隐私、成本四维选型结论表
  try:
    matrix = mod.build_selection_matrix(fixture["benchmark_profiles"])
    dims = set(matrix.get("dimensions", []))
    md_table = str(matrix.get("markdown_table", ""))
    recs = matrix.get("recommendations", {})
    dims_ok = {"accuracy", "speed", "privacy", "cost"}.issubset(dims)
    table_ok = (
        all(kw in md_table for kw in ("准确率", "速度", "隐私", "成本"))
        and all(p["display_name"] in md_table for p in fixture["benchmark_profiles"])
        and md_table.count("\n") >= 4
    )
    recs_ok = (
        "sensitive_internal_memo" in recs
        and "high_volume_public_batch" in recs
        and str(recs["sensitive_internal_memo"].get("selected_profile", "")).startswith("local_")
        and recs["high_volume_public_batch"].get("selected_profile") == "cloud_mini_api"
    )
    v.check(
        "产出包含准确率、响应速度、数据隐私、成本四维的本地 vs 云端选型结论表",
        bool(dims_ok and table_ok and recs_ok),
        "请完善 build_selection_matrix：dimensions 需覆盖 ['accuracy', 'speed', 'privacy', 'cost']，"
        "markdown_table 包含全部候选模型与四维指标列，并在 recommendations 中给出 sensitive_internal_memo（选本地）与 high_volume_public_batch（选云端）的选型建议。",
    )
  except Exception as exc:
    v.check(
        "产出包含准确率、响应速度、数据隐私、成本四维的本地 vs 云端选型结论表",
        False,
        f"执行 build_selection_matrix 出错（{exc}），请检查返回结构。",
    )

  return v.finish()


if __name__ == "__main__":
  main()
