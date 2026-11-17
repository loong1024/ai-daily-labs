#!/usr/bin/env python3
"""S2-M05 起点基线：存在重发漏重、无退避盲目重试、审批超时自动误发与缺预算熔断的周报流水线。

请按 README.md 指引补齐 Part A（幂等表、指数退避+抖动、死信补发、草稿校验与预算硬熔断）
与 Part B（一次性鉴权审批令牌、30 秒超时默认中止）。
"""

from __future__ import annotations

import json
import pathlib
import random
import secrets
import sqlite3
import sys
import time
from typing import Any, Callable

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


class SimulatedMailGateway:
  """本地模拟邮件发送网关：真实统计每位订户的调用次数与实际成功投递次数。"""

  def __init__(self, subscribers: list[dict[str, Any]]) -> None:
    self.behaviors = {s["subscriber_id"]: s["gateway_behavior"] for s in subscribers}
    self.call_attempts: dict[str, int] = {s["subscriber_id"]: 0 for s in subscribers}
    self.delivered_count: dict[str, int] = {s["subscriber_id"]: 0 for s in subscribers}
    self.seen_idempotency_keys: set[str] = set()
    self.transient_recovered: bool = False

  def send_email(
      self,
      subscriber_id: str,
      email: str,
      subject: str,
      body: str,
      *,
      idempotency_key: str | None = None,
  ) -> tuple[int | str, str]:
    _ = (subject, body)
    self.call_attempts[subscriber_id] = self.call_attempts.get(subscriber_id, 0) + 1
    attempt_no = self.call_attempts[subscriber_id]
    behavior = self.behaviors.get(subscriber_id, "ok")

    if behavior == "bad_request_400" or "@" not in email:
      return (400, "Invalid recipient email address")

    if not self.transient_recovered:
      if behavior == "flaky_once_503" and attempt_no == 1:
        return (503, "Upstream mail relay temporarily unavailable")
      if behavior == "flaky_twice_429" and attempt_no <= 2:
        return (429, "Rate limit exceeded")
      if behavior == "always_503":
        return (503, "Persistent upstream outage")
      if behavior == "always_timeout":
        return ("TIMEOUT", "Socket timed out after 10s")

    if idempotency_key and idempotency_key in self.seen_idempotency_keys:
      return (200, "Duplicate suppressed by idempotency key")

    if idempotency_key:
      self.seen_idempotency_keys.add(idempotency_key)
    self.delivered_count[subscriber_id] = self.delivered_count.get(subscriber_id, 0) + 1
    return (200, "Delivered")


def draft_llm_mock(messages: list[dict[str, str]]) -> str:
  """离线周报草稿生成 Mock：首轮故意遗留未替换占位符 {{UNFILLED_METRIC}}，重写轮次修复。"""
  is_rewrite = len(messages) >= 3 and any(
      "占位符" in m.get("content", "") for m in messages[1:]
  )
  if not is_rewrite:
    return (
        "【AI 日课周刊 · 2026-W20】本周聚焦确定性 AI 工作流编排："
        "1）使用原生结构化输出与分隔符隔离抵御提示注入，当前线上拦截率达 {{UNFILLED_METRIC}}；"
        "2）上线前执行六维只读安全审查；"
        "3）邮件群发接入幂等键与指数退避死信队列。"
        "延伸阅读：https://example.org/ai-daily/ch5-structured-output"
    )
  return (
      "【AI 日课周刊 · 2026-W20】本周聚焦确定性 AI 工作流编排："
      "1）使用原生结构化输出与分隔符隔离抵御提示注入，批量校验显著降低格式漂移；"
      "2）上线前通过六维只读审查清单排查硬编码凭证与无限循环；"
      "3）群发流水线配置期号加订户唯一幂等键、指数退避与一次性人工审批卡点。"
      "延伸阅读：https://example.org/ai-daily/ch5-structured-output "
      "与 https://example.org/ai-daily/ch5-idempotent-workflow"
  )


