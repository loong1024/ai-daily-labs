# CSV 与 Excel 批量合并清洗沙盒（Starter 待改进初稿）

## 一、造物与清洗提示词（反面裸提问基线）

> TODO：以下提问直接让大模型心算表格，缺少脱敏本地工具要求、同义表头映射、来源文件名溯源、UTF-8 BOM 防乱码导出，以及“行数守恒对账面板 + 异常待复核清单”约束，请按 README 指引重构为三轮渐进式指令模板。

“我下面把几十张门店和直播间的原始 CSV 明细直接贴进对话框里，请你帮我直接心算合并成一张总表，去掉看着重复的数据，直接告诉我总金额是多少。”

---

## 二、基于 `fixtures/` 三份脏样本的对账核验单（JSON）

> TODO：以下对账数据是未经严格规则核对的拍脑袋结果（漏排了跨表重复单号与非数字/缺单号异常行），请按 `store_east.csv` → `channel_live.csv` → `partner_south.csv` 顺序核算并修正。

```json
{
  "file_count": 3,
  "raw_rows": 15,
  "empty_rows": 1,
  "anomaly_rows": 0,
  "duplicate_rows": 1,
  "valid_rows": 13,
  "conservation_check": "未做守恒核对",
  "expected_amount_sum": 950.0,
  "valid_order_ids": [
    "ORD-202604-001",
    "ORD-202604-002"
  ],
  "anomalies": []
}
```
