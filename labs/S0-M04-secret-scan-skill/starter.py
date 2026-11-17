"""S0-M04 提交前密钥安检与 pre-commit 守卫（Starter 待完善版）。

当前存在明显缺陷，请结合 README.md 与 verify.py 提示逐步修复：
1. mask_secret 直接返回了完整明文密钥，造成报告二次泄露；
2. scan_repo_changes 只扫描了 worktree 下的 .py 文件，漏掉了 .env、前端代码与 git_history 历史残留；
3. audit_gitignore 未校验 .env 与 *.pem 规则；
4. run_pre_commit_check 仅打印提示但始终返回 exit_code=0，无法阻断带病 git commit。
"""

from __future__ import annotations

import re
from typing import Any

RAW_ASSIGN_RE = re.compile(r"(?:API_KEY|SECRET|TOKEN)\s*=\s*['\"]?([A-Za-z0-9_<>\-]{10,})['\"]?")


def mask_secret(secret: str) -> str:
  """TODO: 只保留前 4 位字符，其余用 '*' 遮盖（如 'FAKE********'）。"""
  return secret


def audit_gitignore(entries: list[str]) -> list[str]:
  """TODO: 检查 .gitignore 条目是否覆盖 '.env' 与 '*.pem'，返回缺失项列表。"""
  return []


def scan_repo_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """扫描变更集中的伪造密钥泄露（当前基线版存在漏报与误报）。"""
  findings: list[dict[str, Any]] = []
  for item in changes:
    # 缺陷：漏扫 git_history 提交历史，且只看了 .py 文件
    if item.get("scope") != "worktree":
      continue
    path = str(item.get("path", ""))
    if not (path.endswith(".py") or path.endswith(".example")):
      continue
    content = str(item.get("content", ""))
    match = RAW_ASSIGN_RE.search(content)
    if match:
      raw_val = match.group(1)
      findings.append({
          "id": item.get("id", path),
          "path": path,
          "line": int(item.get("line", 1)),
          "scope": item.get("scope", "worktree"),
          "secret_type": "hardcoded-credential",
          "masked_secret": mask_secret(raw_val),
      })
  return findings


def format_audit_report(findings: list[dict[str, Any]], gitignore_missing: list[str]) -> str:
  """生成提交前密钥卫生检查报告。"""
  status = "不通过" if (findings or gitignore_missing) else "通过"
  lines = [f"结论：{status}"]
  for f in findings:
    lines.append(
        f"- {f['path']}:{f['line']} [{f['scope']}] ({f['secret_type']}): {f['masked_secret']}"
    )
  return "\n".join(lines)


def run_pre_commit_check(
    changes: list[dict[str, Any]],
    gitignore_entries: list[str],
) -> dict[str, Any]:
  """执行本地 pre-commit 安检（TODO：发现泄露或缺失忽略配置时应返回非零退出码 1）。"""
  findings = scan_repo_changes(changes)
  gitignore_missing = audit_gitignore(gitignore_entries)
  report = format_audit_report(findings, gitignore_missing)
  return {
      "exit_code": 0,  # 缺陷：未返回非零状态码阻断提交
      "findings": findings,
      "gitignore_missing": gitignore_missing,
      "report": report,
  }