class NewsletterPipeline:
  """【待改进】起点周报流水线骨架。"""

  def __init__(
      self,
      db_path: pathlib.Path | str = ":memory:",
      *,
      subscribers: list[dict[str, Any]] | None = None,
      issue_context: dict[str, Any] | None = None,
      gateway: SimulatedMailGateway | None = None,
      clock_fn: Callable[[], float] = time.time,
      sleep_fn: Callable[[float], None] = time.sleep,
      rng: random.Random | None = None,
  ) -> None:
    self.conn = sqlite3.connect(str(db_path))
    self.subscribers = subscribers or json.loads(
        (LAB_DIR / "fixtures" / "subscribers.json").read_text(encoding="utf-8")
    )
    self.issue_context = issue_context or json.loads(
        (LAB_DIR / "fixtures" / "issue_context.json").read_text(encoding="utf-8")
    )
    self.gateway = gateway or SimulatedMailGateway(self.subscribers)
    self.clock_fn = clock_fn
    self.sleep_fn = sleep_fn
    self.rng = rng or random.Random(42)
    self.alerts: list[str] = []
    self._init_db()

  def _init_db(self) -> None:
    # TODO: 缺少 UNIQUE(issue_id, subscriber_id) 幂等约束、dead_letters 死信表与 cost_ledger 表
    self.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS drafts (
          issue_id TEXT PRIMARY KEY,
          content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
          issue_id TEXT PRIMARY KEY,
          token TEXT NOT NULL,
          expires_at REAL NOT NULL,
          approved INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS send_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issue_id TEXT NOT NULL,
          subscriber_id TEXT NOT NULL,
          status TEXT NOT NULL
        );
        """
    )
    self.conn.commit()

  def prepare_issue(
      self,
      issue_id: str,
      *,
      max_budget_usd: float = 0.05,
      approval_timeout_seconds: float = 172800.0,
  ) -> dict[str, Any]:
    """生成周报草稿并创建本地待审批记录。【缺陷】：未做预算熔断，也未拦截 {{...}} 占位符。"""
    _ = max_budget_usd
    messages = [{"role": "user", "content": f"请为 {issue_id} 期生成周报草稿"}]
    draft = chat_complete(messages, mock_fn=draft_llm_mock)

    token = f"appr_{secrets.token_hex(12)}"
    expires_at = self.clock_fn() + approval_timeout_seconds
    self.conn.execute(
        "INSERT OR REPLACE INTO drafts(issue_id, content) VALUES (?, ?)",
        (issue_id, draft),
    )
    self.conn.execute(
        "INSERT OR REPLACE INTO approvals(issue_id, token, expires_at, approved) VALUES (?, ?, ?, 0)",
        (issue_id, token, expires_at),
    )
    self.conn.commit()
    return {
        "status": "pending_approval",
        "issue_id": issue_id,
        "draft": draft,
        "approval_token": token,
        "spent_usd": 0.0,
    }

  def approve_issue(self, issue_id: str, token: str) -> bool:
    """确认审批令牌。【缺陷】：未检查是否已消费或过期，同一令牌可被无限重复点击生效！"""
    row = self.conn.execute(
        "SELECT token FROM approvals WHERE issue_id = ?", (issue_id,)
    ).fetchone()
    if not row or row[0] != token:
      return False
    self.conn.execute(
        "UPDATE approvals SET approved = 1 WHERE issue_id = ?", (issue_id,)
    )
    self.conn.commit()
    return True

  def dispatch_issue(self, issue_id: str, *, max_retries: int = 4) -> dict[str, Any]:
    """执行群发。【缺陷】：超时默认自动发出、不跳已成功订户、400 也无退避死磕重试、无死信落盘。"""
    row = self.conn.execute(
        "SELECT approved, expires_at FROM approvals WHERE issue_id = ?", (issue_id,)
    ).fetchone()
    if not row:
      return {"status": "missing_approval", "sent_count": 0, "dead_letter_count": 0}

    approved, expires_at = int(row[0]), float(row[1])
    # 危险反模式：超时未处理竟然默认自动通过继续发信！
    if not approved and self.clock_fn() < expires_at:
      return {"status": "waiting_approval", "sent_count": 0, "dead_letter_count": 0}

    draft_row = self.conn.execute(
        "SELECT content FROM drafts WHERE issue_id = ?", (issue_id,)
    ).fetchone()
    body = draft_row[0] if draft_row else ""

    sent_count = 0
    for sub in self.subscribers:
      sub_id = sub["subscriber_id"]
      for _ in range(max_retries + 1):
        code, _msg = self.gateway.send_email(
            sub_id, sub["email"], f"AI 日课周刊 {issue_id}", body
        )
        if code == 200:
          sent_count += 1
          self.conn.execute(
              "INSERT INTO send_logs(issue_id, subscriber_id, status) VALUES (?, ?, 'sent')",
              (issue_id, sub_id),
          )
          break
        self.sleep_fn(0.0)

    self.conn.commit()
    return {
        "status": "completed",
        "sent_count": sent_count,
        "skipped_idempotent_count": 0,
        "skipped_non_retryable_count": 0,
        "dead_letter_count": 0,
    }

  def replay_dead_letters(self, issue_id: str) -> dict[str, Any]:
    """【待实现】仅补发死信表中的失败记录。"""
    _ = issue_id
    return {"replayed_sent_count": 0, "remaining_dead_letters": 0}


if __name__ == "__main__":
  pipe = NewsletterPipeline()
  prep = pipe.prepare_issue("2026-W20")
  pipe.approve_issue("2026-W20", prep["approval_token"])
  result = pipe.dispatch_issue("2026-W20")
  print("基线运行结果：", result)
