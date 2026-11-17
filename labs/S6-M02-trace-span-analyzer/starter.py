"""S6-M02 Langfuse 链路脱敏与轨迹归因分析 —— 起点骨架（含待完善的工程 TODO）。"""

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


def scrub_pii(text: str) -> str:
    """对上报云端前的日志文本做手机号与邮箱脱敏。

    TODO:
    1. 将 11 位手机号掩码为 138****5678 格式。
    2. 将邮箱掩码为首字符 + ***@域名 格式（避免明文邮箱泄露）。
    """
    # 缺陷基线：未做任何敏感信息掩码
    return text


def build_sanitized_trace(raw_event: dict[str, Any]) -> dict[str, Any]:
    """将多步执行事件组装为单条脱敏 Trace（含检索、工具、模型独立 Span 及版本元数据）。

    TODO:
    1. 对 user_id 做单向 SHA-256 哈希截断（如 usr_hash_xxxxxxxxxxxx），不保留明文 user_id。
    2. 对每个 step 的 input/output 调用 scrub_pii 脱敏，统计 total_latency_ms 与 total_tokens。
    """
    spans = list(raw_event.get("steps", []))
    return {
        "trace_id": f"trace_{raw_event.get('request_id', 'unknown')}",
        "status": raw_event.get("status", "ok"),
        "metadata": {
            "prompt_version": raw_event.get("prompt_version", ""),
            "model": raw_event.get("model", ""),
            "feature": raw_event.get("feature", ""),
            "user_hash": raw_event.get("user_id", ""),  # 缺陷：直接暴露明文 user_id
        },
        "total_latency_ms": 0,
        "total_tokens": 0,
        "spans": spans,
    }


def audit_trace_trajectory(
    trace: dict[str, Any], latency_sla_ms: int = 2500
) -> dict[str, Any]:
    """检查单条 Trace 的调用轨迹异常。

    TODO:
    1. 统计同一请求中各 tool Span 的调用次数，若任意同名工具调用 > 1 次，即使 status == "ok" 也必须加入 "duplicate_tool_call" 异常并判定 passed=False。
    2. 检查检索超时/超过 latency_sla_ms ("slow_retrieval_timeout") 等轨迹异常。
    """
    # 缺陷基线：只看顶层 status 是否报错，漏掉“结果碰巧正确但重复调了多次工具”的隐性烧钱请求
    passed = trace.get("status") != "error"
    return {
        "passed": passed,
        "anomalies": [] if passed else ["status_error"],
        "tool_call_counts": {},
    }


def triage_abnormal_traces(
    traces: list[dict[str, Any]], latency_sla_ms: int = 2500
) -> dict[str, Any]:
    """对 20+ 条异常 Trace 归因计数排序、统计各版本 P95 延迟，并导出前 3 类典型坏例 JSONL 种子。

    根因分类约定：
    - "duplicate_tool_call": 单次请求内同一工具调用 > 1 次
    - "slow_retrieval_timeout": retrieval 节点报错 retrieval_timeout 或耗时 >= latency_sla_ms
    - "empty_context_hallucination": retrieval 节点 hit_count == 0 但未拒答导致点踩 (thumb_down)
    - "schema_parse_error": 节点报错 invalid_tool_args 或 json_schema_error

    TODO:
    1. 对全部异常样本分类计数，按样本数降序生成 top_3_causes 列表 [{"cause": ..., "count": ..., "share": ...}]。
    2. 按 metadata.prompt_version 计算各版本总耗时 P95 (version_p95_latency_ms)。
    3. 为前 3 类根因抽取代表性样本，调用 scrub_pii 脱敏后序列化为 seed_jsonl_lines（每行一条 JSON 字符串）。
    """
    _ = (traces, latency_sla_ms, json, chat_complete)
    return {
        "total_abnormal": 0,
        "cause_counts": {},
        "top_3_causes": [],
        "version_p95_latency_ms": {},
        "seed_jsonl_lines": [],
        "weekly_summary": "",
    }
