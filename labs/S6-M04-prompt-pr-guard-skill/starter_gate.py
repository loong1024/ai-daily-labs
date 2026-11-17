#!/usr/bin/env python3
"""LLM 变更防退化闸门脚本（Starter 待完善版）。"""

from __future__ import annotations

from typing import Any


def _pass_rate(cases: list[dict[str, Any]]) -> float:
  if not cases:
    return 0.0
  return sum(1 for c in cases if c.get("passed")) / len(cases)


def evaluate_change(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    change_meta: dict[str, str] | None = None,
) -> dict[str, Any]:
  """对比候选评测结果与基线（Starter 缺陷：只看总体通过率，漏检 critical 退化与删题作弊）。"""
  del change_meta
  base_cases = baseline.get("cases", [])
  cand_cases = candidate.get("cases", [])

  base_rate = _pass_rate(base_cases)
  cand_rate = _pass_rate(cand_cases)

  # TODO 1：检查候选集是否缺失了基线用例（防删题作弊）
  # TODO 2：逐条找出由 passed=True 变为 passed=False 的用例，并对 critical=True 用例实施一票否决
  # TODO 3：统计平均 tokens 与 P95 延迟变化
  passed = cand_rate >= base_rate
  return {
      "verdict": "PASS" if passed else "FAIL",
      "baseline_pass_rate": round(base_rate, 4),
      "candidate_pass_rate": round(cand_rate, 4),
      "regressed_cases": [],
      "critical_regressions": [],
      "improved_cases": [],
      "missing_cases": [],
  }


def format_changelog_entry(report: dict[str, Any], change_meta: dict[str, str]) -> str:
  """生成 CHANGELOG-llm.md 记录条目（Starter 缺陷：缺少前后对比指标与回滚命令）。"""
  del report
  # TODO：补充改动原因、通过率/critical/token/P95 延迟前后对比，以及明确的一键回滚命令
  return f"## {change_meta.get('version', 'unknown')}\n- 改动：{change_meta.get('summary', '')}\n"


def rollback_to_snapshot(
    snapshots_state: dict[str, Any], target_version: str
) -> dict[str, Any]:
  """一键切回指定历史快照版本（Starter 尚未实现）。"""
  del target_version
  # TODO：校验 target_version 存在于 snapshots 中，并将 active_version 与 active_prompt_sha256 切回目标快照
  return snapshots_state


def render_pre_commit_hook(gate_script_rel: str = "solution_gate.py") -> str:
  """生成 Git pre-commit 钩子脚本内容（Starter 尚未阻断提交）。"""
  del gate_script_rel
  # TODO：当 git diff --cached 命中 prompts/ 或模型配置文件时自动执行闸门检查，失败 exit 1
  return "#!/usr/bin/env sh\necho 'TODO: configure pre-commit gate'\nexit 0\n"
