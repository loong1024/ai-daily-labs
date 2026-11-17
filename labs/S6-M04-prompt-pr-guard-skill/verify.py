#!/usr/bin/env python3
"""S6-M04 实验验收脚本：检验 llm-change-gate Skill 规范与硬闸门红蓝对抗效果。"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_gate_module(path: pathlib.Path):
  spec = importlib.util.spec_from_file_location("aid_llm_gate_mod", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod
  spec.loader.exec_module(mod)
  return mod


def _check_skill_markdown(text: str) -> tuple[bool, list[str]]:
  issues: list[str] = []
  fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
  if not fm_match:
    issues.append("缺少顶部 YAML Frontmatter（`--- ... ---`）")
  else:
    fm = fm_match.group(1)
    if "name: llm-change-gate" not in fm:
      issues.append("Frontmatter 缺少 `name: llm-change-gate`")
    if "description:" not in fm or "Prompt" not in fm:
      issues.append("Frontmatter `description` 未清晰声明触发场景")

  if "prompts/" not in text or "temperature" not in text:
    issues.append("缺少 `prompts/` 目录及采样参数（如 `temperature`）/检索配置触发条件")
  if "critical" not in text:
    issues.append("缺少 `critical` 高危用例一票否决硬门槛说明")
  if "CHANGELOG-llm.md" not in text:
    issues.append("缺少 `CHANGELOG-llm.md` 变更日志约定")
  if not any(kw in text for kw in ("修改或删除评测用例", "删除评测用例", "删改评测用例")):
    issues.append("缺少禁止为凑通过率擅自修改或删除评测用例的防作弊红线")
  return (len(issues) == 0, issues)


def main() -> int:
  v = LabVerifier("S6-M04", "Agent 改提示词就乱提交？装 Skill 搭防退化闸门")

  skill_path = target_file(LAB_DIR, "starter_skill.md", "solution_skill.md")
  gate_path = target_file(LAB_DIR, "starter_gate.py", "solution_gate.py")

  try:
    skill_text = skill_path.read_text(encoding="utf-8")
    gate_mod = _load_gate_module(gate_path)
    bundle = json.loads((LAB_DIR / "fixtures" / "eval_scenarios.json").read_text(encoding="utf-8"))
    baseline = bundle["baseline"]
    cand_regressed = bundle["candidate_regressed"]
    cand_healthy = bundle["candidate_healthy"]
    snapshots = bundle["snapshots"]
  except Exception as exc:
    v.check("加载 Skill、闸门模块与测试集", False, f"加载异常：{exc}")
    return v.finish()

  skill_ok, skill_issues = _check_skill_markdown(skill_text)
  v.check(
      "llm-change-gate SKILL.md 规范头部、触发范围与防删题契约完整",
      skill_ok,
      "请完善 starter_skill.md：" + "；".join(skill_issues),
  )

  red_ok = False
  red_hint = ""
  try:
    reg_report: dict[str, Any] = gate_mod.evaluate_change(baseline, cand_regressed)
    tampered = copy.deepcopy(cand_healthy)
    tampered["cases"] = [c for c in tampered["cases"] if c["id"] != "CRIT-02"]
    tamper_report: dict[str, Any] = gate_mod.evaluate_change(baseline, tampered)

    blocked_crit = (
        reg_report.get("verdict") == "FAIL"
        and "CRIT-02" in reg_report.get("critical_regressions", [])
    )
    blocked_tamper = (
        tamper_report.get("verdict") == "FAIL"
        and "CRIT-02" in tamper_report.get("missing_cases", [])
    )
    red_ok = blocked_crit and blocked_tamper
    if not red_ok:
      red_hint = (
          f"高危退化判定={reg_report.get('verdict')} (critical_regressions={reg_report.get('critical_regressions')})，"
          f"删题作弊判定={tamper_report.get('verdict')} (missing_cases={tamper_report.get('missing_cases')})。"
          "请在 evaluate_change 中实现 critical 用例一票否决与缺失用例检测，不能只看总体通过率！"
      )
  except Exception as exc:
    red_hint = f"evaluate_change 执行出错：{exc}"

  v.check(
      "红队拦截：总体涨分但 Critical 用例退化（及删减用例）时 100% 拒绝放行",
      red_ok,
      red_hint,
  )

  green_ok = False
  green_hint = ""
  try:
    ok_report = gate_mod.evaluate_change(baseline, cand_healthy)
    entry = gate_mod.format_changelog_entry(
        ok_report,
        {
            "version": "v1.3.0",
            "date": "2026-11-16",
            "summary": "收紧越权退款约束并优化多语言邮件润色提示词",
            "reason": "修复 CRIT-02 越权退款漏洞，同时保留常规润色题涨分",
            "rollback_cmd": "python3 solution_gate.py --rollback v1.2.0 --scenarios fixtures/eval_scenarios.json",
        },
    )
    has_metrics = all(
        token in entry
        for token in ("80.0%", "90.0%", "4/4", "Token", "P95", "--rollback v1.2.0", "修复 CRIT-02")
    )
    green_ok = ok_report.get("verdict") == "PASS" and has_metrics
    if not green_ok:
      green_hint = (
          "请在 format_changelog_entry 中完整输出改动原因、前后通过率（80.0% -> 90.0%）、"
          "Critical 通过数（4/4）、平均 Token、P95 延迟与一键回滚命令（--rollback v1.2.0）。"
      )
  except Exception as exc:
    green_hint = f"生成变更日志异常：{exc}"

  v.check(
      "绿队放行并生成含改动原因、对比指标与回滚命令的 CHANGELOG 条目",
      green_ok,
      green_hint,
  )

  ops_ok = False
  ops_hint = ""
  try:
    restored = gate_mod.rollback_to_snapshot(snapshots, "v1.2.0")
    hook_text = gate_mod.render_pre_commit_hook("solution_gate.py")
    rollback_valid = (
        restored.get("active_version") == "v1.2.0"
        and restored.get("active_prompt_sha256") == baseline["prompt_sha256"]
        and snapshots.get("active_version") == "v1.3.0-rc1"
    )
    hook_valid = (
        "git diff --cached" in hook_text
        and "prompts/" in hook_text
        and ("set -e" in hook_text or "exit 1" in hook_text)
        and "--baseline" in hook_text
    )
    ops_ok = rollback_valid and hook_valid
    if not ops_ok:
      ops_hint = (
          f"快照回滚后 active_version={restored.get('active_version')} "
          f"(sha256={restored.get('active_prompt_sha256')})，hook_valid={hook_valid}。"
          "请完善 rollback_to_snapshot（切回 v1.2.0 快照哈希且不原地破坏入参）与 render_pre_commit_hook（检测暂存区 prompts/ 并执行基线阻断检查）。"
      )
  except Exception as exc:
    ops_hint = f"回滚或钩子生成异常：{exc}"

  v.check(
      "一键切回 v1.2.0 稳定快照恢复基线，并具备有效的 Git pre-commit 阻断钩子",
      ops_ok,
      ops_hint,
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
