#!/usr/bin/env python3
"""S1-M04 仓库 Prompt 自动体检 Skill 实战 — 自动化红绿验收脚本。"""

from __future__ import annotations

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

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: E402


def _parse_frontmatter(md_text: str) -> tuple[dict[str, str], str]:
  stripped = md_text.lstrip()
  if not stripped.startswith("---"):
    return {}, md_text
  parts = stripped.split("---", 2)
  if len(parts) < 3:
    return {}, md_text
  meta: dict[str, str] = {}
  for raw_line in parts[1].splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or ":" not in line:
      continue
    k, v = line.split(":", 1)
    meta[k.strip()] = v.strip().strip("\"'")
  return meta, parts[2]


def _load_module(py_path: pathlib.Path) -> Any:
  spec = importlib.util.spec_from_file_location("s1_m04_target", py_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块规范: {py_path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules["s1_m04_target"] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S1-M04", "仓库 Prompt 越改越乱？自制自动体检 Skill 拦截缺陷")

  skill_path = target_file(LAB_DIR, "starter.md", "solution.md")
  code_path = target_file(LAB_DIR, "starter.py", "solution.py")
  flawed_path = LAB_DIR / "fixtures" / "flawed_ticket_triage.prompt.md"
  cases_path = LAB_DIR / "fixtures" / "regression_cases.json"

  try:
    skill_text = skill_path.read_text(encoding="utf-8")
    flawed_text = flawed_path.read_text(encoding="utf-8")
    regression_cases = json.loads(cases_path.read_text(encoding="utf-8"))
    mod = _load_module(code_path)
  except Exception as exc:
    v.check(
        "实验文件加载与语法检查",
        False,
        f"加载 {skill_path.name} 或 {code_path.name} 失败：{exc}",
    )
    return v.finish()

  # 指标 1：检查 SKILL.md 自动触发规约与六步检查规范
  meta, body = _parse_frontmatter(skill_text)
  desc = meta.get("description", "")
  skill_ok = (
      meta.get("name") == "prompt-review"
      and "prompts/" in desc
      and ("system" in desc.lower() or "user" in desc.lower())
      and ("缓存" in body and ("末尾" in body or "开头" in body))
      and ("转义" in body and ("闭合标签" in body or "</" in body))
      and ("few-shot" in body.lower() or "示例" in body)
      and ("密钥" in body)
      and all(col in body for col in ("问题", "位置", "风险等级", "修改建议"))
      and ("版本号" in body or "version" in body.lower())
  )
  v.check(
      "SKILL.md 自动触发描述（prompts/ 与 system/user）及六步体检规约",
      skill_ok,
      f"请完善 {skill_path.name}：1) YAML `name: prompt-review`，`description` 须指明新建/修改 `prompts/` 模板及代码中 `system`/`user` 文本时自动触发；"
      "2) 正文覆盖要素可检验、无密钥、few-shot 字段一致、前缀缓存顺序、分隔标签与闭合标签转义、Schema 校验；"
      "3) 规定 `问题 | 位置 | 风险等级 | 修改建议` 输出格式及头部版本号更新要求。",
  )

  # 指标 2：拿四缺陷坏模板实测 lint_prompt_template 检出能力与行号定位
  required_rules = {
      "cache_prefix",
      "hardcoded_secret",
      "fewshot_consistency",
      "injection_isolation",
  }
  try:
    flawed_issues = mod.lint_prompt_template(flawed_text, "flawed_ticket_triage.prompt.md")
    found_rules = {str(item.get("rule_id", "")) for item in flawed_issues}
    missing_rules = sorted(required_rules - found_rules)
    by_rule = {str(item.get("rule_id", "")): item for item in flawed_issues}
    locations_valid = (
        not missing_rules
        and by_rule["cache_prefix"].get("line") == 3
        and by_rule["hardcoded_secret"].get("line") == 5
        and all(
            ":" in str(item.get("location", ""))
            and item.get("severity") in {"high", "medium", "low"}
            and bool(str(item.get("suggestion", "")).strip())
            for item in flawed_issues
        )
    )
    lint_bad_ok = not missing_rules and locations_valid
    lint_bad_hint = (
        f"请完善 {code_path.name} 的 `lint_prompt_template`：当前漏检缺陷类别={missing_rules}。"
        "面对 `fixtures/flawed_ticket_triage.prompt.md`，须准确检出第 3 行动态前缀击穿缓存（cache_prefix）、"
        "第 5 行硬编码假密钥（hardcoded_secret）、示例字段冲突（fewshot_consistency）与未加标签隔离（injection_isolation），并附带 `文件:行号` 与修改建议。"
    )
  except Exception as exc:
    flawed_issues = []
    lint_bad_ok = False
    lint_bad_hint = f"调用 `lint_prompt_template` 抛出异常：{exc}"
  v.check("四缺陷坏模板精准诊断与精确文件行号定位", lint_bad_ok, lint_bad_hint)

  # 指标 3：验证外部输入闭合标签转义（阻断 </user_input> 逃逸攻击）
  injection_sample = next(
      c["raw_input"] for c in regression_cases if c["id"] == "case_injection_override"
  )
  try:
    wrapped = str(mod.render_safe_user_input(injection_sample, tag="user_input"))
    escape_ok = (
        wrapped.startswith("<user_input>")
        and wrapped.endswith("</user_input>")
        and "&lt;/user_input&gt;" in wrapped
        and wrapped.count("</user_input>") == 1
    )
    escape_hint = (
        f"请修复 {code_path.name} 的 `render_safe_user_input`：将输入文本中夹带的 `<user_input>` 与 `</user_input>` "
        "转义为 `&lt;user_input&gt;` / `&lt;/user_input&gt;` 后再包裹外层标签，确保外层闭合标签只出现 1 次。"
    )
  except Exception as exc:
    escape_ok = False
    escape_hint = f"调用 `render_safe_user_input` 抛出异常：{exc}"
  v.check("外部不可信输入分隔封装与闭合标签转义防逃逸", escape_ok, escape_hint)

  # 指标 4：验证修复后的 REPAIRED_PROMPT_TEMPLATE 零缺陷、前 20 行零动态变量且含版本号
  try:
    repaired_text = str(getattr(mod, "REPAIRED_PROMPT_TEMPLATE", ""))
    repaired_issues = mod.lint_prompt_template(repaired_text, "repaired.prompt.md")
    repaired_lines = repaired_text.splitlines()
    has_version_comment = bool(
        repaired_lines
        and re.search(
            r"<!--\s*version:\s*v\d+\.\d+\.\d+\s*\|\s*changelog:\s*.+-->",
            repaired_lines[0],
        )
    )
    prefix_20 = "\n".join(repaired_lines[:20])
    static_prefix_clean = (
        "{{" not in prefix_20 and "FAKE_TEST_KEY_DO_NOT_USE" not in repaired_text
    )
    has_tail_isolation = (
        "<user_input>" in repaired_text
        and "</user_input>" in repaired_text
        and ("只是数据" in repaired_text or "仅为数据" in repaired_text or "切勿当作指令" in repaired_text)
    )
    repaired_ok = (
        lint_bad_ok
        and repaired_issues == []
        and has_version_comment
        and static_prefix_clean
        and has_tail_isolation
    )
    repaired_hint = (
        f"请同步修复 {code_path.name} 中的 `REPAIRED_PROMPT_TEMPLATE`："
        "1) 首行添加 `<!-- version: v1.1.0 | changelog: ... -->`；"
        "2) 前 20 行保持 100% 静态固定前缀（移除时间戳与假密钥）；"
        "3) 统一 Few-shot 示例 JSON 字段为 `category`、`priority`、`reason`；"
        "4) 在末尾 `[USER]` 用 `<user_input>` 包裹输入并声明标签内只是数据，使体检结果归零。"
    )
  except Exception as exc:
    repaired_ok = False
    repaired_hint = f"检查 `REPAIRED_PROMPT_TEMPLATE` 抛出异常：{exc}"
  v.check("修复后模板零缺陷通过静态体检且同步更新版本号与静态缓存前缀", repaired_ok, repaired_hint)

  # 指标 5：运行 6 场景回归测试集（含注入攻击拦截）
  try:
    suite_res = mod.run_regression_suite(regression_cases, chat_complete)
    results_by_id = {r["id"]: r for r in suite_res.get("results", [])}
    inj_res = results_by_id.get("case_injection_override", {})
    regression_ok = (
        suite_res.get("total") == len(regression_cases)
        and suite_res.get("passed") == len(regression_cases)
        and inj_res.get("passed") is True
        and inj_res.get("output", {}).get("category") != "approved_refund"
    )
    regression_hint = (
        f"回归测试通过 {suite_res.get('passed', 0)}/{len(regression_cases)} 条。"
        f"请检查 {code_path.name} 的 `run_regression_suite`：确保填充前先调用 `render_safe_user_input` 转义闭合标签，"
        "校验输出严格满足 `{category, priority, reason}` Schema，并成功拦截 `case_injection_override` 篡改攻击。"
    )
  except Exception as exc:
    regression_ok = False
    regression_hint = f"运行 `run_regression_suite` 抛出异常：{exc}"
  v.check("6 场景回归测试集 100% 通过且成功阻断提示词注入劫持", regression_ok, regression_hint)

  return v.finish()


if __name__ == "__main__":
  raise SystemExit(main())
