#!/usr/bin/env python3
"""S0-M04 提交前密钥安检 Skill 实战 — 自动化红绿验收脚本。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tomllib
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
  spec = importlib.util.spec_from_file_location("s0_m04_target", py_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块规范: {py_path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules["s0_m04_target"] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S0-M04", "怕误推密钥上仓库？提交前密钥安检 Skill 实战")

  skill_path = target_file(LAB_DIR, "starter.md", "solution.md")
  code_path = target_file(LAB_DIR, "starter.py", "solution.py")
  fixture_path = LAB_DIR / "fixtures" / "repo_changes.json"
  toml_path = LAB_DIR / "fixtures" / "gitleaks_allowlist_sample.toml"

  try:
    fixture_data = json.loads(fixture_path.read_text(encoding="utf-8"))
    _ = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    skill_text = skill_path.read_text(encoding="utf-8")
    mod = _load_module(code_path)
  except Exception as exc:
    v.check(
        "实验文件加载与语法检查",
        False,
        f"加载 {skill_path.name} 或 {code_path.name} 出错：{exc}",
    )
    return v.finish()

  # 指标 1：检查 SKILL.md 触发条件与五步全覆盖检查规范
  meta, body = _parse_frontmatter(skill_text)
  desc = meta.get("description", "")
  trigger_hits = sum(1 for kw in ("提交", "推送", "开源", "泄露") if kw in desc)
  has_steps = (
      meta.get("name") == "secret-hygiene-check"
      and trigger_hits >= 3
      and (".env" in desc or ".gitignore" in desc)
      and "gitleaks version" in body
      and "gitleaks dir" in body
      and "gitleaks git" in body
      and ".gitignore" in body
      and "os.environ" in body
      and ".env.example" in body
      and ("前端" in body or "浏览器" in body)
  )
  v.check(
      "SKILL.md 触发元数据与双模扫描步骤（工作区 + Git 历史 + 前端检查）",
      has_steps,
      f"请在 {skill_path.name} 补齐 YAML description 触发场景（提交前/推送前/开源/泄露及 .env/.gitignore），"
      "并在检查步骤中完整覆盖 `gitleaks version`、`gitleaks dir`、`gitleaks git` 历史扫描、"
      "`.gitignore`/`os.environ`/`.env.example` 核查及前端代码零密钥检查。",
  )

  # 指标 2：检查 SKILL.md 脱敏规范、先吊销后清历史顺序与安全禁令
  idx_revoke = -1
  for kw in ("吊销", "轮换"):
    pos = body.find(kw)
    if pos != -1 and (idx_revoke == -1 or pos < idx_revoke):
      idx_revoke = pos
  idx_history_clean = -1
  for kw in ("清理历史", "清理仓库历史", "filter-repo"):
    pos = body.find(kw)
    if pos != -1 and (idx_history_clean == -1 or pos < idx_history_clean):
      idx_history_clean = pos

  has_mask_spec = ("前 4 位" in body or "前4位" in body) and "*" in body
  has_safe_order = (
      "控制台" in body
      and idx_revoke != -1
      and idx_history_clean != -1
      and idx_revoke < idx_history_clean
  )
  has_prohibitions = (
      "完整密钥" in body
      and ("未经用户" in body or "明确确认" in body)
      and ("强制推送" in body or "--force" in body)
  )
  v.check(
      "SKILL.md 脱敏遮盖规范与“先控制台吊销、后清理历史”红线",
      has_mask_spec and has_safe_order and has_prohibitions,
      f"请在 {skill_path.name} 明确要求输出仅保留密钥前 4 位并用 `*` 遮盖；"
      "应急处置第一优先级必须是前往服务商控制台吊销并轮换密钥，之后再清理 Git 历史；"
      "并在禁止事项中写明严禁输出完整密钥、未经用户明确确认严禁执行强制推送或改写历史。",
  )

  # 指标 3：拿 fixtures 红蓝样本实测检出率与 .env.example 免误报
  changes: list[dict[str, Any]] = fixture_data["changes"]
  expected_flagged = {c["id"] for c in changes if c["should_flag"]}
  expected_clean = {c["id"] for c in changes if not c["should_flag"]}
  try:
    findings = mod.scan_repo_changes(changes)
    actual_flagged = {str(f.get("id", "")) for f in findings}
    false_negatives = sorted(expected_flagged - actual_flagged)
    false_positives = sorted(actual_flagged & expected_clean)
    scan_ok = (actual_flagged == expected_flagged) and not false_positives
    scan_hint = (
        f"请改进 {code_path.name} 的 `scan_repo_changes`：当前漏检={false_negatives}，误报={false_positives}。"
        "需同时扫描 `worktree` 与 `git_history`（覆盖 .py、.env 与前端代码），并放行 `.env.example` 及安全占位符。"
    )
  except Exception as exc:
    findings = []
    scan_ok = False
    scan_hint = f"调用 `scan_repo_changes` 抛出异常：{exc}"
  v.check("红蓝对抗样本精准检出（含 Git 历史与前端泄露）且占位模板零误报", scan_ok, scan_hint)

  # 指标 4：验证脱敏函数与安检报告绝不泄露完整假密钥原文
  try:
    sample_masked = str(mod.mask_secret("FAKE_TEST_KEY_DO_NOT_USE_9876543210ABCDEF"))
    report_text = str(mod.format_audit_report(findings, [".env"]))
    raw_secrets = [c["secret_value"] for c in changes if c["secret_value"]]
    leaked_in_report = [s[:12] + "..." for s in raw_secrets if s in report_text]
    expected_prefixes = ["FAKE****", "DEMO****", "MOCK****", "TEST****"]
    prefixes_present = all(p in report_text for p in expected_prefixes)
    mask_ok = (
        sample_masked.startswith("FAKE****")
        and "DO_NOT_USE" not in sample_masked
        and "9876543210" not in sample_masked
        and not leaked_in_report
        and prefixes_present
    )
    mask_hint = (
        f"请修复 {code_path.name} 的 `mask_secret` 与 `format_audit_report`："
        "只保留密钥前 4 位并拼接 `*` 号遮盖（如 `FAKE********`），严禁在报告中出现完整密钥字符串。"
    )
  except Exception as exc:
    mask_ok = False
    mask_hint = f"调用 `mask_secret` / `format_audit_report` 抛出异常：{exc}"
  v.check("检查报告敏感片段遮盖保护（仅显示前 4 位 + 星号）", mask_ok, mask_hint)

  # 指标 5：验证本地 pre-commit 钩子硬阻断退出码契约
  clean_only = [c for c in changes if not c["should_flag"]]
  broken_gitignore = fixture_data["gitignore_entries_broken"]
  secure_gitignore = fixture_data["gitignore_entries_secure"]
  try:
    res_dirty = mod.run_pre_commit_check(changes, secure_gitignore)
    res_bad_ignore = mod.run_pre_commit_check(clean_only, broken_gitignore)
    res_clean = mod.run_pre_commit_check(clean_only, secure_gitignore)
    hook_ok = (
        isinstance(res_dirty, dict)
        and int(res_dirty.get("exit_code", 0)) != 0
        and int(res_bad_ignore.get("exit_code", 0)) != 0
        and int(res_clean.get("exit_code", -1)) == 0
    )
    hook_hint = (
        f"请修复 {code_path.name} 的 `audit_gitignore` 与 `run_pre_commit_check`："
        "1) 含伪造密钥时必须返回非零 `exit_code`（如 1）硬阻断提交；"
        "2) `.gitignore` 缺少 `.env` 或 `*.pem` 时同样返回非零 `exit_code`；"
        "3) 仅含合规变更且 `.gitignore` 齐全时返回 `exit_code == 0`。"
    )
  except Exception as exc:
    hook_ok = False
    hook_hint = f"调用 `run_pre_commit_check` 抛出异常：{exc}"
  v.check("本地 pre-commit 钩子硬阻断退出码契约与 .gitignore 防线", hook_ok, hook_hint)

  return v.finish()


if __name__ == "__main__":
  raise SystemExit(main())
