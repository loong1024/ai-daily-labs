"""S5-M01 多工具 1 页纸规则文件桥接与对照实验验证（Starter 待完善版）。

当前存在以下缺陷：
1. build_multitool_adapters 生成了非标准的 AI_NOTES.txt，Claude Code / Cursor / Copilot 均无法自动载入；
2. audit_rules_doc 尚未校验 ≤60 行上限、真实命令对齐、禁改目录与零废话零密钥；
3. evaluate_onboarding_tasks 尚未基于自载入规则消除裸奔对照组的踩坑问题。
"""

from __future__ import annotations

from typing import Any, Callable


def build_multitool_adapters(agents_md_rel: str = "AGENTS.md") -> dict[str, str]:
  """TODO: 生成 Claude Code (CLAUDE.md)、Cursor (.cursor/rules/project.mdc) 与
  GitHub Copilot (.github/copilot-instructions.md) 的自动载入桥接内容。
  """
  return {
      "AI_NOTES.txt": f"请手动去读 {agents_md_rel}",
  }


def audit_rules_doc(markdown_text: str, manifest: dict[str, Any]) -> dict[str, Any]:
  """TODO: 审计 AGENTS.md 是否满足 ≤60 行、四段式结构、真实命令、禁改目录与零废话零密钥。"""
  lines = markdown_text.strip().splitlines()
  return {
      "line_count": len(lines),
      "within_line_limit": False,
      "missing_sections": manifest.get("required_sections", []),
      "missing_commands": list(manifest.get("valid_commands", {}).values()),
      "stale_commands_found": [],
      "missing_forbidden_paths": manifest.get("forbidden_paths", []),
      "bloat_phrases_found": [],
      "secrets_found": [],
      "passed": False,
  }


def evaluate_onboarding_tasks(
    markdown_text: str,
    adapters: dict[str, str],
    baseline_log: dict[str, Any],
    manifest: dict[str, Any],
    chat_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
  """TODO: 验证四类客户端自动载入状态，并在 4 项典型开发任务上复测实验组表现。"""
  return {
      "auto_loaded_clients": [],
      "tasks_total": len(baseline_log.get("tasks", [])),
      "tasks_passed": 0,
      "forbidden_touches": 1,
      "pitfalls_eliminated": 0,
  }
