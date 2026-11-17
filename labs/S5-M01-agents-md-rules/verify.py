#!/usr/bin/env python3
"""S5-M01 多工具 1 页纸规则文件实战 — 自动化红绿验收脚本。"""

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

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: E402


def _load_module(py_path: pathlib.Path) -> Any:
  spec = importlib.util.spec_from_file_location("s5_m01_target", py_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块规范: {py_path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules["s5_m01_target"] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S5-M01", "规则总不生效？45分钟配通多工具1页纸规则文件")

  rules_path = target_file(LAB_DIR, "starter.md", "solution.md")
  code_path = target_file(LAB_DIR, "starter.py", "solution.py")
  manifest_path = LAB_DIR / "fixtures" / "project_manifest.json"
  baseline_path = LAB_DIR / "fixtures" / "baseline_control_log.json"

  try:
    rules_text = rules_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline_log = json.loads(baseline_path.read_text(encoding="utf-8"))
    mod = _load_module(code_path)
  except Exception as exc:
    v.check(
        "实验文件加载与语法检查",
        False,
        f"加载 {rules_path.name} 或 {code_path.name} 失败：{exc}",
    )
    return v.finish()

  # 指标 1：检查主规则文件篇幅（≤60 行）、四段式骨架与零废话零密钥
  lines = rules_text.strip().splitlines()
  line_count = len(lines)
  missing_sections = [s for s in manifest["required_sections"] if s not in rules_text]
  bloat_hits = [b for b in manifest["generic_bloat_phrases"] if b in rules_text]
  has_secret = "FAKE_TEST_KEY_DO_NOT_USE" in rules_text
  budget_ok = (
      10 <= line_count <= int(manifest["max_lines"])
      and not missing_sections
      and not bloat_hits
      and not has_secret
  )
  v.check(
      f"主规则文件精简预算（当前 {line_count} 行，要求 ≤60 行）且零废话零密钥",
      budget_ok,
      f"请精简 {rules_path.name}：当前共 {line_count} 行，缺少章节={missing_sections}，"
      f"检出通用废话={bloat_hits}，含测试密钥={has_secret}。"
      "请删去 SOLID/PEP8 等通用编程说教与任何密钥，保留 `## 命令 / ## 约定 / ## 禁区 / ## 常见坑` 且总行数 ≤60 行。",
  )

  # 指标 2：检查规则文件中的安装、单测、全量体检与代码生成命令 100% 真实对齐且零过期命令
  missing_cmds = [
      cmd for cmd in manifest["valid_commands"].values() if cmd not in rules_text
  ]
  stale_hits = [
      bad for bad in manifest["stale_or_wrong_commands"] if bad in rules_text
  ]
  cmds_ok = not missing_cmds and not stale_hits
  v.check(
      "安装、单测与提交前体检命令 100% 真实可跑通且零过期幻觉命令",
      cmds_ok,
      f"请修正 {rules_path.name} 的 `## 命令`：缺少真实命令={missing_cmds}，残留过期命令={stale_hits}。"
      "须写明 `uv sync --frozen`、`uv run pytest`、`uv run ruff check . && uv run mypy src && uv run pytest` "
      "与 `uv run python scripts/gen_schema.py`，并彻底删除 `pip install -r`、`poetry`、`flake8` 等旧指令。",
  )

  # 指标 3：检查禁改目录红线、错误处理约定与集成测试常见坑完整覆盖
  missing_forbid = [p for p in manifest["forbidden_paths"] if p not in rules_text]
  missing_conv = [c for c in manifest["required_conventions"] if c not in rules_text]
  missing_gotchas = [g for g in manifest["required_gotchas"] if g not in rules_text]
  has_dep_rule = ("依赖" in rules_text) or ("pyproject.toml" in rules_text)
  guards_ok = (
      not missing_forbid
      and not missing_conv
      and not missing_gotchas
      and has_dep_rule
  )
  v.check(
      "禁改生成目录红线、AppError 约定与内存数据库常见坑完整覆盖",
      guards_ok,
      f"请补齐 {rules_path.name}：缺少禁改目录={missing_forbid}，缺少约定关键词={missing_conv}，"
      f"缺少常见坑={missing_gotchas}，新增依赖约束={has_dep_rule}。",
  )

  # 指标 4：检查多客户端自动载入桥接文件（Claude Code / Cursor / GitHub Copilot）
  try:
    adapters = mod.build_multitool_adapters("AGENTS.md")
    claude_ok = "@AGENTS.md" in str(adapters.get("CLAUDE.md", ""))
    cursor_txt = str(adapters.get(".cursor/rules/project.mdc", ""))
    cursor_ok = (
        cursor_txt.lstrip().startswith("---")
        and "alwaysApply: true" in cursor_txt
        and "AGENTS.md" in cursor_txt
    )
    copilot_ok = "AGENTS.md" in str(adapters.get(".github/copilot-instructions.md", ""))
    bridge_ok = claude_ok and cursor_ok and copilot_ok
    bridge_hint = (
        f"请完善 {code_path.name} 的 `build_multitool_adapters`："
        "1) `CLAUDE.md` 包含 `@AGENTS.md` 引用；"
        "2) `.cursor/rules/project.mdc` 包含 `alwaysApply: true` 的 YAML Frontmatter 并指向 `AGENTS.md`；"
        "3) `.github/copilot-instructions.md` 指向根目录 `AGENTS.md` 权威规范。"
    )
  except Exception as exc:
    adapters = {}
    bridge_ok = False
    bridge_hint = f"调用 `build_multitool_adapters` 抛出异常：{exc}"
  v.check("多工具自动载入桥接配置（Codex / Claude Code / Cursor / Copilot）", bridge_ok, bridge_hint)

  # 指标 5：运行对照组 vs 实验组新会话实测，验证首轮跑对单测且零触碰禁区
  try:
    audit_res = mod.audit_rules_doc(rules_text, manifest)
    eval_res = mod.evaluate_onboarding_tasks(
        rules_text, adapters, baseline_log, manifest, chat_complete
    )
    expected_clients = {"codex", "claude_code", "cursor", "copilot"}
    actual_clients = set(eval_res.get("auto_loaded_clients", []))
    total_tasks = len(baseline_log["tasks"])
    sim_ok = (
        budget_ok
        and cmds_ok
        and guards_ok
        and bridge_ok
        and bool(audit_res.get("passed"))
        and actual_clients == expected_clients
        and eval_res.get("tasks_passed") == total_tasks
        and eval_res.get("forbidden_touches") == 0
        and int(eval_res.get("pitfalls_eliminated", 0)) >= total_tasks
    )
    sim_hint = (
        f"请完善 {code_path.name} 的 `audit_rules_doc` 与 `evaluate_onboarding_tasks`："
        f"当前自动载入客户端={sorted(actual_clients)}（需覆盖四端），"
        f"任务通过={eval_res.get('tasks_passed', 0)}/{total_tasks}，"
        f"误触禁区次数={eval_res.get('forbidden_touches', -1)}。"
    )
  except Exception as exc:
    sim_ok = False
    sim_hint = f"调用对照验证函数抛出异常：{exc}"
  v.check("对照组 vs 实验组会话实测（四端全载入、首轮跑对测试且零触碰禁区）", sim_ok, sim_hint)

  return v.finish()


if __name__ == "__main__":
  raise SystemExit(main())
