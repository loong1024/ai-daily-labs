"""S5-M06 标准参考实现：AI 代码合并前五维排雷审查器 + 独立会话交叉互审。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

LOCAL_PROJECT_PACKAGES = {"api", "services", "infra", "models", "tests", "app", "shared"}
_FALLBACK_STDLIB = {
    "os",
    "sys",
    "json",
    "decimal",
    "hashlib",
    "urllib",
    "re",
    "pathlib",
    "typing",
    "dataclasses",
    "unittest",
}

CANARY_FAKE_KEY_RE = re.compile(r"FAKE_[A-Z0-9_]*_DO_NOT_USE_[A-Za-z0-9_]+")
CREDENTIAL_ASSIGN_RE = re.compile(
    r"""(?i)\b(?:api_key|api_token|secret|password|passwd|dsn|access_token)\b\s*=\s*["']([^"']{8,})["']"""
)
SKIP_DECORATOR_RE = re.compile(r"(?:@pytest\.mark\.skip\b|pytest\.skip\s*\(|@unittest\.skip\b)")
STRICT_ASSERT_RE = re.compile(r"(?:\bassert\b.+(?:==|!=|<=|>=|<|>|\bin\b)|pytest\.raises\s*\()")
WEAK_ASSERT_RE = re.compile(r"(?:\bassert\s+[A-Za-z_][A-Za-z0-9_.]*\s+is\s+not\s+None\b|\bassert\s+True\b)")
VALIDATION_CALL_RE = re.compile(r"\b((?:verify|validate|check_auth|check_permission)_[A-Za-z0-9_]+)\s*\(")
REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:==|>=|<=|~=|!=|>|<|$)")
IMPORT_LINE_RE = re.compile(r"^\s*(?:from\s+([A-Za-z_][A-Za-z0-9_]*)|import\s+([A-Za-z_][A-Za-z0-9_]*))")
SQL_INTERP_RE = re.compile(r"""(?i)\bf["']\s*(?:SELECT|INSERT|UPDATE|DELETE)\b[^"']*\{""")
ADMIN_ROUTE_RE = re.compile(r"""@router\.(?:get|post|put|delete|patch)\(\s*["']/admin/""")


@dataclass
class AuditFinding:
  category: str  # "secret" | "test_integrity" | "diff_hygiene" | "dependency" | "security"
  rule_id: str
  summary: str
  evidence: str


@dataclass
class DiffAuditReport:
  pr_id: str
  decision: str  # "BLOCK" | "APPROVE"
  categories_flagged: list[str] = field(default_factory=list)
  findings: list[AuditFinding] = field(default_factory=list)
  cross_review: dict[str, Any] = field(default_factory=dict)


def _split_diff_by_file(diff_text: str) -> list[tuple[str, list[str], list[str]]]:
  """按文件切分 unified diff，返回 (file_path, added_lines, removed_lines)。"""
  sections: list[tuple[str, list[str], list[str]]] = []
  cur_file = "<unknown>"
  added: list[str] = []
  removed: list[str] = []

  for raw in diff_text.splitlines():
    if raw.startswith("+++ b/"):
      if added or removed:
        sections.append((cur_file, added, removed))
        added, removed = [], []
      cur_file = raw[len("+++ b/") :].strip()
    elif raw.startswith("--- "):
      continue
    elif raw.startswith("+") and not raw.startswith("+++"):
      added.append(raw[1:])
    elif raw.startswith("-") and not raw.startswith("---"):
      removed.append(raw[1:])

  if added or removed:
    sections.append((cur_file, added, removed))
  return sections


def render_gitleaks_toml() -> str:
  """生成可直接用于 `gitleaks protect --staged -c .gitleaks.toml` 的配置。"""
  return """title = "AI Pre-Merge Secret Scanner Config"

[[rules]]
id = "aid-canary-fake-secret"
description = "Block simulated canary test secrets during pre-commit verification"
regex = '''FAKE_[A-Z0-9_]*_DO_NOT_USE_[A-Za-z0-9_]+'''
tags = ["secret", "canary"]

[[rules]]
id = "hardcoded-credential-assignment"
description = "Block hardcoded API keys, passwords, tokens, and database DSNs"
regex = '''(?i)\\b(api_key|api_token|secret|password|passwd|dsn|access_token)\\b\\s*=\\s*["'][^"']{8,}["']'''
tags = ["secret", "credential"]

[allowlist]
description = "Allow documentation templates and historical audit fixtures"
paths = [
  '''fixtures/trapped_pr_diffs\\.json$''',
  '''README\\.md$''',
]
"""


def scan_secrets_like_gitleaks(diff_text: str) -> list[AuditFinding]:
  """扫描新增代码行中的硬编码密钥、令牌或连接串，放行环境变量读取。"""
  findings: list[AuditFinding] = []
  for file_path, added, _ in _split_diff_by_file(diff_text):
    for line in added:
      stripped = line.strip()
      if "os.environ" in stripped or "os.getenv" in stripped:
        continue
      if CANARY_FAKE_KEY_RE.search(stripped):
        findings.append(
            AuditFinding(
                category="secret",
                rule_id="canary_secret_detected",
                summary=f"{file_path} 存在硬编码密钥/连接串占位符，触发扫密阻断",
                evidence=stripped,
            )
        )
      elif CREDENTIAL_ASSIGN_RE.search(stripped):
        findings.append(
            AuditFinding(
                category="secret",
                rule_id="hardcoded_credential_assignment",
                summary=f"{file_path} 存在硬编码敏感凭据赋值，应改为环境变量注入",
                evidence=stripped,
            )
        )
  return findings


def audit_test_integrity(diff_text: str) -> list[AuditFinding]:
  """检查单测是否被跳过或改弱断言。"""
  findings: list[AuditFinding] = []
  for file_path, added, removed in _split_diff_by_file(diff_text):
    for line in added:
      if SKIP_DECORATOR_RE.search(line):
        findings.append(
            AuditFinding(
                category="test_integrity",
                rule_id="no_skipped_tests",
                summary=f"{file_path} 新增了测试跳过标记，掩盖了边界用例失败",
                evidence=line.strip(),
            )
        )

    had_strict_removed = any(STRICT_ASSERT_RE.search(r) for r in removed)
    weak_lines = [a.strip() for a in added if WEAK_ASSERT_RE.search(a)]
    if had_strict_removed and weak_lines:
      findings.append(
          AuditFinding(
              category="test_integrity",
              rule_id="no_weakened_assertions",
              summary=f"{file_path} 删除了原有的严格业务断言并降级为非空宽泛断言",
              evidence=weak_lines[0],
          )
      )
  return findings


def audit_diff_hygiene(diff_text: str) -> list[AuditFinding]:
  """检查静默吞异常、残留调试输出与误删安全/业务校验。"""
  findings: list[AuditFinding] = []
  for file_path, added, removed in _split_diff_by_file(diff_text):
    non_empty_added = [ln.strip() for ln in added if ln.strip()]
    for idx, stmt in enumerate(non_empty_added):
      if stmt.startswith("except") and stmt.endswith(":"):
        next_stmt = non_empty_added[idx + 1] if idx + 1 < len(non_empty_added) else ""
        if next_stmt in {"pass", "..."}:
          findings.append(
              AuditFinding(
                  category="diff_hygiene",
                  rule_id="no_silent_exception_swallowing",
                  summary=f"{file_path} 使用 except + {next_stmt} 静默吞掉了异常",
                  evidence=f"{stmt} {next_stmt}",
              )
          )
      if ("print(" in stmt and "DEBUG" in stmt) or "breakpoint()" in stmt or "pdb.set_trace()" in stmt:
        findings.append(
            AuditFinding(
                category="diff_hygiene",
                rule_id="no_residual_debug_code",
                summary=f"{file_path} 残留了调试打印或断点语句",
                evidence=stmt,
            )
        )

    added_blob = "\n".join(added)
    removed_checks: set[str] = set()
    for r_line in removed:
      for match in VALIDATION_CALL_RE.finditer(r_line):
        fn_name = match.group(1)
        if fn_name not in added_blob:
          removed_checks.add(fn_name)
    for fn_name in sorted(removed_checks):
      findings.append(
          AuditFinding(
              category="diff_hygiene",
              rule_id="no_deleted_validation",
              summary=f"{file_path} 删除了原有的校验调用 `{fn_name}` 且未在重构后保留",
              evidence=fn_name,
          )
      )
  return findings


def _normalize_pkg_name(name: str) -> str:
  return name.strip().lower().replace("_", "-")


def audit_dependencies(diff_text: str, registry: dict[str, Any]) -> list[AuditFinding]:
  """核实新增依赖是否在可信包快照中，且拦截可用标准库直接完成的冗余引包。"""
  findings: list[AuditFinding] = []
  verified = {_normalize_pkg_name(k): v for k, v in registry.get("verified_pypi_packages", {}).items()}
  stdlib_equiv = {_normalize_pkg_name(k): v for k, v in registry.get("stdlib_equivalents", {}).items()}
  stdlib_names = set(getattr(sys, "stdlib_module_names", _FALLBACK_STDLIB))

  candidates: list[tuple[str, str, str]] = []  # (norm_pkg, raw_module, file_path)
  for file_path, added, _ in _split_diff_by_file(diff_text):
    if file_path.endswith("requirements.txt"):
      for line in added:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
          continue
        m = REQ_LINE_RE.match(stripped)
        if m:
          pkg = m.group(1)
          candidates.append((_normalize_pkg_name(pkg), pkg, file_path))
    elif file_path.endswith(".py"):
      for line in added:
        m = IMPORT_LINE_RE.match(line)
        if m:
          mod = m.group(1) or m.group(2)
          if mod in stdlib_names or mod in LOCAL_PROJECT_PACKAGES:
            continue
          candidates.append((_normalize_pkg_name(mod), mod, file_path))

  seen: set[str] = set()
  for norm_pkg, raw_ref, file_path in candidates:
    if norm_pkg in seen:
      continue
    seen.add(norm_pkg)

    if norm_pkg in stdlib_equiv:
      std_mod = stdlib_equiv[norm_pkg]
      findings.append(
          AuditFinding(
              category="dependency",
              rule_id="redundant_or_hallucinated_stdlib_pkg",
              summary=f"{file_path} 引入了未核实包 `{raw_ref}`，且功能可直接由 Python 标准库 `{std_mod}` 完成",
              evidence=raw_ref,
          )
      )
    elif norm_pkg not in verified or not verified[norm_pkg].get("active", False):
      findings.append(
          AuditFinding(
              category="dependency",
              rule_id="unverified_package",
              summary=f"{file_path} 新增依赖 `{raw_ref}` 未在可信包索引中核实发布者与活跃度（疑似幻觉包名）",
              evidence=raw_ref,
          )
      )
  return findings


def audit_security_boundaries(diff_text: str) -> list[AuditFinding]:
  """检查 SQL 拼接注入、管理端路由鉴权缺失与内部异常堆栈泄露。"""
  findings: list[AuditFinding] = []
  for file_path, added, _ in _split_diff_by_file(diff_text):
    for idx, line in enumerate(added):
      stripped = line.strip()
      if SQL_INTERP_RE.search(stripped):
        findings.append(
            AuditFinding(
                category="security",
                rule_id="no_sql_string_interpolation",
                summary=f"{file_path} 直接用 f-string 拼接 SQL 语句，存在 SQL 注入风险",
                evidence=stripped,
            )
        )
      if ADMIN_ROUTE_RE.search(stripped):
        sig_window = " ".join(added[idx : idx + 4])
        if "require_admin_auth" not in sig_window and "Depends(" not in sig_window:
          findings.append(
              AuditFinding(
                  category="security",
                  rule_id="missing_admin_auth",
                  summary=f"{file_path} 新增 `/admin/` 接口缺少管理员鉴权依赖 `require_admin_auth`",
                  evidence=stripped,
              )
          )
      if "traceback.format_exc()" in stripped and ("return" in stripped or "error" in stripped):
        findings.append(
            AuditFinding(
                category="security",
                rule_id="no_internal_traceback_exposure",
                summary=f"{file_path} 将内部堆栈 `traceback.format_exc()` 直接暴露在接口响应中",
                evidence=stripped,
            )
        )
  return findings


def build_clean_reviewer_messages(pr_item: dict[str, Any]) -> list[dict[str, str]]:
  """构造零上下文污染的挑刺审稿提示词（物理剥离 author_note，防止自我背书误导）。"""
  system_prompt = (
      "你是一名独立的合并前安全与质量挑刺审稿人（Clean-Session Adversarial Reviewer）。\n"
      "请严格按五维核对表审查用户提供的 Git Diff：\n"
      "1. 测试：是否跳过测试或将严格断言改弱为 is not None / assert True；\n"
      "2. Diff：是否静默吞掉异常（except: pass）、残留 DEBUG 打印或误删原有签名/输入校验；\n"
      "3. 依赖：是否引入未经核实的幻觉包或可用标准库替代的新包；\n"
      "4. 安全：是否硬编码密钥/连接串、拼接 SQL、新增 /admin 接口缺鉴权或向外暴露 traceback。\n"
      "若代码改动完全合规（如使用标准库、环境变量读取配置且具备正反向严格断言单测），"
      "verdict 必须为 \"APPROVE\" 且 blind_spots_caught 为 []。\n"
      "请仅输出严格 JSON：{\"reviewer_mode\": \"isolated_clean_session\", "
      "\"verdict\": \"BLOCK\" 或 \"APPROVE\", \"blind_spots_caught\": [\"问题1\", ...]}。"
  )
  user_prompt = (
      f"PR 编号：{pr_item.get('pr_id', '')}\n"
      f"涉及文件：{', '.join(pr_item.get('files_changed', []))}\n"
      f"待审原始 Diff：\n```diff\n{pr_item.get('diff', '')}\n```"
  )
  return [
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": user_prompt},
  ]


def _mock_adversarial_reviewer(messages: list[dict[str, str]]) -> str:
  """离线确定性挑刺审稿器：仅依据传入的干净 Diff 独立判别隐患。"""
  user_text = messages[-1]["content"] if messages else ""
  diff_match = re.search(r"```diff\n(.*?)\n```", user_text, flags=re.DOTALL)
  raw_diff = diff_match.group(1) if diff_match else user_text

  caught: list[str] = []
  if SKIP_DECORATOR_RE.search(raw_diff) or WEAK_ASSERT_RE.search(raw_diff):
    caught.append("测试断言被弱化为非空检查或被 skip 跳过，制造了虚假全绿")
  if "except Exception:" in raw_diff and "\n+        pass" in raw_diff:
    caught.append("异常被 except Exception: pass 静默吞没，故障将无法感知")
  if "-    if not verify_hmac_signature" in raw_diff:
    caught.append("原有的 HMAC 签名安全校验在重构中被直接删除")
  if "fastjson-ultra-parse" in raw_diff or "fastjson_ultra_parse" in raw_diff:
    caught.append("引入了未经核实的疑似幻觉包 fastjson-ultra-parse，应直接使用标准库 json")
  if CANARY_FAKE_KEY_RE.search(raw_diff):
    caught.append("代码中硬编码了 API 密钥与数据库 DSN 凭据")
  if SQL_INTERP_RE.search(raw_diff) or '@router.get("/admin/' in raw_diff:
    caught.append("新增后台导出接口缺少管理员鉴权，且存在 SQL 字符串拼接注入与堆栈泄露")

  verdict = "BLOCK" if caught else "APPROVE"
  return json.dumps(
      {
          "reviewer_mode": "isolated_clean_session",
          "verdict": verdict,
          "blind_spots_caught": caught,
      },
      ensure_ascii=False,
  )


def _parse_reviewer_json(raw_resp: Any) -> dict[str, Any]:
  if isinstance(raw_resp, dict):
    return raw_resp
  text = str(raw_resp).strip()
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
  start = text.find("{")
  end = text.rfind("}")
  if start != -1 and end != -1 and end >= start:
    text = text[start : end + 1]
  return json.loads(text)


def cross_review_with_clean_agent(
    pr_item: dict[str, Any],
    deterministic_findings: list[AuditFinding],
) -> dict[str, Any]:
  """开启无历史包袱独立 AI 审稿会话执行交叉互审。"""
  _ = deterministic_findings
  messages = build_clean_reviewer_messages(pr_item)
  raw_resp = chat_complete(
      messages,
      mock_fn=_mock_adversarial_reviewer,
      temperature=0.0,
      response_json=True,
  )
  parsed = _parse_reviewer_json(raw_resp)
  verdict = str(parsed.get("verdict", "BLOCK")).strip().upper()
  if verdict not in {"BLOCK", "APPROVE"}:
    verdict = "BLOCK"
  return {
      "reviewer_mode": str(parsed.get("reviewer_mode") or "isolated_clean_session"),
      "verdict": verdict,
      "blind_spots_caught": list(parsed.get("blind_spots_caught", [])),
      "prompt_messages": messages,
  }


def audit_pr_diff(pr_item: dict[str, Any], registry: dict[str, Any]) -> DiffAuditReport:
  """执行合并前完整排雷闭环：本地扫密 + 清单五维检查 + 独立会话交叉互审。"""
  diff_text = pr_item.get("diff", "")
  findings: list[AuditFinding] = []
  findings.extend(scan_secrets_like_gitleaks(diff_text))
  findings.extend(audit_test_integrity(diff_text))
  findings.extend(audit_diff_hygiene(diff_text))
  findings.extend(audit_dependencies(diff_text, registry))
  findings.extend(audit_security_boundaries(diff_text))

  cross = cross_review_with_clean_agent(pr_item, findings)
  categories = sorted({f.category for f in findings})
  decision = "BLOCK" if (findings or cross.get("verdict") == "BLOCK") else "APPROVE"
  return DiffAuditReport(
      pr_id=pr_item["pr_id"],
      decision=decision,
      categories_flagged=categories,
      findings=findings,
      cross_review=cross,
  )
