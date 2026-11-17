"""S0-M04 提交前密钥安检与 pre-commit 守卫（Solution 标准参考实现）。"""

from __future__ import annotations

import pathlib
import re
from typing import Any

# 匹配实验演练用伪造高危密钥及常见硬编码高熵密钥赋值
FAKE_DRILL_KEY_RE = re.compile(
    r"(?:FAKE|DEMO|MOCK|TEST)_(?:TEST_)?(?:FAKE_)?KEY_DO_NOT_USE_[A-Za-z0-9_]{8,}"
)
GENERIC_ASSIGN_RE = re.compile(
    r"(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*['\"]([A-Za-z0-9_\-]{20,})['\"]",
    re.IGNORECASE,
)

ALLOWLIST_FILENAMES = {".env.example", ".env.template", ".env.sample"}
SAFE_PLACEHOLDER_MARKERS = (
    "YOUR_API_KEY_HERE",
    "REPLACE_IN_LOCAL_ENV",
    "EXAMPLE_PLACEHOLDER_ONLY",
    "CHANGEME",
    "<REPLACE",
)
REQUIRED_GITIGNORE_PATTERNS = (".env", "*.pem")


def mask_secret(secret: str) -> str:
  """脱敏显示：仅保留前 4 位，其余一律用 8 个 '*' 遮盖，严禁暴露完整密钥。"""
  cleaned = (secret or "").strip()
  if len(cleaned) <= 4:
    return "*" * 8
  return f"{cleaned[:4]}{'*' * 8}"


def _is_safe_placeholder(value: str) -> bool:
  upper = value.upper()
  return any(marker in upper for marker in SAFE_PLACEHOLDER_MARKERS)


def _classify_secret(path: str, scope: str) -> str:
  pure_name = pathlib.PurePosixPath(path).name
  if scope == "git_history":
    return "git-history-leaked-token"
  if pure_name == ".env" or pure_name.startswith(".env."):
    return "tracked-dotenv-secret"
  if path.startswith(("web/", "frontend/", "client/")) or "PUBLIC_" in path:
    return "frontend-exposed-secret"
  return "hardcoded-api-key"


def audit_gitignore(entries: list[str]) -> list[str]:
  """核查 .gitignore 是否覆盖 .env 与 *.pem 等敏感本地文件。"""
  normalized = {e.strip() for e in entries if e.strip() and not e.strip().startswith("#")}
  missing: list[str] = []
  for req in REQUIRED_GITIGNORE_PATTERNS:
    if req not in normalized:
      missing.append(req)
  return missing


def scan_repo_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """扫描当前工作区（worktree）与 Git 提交历史（git_history），同时放行合规占位模板。"""
  findings: list[dict[str, Any]] = []
  for item in changes:
    path = str(item.get("path", ""))
    pure_name = pathlib.PurePosixPath(path).name
    if pure_name in ALLOWLIST_FILENAMES:
      continue

    content = str(item.get("content", ""))
    scope = str(item.get("scope", "worktree"))
    line_no = int(item.get("line", 1))

    matched_secret: str | None = None
    drill_match = FAKE_DRILL_KEY_RE.search(content)
    if drill_match:
      matched_secret = drill_match.group(0)
    else:
      assign_match = GENERIC_ASSIGN_RE.search(content)
      if assign_match and not _is_safe_placeholder(assign_match.group(1)):
        matched_secret = assign_match.group(1)

    if matched_secret and not _is_safe_placeholder(matched_secret):
      findings.append({
          "id": str(item.get("id", path)),
          "path": path,
          "line": line_no,
          "scope": scope,
          "commit": str(item.get("commit", "")),
          "secret_type": _classify_secret(path, scope),
          "masked_secret": mask_secret(matched_secret),
      })
  return findings


def format_audit_report(findings: list[dict[str, Any]], gitignore_missing: list[str]) -> str:
  """输出遮盖敏感片段的结构化安检报告与标准应急处置指引。"""
  passed = not findings and not gitignore_missing
  lines = [f"结论：{'通过' if passed else '不通过'}"]

  if findings:
    lines.append("\n发现列表（已脱敏，仅保留前 4 位）：")
    for f in findings:
      commit_note = f" @commit:{f['commit']}" if f.get("commit") else ""
      lines.append(
          f"- {f['path']}:{f['line']} [{f['scope']}{commit_note}] "
          f"类型={f['secret_type']} | 片段={f['masked_secret']}"
      )

  if gitignore_missing:
    lines.append(f"\n配置缺失：.gitignore 缺少规则 {', '.join(gitignore_missing)}")

  if not passed:
    lines.extend([
        "\n修复与应急处置顺序：",
        "1. 【第一优先级】立即前往服务商控制台吊销并轮换已暴露密钥（删代码无法撤回泄露）；",
        "2. 将新密钥写入本地未跟踪的 .env 或密钥管理器，代码中统一改为 os.environ 读取；",
        "3. 确认用户授权后按官方文档清理 Git 历史，并核查暴露期间用量与账单；",
        "4. 补齐 .gitignore（.env、*.pem）并启用 pre-commit + gitleaks 硬拦截。",
    ])
  return "\n".join(lines)


def run_pre_commit_check(
    changes: list[dict[str, Any]],
    gitignore_entries: list[str],
) -> dict[str, Any]:
  """本地 pre-commit 钩子主入口：存在任何密钥风险或忽略规则缺失时返回非零退出码 1。"""
  findings = scan_repo_changes(changes)
  gitignore_missing = audit_gitignore(gitignore_entries)
  report = format_audit_report(findings, gitignore_missing)
  exit_code = 1 if (findings or gitignore_missing) else 0
  return {
      "exit_code": exit_code,
      "findings": findings,
      "gitignore_missing": gitignore_missing,
      "report": report,
  }
