"""S5-M02 Solution：复现优先调试包装器、历史 Bug 最小修复与二振止损守卫参考实现。"""

from __future__ import annotations

from typing import Any, Callable

ROOT_CAUSE_SUMMARY = (
    "根因：paid_cents 已是扣完优惠券后的实付金额，calculate_prorated_refund 在按剩余天数比例折算后又重复减去了 promo_cents，"
    "导致优惠券订单少退 3000 分甚至在临近到期时算出负数。"
)


def summarize_test_run(raw_output: str, max_tail_lines: int = 15) -> str:
    """精简测试输出包装器：全绿只回一行汇总，失败提取用例名并截断末尾报错行。"""
    lines = [ln.rstrip() for ln in raw_output.splitlines() if ln.strip()]
    if not lines:
        return "PASS SUMMARY: empty output"

    summary_line = lines[-1]
    failed_items: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("FAILED "):
            failed_items.append(stripped)
        elif "::" in stripped and stripped.endswith(" FAILED"):
            failed_items.append(stripped)

    lower_summary = summary_line.lower()
    has_failure = bool(failed_items) or ("failed" in lower_summary) or ("error" in lower_summary)
    if not has_failure:
        clean_summary = summary_line.strip("= ").strip()
        return f"PASS SUMMARY: {clean_summary}"

    noise_prefixes = ("DEBUG ", "INFO ")
    filtered = [
        ln
        for ln in lines
        if not ln.lstrip().startswith(noise_prefixes)
        and not ("::" in ln and ln.rstrip().endswith("PASSED"))
    ]
    tail = filtered[-max_tail_lines:] if max_tail_lines > 0 else []

    parts = ["FAIL SUMMARY:"]
    if failed_items:
        unique_failed = list(dict.fromkeys(failed_items))
        parts.append("Failed tests: " + "; ".join(unique_failed))
    parts.append(f"Error tail ({len(tail)} lines):")
    parts.extend(tail)
    return "\n".join(parts)


def test_promo_refund_repro(calc_fn: Callable[..., int]) -> None:
    """针对 BUG-2026-0418 的最小必败回归测试。"""
    assert calc_fn(paid_cents=7000, total_days=30, used_days=15, promo_cents=3000) == 3500
    assert calc_fn(paid_cents=7000, total_days=30, used_days=25, promo_cents=3000) == 1166


def calculate_prorated_refund(
    paid_cents: int,
    total_days: int,
    used_days: int,
    promo_cents: int = 0,
) -> int:
    """按实付金额与剩余天数比例计算应退金额（最小修复：移除重复扣减的 promo_cents 并保证非负）。"""
    del promo_cents
    if total_days <= 0:
        raise ValueError("total_days must be positive")
    if used_days <= 0:
        return max(0, paid_cents)
    if used_days >= total_days:
        return 0

    remaining_days = total_days - used_days
    return max(0, (paid_cents * remaining_days) // total_days)


def decide_debug_next_action(state: dict[str, Any]) -> dict[str, str]:
    """严格遵循 repro-first-debugging 纪律的下一步决策守卫。"""
    required_info_keys = (
        "has_stacktrace",
        "has_repro_steps",
        "has_expected_actual",
        "has_env_info",
    )
    missing = [k for k in required_info_keys if not state.get(k, False)]
    if missing:
        return {
            "action": "ask_user",
            "reason": f"缺少关键排障信息（{', '.join(missing)}），先向用户询问确认，禁止盲猜改代码。",
        }

    if int(state.get("failed_attempts", 0)) >= 2:
        return {
            "action": "rollback_and_report",
            "reason": "同一问题连续 2 次修复无效，立即停止修改并回滚到修复前状态，汇报已验证与已排除假设。",
        }

    if not state.get("repro_test_failing_confirmed", False):
        return {
            "action": "write_repro_test",
            "reason": "尚未构造稳定失败的最小复现测试，须先写必败测试确认故障复现。",
        }

    if state.get("touches_public_api_or_schema", False) and not state.get(
        "user_approved_breaking_change", False
    ):
        return {
            "action": "request_approval",
            "reason": "修复涉及公共接口、数据库结构或新增依赖，须先说明理由并征得用户同意。",
        }

    return {
        "action": "apply_minimal_fix",
        "reason": "必败复现已锁定且不触碰高危契约边界，可执行最小范围根因修复并跑全量回归。",
    }
