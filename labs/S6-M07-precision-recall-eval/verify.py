#!/usr/bin/env python3
"""S6-M07 自动化红绿验收脚本。"""

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
  spec = importlib.util.spec_from_file_location("s6_m07_target", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S6-M07", "AI 质检爱瞎挑刺或漏坑？测出真实检出与误报率")

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块加载", False, f"导入目标文件失败：{exc}")
    return v.finish()

  # 验收项 1：24 条正负配对样本加载与 JSON 解析异常容错单测
  try:
    cases = mod.load_eval_cases()
    pos_cnt = sum(1 for c in cases if c.get("has_issue") is True)
    neg_cnt = sum(1 for c in cases if c.get("has_issue") is False)

    p_clean = mod.parse_judge_json('{"found_issue": true, "reason": "发现私下收款诱导"}')
    p_fence = mod.parse_judge_json('下面是审查结论：\n```json\n{"found_issue": false, "reason": "合规客服答复"}\n```')
    p_broken = mod.parse_judge_json("网关超时：502 Bad Gateway（非 JSON 文本）")

    check1_ok = (
        len(cases) == 24
        and pos_cnt == 12
        and neg_cnt == 12
        and p_clean.get("found_issue") is True
        and p_clean.get("parse_ok") is True
        and p_fence.get("found_issue") is False
        and p_fence.get("parse_ok") is True
        and p_broken.get("parse_ok") is False
        and isinstance(p_broken.get("found_issue"), bool)
    )
    v.check(
        "24 条正负配对集加载与结构化 JSON 容错解析（兼容 ```json 代码块与异常文本兜底）",
        check1_ok,
        "请在 parse_judge_json 中剥离 Markdown ```json 代码块或提取 {...} 主体，并对非 JSON 异常文本返回 parse_ok=False 而不抛异常。",
    )
  except Exception as exc:
    cases = []
    v.check(
        "24 条正负配对集加载与结构化 JSON 容错解析（兼容 ```json 代码块与异常文本兜底）",
        False,
        f"parse_judge_json 抛出未捕获异常：{exc}。请为 JSON 解析增加容错处理。",
    )

  # 验收项 2：Recall（检出率）、FPR（误报率）、耗时与花费统计准确性
  try:
    synthetic = (
        [{"has_issue": True, "predicted_issue": True, "parse_ok": True, "latency_ms": 12.0, "cost_usd": 0.0001}] * 10
        + [{"has_issue": True, "predicted_issue": False, "parse_ok": True, "latency_ms": 10.0, "cost_usd": 0.0001}] * 2
        + [{"has_issue": False, "predicted_issue": True, "parse_ok": True, "latency_ms": 11.0, "cost_usd": 0.0001}] * 3
        + [{"has_issue": False, "predicted_issue": False, "parse_ok": True, "latency_ms": 9.0, "cost_usd": 0.0001}] * 9
    )
    m = mod.compute_eval_metrics(synthetic)
    check2_ok = (
        "recall" in m
        and "fpr" in m
        and abs(float(m["recall"]) - (10 / 12)) < 1e-3
        and abs(float(m["fpr"]) - (3 / 12)) < 1e-3
        and abs(float(m.get("precision", -1.0)) - (10 / 13)) < 1e-3
        and float(m.get("total_latency_ms", 0.0)) > 200.0
        and float(m.get("estimated_cost_usd", 0.0)) > 0.002
    )
    v.check(
        "混淆矩阵双核心指标核算（准确计算 Recall 检出率、FPR 误报率、Precision、耗时与花费）",
        check2_ok,
        "请在 compute_eval_metrics 中分别统计 TP/FN/FP/TN，计算 recall=TP/(TP+FN)、fpr=FP/(FP+TN)、precision、total_latency_ms 与 estimated_cost_usd。",
    )
  except Exception as exc:
    v.check(
        "混淆矩阵双核心指标核算（准确计算 Recall 检出率、FPR 误报率、Precision、耗时与花费）",
        False,
        f"compute_eval_metrics 执行异常：{exc}",
    )

  # 验收项 3：24 条样本去诱导前后对照实测（FPR 显著下降且高检出不掉点，100% 合法 JSON）
  comp = None
  try:
    if not cases:
      cases = mod.load_eval_cases()
    comp = mod.compare_prompts(cases)
    b_m = comp["biased"]["metrics"]
    c_m = comp["calibrated"]["metrics"]
    c_records = comp["calibrated"]["records"]

    all_json_valid = (
        len(c_records) == 24
        and all(
            r.get("parse_ok") is True
            and isinstance(r.get("predicted_issue"), bool)
            and bool(str(r.get("reason", "")).strip())
            for r in c_records
        )
    )
    b_fpr = float(b_m.get("fpr", 1.0))
    c_fpr = float(c_m.get("fpr", 1.0))
    c_recall = float(c_m.get("recall", 0.0))

    check3_ok = (
        all_json_valid
        and c_recall >= 0.90
        and c_fpr <= 0.17
        and (b_fpr - c_fpr) >= 0.40
    )
    v.check(
        "去诱导前后 A/B 对照实测（24 条全部合法 JSON，去诱导后 FPR <= 17% 且较诱导版下降 >= 40%，Recall >= 90%）",
        check3_ok,
        f"当前校准版 Recall={c_recall:.2%}、FPR={c_fpr:.2%}（诱导基线 FPR={b_fpr:.2%}）。请移除 DEFAULT_SYSTEM_PROMPT 中的『至少指出 2 处问题』诱导语，明确实质违规红线与正常合规免责边界。",
    )
  except Exception as exc:
    v.check(
        "去诱导前后 A/B 对照实测（24 条全部合法 JSON，去诱导后 FPR <= 17% 且较诱导版下降 >= 40%，Recall >= 90%）",
        False,
        f"compare_prompts 评测执行异常：{exc}",
    )

  # 验收项 4：输出可读对照统计报告
  try:
    if comp is None:
      comp = mod.compare_prompts(mod.load_eval_cases())
    report = str(mod.format_comparison_report(comp))
    check4_ok = (
        "Recall" in report
        and "FPR" in report
        and "%" in report
        and "$" in report
        and len(report.splitlines()) >= 5
    )
    v.check(
        "生成可读评测对照表（包含 Recall、FPR、百分比对比、耗时与花费摘要）",
        check4_ok,
        "请完善 format_comparison_report，输出包含诱导版与校准版 Recall、FPR、耗时及美元花费的对齐统计表。",
    )
  except Exception as exc:
    v.check(
        "生成可读评测对照表（包含 Recall、FPR、百分比对比、耗时与花费摘要）",
        False,
        f"format_comparison_report 执行异常：{exc}",
    )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
