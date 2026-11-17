"""S5-M03 Solution：Spec 先行与单会话小步 TDD 标准参考实现。"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete  # noqa: E402

VALID_COUPONS: dict[str, int] = {
    "LAUNCH30": 3000,
    "TEAM100": 10000,
    "MEGA150": 15000,
}

ALLOWED_OUTPUT_KEYS = {
    "seats",
    "subtotal_cents",
    "discount_cents",
    "payable_cents",
    "currency",
}


def _mock_spec_generator(messages: list[dict[str, str]]) -> str:
    del messages
    return """# 企业团队席位阶梯报价器规格说明（spec.md）

## 1. 目标
为企业自助订阅结算流程提供确定性的席位阶梯报价与优惠码抵扣计算函数 `quote_team_subscription`，供结算服务调用，所有金额以整数“分（cents）”为单位，杜绝浮点精度误差。

## 2. 非目标（Non-Goals）
- **不做多币种与汇率换算**：本次仅支持人民币 `"CNY"`，不内置或请求任何汇率表。
- **不做税费与积分赠送计算**：不输出 `tax_cents`、`vip_points` 等账单扩展字段。
- **不改动同模块无关既有逻辑**：严禁顺手修改上游依赖的 `normalize_account_slug` 函数行为。

## 3. 接口与数据结构
函数签名：`quote_team_subscription(order: dict[str, Any]) -> dict[str, Any]`

| 场景说明 | 输入示例 `order` | 期望输出或异常 |
| :--- | :--- | :--- |
| 基础 1 席无券 | `{"seats": 1, "currency": "CNY"}` | `{"seats": 1, "subtotal_cents": 10000, "discount_cents": 0, "payable_cents": 10000, "currency": "CNY"}` |
| 跨档 12 席超额累进 | `{"seats": 12, "currency": "CNY"}` | `{"seats": 12, "subtotal_cents": 116000, "discount_cents": 0, "payable_cents": 116000, "currency": "CNY"}` |
| 跨三档 55 席叠券 | `{"seats": 55, "currency": "CNY", "coupon_code": "TEAM100"}` | `{"seats": 55, "subtotal_cents": 450000, "discount_cents": 10000, "payable_cents": 440000, "currency": "CNY"}` |
| 大额券零元封底 | `{"seats": 1, "currency": "CNY", "coupon_code": "MEGA150"}` | `{"seats": 1, "subtotal_cents": 10000, "discount_cents": 10000, "payable_cents": 0, "currency": "CNY"}` |
| 非目标币种拦截 | `{"seats": 8, "currency": "USD"}` | 抛出 `ValueError("UNSUPPORTED_CURRENCY")` |

## 4. 边界情况与错误处理
- 边界 1：`seats` 为 `0`、负数或大于自助上限 `500` 时，立即抛出 `ValueError`。
- 边界 2：`seats` 传入布尔值 `True`/`False`（Python 中 `bool` 继承自 `int`）或字符串时，立即抛出 `ValueError`。
- 边界 3：`coupon_code` 含首尾空白或小写字母（如 `" launch30 "`）时，自动做 `strip().upper()` 归一化匹配。
- 边界 4：`coupon_code` 非空但不在有效字典 `VALID_COUPONS` 中时，严禁静默忽略，必须抛出 `ValueError`。
- 边界 5：优惠券面额大于席位小计 `subtotal_cents` 时，`discount_cents` 取 `subtotal_cents`，`payable_cents` 封底为 `0` 分。
- 边界 6：`currency` 传入非 `"CNY"` 值时，抛出 `ValueError`，拒绝猜测汇率。

## 5. 验收标准
- **用例 1**：给定 `seats=12, currency="CNY"`，当调用报价函数时，那么按分段超额累进返回 `subtotal_cents=116000, payable_cents=116000`。
- **用例 2**：给定 `seats=1, coupon_code="MEGA150"`，当调用报价函数时，那么返回 `discount_cents=10000, payable_cents=0` 且不为负数。
- **用例 3**：给定未知优惠码 `"HACK999"` 或非目标币种 `"USD"`，当调用报价函数时，那么立即抛出 `ValueError`。
- **用例 4**：给定任意合法订单，当检查返回字典键集合时，那么严格等于 5 个约定字段，无多余越界字段。

