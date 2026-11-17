"""S5-M06 起点骨架：AI 代码合并前排雷审查器（待完善版）。

当前存在典型“肉眼草率放行”缺陷：
1. render_gitleaks_toml() 尚未编写有效的扫密规则；
2. scan_secrets_like_gitleaks() 漏检测试假密钥占位符与常见硬编码凭据赋值；
3. 测试放水、静默吞异常/误删校验、幻觉依赖包、SQL 注入与鉴权缺失尚未拦截；
4. cross_review_with_clean_agent() 直接盲信原作者备注给出了橡皮图章放行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


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


def render_gitleaks_toml() -> str:
  """TODO(Step 2): 生成可落盘的 .gitleaks.toml 配置文本。

  要求：
  - 合法的 TOML 语法；
  - 包含 [[rules]] 规则，至少覆盖 FAKE_..._DO_NOT_USE_... 演练假密钥规则与硬编码凭据规则；
  - 包含 [allowlist] 忽略说明。
  """
  return "# TODO: 请补全 .gitleaks.toml 扫密规则\n"


def scan_secrets_like_gitleaks(diff_text: str) -> list[AuditFinding]:
  """TODO(Step 2): 扫描 Diff 新增行（+ 开头，排除 +++ 文件头）中的硬编码密钥或连接串。

  注意：对使用 os.environ / os.getenv 读取环境变量的安全写法不要误报！
  """
  findings: list[AuditFinding] = []
  for raw_line in diff_text.splitlines():
    if raw_line.startswith("+") and "SUPER_OBVIOUS_PLAINTEXT_PWD=" in raw_line:
      findings.append(
          AuditFinding(
              category="secret",
              rule_id="hardcoded_secret",
              summary="检测到明文密码",
              evidence=raw_line[1:].strip(),
          )
      )
  return findings


def audit_test_integrity(diff_text: str) -> list[AuditFinding]:
  """TODO(Step 3.1): 检查测试是否被放水（新增 skip 跳过、删掉严格断言改为 is not None / assert True）。"""
  return []


def audit_diff_hygiene(diff_text: str) -> list[AuditFinding]:
  """TODO(Step 3.2): 检查是否存在 except ...: pass 静默吞异常、残留 DEBUG 打印，或误删 verify_/validate_ 校验。"""
  return []


def audit_dependencies(diff_text: str, registry: dict[str, Any]) -> list[AuditFinding]:
  """TODO(Step 3.3): 核实新增依赖是否在 registry['verified_pypi_packages'] 中，以及是否可用标准库平替。"""
  return []


def audit_security_boundaries(diff_text: str) -> list[AuditFinding]:
  """TODO(Step 3.4): 检查是否存在 f-string SQL 拼接注入、新增 /admin 路由缺 require_admin_auth 鉴权、暴露 traceback。"""
  return []


def build_clean_reviewer_messages(pr_item: dict[str, Any]) -> list[dict[str, str]]:
  """TODO(Step 4): 构造无历史包袱的独立挑刺审稿会话消息。

  注意：严禁把 pr_item['author_note']（原作者自信背书话术）带入提示词，避免锚定偏见！
  """
  return [
      {"role": "system", "content": "你是代码助手。"},
      {
          "role": "user",
          "content": f"作者说：{pr_item.get('author_note', '')}\n代码改动：\n{pr_item.get('diff', '')}",
      },
  ]


def cross_review_with_clean_agent(
    pr_item: dict[str, Any],
    deterministic_findings: list[AuditFinding],
) -> dict[str, Any]:
  """TODO(Step 4): 使用隔离提示词调用 chat_complete 执行交叉互审，返回结构化字典。"""
  _ = deterministic_findings
  messages = build_clean_reviewer_messages(pr_item)
  _ = chat_complete(
      messages,
      mock_fn=lambda _msgs: '{"reviewer_mode": "rubber_stamp", "verdict": "APPROVE", "blind_spots_caught": []}',
      response_json=True,
  )
  return {
      "reviewer_mode": "rubber_stamp",
      "verdict": "APPROVE",
      "blind_spots_caught": [],
      "prompt_messages": messages,
  }


def audit_pr_diff(pr_item: dict[str, Any], registry: dict[str, Any]) -> DiffAuditReport:
  """汇总本地扫密、清单逐条核验与独立 AI 交叉互审结果。"""
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
