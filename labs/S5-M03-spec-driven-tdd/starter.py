"""S5-M03 Starter：Spec 先行与小步 TDD 演练骨架（含“AI 一把梭”典型缺陷供重构对比）。"""

from __future__ import annotations

from typing import Any, Callable

VALID_COUPONS: dict[str, int] = {
    "LAUNCH30": 3000,
    "TEAM100": 10000,
    "MEGA150": 15000,
}


def draft_spec_markdown(req_context: dict[str, Any]) -> str:
    """根据模糊需求生成待确认的 spec.md（只出规格，不写业务实现代码）。

    要求包含完整 7 节：
    1. 目标
    2. 非目标（Non-Goals）
    3. 接口与数据结构（含输入输出样例 Markdown 表格 `| ... |`）
    4. 边界情况与错误处理（至少 5 条列表项）
    5. 验收标准（使用“给定……当……那么……”格式）
    6. 任务拆分（每个小步注明验证方式，并显式标记“须串行”或“可并行”）
    7. 待确认问题（至少 3 条含候选方案的问题，不自行假设）
    """
    # TODO 1：当前仅返回了一句敷衍草稿，请升级为结构化 7 节 spec.md（可调用 chat_complete 并配确定性 mock_fn）
    return f"# 规格草稿\n需求：{req_context.get('vague_prompt', '')}\n直接开始写代码即可。"


def audit_spec_markdown(spec_md: str) -> dict[str, Any]:
    """量化审查一份 spec.md 是否满足动工前门禁。

    返回格式：{"valid": bool, "missing": list[str]}
    """
    # TODO 2：当前基线未做任何检查直接放行，连残缺的 bad_spec_stub.md 也会误判通过！
    del spec_md
    return {"valid": True, "missing": []}


def normalize_account_slug(raw: str) -> str:
    """同模块既有稳定函数（上游账单导出依赖，规格明确要求保持原样严禁乱改！）。

    原有契约：去首尾空格 -> 转小写 -> 连续空白替换为单个连字符 `-`。
    例如："  Acme   Cloud  " -> "acme-cloud"
    """
    cleaned = "-".join(raw.strip().lower().split())
    # ❌ AI 一把梭时顺手画蛇添足加了 "-v2" 后缀！请按规格 Diff 复核要求还原此处越界修改
    return f"{cleaned}-v2"


def quote_team_subscription(order: dict[str, Any]) -> dict[str, Any]:
    """企业团队席位阶梯报价器。

    澄清锁死规格（详见 fixtures/vague_requirement.json 与 clarified_io_cases.json）：
    - seats：严格整数 1..500（注意排除 bool），否则抛 ValueError
    - currency：仅支持 "CNY"（默认 "CNY"），其他币种属于非目标范围，必须抛 ValueError
    - 阶梯单价（分段超额累进，单位：分）：
      * 第 1..10 席：10000 分/席
      * 第 11..50 席：8000 分/席
      * 第 51..500 席：6000 分/席
    - coupon_code：None 或空串时折扣为 0；非空时 strip().upper() 查 VALID_COUPONS，未知码抛 ValueError；
      实际抵扣 discount_cents = min(subtotal_cents, coupon_value)，应付 payable_cents = subtotal_cents - discount_cents（封底 0 分）
    - 返回字典字段严格限定为：
      {"seats", "subtotal_cents", "discount_cents", "payable_cents", "currency"}
    """
    # ❌ 下面是“未写 Spec 直接让 AI 一把梭”写出的典型问题代码（请通过小步 TDD 逐步修正）：
    seats = int(order.get("seats", 1))
    currency = order.get("currency", "CNY")

    # 缺陷 A：把分段超额累进写成了全量跳档打折，还用了 float
    if seats > 50:
        unit = 60.0
    elif seats > 10:
        unit = 80.0
    else:
        unit = 100.0
    subtotal_cents = int(seats * unit * 100)

    # 缺陷 B：未知优惠码被静默当成 0，且未做大额券零元封底保护
    code = str(order.get("coupon_code") or "")
    discount_cents = VALID_COUPONS.get(code, 0)
    payable_cents = subtotal_cents - discount_cents

    # 缺陷 C：擅自脑补 USD 汇率与规格外字段（tax_cents / vip_points）
    if currency == "USD":
        payable_cents = int(payable_cents / 7.2)

    return {
        "seats": seats,
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "payable_cents": payable_cents,
        "currency": currency,
        "tax_cents": int(payable_cents * 0.06),
        "vip_points": seats * 10,
    }


def run_tdd_suite(quote_fn: Callable[[dict[str, Any]], dict[str, Any]]) -> list[str]:
    """按 spec.md 任务拆分编写的小步 TDD 自动化断言集。

    要求：
    - 至少拆分为 3 个小步验证（阶梯累进、优惠码校验与封底、异常入参与非目标越界门禁）；
    - 当传入存在缺陷的 quote_fn 时必须抛出 AssertionError（证明测试真能抓虫）；
    - 全部通过时返回已完成的小步名称列表（长度 >= 3）。
    """
    # TODO 3：当前仅有 1 条正常路径弱断言，无法拦截阶梯算错、无效券漏放与越界字段！
    res = quote_fn({"seats": 1, "currency": "CNY"})
    assert res["payable_cents"] == 10000
    return ["step1_basic_only"]
