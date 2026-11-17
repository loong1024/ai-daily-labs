"""历史故障快照（只读基准，请勿修改本文件）。

verify.py 会将你的回归测试函数传入本模块中的 calculate_prorated_refund，
验证你的回归测试是否做到了真正的“修复前必败（Red）”。
"""

from __future__ import annotations


def calculate_prorated_refund(
    paid_cents: int,
    total_days: int,
    used_days: int,
    promo_cents: int = 0,
) -> int:
    """历史带缺陷版本：按剩余天数折算会员退订金额（单位：分）。"""
    if total_days <= 0:
        raise ValueError("total_days must be positive")
    if used_days <= 0:
        return paid_cents
    if used_days >= total_days:
        return 0

    remaining_days = total_days - used_days
    # 历史缺陷：paid_cents 已经是扣除优惠券后的实付金额，此处又重复减去了 promo_cents！
    raw_refund = (paid_cents * remaining_days) // total_days - promo_cents
    return raw_refund
