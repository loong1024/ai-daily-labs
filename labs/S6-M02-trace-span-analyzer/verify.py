#!/usr/bin/env python3
"""S6-M02 自动化验收脚本。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: E402

_RAW_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_RAW_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _load_target_module() -> Any:
    mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
    spec = importlib.util.spec_from_file_location("s6_m02_target", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s6_m02_target"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    v = LabVerifier("S6-M02", "Langfuse 串联链路 Trace 与坏例归因")

    sample_requests = json.loads(
        (LAB_DIR / "fixtures" / "sample_multistep_request.json").read_text(encoding="utf-8")
    )
    abnormal_lines = (
        (LAB_DIR / "fixtures" / "abnormal_traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    abnormal_traces = [json.loads(line) for line in abnormal_lines if line.strip()]

    try:
        mod = _load_target_module()
    except Exception as exc:
        v.check("模块加载与语法检查", False, f"导入目标模块失败：{exc}")
        return v.finish()

    # Check 1: 多步 Span 串联、元数据附加与手机号/邮箱/用户 ID 脱敏
    normal_trace: dict[str, Any] = {}
    sneaky_trace: dict[str, Any] = {}
    try:
        normal_trace = mod.build_sanitized_trace(sample_requests["normal_request"])
        sneaky_trace = mod.build_sanitized_trace(sample_requests["sneaky_duplicate_request"])
        serialized = json.dumps(normal_trace, ensure_ascii=False)
        spans = normal_trace.get("spans") or []
        span_types = {sp.get("type") for sp in spans if isinstance(sp, dict)}
        meta = normal_trace.get("metadata") or {}

        ok_trace = (
            bool(normal_trace.get("trace_id"))
            and span_types == {"retrieval", "tool", "llm"}
            and int(normal_trace.get("total_latency_ms", 0)) == 1045
            and int(normal_trace.get("total_tokens", 0)) == 310
            and meta.get("prompt_version") == "v2.2"
            and str(meta.get("user_hash", "")) != sample_requests["normal_request"]["user_id"]
            and "wangmin" not in serialized
            and _RAW_PHONE_RE.search(serialized) is None
            and _RAW_EMAIL_RE.search(serialized) is None
        )
        v.check(
            "多步链路 Span 串联与手机号/邮箱/用户 ID 脱敏",
            ok_trace,
            "请在 scrub_pii 与 build_sanitized_trace 中掩码手机号和邮箱、哈希处理 user_id，并汇总 total_latency_ms 与 total_tokens。",
        )
    except Exception as exc:
        v.check(
            "多步链路 Span 串联与手机号/邮箱/用户 ID 脱敏",
            False,
            f"build_sanitized_trace 执行异常 ({exc})。",
        )

    # Check 2: 轨迹检查脚本准确拦截“结果正确但同一工具重复调用 > 1 次”
    try:
        audit_ok = mod.audit_trace_trajectory(normal_trace)
        audit_dup = mod.audit_trace_trajectory(sneaky_trace)
        tool_counts = audit_dup.get("tool_call_counts") or {}
        ok_trajectory = (
            audit_ok.get("passed") is True
            and audit_dup.get("passed") is False
            and "duplicate_tool_call" in (audit_dup.get("anomalies") or [])
            and tool_counts.get("get_weather") == 3
        )
        v.check(
            "轨迹检查器拦截单次请求同一工具调用 > 1 次的隐性异常",
            ok_trajectory,
            "请在 audit_trace_trajectory 中统计各 tool Span 调用次数，当同名工具调用 > 1 次时即使 status=='ok' 也返回 passed=False 并标记 duplicate_tool_call。",
        )
    except Exception as exc:
        v.check(
            "轨迹检查器拦截单次请求同一工具调用 > 1 次的隐性异常",
            False,
            f"audit_trace_trajectory 执行异常 ({exc})。",
        )

    # Check 3: 20+ 条异常样本错因贴标排序与版本 P95 延迟对比
    report: dict[str, Any] = {}
    try:
        report = mod.triage_abnormal_traces(abnormal_traces)
        top3 = report.get("top_3_causes") or []
        causes_order = [item.get("cause") for item in top3 if isinstance(item, dict)]
        counts_order = [item.get("count") for item in top3 if isinstance(item, dict)]
        p95_map = report.get("version_p95_latency_ms") or {}

        ok_triage = (
            int(report.get("total_abnormal", 0)) >= 20
            and causes_order
            == [
                "duplicate_tool_call",
                "slow_retrieval_timeout",
                "empty_context_hallucination",
            ]
            and counts_order == [9, 7, 5]
            and int(p95_map.get("v2.2", 0)) > int(p95_map.get("v2.1", 0)) > 0
        )
        v.check(
            "20+ 条异常样本错因归因排序与版本 P95 延迟统计",
            ok_triage,
            "请在 triage_abnormal_traces 中完成 24 条异常样本的四类根因归并排序（提取 Top 3 根因及计数）并按 prompt_version 计算 P95 延迟。",
        )
    except Exception as exc:
        v.check(
            "20+ 条异常样本错因归因排序与版本 P95 延迟统计",
            False,
            f"triage_abnormal_traces 执行异常 ({exc})。",
        )

    # Check 4: Top 3 典型坏例脱敏导出为回归种子 JSONL
    try:
        seed_lines = report.get("seed_jsonl_lines") or []
        parsed_seeds = [json.loads(line) for line in seed_lines if isinstance(line, str) and line.strip()]
        exported_causes = {item.get("root_cause") for item in parsed_seeds}
        joined_seeds = "\n".join(seed_lines)
        has_required_fields = all(
            bool(item.get("trace_id"))
            and bool(item.get("input"))
            and bool(item.get("expected_guardrail"))
            for item in parsed_seeds
        )
        ok_seeds = (
            len(parsed_seeds) >= 3
            and exported_causes
            == {
                "duplicate_tool_call",
                "slow_retrieval_timeout",
                "empty_context_hallucination",
            }
            and has_required_fields
            and _RAW_PHONE_RE.search(joined_seeds) is None
            and _RAW_EMAIL_RE.search(joined_seeds) is None
        )
        v.check(
            "Top 3 典型坏例脱敏导出为 JSONL 回归种子样本",
            ok_seeds,
            "请将前三类根因的代表性坏例经 scrub_pii 脱敏后导出到 seed_jsonl_lines（包含 trace_id、root_cause、input、expected_guardrail 字段）。",
        )
    except Exception as exc:
        v.check(
            "Top 3 典型坏例脱敏导出为 JSONL 回归种子样本",
            False,
            f"校验导出种子 JSONL 时异常 ({exc})。",
        )

    return v.finish()


if __name__ == "__main__":
    raise SystemExit(main())
