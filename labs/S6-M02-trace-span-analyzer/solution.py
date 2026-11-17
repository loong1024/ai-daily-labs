"""S6-M02 Langfuse 链路脱敏与轨迹归因分析 —— 标准参考实现。"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_FAKE_KEY_RE = re.compile(r"FAKE_TEST_KEY_DO_NOT_USE_[A-Za-z0-9_]+")

_GUARDRAIL_MAP = {
    "duplicate_tool_call": "单次请求同一工具调用不得超过 1 次，命中缓存直接复用结果",
    "slow_retrieval_timeout": "检索节点超时或慢查询需触发降级提示并优化索引分片",
    "empty_context_hallucination": "知识库召回数为 0 时必须明确告知未查到依据，禁止编造报销口径",
    "schema_parse_error": "启用严格结构化 Schema 校验并在工具入参不合法时触发参数修正",
}


def scrub_pii(text: str) -> str:
    """掩码脱敏文本中的 11 位手机号、电子邮箱及测试占位密钥。"""
    if not text:
        return ""
    masked = _PHONE_RE.sub(r"\1****\2", str(text))
    masked = _EMAIL_RE.sub(r"\1***@\2", masked)
    masked = _FAKE_KEY_RE.sub("[REDACTED_KEY]", masked)
    return masked


def _hash_user_id(raw_user_id: str) -> str:
    digest = hashlib.sha256((raw_user_id or "anonymous").encode("utf-8")).hexdigest()[:12]
    return f"usr_hash_{digest}"


def build_sanitized_trace(raw_event: dict[str, Any]) -> dict[str, Any]:
    """将多步执行记录组装为统一 trace_id 下的脱敏 Span 列表。"""
    sanitized_spans: list[dict[str, Any]] = []
    total_latency_ms = 0
    total_tokens = 0

    for step in raw_event.get("steps", []):
        dur = int(step.get("duration_ms", 0))
        toks = int(step.get("tokens", 0))
        total_latency_ms += dur
        total_tokens += toks
        span_item: dict[str, Any] = {
            "span_id": str(step.get("step_id", "")),
            "type": str(step.get("type", "")),
            "name": str(step.get("name", "")),
            "duration_ms": dur,
            "tokens": toks,
            "input": scrub_pii(str(step.get("input", ""))),
            "output": scrub_pii(str(step.get("output", ""))),
            "error": str(step.get("error", "")),
        }
        if "hit_count" in step:
            span_item["hit_count"] = int(step["hit_count"])
        sanitized_spans.append(span_item)

    return {
        "trace_id": f"trace_{raw_event.get('request_id', 'unknown')}",
        "status": str(raw_event.get("status", "ok")),
        "metadata": {
            "prompt_version": str(raw_event.get("prompt_version", "")),
            "model": str(raw_event.get("model", "")),
            "feature": str(raw_event.get("feature", "")),
            "user_hash": _hash_user_id(str(raw_event.get("user_id", ""))),
        },
        "total_latency_ms": total_latency_ms,
        "total_tokens": total_tokens,
        "spans": sanitized_spans,
    }


def audit_trace_trajectory(
    trace: dict[str, Any], latency_sla_ms: int = 2500
) -> dict[str, Any]:
    """检查单条 Trace 轨迹中的重复工具调用、慢检索、空召回点踩与解析错误。"""
    spans = trace.get("spans") or []
    tool_counts: dict[str, int] = collections.Counter()
    anomalies: list[str] = []

    has_llm = False
    for sp in spans:
        sp_type = sp.get("type")
        sp_err = str(sp.get("error", ""))
        dur = int(sp.get("duration_ms", 0))

        if sp_err in ("invalid_tool_args", "json_schema_error"):
            if "schema_parse_error" not in anomalies:
                anomalies.append("schema_parse_error")

        if sp_type == "tool":
            tool_name = str(sp.get("name", "unknown_tool"))
            tool_counts[tool_name] += 1

        if sp_type == "retrieval":
            if sp_err == "retrieval_timeout" or dur >= latency_sla_ms:
                if "slow_retrieval_timeout" not in anomalies:
                    anomalies.append("slow_retrieval_timeout")
            if int(sp.get("hit_count", 1)) == 0 and trace.get("user_feedback") == "thumb_down":
                if "empty_context_hallucination" not in anomalies:
                    anomalies.append("empty_context_hallucination")

        if sp_type == "llm":
            has_llm = True

    if any(cnt > 1 for cnt in tool_counts.values()):
        anomalies.insert(0, "duplicate_tool_call")

    if not has_llm:
        anomalies.append("missing_llm_span")

    return {
        "passed": len(anomalies) == 0 and trace.get("status") != "error",
        "anomalies": anomalies,
        "tool_call_counts": dict(tool_counts),
    }


def _compute_p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[idx]


def _classify_primary_cause(trace: dict[str, Any], latency_sla_ms: int) -> str | None:
    audit = audit_trace_trajectory(trace, latency_sla_ms=latency_sla_ms)
    if audit["passed"]:
        return None
    priority = [
        "schema_parse_error",
        "duplicate_tool_call",
        "slow_retrieval_timeout",
        "empty_context_hallucination",
    ]
    for cause in priority:
        if cause in audit["anomalies"]:
            return cause
    return audit["anomalies"][0] if audit["anomalies"] else "unknown_error"


def triage_abnormal_traces(
    traces: list[dict[str, Any]], latency_sla_ms: int = 2500
) -> dict[str, Any]:
    """对异常 Trace 批量贴标归因、统计各版本 P95 延迟并导出脱敏回归种子集。"""
    cause_counter: collections.Counter[str] = collections.Counter()
    grouped_examples: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    version_latencies: dict[str, list[int]] = collections.defaultdict(list)

    for tr in traces:
        spans = tr.get("spans") or []
        total_dur = sum(int(sp.get("duration_ms", 0)) for sp in spans)
        ver = str((tr.get("metadata") or {}).get("prompt_version", "unknown"))
        version_latencies[ver].append(total_dur)

        cause = _classify_primary_cause(tr, latency_sla_ms=latency_sla_ms)
        if cause is not None:
            cause_counter[cause] += 1
            grouped_examples[cause].append(tr)

    total_abnormal = sum(cause_counter.values())
    ranked = cause_counter.most_common(3)
    top_3_causes = [
        {
            "cause": cause,
            "count": count,
            "share": round(count / max(1, total_abnormal), 4),
        }
        for cause, count in ranked
    ]

    seed_jsonl_lines: list[str] = []
    for item in top_3_causes:
        cause_name = item["cause"]
        for sample in grouped_examples[cause_name][:2]:
            meta = sample.get("metadata") or {}
            seed_obj = {
                "trace_id": sample.get("trace_id", ""),
                "root_cause": cause_name,
                "prompt_version": meta.get("prompt_version", ""),
                "user_hash": _hash_user_id(str(meta.get("user_id", ""))),
                "input": scrub_pii(str(sample.get("input", ""))),
                "expected_guardrail": _GUARDRAIL_MAP.get(cause_name, "补充回归断言"),
            }
            seed_jsonl_lines.append(json.dumps(seed_obj, ensure_ascii=False))

    version_p95 = {
        ver: _compute_p95(lats) for ver, lats in sorted(version_latencies.items())
    }

    summary = chat_complete(
        [
            {
                "role": "user",
                "content": f"请用一句话总结本周异常归因 Top3：{json.dumps(top_3_causes, ensure_ascii=False)}",
            }
        ],
        mock_fn=lambda _m: (
            f"共归因 {total_abnormal} 条异常 Trace，前三类根因为："
            + "、".join(f"{x['cause']}({x['count']}条)" for x in top_3_causes)
        ),
    )

    return {
        "total_abnormal": total_abnormal,
        "cause_counts": dict(cause_counter),
        "top_3_causes": top_3_causes,
        "version_p95_latency_ms": version_p95,
        "seed_jsonl_lines": seed_jsonl_lines,
        "weekly_summary": summary,
    }
