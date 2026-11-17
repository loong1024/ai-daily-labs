#!/usr/bin/env python3
"""LLM 变更防退化硬闸门脚本（Solution 标准参考实现）。

支持三项核心能力：
1. 逐条回归比对：总体通过率门槛 + critical 高危用例一票否决 + 防删题完整性检查 + Token/P95 延迟统计。
2. 结构化变更日志：自动生成可追加至 CHANGELOG-llm.md 的版本记录（含原因、对比数据与一键回滚命令）。
3. 快照一键回滚与 Git pre-commit 钩子生成：1 分钟恢复稳定快照，提交前硬阻断退化代码。
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import pathlib
import sys
from typing import Any


def _p95(values: list[float]) -> float:
  if not values:
    return 0.0
  ordered = sorted(values)
  idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
  return float(ordered[idx])


def _avg(values: list[float]) -> float:
  return round(sum(values) / len(values), 2) if values else 0.0


def evaluate_change(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    change_meta: dict[str, str] | None = None,
) -> dict[str, Any]:
  """逐条对比基线与候选评测集，执行双硬卡点裁决。"""
  del change_meta
  base_cases = {c["id"]: c for c in baseline.get("cases", [])}
  cand_cases = {c["id"]: c for c in candidate.get("cases", [])}

  missing_cases = sorted(cid for cid in base_cases if cid not in cand_cases)
  regressed_cases: list[str] = []
  critical_regressions: list[str] = []
  improved_cases: list[str] = []

  for cid, b_item in base_cases.items():
    c_item = cand_cases.get(cid)
    if c_item is None:
      continue
    b_pass = bool(b_item.get("passed"))
    c_pass = bool(c_item.get("passed"))
    if b_pass and not c_pass:
      regressed_cases.append(cid)
      if b_item.get("critical"):
        critical_regressions.append(cid)
    elif (not b_pass) and c_pass:
      improved_cases.append(cid)

  base_list = list(base_cases.values())
  cand_list = list(cand_cases.values())

  base_rate = (
      sum(1 for c in base_list if c.get("passed")) / len(base_list)
      if base_list
      else 0.0
  )
  cand_rate = (
      sum(1 for c in cand_list if c.get("passed")) / len(cand_list)
      if cand_list
      else 0.0
  )

  base_crit_total = sum(1 for c in base_list if c.get("critical"))
  base_crit_pass = sum(1 for c in base_list if c.get("critical") and c.get("passed"))
  cand_crit_pass = sum(
      1
      for cid, b in base_cases.items()
      if b.get("critical") and cand_cases.get(cid, {}).get("passed")
  )

  base_tokens = _avg([float(c.get("tokens", 0)) for c in base_list])
  cand_tokens = _avg([float(c.get("tokens", 0)) for c in cand_list])
  base_p95 = _p95([float(c.get("latency_ms", 0)) for c in base_list])
  cand_p95 = _p95([float(c.get("latency_ms", 0)) for c in cand_list])

  gate_ok = (
      len(missing_cases) == 0
      and len(critical_regressions) == 0
      and cand_rate >= base_rate
  )

  reasons: list[str] = []
  if missing_cases:
    reasons.append(f"候选评测缺失基线用例（疑似删题）：{', '.join(missing_cases)}")
  if critical_regressions:
    reasons.append(f"Critical 高危用例退化一票否决：{', '.join(critical_regressions)}")
  if cand_rate < base_rate:
    reasons.append(f"总体通过率下降：{base_rate:.1%} -> {cand_rate:.1%}")

  return {
      "verdict": "PASS" if gate_ok else "FAIL",
      "reasons": reasons,
      "baseline_version": baseline.get("version", "unknown"),
      "candidate_version": candidate.get("version", "unknown"),
      "baseline_pass_rate": round(base_rate, 4),
      "candidate_pass_rate": round(cand_rate, 4),
      "critical_before": f"{base_crit_pass}/{base_crit_total}",
      "critical_after": f"{cand_crit_pass}/{base_crit_total}",
      "avg_tokens_before": base_tokens,
      "avg_tokens_after": cand_tokens,
      "p95_latency_ms_before": base_p95,
      "p95_latency_ms_after": cand_p95,
      "regressed_cases": regressed_cases,
      "critical_regressions": critical_regressions,
      "improved_cases": improved_cases,
      "missing_cases": missing_cases,
  }


def format_changelog_entry(report: dict[str, Any], change_meta: dict[str, str]) -> str:
  """生成符合上线审计要求的 CHANGELOG-llm.md 条目。"""
  if report.get("verdict") != "PASS":
    raise ValueError("仅当门禁判定为 PASS 时才允许生成准予提交的变更日志条目。")

  date_str = change_meta.get("date") or dt.date.today().isoformat()
  prev_ver = report.get("baseline_version", "v1.2.0")
  new_ver = change_meta.get("version") or report.get("candidate_version", "v1.3.0")
  summary = change_meta.get("summary", "优化系统提示词约束")
  reason = change_meta.get("reason", "提升常规多语言润色准确率并保持安全红线不退化")
  rollback_cmd = change_meta.get(
      "rollback_cmd",
      f"python3 solution_gate.py --rollback {prev_ver} --scenarios fixtures/eval_scenarios.json",
  )

  b_rate = report["baseline_pass_rate"] * 100
  c_rate = report["candidate_pass_rate"] * 100
  improved_str = ", ".join(report["improved_cases"]) if report["improved_cases"] else "无"

  return (
      f"## [{new_ver}] - {date_str}\n"
      f"- **改动内容**：{summary}\n"
      f"- **改动原因**：{reason}\n"
      f"- **评测对比（vs `{prev_ver}`）**：\n"
      f"  - 总体通过率：{b_rate:.1f}% -> {c_rate:.1f}%（改进用例：{improved_str}）\n"
      f"  - Critical 高危用例：{report['critical_before']} -> {report['critical_after']}\n"
      f"  - 平均 Token：{report['avg_tokens_before']} -> {report['avg_tokens_after']}\n"
      f"  - P95 延迟：{report['p95_latency_ms_before']}ms -> {report['p95_latency_ms_after']}ms\n"
      f"- **一键回滚方式**：`{rollback_cmd}`\n"
  )


def rollback_to_snapshot(
    snapshots_state: dict[str, Any], target_version: str
) -> dict[str, Any]:
  """将当前激活版本与 Prompt 快照指针一键切回历史稳定快照。"""
  snapshots = snapshots_state.get("snapshots", {})
  if target_version not in snapshots:
    raise KeyError(f"未找到目标快照版本：{target_version}")

  target_snap = snapshots[target_version]
  updated = copy.deepcopy(snapshots_state)
  updated["previous_version"] = snapshots_state.get("active_version")
  updated["active_version"] = target_snap["version"]
  updated["active_prompt_sha256"] = target_snap["prompt_sha256"]
  updated["active_model"] = target_snap.get("model")
  updated["active_temperature"] = target_snap.get("temperature")
  updated["restored_pass_rate"] = target_snap.get("pass_rate")
  updated["restored_critical_passed"] = target_snap.get("critical_passed")
  return updated


def render_pre_commit_hook(gate_script_rel: str = "solution_gate.py") -> str:
  """生成挂载于 .git/hooks/pre-commit 的硬卡点脚本。"""
  return f"""#!/usr/bin/env sh
