#!/usr/bin/env python3
"""S6-M06 上线攻防自检（Starter 基线版 —— 含典型上线前安全漏洞，待加固）。"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

HIGH_RISK_ACTIONS = {
    "delete_workspace",
    "send_invoice_payment",
    "send_external_email",
    "drop_records",
}


def scan_release_security(
    artifacts: list[dict[str, Any]],
    billing_config: dict[str, Any],
) -> dict[str, Any]:
  """发布前静态核查：扫描前端构建产物/Git 历史密钥泄露，并核对硬花费封顶与监控回滚就绪度。

  TODO(S6-M06):
  1. 当前仅检查路径名是否完全等于 '.env'，漏掉了 dist/*.js 构建产物和 git_history_patch.txt 中的密钥！
     请用正则扫描内容中的密钥特征（如 FAKE_TEST_KEY_DO_NOT_USE_* 或赋值型凭据，同时排除 PLACEHOLDER/EXAMPLE 占位符）。
  2. 当前把 soft_alert_usd > 0 当成了硬封顶达标！必须校验 hard_cap_enabled is True 且 hard_limit_usd > 0。
  3. 核对 rollback_rehearsed 为 True 且 alerts 同时覆盖 error_rate / latency_p95 / spend，生成具体证据列表。
  """
  leaked_paths: list[str] = []
  for item in artifacts:
    if item.get("path") == ".env":
      leaked_paths.append(item["path"])

  # 缺陷：误将邮件软告警当成硬花费封顶
  hard_cap_ok = bool((billing_config.get("soft_alert_usd") or 0) > 0)
  ops_ready = True
  block_release = bool(leaked_paths) or (not hard_cap_ok)
  return {
      "leaked_paths": leaked_paths,
      "hard_cap_ok": hard_cap_ok,
      "ops_ready": ops_ready,
      "block_release": block_release,
      "evidence": [],
  }


class SecurityGateway:
  """AI 接口上线防御网关（Starter 版缺失 IP 限流、跨户鉴权、高危确认、注入隔离、XSS 转义与日志脱敏）。"""

  def __init__(
      self,
      valid_tokens: dict[str, str],
      resource_owners: dict[str, str],
      per_ip_limit: int = 5,
      per_user_daily_limit: int = 8,
  ) -> None:
    self.valid_tokens = dict(valid_tokens)
    self.resource_owners = dict(resource_owners)
    self.per_ip_limit = per_ip_limit
    self.per_user_daily_limit = per_user_daily_limit
    self.ip_counts: dict[str, int] = {}
    self.user_counts: dict[str, int] = {}

  def handle_request(self, req: dict[str, Any]) -> dict[str, Any]:
    """处理单次 AI 请求并返回状态码、转义后的安全 HTML 与脱敏审计日志。

    TODO(S6-M06):
    1. 未登录或无效 token 必须立即拦截并返回 status=401（切勿先调模型扣费！）。
    2. 同时按 client_ip（上限 per_ip_limit）与 user_id（上限 per_user_daily_limit）限流，超限返回 status=429。
    3. 工具调用若访问不属于当前登录用户的 resource_id，返回 status=403（防跨账号越权 IDOR）。
    4. HIGH_RISK_ACTIONS 中的高危不可逆操作若未携带 confirmed=True，返回 status=409。
    5. 拦截 external_context 中的间接提示词注入指令（标记 injection_blocked=True，不泄露内部敏感词）。
    6. 对模型输出做 HTML 转义并阻断 javascript: 伪协议；对审计日志中的手机号、邮箱、密钥脱敏。
    """
    token = str(req.get("token") or "")
    user_id = self.valid_tokens.get(token, "anonymous")
    prompt = str(req.get("prompt") or "")
    external_ctx = str(req.get("external_context") or "")

    def _mock_reply(_messages: list[dict[str, str]]) -> str:
      return str(req.get("mock_model_output") or "默认回复")

    raw_output = chat_complete(
        [{"role": "user", "content": f"{prompt}\n{external_ctx}"}],
        mock_fn=_mock_reply,
    )

    # 缺陷：直接原样拼入网页，且原样把隐私信息写入审计日志
    audit_log = f"user={user_id} ip={req.get('client_ip')} prompt={prompt}"
    return {
        "status": 200,
        "reason": "ok",
        "injection_blocked": False,
        "safe_html": raw_output,
        "audit_log": audit_log,
    }


def export_regression_suite(
    attack_cases: list[dict[str, Any]],
    gateway: SecurityGateway | None = None,
) -> list[dict[str, Any]]:
  """运行攻击样本并将恶意注入/越权/XSS 用例导出为回归评测集记录。

  TODO(S6-M06): 遍历 attack_cases 中 is_malicious=True 的样本，实测网关响应并记录真实证据摘要。
  """
  _ = (attack_cases, gateway)
  return []


if __name__ == "__main__":
  bundle = json.loads((LAB_DIR / "fixtures" / "release_bundle.json").read_text(encoding="utf-8"))
  print("发布前扫描结果（Starter）：", scan_release_security(bundle["artifacts"], bundle["billing_configs"]["soft_only"]))
