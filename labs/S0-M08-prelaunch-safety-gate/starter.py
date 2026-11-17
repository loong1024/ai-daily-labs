"""S0-M08 上线前硬兜底安全排查 —— 起点骨架（含待修复的软防御缺陷）。"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


def classify_injection_channel(user_query: str, external_doc: str) -> dict[str, Any]:
    """识别输入风险通道并构造送往模型的消息列表。

    TODO:
    1. 区分来自 user_query 的直接提示注入 ("direct") 与来自 external_doc 的间接注入 ("indirect")，无风险为 "none"。
    2. 将不可信外部文档包裹在 <untrusted_document>...</untrusted_document> 边界标签中，避免与指令混同。
    """
    # 缺陷基线：仅靠系统提示词软叮嘱，把用户问题与外部文档直接拼在一起，也不区分注入通道
    combined = f"请严格遵守规则不要泄密。\n用户问题：{user_query}\n文档内容：{external_doc}"
    return {
        "risk_category": "none",
        "source_type": "none",
        "isolated_messages": [
            {"role": "user", "content": combined},
        ],
    }


def sanitize_model_html(raw_output: str) -> str:
    """在送交前端展示前对模型输出做安全转义。

    TODO: 使用标准库 html.escape(..., quote=True) 将 <script> 及引号转义为安全纯文本实体。
    """
    # 缺陷基线：原样透传 HTML 字符串
    return raw_output


def build_authorized_doc_query(
    session_user_id: str,
    requested_owner_id: str,
    category: str,
) -> dict[str, Any]:
    """构建带服务端会话权限校验与参数化占位的文档查询。

    TODO:
    1. 校验 session_user_id 非空且必须严格等于 requested_owner_id，否则拒绝访问 (allowed=False)。
    2. 使用 ? 参数化占位符返回 sql 与 params 元组，禁止字符串直接拼接 SQL。
    """
    # 缺陷基线：未核验当前登录用户与目标 owner 是否一致，且直接拼接 SQL 字符串
    sql = (
        f"SELECT doc_id, title FROM user_docs "
        f"WHERE owner_id = '{requested_owner_id}' AND category = '{category}'"
    )
    return {
        "allowed": True,
        "sql": sql,
        "params": (),
        "reason": "ok",
    }


def enforce_hard_quota_and_call(
    request_ctx: dict[str, Any],
    policy: dict[str, Any],
    messages: list[dict[str, str]],
    simulated_output: str = "默认摘要结果",
) -> dict[str, Any]:
    """网关层硬配额/鉴权门禁：先拦截超限请求，允许通过时调用模型并转义输出。

    TODO:
    1. 拦截未登录请求 (session_user_id 为空 -> blocked_reason="unauthenticated")。
    2. 拦截超出单窗口频控请求 (user_requests_in_window >= max_requests_per_minute -> blocked_reason="rate_limit_exceeded")。
    3. 拦截超出每日硬预算上限请求 (daily_spend_usd + estimated_cost_usd > hard_cap_usd -> blocked_reason="hard_cap_exceeded")。
    4. 拦截时不得调用 chat_complete (llm_called=False)；放行时对模型返回结果调用 sanitize_model_html。
    """
    projected = float(request_ctx.get("daily_spend_usd", 0.0)) + float(
        request_ctx.get("estimated_cost_usd", 0.0)
    )
    soft_alert = projected > float(policy.get("soft_alert_usd", 8.0))

    # 缺陷基线：仅打软告警标记，未做硬阻断，超额仍继续调用大模型且未转义输出
    raw_reply = chat_complete(
        messages,
        mock_fn=lambda _msgs: simulated_output,
    )
    return {
        "allowed": True,
        "blocked_reason": "",
        "soft_alert": soft_alert,
        "llm_called": True,
        "safe_html": raw_reply,
    }
