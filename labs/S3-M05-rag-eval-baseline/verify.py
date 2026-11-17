#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def _load_target_module():
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  spec = importlib.util.spec_from_file_location("s3_m05_target", mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块: {mod_path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def main() -> int:
  # 默认启用确定性裁判模拟，确保离线/CI 环境稳定可复现
  os.environ.setdefault("AID_FORCE_MOCK", "1")
  _ = (chat_complete, use_solution)

  v = LabVerifier("S3-M05", "拒绝凭感觉调参：建 30 题双层回归评测基线")

  dataset = json.loads((LAB_DIR / "fixtures" / "eval_dataset_30.json").read_text(encoding="utf-8"))
  human_samples = json.loads(
      (LAB_DIR / "fixtures" / "human_audit_10.json").read_text(encoding="utf-8")
  )

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块加载与语法检查", False, f"导入模块失败：{exc}")
    return v.finish()

  # 验收 1：检索层确定性指标（仅对 25 道有答案题计算 Recall@5=0.88 与 MRR=0.72）
  try:
    ret = mod.compute_retrieval_metrics(dataset, retrieved_key="retrieved_chunks", k=5)
    ret_ok = (
        isinstance(ret, dict)
        and ret.get("answerable_count") == 25
        and abs(float(ret.get("recall_at_5", -1.0)) - 0.88) < 1e-4
        and abs(float(ret.get("mrr", -1.0)) - 0.72) < 1e-4
    )
  except Exception as exc:
    ret = {}
    ret_ok = False
    ret_err = f"运行异常：{exc}。"
  else:
    ret_err = f"当前返回 {ret}。"

  v.check(
      "检索层确定性指标分离计算（25 道有答案题 Recall@5=0.88, MRR=0.72）",
      ret_ok,
      f"{ret_err}请过滤掉 unanswerable=True 的 5 道题，并按前 5 名命中与 1/rank 均值计算 Recall@5 和 MRR。",
  )

  # 验收 2：生成层与 5 道无答案拒答题剥离统计
  baseline_report = {}
  try:
    baseline_report = mod.evaluate_rag_run(
        dataset, retrieved_key="retrieved_chunks", answer_key="model_answer"
    )
    gen = baseline_report.get("generation", {})
    ref = baseline_report.get("refusal", {})
    per_item = baseline_report.get("per_item", [])
    unans_items = [x for x in per_item if x.get("unanswerable")]

    gen_ref_ok = (
        gen.get("evaluated_count") == 25
        and float(gen.get("faithfulness", 0.0)) >= 0.85
        and float(gen.get("response_relevancy", 0.0)) >= 0.85
        and ref.get("unanswerable_count") == 5
        and ref.get("correct_refusals") == 4
        and ref.get("refusal_accuracy") is not None
        and abs(float(ref.get("refusal_accuracy", -1.0)) - 0.80) < 1e-4
        and len(unans_items) == 5
        and all(x.get("response_relevancy") is None for x in unans_items)
    )
    gen_err = f"当前 generation={gen}, refusal={ref}。"
  except Exception as exc:
    gen_ref_ok = False
    gen_err = f"运行异常：{exc}。"

  v.check(
      "无答案拒答题剥离与独立拒答准确率（排除出相关性分母，拒答率 4/5=0.80）",
      gen_ref_ok,
      f"{gen_err}请将 5 道 unanswerable 题从 generation 分母中剔除（response_relevancy 置 None），单独统计 refusal_accuracy。",
  )

  # 验收 3：10 题人工抽检校准尺子
  try:
    calib = mod.calibrate_judge_alignment(baseline_report.get("per_item", []), human_samples)
    calib_ok = (
        isinstance(calib, dict)
        and calib.get("sample_size") == 10
        and 0.80 <= float(calib.get("agreement_rate", 0.0)) <= 1.0
        and isinstance(calib.get("discrepant_ids"), list)
        and "Q22" in calib.get("discrepant_ids", [])
    )
    calib_err = f"当前返回 {calib}。"
  except Exception as exc:
    calib_ok = False
    calib_err = f"运行异常：{exc}。"

  v.check(
      "10 题人工抽检校准闭环（对齐一致率、偏差均值与分歧题号 Q22）",
      calib_ok,
      f"{calib_err}请在 calibrate_judge_alignment 中按题目 id 比对 machine_pass 与 human_pass，记录 sample_size=10、agreement_rate、mean_bias 与 discrepant_ids。",
  )

  # 验收 4：单变量对照实验（chunk_500 基线 vs chunk_1500 大切片退步检测）
  try:
    exp_1500_report = mod.evaluate_rag_run(
        dataset,
        retrieved_key="alt_chunk_1500_retrieved_chunks",
        answer_key="alt_chunk_1500_answer",
    )
    diff = mod.compare_configs(baseline_report, exp_1500_report)
    diff_ok = (
        isinstance(diff, dict)
        and float(diff.get("recall_at_5_delta", 0.0)) < -0.15
        and float(diff.get("mrr_delta", 0.0)) < -0.15
        and diff.get("regression_detected") is True
    )
    diff_err = f"当前返回 {diff}。"
  except Exception as exc:
    diff_ok = False
    diff_err = f"运行异常：{exc}。"

  v.check(
      "单变量回归对照检测（捕获 chunk_500 -> chunk_1500 的召回与相关性下滑）",
      diff_ok,
      f"{diff_err}请在 compare_configs 中计算实验组减基线组的指标差值（recall_at_5_delta、mrr_delta 等）并标记 regression_detected=True。",
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
