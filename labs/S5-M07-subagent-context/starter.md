---
name: codebase-scout
description: 帮忙在代码库里搜索文件并顺手修复看到的问题。
allowed-tools: [Read, Grep, Glob, Write, Bash]
max-output-lines: 80
---

# Codebase Scout（只读摸底规范 · 待完善草稿）

1. **边界约定**：请尽量只看代码，除非顺手能改好否则别乱动文件。
2. **委派清单**：把代码库翻一遍，把觉得有用的函数贴回主窗口。

## 针对 `fixtures/mini_repo` 的侦察返回摘要

```scout-brief
[核心调用链]
我已经帮你把几个文件的代码都拷过来了：
1. api/orders_router.py:L88 (`post_order_refund`)
代码如下：
def post_order_refund(body: dict, service: RefundService) -> dict:
    req = parse_refund_payload(body)
    entry = service.submit_refund(req)
    return {"refund_id": entry.entry_id, "status": entry.status}

2. services/legacy_coupon_noise.py:L15 (`compute_legacy_order_coupon`)
这里也有 order_amount_cents：
def compute_legacy_order_coupon(order_amount_cents: int, tier_code: str) -> int:
    rule = LEGACY_CAMPAIGN_TIERS.get(tier_code)
    if not rule or order_amount_cents < rule["min_order_cents"]:
        return 0
    return rule["discount_cents"]

3. services/refund_service.py:L52 (`submit_refund`)
这里处理退款并调用账本：
existing = self._repo.find_by_idempotency_key(req.idempotency_key)
if existing is not None:
    return existing

4. models/ledger_entry.py:L30 (`auto_retry_webhook`)
我猜这里会自动把失败的银行网关回调放入异步重试队列。

[现有约定与测试参考]
单测文件大概在 tests 目录下，可以自己跑 pytest 试试。
还有一些多余的日志行：
scanning file 1...
scanning file 2...
scanning file 3...
scanning file 4...
scanning file 5...
scanning file 6...
scanning file 7...
```

## 对照实验记录表

| 实验分组 | 只读约束方式 | 主会话检索轮数 | 主会话注入 Token（上下文占比） | 坐标核验准确率 | 后续修改定位轮数 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 对照组（主会话直接盲搜） | TODO | TODO | TODO | TODO | TODO |
| 实验组（工具级只读子会话侦察） | TODO | TODO | TODO | TODO | TODO |