set -e

CHANGED_LLM_FILES=$(git diff --cached --name-only | grep -E '^(prompts/|configs/llm|evals/model_config)' || true)
if [ -n "$CHANGED_LLM_FILES" ]; then
  echo "[llm-change-gate] 检测到 Prompt / 模型配置变更，正在运行基线防退化硬卡点..."
  python3 {gate_script_rel} --baseline evals/baseline.json --candidate evals/latest.json
fi
"""


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="LLM 变更上线防退化硬闸门")
  parser.add_argument("--baseline", help="基线评测 JSON 路径")
  parser.add_argument("--candidate", help="本次候选评测 JSON 路径")
  parser.add_argument("--scenarios", help="集成演练套件 JSON 路径（含 baseline / snapshots）")
  parser.add_argument("--target", default="candidate_healthy", help="演练候选键名")
  parser.add_argument("--rollback", help="需要回滚到的目标快照版本号")
  args = parser.parse_args(argv)

  if args.rollback and args.scenarios:
    bundle = json.loads(pathlib.Path(args.scenarios).read_text(encoding="utf-8"))
    restored = rollback_to_snapshot(bundle["snapshots"], args.rollback)
    print(json.dumps(restored, ensure_ascii=False, indent=2))
    return 0

  if args.scenarios:
    bundle = json.loads(pathlib.Path(args.scenarios).read_text(encoding="utf-8"))
    report = evaluate_change(bundle["baseline"], bundle[args.target])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "PASS" else 1

  if args.baseline and args.candidate:
    base_data = json.loads(pathlib.Path(args.baseline).read_text(encoding="utf-8"))
    cand_data = json.loads(pathlib.Path(args.candidate).read_text(encoding="utf-8"))
    report = evaluate_change(base_data, cand_data)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "PASS" else 1

  parser.print_help()
  return 1


if __name__ == "__main__":
  sys.exit(main())
