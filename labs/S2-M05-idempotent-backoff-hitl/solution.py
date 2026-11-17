#!/usr/bin/env python3
"""S2-M05 标准参考实现：幂等发送表 + 带抖动指数退避 + 死信补发 + 单期预算硬熔断 + 一次性本地审批。"""

from __future__ import annotations

import json
import pathlib
import random
import re
import secrets
import sqlite3
import sys
import time
import urllib.parse
from typing import Any, Callable

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

RETRYABLE_CODES: set[int | str] = {429, 500, 502, 503, 504, "TIMEOUT"}
NON_RETRYABLE_CODES: set[int | str] = {400, 401, 403, 422}
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")


class SimulatedMailGateway:
  """本地模拟邮件发送网关：精确追踪每位订户的尝试次数与实际送达次数。"""

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


def validate_draft_quality(draft: str, min_chars: int = 80, max_chars: int = 800) -> list[str]:
  """周报草稿质量关卡校验：字数范围、无未替换占位符、包含合法 https 链接。"""
  issues: list[str] = []
  length = len(draft.strip())
  if length < min_chars or length > max_chars:
    issues.append(f"草稿字数 {length} 不在 [{min_chars}, {max_chars}] 要求范围内")
  if PLACEHOLDER_RE.search(draft):
    issues.append("草稿包含未替换的模板占位符（如 {{...}}）")
  if "https://" not in draft:
    issues.append("草稿缺少可访问的 https:// 参考链接")
  return issues


