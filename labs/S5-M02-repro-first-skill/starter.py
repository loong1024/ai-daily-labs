"""S5-M02 Starter：复现优先调试包装器、历史 Bug 先红后绿练习与二振止损守卫。"""

from __future__ import annotations

from typing import Any, Callable

# TODO 3a：定位 fixtures/buggy_billing.py 的缺陷后，用一句话写清根因及证据（不少于 15 字，去掉 TODO）
ROOT_CAUSE_SUMMARY = "TODO: 请填写一句话根因与证据"


def summarize_test_run(raw_output: str, max_tail_lines: int = 15) -> str:
    """精简测试输出包装器（避免海量日志刷爆 AI 上下文）。

    目标规格：
    1. 若全部测试通过（无 FAILED / failed / error）：仅返回不超过 3 行的简短通过汇总，不输出 DEBUG 噪音行。
    2. 若存在测试失败：提取所有失败用例标识（如 FAILED tests/...::test_xxx），
       过滤掉 PASSED 与 DEBUG/INFO 噪音行，仅附带最后 max_tail_lines 行关键报错详情。
    """
    # TODO 1：当前基线原样返回了完整刷屏日志，请实现降噪截取逻辑
    return raw_output


def test_promo_refund_repro(calc_fn: Callable[..., int]) -> None:
    """针对 BUG-2026-0418（优惠券订单中途退订）的最小必败回归测试。

    要求：
    - 当传入故障基准函数（fixtures/buggy_billing.py）时，本函数必须触发 AssertionError（先红）；
    - 当传入修复后的 calculate_prorated_refund 时，本函数正常通过（后绿）。
    """
    # TODO 2：请根据 fixtures/repro_cases.json 中的 bug_reports 编写最小复现 assert 断言
    pass


def calculate_prorated_refund(
    paid_cents: int,
    total_days: int,
    used_days: int,
    promo_cents: int = 0,
) -> int:
    """计算会员中途退订应退金额（单位：分）。

    既有测试约定（严禁破坏）：
    - total_days <= 0 抛出 ValueError
    - used_days <= 0 全额退还 paid_cents
    - used_days >= total_days 退还 0
    - 中途退订按实付金额 paid_cents 与剩余天数等比向下取整折算
    """
    if total_days <= 0:
        raise ValueError("total_days must be positive")
    if used_days <= 0:
        return paid_cents
    if used_days >= total_days:
        return 0

    remaining_days = total_days - used_days
    # TODO 3b：修复此处重复扣减 promo_cents 导致少退/算出负数的缺陷（做最小改动）
    raw_refund = (paid_cents * remaining_days) // total_days - promo_cents
    return raw_refund


def decide_debug_next_action(state: dict[str, Any]) -> dict[str, str]:
    """复现优先与止损状态机守卫。

    输入 state 字段见 fixtures/repro_cases.json 的 triage_scenarios，返回值必须包含 {"action": ..., "reason": ...}：
    - 缺少堆栈/复现步骤/期望实际对比/环境信息任一项 -> action = "ask_user"
    - 连续修复无效次数 failed_attempts >= 2 -> action = "rollback_and_report"
    - 还没有确认失败的复现测试（repro_test_failing_confirmed 为 False） -> action = "write_repro_test"
    - 需要改动公共接口或数据库结构但尚未获用户批准 -> action = "request_approval"
    - 其余具备最小修复条件 -> action = "apply_minimal_fix"
    """
    # TODO 4：当前基线不管三七二十一直接盲改代码，请按止损纪律重构判断顺序
    return {
        "action": "edit_code_directly",
        "reason": "未检查前置条件直接盲改业务源码",
    }
