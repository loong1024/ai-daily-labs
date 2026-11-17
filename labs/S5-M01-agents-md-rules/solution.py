"""S5-M01 多工具 1 页纸规则文件桥接与对照实验验证（Solution 标准参考实现）。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

FAKE_SECRET_RE = re.compile(
    r"(?:FAKE|DEMO|MOCK|TEST)_(?:TEST_)?(?:FAKE_)?KEY_DO_NOT_USE_[A-Za-z0-9_]+"
)


def build_multitool_adapters(agents_md_rel: str = "AGENTS.md") -> dict[str, str]:
  """围绕单一事实源 AGENTS.md 生成各主流客户端可自动识别载入的轻量入口文件。"""
  claude_md = (
      f"@{agents_md_rel}\n\n"
      "<!-- Claude Code 会自动展开首行 @AGENTS.md，保持单一事实源零重复维护 -->\n"
  )
  cursor_mdc = (
      "---\n"
      "description: acme-invoice-api 核心构建测试命令、代码约定与禁改目录红线\n"
      'globs: "**/*"\n'
      "alwaysApply: true\n"
      "---\n\n"
      f"请严格加载并遵守仓库根目录 `{agents_md_rel}` 中的命令、约定、禁区与常见坑规范。\n"
  )
  copilot_md = (
      "# GitHub Copilot Repository Instructions\n\n"
      f"本仓库唯一权威协作规范位于根目录 `{agents_md_rel}`：\n"
      "- 所有安装、单测与提交前检查统一通过 `uv` 执行（`uv run ruff check . && uv run mypy src && uv run pytest`）；\n"
      "- 严禁手动修改 `src/generated/`、`migrations/versions/` 与 `vendor/` 目录。\n"
  )
  return {
      "CLAUDE.md": claude_md,
      ".cursor/rules/project.mdc": cursor_mdc,
      ".github/copilot-instructions.md": copilot_md,
  }


def _extract_section(markdown_text: str, heading: str) -> str:
  lines = markdown_text.splitlines()
  start = -1
  for idx, line in enumerate(lines):
    if line.strip() == heading:
      start = idx + 1
      break
  if start == -1:
    return ""
  collected: list[str] = []
  for idx in range(start, len(lines)):
    if lines[idx].startswith("## "):
      break
    collected.append(lines[idx])
  return "\n".join(collected)


def audit_rules_doc(markdown_text: str, manifest: dict[str, Any]) -> dict[str, Any]:
  """对主规则文件执行量化体检：行数预算、四段结构、真实命令、禁区覆盖与零废话零密钥。"""
  lines = markdown_text.strip().splitlines()
  line_count = len(lines)
  max_lines = int(manifest.get("max_lines", 60))
  within_line_limit = 10 <= line_count <= max_lines

  missing_sections = [
      sec for sec in manifest.get("required_sections", []) if sec not in markdown_text
  ]

  cmd_section = _extract_section(markdown_text, "## 命令")
  conv_section = _extract_section(markdown_text, "## 约定")
  forbid_section = _extract_section(markdown_text, "## 禁区")
  gotcha_section = _extract_section(markdown_text, "## 常见坑")

  missing_commands = [
      cmd
      for cmd in manifest.get("valid_commands", {}).values()
      if cmd not in cmd_section
  ]
  stale_commands_found = [
      bad
      for bad in manifest.get("stale_or_wrong_commands", [])
      if bad in markdown_text
  ]
  missing_forbidden_paths = [
      p for p in manifest.get("forbidden_paths", []) if p not in forbid_section
  ]
  has_dependency_guard = ("依赖" in forbid_section) or ("pyproject.toml" in forbid_section)
  missing_conventions = [
      c for c in manifest.get("required_conventions", []) if c not in conv_section
  ]
  missing_gotchas = [
      g for g in manifest.get("required_gotchas", []) if g not in gotcha_section
  ]
  bloat_phrases_found = [
      phrase
      for phrase in manifest.get("generic_bloat_phrases", [])
      if phrase in markdown_text
  ]
  secrets_found = FAKE_SECRET_RE.findall(markdown_text)

  passed = (
      within_line_limit
      and not missing_sections
      and not missing_commands
      and not stale_commands_found
      and not missing_forbidden_paths
      and has_dependency_guard
      and not missing_conventions
      and not missing_gotchas
      and not bloat_phrases_found
      and not secrets_found
  )

  return {
      "line_count": line_count,
      "within_line_limit": within_line_limit,
      "missing_sections": missing_sections,
      "missing_commands": missing_commands,
      "stale_commands_found": stale_commands_found,
      "missing_forbidden_paths": missing_forbidden_paths,
      "has_dependency_guard": has_dependency_guard,
      "missing_conventions": missing_conventions,
      "missing_gotchas": missing_gotchas,
      "bloat_phrases_found": bloat_phrases_found,
      "secrets_found": secrets_found,
      "passed": passed,
  }


def detect_autoloaded_clients(
    has_root_agents_md: bool,
    adapters: dict[str, str],
) -> list[str]:
  """判定四大主流客户端（Codex / Claude Code / Cursor / Copilot）是否均能自动载入规则。"""
  loaded: list[str] = []
  if has_root_agents_md:
    loaded.append("codex")

  claude_content = adapters.get("CLAUDE.md", "")
  if "@AGENTS.md" in claude_content:
    loaded.append("claude_code")

  cursor_content = adapters.get(".cursor/rules/project.mdc", "")
  if (
      cursor_content.lstrip().startswith("---")
      and "alwaysApply: true" in cursor_content
      and "AGENTS.md" in cursor_content
  ):
    loaded.append("cursor")

  copilot_content = adapters.get(".github/copilot-instructions.md", "")
  if "AGENTS.md" in copilot_content:
    loaded.append("copilot")

  return loaded


def _plan_mock_from_rules(messages: list[dict[str, str]]) -> str:
  """根据会话自动载入的规则文本生成智能体执行计划（离线确定性仿真）。"""
  system_rules = messages[0]["content"]
  has_precheck = "uv run ruff check . && uv run mypy src && uv run pytest" in system_rules
  has_codegen = "uv run python scripts/gen_schema.py" in system_rules
  guards_generated = "src/generated/" in system_rules
  has_app_error = "AppError" in system_rules and "src/core/errors.py" in system_rules
  has_test_db = "TEST_DATABASE_URL=sqlite:///:memory:" in system_rules

  plans = {
      "task_1_tax_rounding": {
          "commands": (
              [
                  "uv run pytest tests/unit/test_tax.py",
                  "uv run ruff check . && uv run mypy src && uv run pytest",
              ]
              if has_precheck
              else ["poetry run pytest"]
          ),
          "edited_files": ["src/services/tax.py", "tests/unit/test_tax.py"],
      },
      "task_2_invoice_schema": {
          "commands": (
              ["uv run python scripts/gen_schema.py", "uv run mypy src"]
              if (has_codegen and guards_generated)
              else ["pytest"]
          ),
          "edited_files": (
              ["schemas/invoice.yaml"]
              if guards_generated
              else ["schemas/invoice.yaml", "src/generated/invoice_models.py"]
          ),
      },
      "task_3_api_error_handling": {
          "commands": (
              ["uv run ruff check . && uv run mypy src && uv run pytest"]
              if has_precheck
              else ["flake8 ."]
          ),
          "edited_files": (
              ["src/api/invoices.py", "tests/unit/test_invoices_api.py"]
              if has_app_error
              else ["src/api/invoices.py"]
          ),
          "error_helper": "AppError" if has_app_error else "ValueError",
      },
      "task_4_integration_suite": {
          "env": (
              {"TEST_DATABASE_URL": "sqlite:///:memory:"}
              if has_test_db
              else {}
          ),
          "commands": (
              ["uv run pytest tests/integration/test_billing_flow.py"]
              if has_precheck
              else ["nosetests"]
          ),
          "edited_files": [],
      },
  }
  return json.dumps(plans, ensure_ascii=False)


def evaluate_onboarding_tasks(
    markdown_text: str,
    adapters: dict[str, str],
    baseline_log: dict[str, Any],
    manifest: dict[str, Any],
    chat_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
  """对比裸奔对照组，验证自载入精简规则在新会话中的真实执行效果。"""
  audit = audit_rules_doc(markdown_text, manifest)
  clients = detect_autoloaded_clients(bool(markdown_text.strip()), adapters)

  messages = [
      {
          "role": "system",
          "content": (
              "以下是当前仓库自动载入的 AGENTS.md 规则，请严格据此规划 4 个任务的命令与修改文件 JSON：\n\n"
              f"{markdown_text}"
          ),
      },
      {
          "role": "user",
          "content": json.dumps(baseline_log.get("tasks", []), ensure_ascii=False),
      },
  ]

  raw_plan = _plan_mock_from_rules(messages)
  plans = json.loads(raw_plan)
  forbidden_prefixes = tuple(manifest.get("forbidden_paths", []))

  forbidden_touches = 0
  for task_plan in plans.values():
    for fpath in task_plan.get("edited_files", []):
      if str(fpath).startswith(forbidden_prefixes):
        forbidden_touches += 1

  t1_ok = "uv run ruff check . && uv run mypy src && uv run pytest" in plans["task_1_tax_rounding"]["commands"]
  t2_ok = (
      "uv run python scripts/gen_schema.py" in plans["task_2_invoice_schema"]["commands"]
      and forbidden_touches == 0
  )
  t3_ok = (
      plans["task_3_api_error_handling"].get("error_helper") == "AppError"
      and any(p.startswith("tests/") for p in plans["task_3_api_error_handling"]["edited_files"])
  )
  t4_ok = (
      plans["task_4_integration_suite"].get("env", {}).get("TEST_DATABASE_URL")
      == "sqlite:///:memory:"
  )

  task_flags = [t1_ok, t2_ok, t3_ok, t4_ok]
  tasks_passed = sum(1 for flag in task_flags if flag) if (len(clients) == 4 and audit["passed"]) else 0

  return {
      "auto_loaded_clients": clients,
      "tasks_total": len(baseline_log.get("tasks", [])),
      "tasks_passed": tasks_passed,
      "forbidden_touches": forbidden_touches,
      "pitfalls_eliminated": tasks_passed,
  }