class NewsletterPipeline:
  """高可靠周报生成、一次性审批、幂等退避群发与死信补发流水线。"""

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
    self.subscribers_by_id = {s["subscriber_id"]: s for s in self.subscribers}
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
    self.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS drafts (
          issue_id TEXT PRIMARY KEY,
          timezone TEXT NOT NULL,
          content TEXT NOT NULL,
          created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS approvals (
          issue_id TEXT PRIMARY KEY,
          token TEXT NOT NULL,
          expires_at REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          used INTEGER NOT NULL DEFAULT 0,
          decided_at REAL
        );

        CREATE TABLE IF NOT EXISTS send_logs (
          issue_id TEXT NOT NULL,
          subscriber_id TEXT NOT NULL,
          email TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          last_error TEXT,
          updated_at REAL NOT NULL,
          PRIMARY KEY (issue_id, subscriber_id)
        );

        CREATE TABLE IF NOT EXISTS dead_letters (
          issue_id TEXT NOT NULL,
          subscriber_id TEXT NOT NULL,
          email TEXT NOT NULL,
          last_code TEXT NOT NULL,
          reason TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          created_at REAL NOT NULL,
          PRIMARY KEY (issue_id, subscriber_id)
        );

        CREATE TABLE IF NOT EXISTS cost_ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issue_id TEXT NOT NULL,
          step TEXT NOT NULL,
          tokens INTEGER NOT NULL,
          cost_usd REAL NOT NULL,
          created_at REAL NOT NULL
        );
        """
    )
    self.conn.commit()

  def get_issue_spend(self, issue_id: str) -> float:
    row = self.conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM cost_ledger WHERE issue_id = ?",
        (issue_id,),
    ).fetchone()
    return float(row[0]) if row else 0.0

  def _record_llm_cost(self, issue_id: str, step: str, cost_usd: float, tokens: int = 650) -> float:
    self.conn.execute(
        "INSERT INTO cost_ledger(issue_id, step, tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?)",
        (issue_id, step, tokens, cost_usd, self.clock_fn()),
    )
    self.conn.commit()
    return self.get_issue_spend(issue_id)

  def prepare_issue(
      self,
      issue_id: str,
      *,
      max_budget_usd: float | None = None,
      approval_timeout_seconds: float = 172800.0,
      max_rewrites: int = 2,
  ) -> dict[str, Any]:
    """生成周报草稿（带关卡重写与单期预算硬熔断），并签发本地一次性审批令牌。"""
    pricing = self.issue_context.get("pricing", {})
    call_cost = float(pricing.get("estimated_cost_per_call_usd", 0.004))
    budget_cap = (
        float(max_budget_usd)
        if max_budget_usd is not None
        else float(pricing.get("default_issue_budget_usd", 0.05))
    )
    tz_name = self.issue_context.get("timezone", "Asia/Shanghai")
    gate_cfg = self.issue_context.get("quality_gate", {})
    min_chars = int(gate_cfg.get("min_chars", 80))
    max_chars = int(gate_cfg.get("max_chars", 800))

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                f"你是周报编辑（调度时区：{tz_name}）。请生成结构清晰、无残留模板占位符、"
                "附带完整 https 参考链接的中文技术周报。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"期号：{issue_id}\n主题：{self.issue_context.get('topic')}\n"
                f"要点：{json.dumps(self.issue_context.get('highlights', []), ensure_ascii=False)}\n"
                f"链接：{json.dumps(self.issue_context.get('reference_links', []), ensure_ascii=False)}"
            ),
        },
    ]

    draft = ""
    gate_errors: list[str] = []
    for turn in range(1, max_rewrites + 2):
      projected = self.get_issue_spend(issue_id) + call_cost
      if projected > budget_cap:
        alert = (
            f"[HIGH_ALERT][BUDGET_CIRCUIT_BREAKER] 期号 {issue_id} 预计累计费用 "
            f"${projected:.4f} 超过单期上限 ${budget_cap:.4f}，已立即熔断中止！"
        )
        self.alerts.append(alert)
        return {
            "status": "aborted_budget",
            "issue_id": issue_id,
            "draft": None,
            "approval_token": None,
            "spent_usd": self.get_issue_spend(issue_id),
            "alert": alert,
        }

      draft = chat_complete(messages, mock_fn=draft_llm_mock)
      self._record_llm_cost(issue_id, f"draft_attempt_{turn}", call_cost)
      gate_errors = validate_draft_quality(draft, min_chars=min_chars, max_chars=max_chars)
      if not gate_errors:
        break

      if turn <= max_rewrites:
        messages.append({"role": "assistant", "content": draft})
        messages.append({
            "role": "user",
            "content": "草稿未通过质量关卡：" + "；".join(gate_errors) + "。请修正并移除所有 {{...}} 占位符。",
        })

    if gate_errors:
      alert = f"[WARN][QUALITY_GATE] 期号 {issue_id} 重写后仍未通过质量关卡：{gate_errors}"
      self.alerts.append(alert)
      return {
          "status": "aborted_quality_gate",
          "issue_id": issue_id,
          "draft": draft,
          "approval_token": None,
          "spent_usd": self.get_issue_spend(issue_id),
      }

    now = self.clock_fn()
    token = f"appr_{secrets.token_hex(16)}"
    expires_at = now + approval_timeout_seconds
    local_callback_url = (
        f"http://127.0.0.1:8765/approve?issue={urllib.parse.quote(issue_id)}"
        f"&token={urllib.parse.quote(token)}"
    )

    self.conn.execute(
        "INSERT OR REPLACE INTO drafts(issue_id, timezone, content, created_at) VALUES (?, ?, ?, ?)",
        (issue_id, tz_name, draft, now),
    )
    self.conn.execute(
        """
        INSERT OR REPLACE INTO approvals(issue_id, token, expires_at, status, used, decided_at)
        VALUES (?, ?, ?, 'pending', 0, NULL)
        """,
        (issue_id, token, expires_at),
    )
    self.conn.commit()
    return {
        "status": "pending_approval",
        "issue_id": issue_id,
        "draft": draft,
        "approval_token": token,
        "local_callback_url": local_callback_url,
        "spent_usd": self.get_issue_spend(issue_id),
    }

  def approve_via_callback_path(self, request_path: str) -> bool:
    """免公网穿透本地轻量回调路由解析器（可直接供 http.server 或本地 CLI 调用）。"""
    parsed = urllib.parse.urlsplit(request_path)
    if parsed.path != "/approve":
      return False
    params = urllib.parse.parse_qs(parsed.query)
    issue_id = (params.get("issue") or [""])[0]
    token = (params.get("token") or [""])[0]
    if not issue_id or not token:
      return False
    return self.approve_issue(issue_id, token)

  def approve_issue(self, issue_id: str, token: str) -> bool:
    """一次性鉴权审批：核对令牌、检查过期时间，且生效一次后立即作废。"""
    row = self.conn.execute(
        "SELECT token, expires_at, status, used FROM approvals WHERE issue_id = ?",
        (issue_id,),
    ).fetchone()
    if not row:
      return False

    stored_token, expires_at, status, used = row[0], float(row[1]), row[2], int(row[3])
    now = self.clock_fn()
    if now >= expires_at:
      self.conn.execute(
          "UPDATE approvals SET status = 'expired', decided_at = ? WHERE issue_id = ?",
          (now, issue_id),
      )
      self.conn.commit()
      return False

    if used != 0 or status != "pending":
      return False

    if not secrets.compare_digest(stored_token, token):
      return False

    self.conn.execute(
        "UPDATE approvals SET status = 'approved', used = 1, decided_at = ? WHERE issue_id = ?",
        (now, issue_id),
    )
    self.conn.commit()
    return True

  def _deliver_to_subscriber(
      self,
      issue_id: str,
      sub: dict[str, Any],
      body: str,
      *,
      max_retries: int = 4,
  ) -> str:
    """对单个订户执行幂等检查、错误分级与带抖动指数退避投递。"""
    sub_id = sub["subscriber_id"]
    email = sub["email"]
    idem_key = f"{issue_id}:{sub_id}"

    existing = self.conn.execute(
        "SELECT status FROM send_logs WHERE issue_id = ? AND subscriber_id = ?",
        (issue_id, sub_id),
    ).fetchone()
    if existing and existing[0] == "sent":
      return "skipped_idempotent"

    attempts = 0
    last_code: int | str = ""
    last_msg = ""

    for retry_idx in range(max_retries + 1):
      attempts += 1
      code, msg = self.gateway.send_email(
          sub_id,
          email,
          f"AI 日课周刊 {issue_id}",
          body,
          idempotency_key=idem_key,
      )
      last_code, last_msg = code, msg

      if code == 200:
        self.conn.execute(
            """
            INSERT INTO send_logs(issue_id, subscriber_id, email, idempotency_key, status, attempts, last_error, updated_at)
            VALUES (?, ?, ?, ?, 'sent', ?, NULL, ?)
            ON CONFLICT(issue_id, subscriber_id) DO UPDATE SET
              status = 'sent',
              attempts = send_logs.attempts + excluded.attempts,
              last_error = NULL,
              updated_at = excluded.updated_at
            """,
            (issue_id, sub_id, email, idem_key, attempts, self.clock_fn()),
        )
        self.conn.execute(
            "DELETE FROM dead_letters WHERE issue_id = ? AND subscriber_id = ?",
            (issue_id, sub_id),
        )
        self.conn.commit()
        return "sent"

      if code in NON_RETRYABLE_CODES:
        self.conn.execute(
            """
            INSERT INTO send_logs(issue_id, subscriber_id, email, idempotency_key, status, attempts, last_error, updated_at)
            VALUES (?, ?, ?, ?, 'skipped_non_retryable', ?, ?, ?)
            ON CONFLICT(issue_id, subscriber_id) DO UPDATE SET
              status = 'skipped_non_retryable',
              attempts = excluded.attempts,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at
            """,
            (issue_id, sub_id, email, idem_key, attempts, f"{code}: {msg}", self.clock_fn()),
        )
        self.conn.commit()
        return "skipped_non_retryable"

      if code in RETRYABLE_CODES and retry_idx < max_retries:
        backoff_exp = retry_idx + 1  # 2^1=2s, 2^2=4s, 2^3=8s, 2^4=16s
        delay = float(2**backoff_exp) + self.rng.uniform(0.05, 0.95)
        self.sleep_fn(delay)
        continue
      break

    # 可重试错误耗尽上限，写入死信表
    now = self.clock_fn()
    self.conn.execute(
        """
        INSERT INTO send_logs(issue_id, subscriber_id, email, idempotency_key, status, attempts, last_error, updated_at)
        VALUES (?, ?, ?, ?, 'dead_letter', ?, ?, ?)
        ON CONFLICT(issue_id, subscriber_id) DO UPDATE SET
          status = 'dead_letter',
          attempts = send_logs.attempts + excluded.attempts,
          last_error = excluded.last_error,
          updated_at = excluded.updated_at
        """,
        (issue_id, sub_id, email, idem_key, attempts, f"{last_code}: {last_msg}", now),
    )
    self.conn.execute(
        """
        INSERT OR REPLACE INTO dead_letters(issue_id, subscriber_id, email, last_code, reason, attempts, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (issue_id, sub_id, email, str(last_code), last_msg, attempts, now),
    )
    self.conn.commit()
    return "dead_letter"

  def dispatch_issue(self, issue_id: str, *, max_retries: int = 4) -> dict[str, Any]:
    """核验审批状态（超时默认中止不发送），对全量订户执行幂等退避投递并汇总死信告警。"""
    appr = self.conn.execute(
        "SELECT status, expires_at FROM approvals WHERE issue_id = ?",
        (issue_id,),
    ).fetchone()
    if not appr:
      return {"status": "missing_approval", "sent_count": 0, "dead_letter_count": 0}

    status, expires_at = appr[0], float(appr[1])
    now = self.clock_fn()
    if status != "approved":
      if now >= expires_at:
        self.conn.execute(
            "UPDATE approvals SET status = 'expired', decided_at = ? WHERE issue_id = ?",
            (now, issue_id),
        )
        self.conn.commit()
        alert = (
            f"[ALERT][APPROVAL_EXPIRED] 期号 {issue_id} 超过审批时限未确认，"
            "按默认安全策略自动作废中止，本期零邮件发出。"
        )
        self.alerts.append(alert)
        return {"status": "expired_aborted", "sent_count": 0, "dead_letter_count": 0}
      return {"status": "waiting_approval", "sent_count": 0, "dead_letter_count": 0}

    draft_row = self.conn.execute(
        "SELECT content FROM drafts WHERE issue_id = ?", (issue_id,)
    ).fetchone()
    if not draft_row:
      return {"status": "missing_draft", "sent_count": 0, "dead_letter_count": 0}
    body = draft_row[0]

    counts = {
        "sent": 0,
        "skipped_idempotent": 0,
        "skipped_non_retryable": 0,
        "dead_letter": 0,
    }
    for sub in self.subscribers:
      outcome = self._deliver_to_subscriber(issue_id, sub, body, max_retries=max_retries)
      counts[outcome] += 1

    if counts["dead_letter"] > 0:
      alert = (
          f"[HIGH_ALERT][DEAD_LETTER] 期号 {issue_id} 有 {counts['dead_letter']} 位订户重试耗尽落入死信队列，"
          "请排查网关后运行 replay_dead_letters 补发。"
      )
      self.alerts.append(alert)

    return {
        "status": "completed",
        "sent_count": counts["sent"],
        "skipped_idempotent_count": counts["skipped_idempotent"],
        "skipped_non_retryable_count": counts["skipped_non_retryable"],
        "dead_letter_count": counts["dead_letter"],
    }

  def replay_dead_letters(self, issue_id: str, *, max_retries: int = 4) -> dict[str, Any]:
    """仅补发死信入口：只针对指定期号死信表中的记录重新投递，绝不惊扰已成功订户。"""
    draft_row = self.conn.execute(
        "SELECT content FROM drafts WHERE issue_id = ?", (issue_id,)
    ).fetchone()
    if not draft_row:
      return {"replayed_sent_count": 0, "remaining_dead_letters": 0}
    body = draft_row[0]

    dlq_rows = self.conn.execute(
        "SELECT subscriber_id, email FROM dead_letters WHERE issue_id = ? ORDER BY subscriber_id",
        (issue_id,),
    ).fetchall()

    replayed_sent = 0
    for sub_id, email in dlq_rows:
      sub = self.subscribers_by_id.get(
          sub_id, {"subscriber_id": sub_id, "email": email}
      )
      outcome = self._deliver_to_subscriber(issue_id, sub, body, max_retries=max_retries)
      if outcome == "sent":
        replayed_sent += 1

    rem_row = self.conn.execute(
        "SELECT COUNT(*) FROM dead_letters WHERE issue_id = ?", (issue_id,)
    ).fetchone()
    remaining = int(rem_row[0]) if rem_row else 0
    return {
        "replayed_sent_count": replayed_sent,
        "remaining_dead_letters": remaining,
    }


if __name__ == "__main__":
  recorded_delays: list[float] = []
  pipe = NewsletterPipeline(sleep_fn=recorded_delays.append)
  prep = pipe.prepare_issue("2026-W20")
  pipe.approve_issue("2026-W20", prep["approval_token"])
  first_run = pipe.dispatch_issue("2026-W20")
  second_run = pipe.dispatch_issue("2026-W20")
  pipe.gateway.transient_recovered = True
  replay_res = pipe.replay_dead_letters("2026-W20")
  print("首轮发送：", first_run)
  print("同号重跑：", second_run)
  print("死信补发：", replay_res)