## 6. 任务拆分
1. **任务 T1（须串行 - 改同一函数核心算价）**：编写 1/10/12/55 席分段超额累进失败测试并实现阶梯小计逻辑；验证方式：运行 `run_tdd_suite` 阶梯断言通过。
2. **任务 T2（须串行 - 依赖 T1 的 `subtotal_cents`）**：编写优惠码归一化、未知码报错与零元封底测试并实现抵扣逻辑；验证方式：优惠码正反用例全绿。
3. **任务 T3（须串行 - 改同一入参出口门禁）**：补齐席位类型/范围校验、非 `"CNY"` 币种拦截，清理越界返回字段并还原 `normalize_account_slug`；验证方式：`python3 verify.py` 全量通过。

## 7. 待确认问题
1. **问题 Q1（阶梯计费口径）**：跨档席位采用“方案 A：分段超额累进（如 12 席 = 10×100 + 2×80）”还是“方案 B：全量跳档单价（12×80）”？请确认。
2. **问题 Q2（超额立减与无效券策略）**：当券面额超过原价时采用“方案 A：最低应付 0 元封底”还是“方案 B：报错禁止用券”？无效优惠码是否直接抛异常？
3. **问题 Q3（多币种与税费边界）**：本期是否明确排除 `"USD"` 等外币换算与 `tax_cents` 税费字段（列为 Non-Goals）？
"""


def draft_spec_markdown(req_context: dict[str, Any]) -> str:
    """基于结构化 Spec 先行提示词生成 7 节规格文档（只出规格，不写实现）。"""
    system_prompt = (
        "你是一名严谨的软件工程师。在写任何实现代码之前，请严格输出包含以下 7 个二级标题的 spec.md：\n"
        "## 1. 目标\n## 2. 非目标\n## 3. 接口与数据结构（必须包含 Markdown 表格 | ... |）\n"
        "## 4. 边界情况与错误处理（至少 5 条 `- ` 列表项）\n"
        "## 5. 验收标准（必须使用‘给定……当……那么……’句式）\n"
        "## 6. 任务拆分（必须显式标注‘须串行’或‘可并行’及验证方式）\n"
        "## 7. 待确认问题（至少列出 3 个带编号候选方案的问题，不要自行假设）\n"
        "只输出 Markdown 规格说明，不要写业务实现源码。"
    )
    user_prompt = (
        f"需求：{req_context.get('vague_prompt', '')}\n"
        f"技术栈：{req_context.get('tech_stack', '')}\n"
        f"既有约定：{req_context.get('existing_conventions', '')}\n"
        f"硬性约束：{req_context.get('hard_constraints', '')}"
    )
    return chat_complete(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        mock_fn=_mock_spec_generator,
        temperature=0.0,
    )


def audit_spec_markdown(spec_md: str) -> dict[str, Any]:
    """量化检查 spec.md 是否满足 7 节契约门禁。"""
    missing: list[str] = []
    lines = spec_md.splitlines()

    if "目标" not in spec_md:
        missing.append("缺少‘目标’章节")
    if "非目标" not in spec_md and "Non-Goal" not in spec_md:
        missing.append("缺少‘非目标（Non-Goals）’清单")

    table_rows = [ln for ln in lines if ln.strip().startswith("|") and ln.strip().endswith("|")]
    if len(table_rows) < 3:
        missing.append("缺少输入输出样例对照 Markdown 表格（至少表头+分隔线+样例行）")

    bullet_lines = [ln for ln in lines if ln.lstrip().startswith(("- ", "* "))]
    if len(bullet_lines) < 5:
        missing.append("边界情况与错误处理等列表条目不足 5 条")

    if not ("给定" in spec_md and "当" in spec_md and "那么" in spec_md):
        missing.append("缺少‘给定……当……那么……’格式的可测试验收标准")

    if "须串行" not in spec_md and "可并行" not in spec_md:
        missing.append("任务拆分未标注‘须串行’或‘可并行’耦合属性")

    if "待确认问题" not in spec_md or spec_md.count("？") + spec_md.count("?") < 3:
        missing.append("‘待确认问题’不足 3 条具体疑问")

    return {"valid": len(missing) == 0, "missing": missing}


def normalize_account_slug(raw: str) -> str:
    """保持同模块既有稳定函数契约不变（无越界改动）。"""
    return "-".join(raw.strip().lower().split())


def quote_team_subscription(order: dict[str, Any]) -> dict[str, Any]:
    """按澄清锁死的 spec.md 实现分段超额累进报价与优惠码抵扣。"""
    if not isinstance(order, dict):
        raise ValueError("INVALID_ORDER_PAYLOAD")

    seats = order.get("seats")
    if isinstance(seats, bool) or not isinstance(seats, int) or seats < 1 or seats > 500:
        raise ValueError("INVALID_SEATS: seats must be an int between 1 and 500")

    currency = order.get("currency", "CNY")
    if currency != "CNY":
        raise ValueError(f"UNSUPPORTED_CURRENCY: {currency}")

    tier1_seats = min(seats, 10)
    tier2_seats = min(max(seats - 10, 0), 40)
    tier3_seats = max(seats - 50, 0)
    subtotal_cents = tier1_seats * 10000 + tier2_seats * 8000 + tier3_seats * 6000

    raw_coupon = order.get("coupon_code")
    if raw_coupon is None or (isinstance(raw_coupon, str) and raw_coupon.strip() == ""):
        coupon_value = 0
    elif isinstance(raw_coupon, str):
        code = raw_coupon.strip().upper()
        if code not in VALID_COUPONS:
            raise ValueError(f"INVALID_COUPON: {code}")
        coupon_value = VALID_COUPONS[code]
    else:
        raise ValueError("INVALID_COUPON_TYPE")

    discount_cents = min(subtotal_cents, coupon_value)
    payable_cents = subtotal_cents - discount_cents

    return {
        "seats": seats,
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "payable_cents": payable_cents,
        "currency": "CNY",
    }


def _expect_value_error(fn: Callable[[], Any], label: str) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"期望抛出 ValueError 但未触发：{label}")


def run_tdd_suite(quote_fn: Callable[[dict[str, Any]], dict[str, Any]]) -> list[str]:
    """按 spec.md 任务拆分执行的 4 个小步 TDD 验证套件。"""
    completed_steps: list[str] = []

    # Step 1：分段超额累进席位小计验证
    r1 = quote_fn({"seats": 1, "currency": "CNY"})
    assert r1["subtotal_cents"] == 10000 and r1["payable_cents"] == 10000
    r12 = quote_fn({"seats": 12, "currency": "CNY"})
    assert r12["subtotal_cents"] == 116000 and r12["payable_cents"] == 116000
    r55 = quote_fn({"seats": 55, "currency": "CNY"})
    assert r55["subtotal_cents"] == 450000 and r55["payable_cents"] == 450000
    completed_steps.append("step1_progressive_tiers")

    # Step 2：优惠码归一化、未知码报错与大额券零元封底
    rc_norm = quote_fn({"seats": 5, "currency": "CNY", "coupon_code": " launch30 "})
    assert rc_norm["discount_cents"] == 3000 and rc_norm["payable_cents"] == 47000
    rc_floor = quote_fn({"seats": 1, "currency": "CNY", "coupon_code": "MEGA150"})
    assert rc_floor["discount_cents"] == 10000 and rc_floor["payable_cents"] == 0
    _expect_value_error(
        lambda: quote_fn({"seats": 8, "currency": "CNY", "coupon_code": "UNKNOWN99"}),
        "未知优惠码应抛 ValueError",
    )
    completed_steps.append("step2_coupon_and_zero_floor")

    # Step 3：席位边界与 Python bool 陷阱拦截
    _expect_value_error(lambda: quote_fn({"seats": 0, "currency": "CNY"}), "0 席应抛 ValueError")
    _expect_value_error(lambda: quote_fn({"seats": 501, "currency": "CNY"}), "501 席应抛 ValueError")
    _expect_value_error(lambda: quote_fn({"seats": True, "currency": "CNY"}), "bool True 应抛 ValueError")
    completed_steps.append("step3_seat_boundary_guards")

    # Step 4：Non-Goals 非目标币种拦截与返回字段纯净度校验
    _expect_value_error(lambda: quote_fn({"seats": 8, "currency": "USD"}), "非目标币种 USD 应抛 ValueError")
    assert set(r12.keys()) == ALLOWED_OUTPUT_KEYS, f"存在规格外多余字段：{set(r12.keys()) - ALLOWED_OUTPUT_KEYS}"
    completed_steps.append("step4_non_goals_and_schema_purity")

    return completed_steps
