#!/usr/bin/env python3
"""S5-M10 CSV 与 Excel 合并清洗小工具沙盒 自动化验收脚本。"""

from __future__ import annotations

import csv
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

from shared.aid_lab import LabVerifier, target_file

ORDERED_FIXTURES = ("store_east.csv", "channel_live.csv", "partner_south.csv")

HEADER_SYNONYMS = {
    "日期": "日期",
    "来源渠道": "渠道名称",
    "渠道": "渠道名称",
    "渠道名称": "渠道名称",
    "订单编号": "订单编号",
    "单号": "订单编号",
    "订单号": "订单编号",
    "假设金额": "假设金额",
    "实付金额": "假设金额",
    "金额": "假设金额",
    "备注": "备注",
}


def compute_fixture_ground_truth(fixtures_dir: pathlib.Path) -> dict[str, Any]:
  """对 fixtures 下的三份脏样本执行确定性清洗与行数守恒对账。"""
  raw_rows = 0
  empty_rows = 0
  duplicate_rows = 0
  seen_orders: set[str] = set()
  valid_records: list[dict[str, Any]] = []
  anomalies: list[dict[str, str]] = []

  for fname in ORDERED_FIXTURES:
    fpath = fixtures_dir / fname
    with fpath.open("r", encoding="utf-8", newline="") as fp:
      reader = list(csv.reader(fp))
    headers = [HEADER_SYNONYMS.get(col.strip(), col.strip()) for col in reader[0]]

    for row in reader[1:]:
      raw_rows += 1
      cleaned = [cell.strip() for cell in row]
      if all(cell == "" for cell in cleaned):
        empty_rows += 1
        continue

      record = {headers[i]: (cleaned[i] if i < len(cleaned) else "") for i in range(len(headers))}
      order_id = record.get("订单编号", "")
      raw_amount = record.get("假设金额", "")

      if not order_id:
        anomalies.append({"source_file": fname, "order_id": "", "raw_amount": raw_amount})
        continue

      try:
        amount_val = float(raw_amount)
        if not math.isfinite(amount_val):
          raise ValueError("non-finite")
      except ValueError:
        anomalies.append({"source_file": fname, "order_id": order_id, "raw_amount": raw_amount})
        continue

      if order_id in seen_orders:
        duplicate_rows += 1
        continue

      seen_orders.add(order_id)
      valid_records.append(
          {
              "source_file": fname,
              "order_id": order_id,
              "amount": amount_val,
          }
      )

  return {
      "file_count": len(ORDERED_FIXTURES),
      "raw_rows": raw_rows,
      "empty_rows": empty_rows,
      "anomaly_rows": len(anomalies),
      "duplicate_rows": duplicate_rows,
      "valid_rows": len(valid_records),
      "expected_amount_sum": round(sum(item["amount"] for item in valid_records), 2),
      "valid_order_ids": [item["order_id"] for item in valid_records],
      "anomaly_sources": [item["source_file"] for item in anomalies],
  }


def extract_json_block(markdown_text: str) -> dict[str, Any] | None:
  match = re.search(r"```json\s*(\{.*?\})\s*```", markdown_text, flags=re.DOTALL)
  if not match:
    return None
  return json.loads(match.group(1))


def main() -> None:
  v = LabVerifier("S5-M10", "告别手工贴表：定制 CSV 与 Excel 合并清洗小工具")
  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")

  try:
    gt = compute_fixture_ground_truth(LAB_DIR / "fixtures")
    doc_text = doc_path.read_text(encoding="utf-8")
    audit_json = extract_json_block(doc_text)
  except Exception as exc:
    v.check("沙盒文档与对账 JSON 解析", False, f"读取文档或解析 JSON 块失败：{exc}")
    v.finish()
    return

  v.check(
      "沙盒文档结构与可机读对账 JSON 区块完备",
      isinstance(audit_json, dict) and len(doc_text.strip()) > 100,
      "请保留 Markdown 文档中的 ```json ... ``` 对账核验单区块并确保 JSON 语法合法。",
  )

  forbids_mental_math = (
      any(kw in doc_text for kw in ("不要直接心算", "不要心算", "拒绝心算", "切勿直接"))
      and "直接把几十张门店和直播间的原始 CSV 明细直接贴进对话框" not in doc_text
  )
  has_cleaning_rules = all(
      kw in doc_text
      for kw in ("来源渠道", "单号", "订单编号", "渠道名称", "来源文件名", "BOM")
  )

  v.check(
      "第一轮脱敏造工具指令：拒绝心算原表 + 同义表头映射 + 来源溯源 + BOM 导出",
      forbids_mental_math and has_cleaning_rules,
      "修改第一部分提示词：明确要求生成本地单文件批处理工具而非心算原始表，写明同义表头映射（来源渠道/单号等）、新增“来源文件名”列以及带 UTF-8 BOM 头导出 CSV。",
  )

  has_conservation_panel = all(
      kw in doc_text for kw in ("原始总行数", "空行", "去重", "最终有效行数")
  )
  has_anomaly_isolation = (
      ("异常待复核清单" in doc_text or "异常隔离" in doc_text)
      and ("缺失" in doc_text or "为空" in doc_text)
      and ("有效数字" in doc_text or "非数字" in doc_text)
  )

  v.check(
      "第二轮对账面板指令：行数守恒等式校验与异常记录单独隔离",
      has_conservation_panel and has_anomaly_isolation,
      "补充第二轮指令：要求展示原始总行数、过滤空行数、异常隔离行数、去重剔除行数与最终有效行数的守恒核对，并将缺单号或非数字金额单独列入《异常待复核清单》。",
  )

  audit = audit_json or {}
  anomalies_list = audit.get("anomalies") if isinstance(audit.get("anomalies"), list) else []
  numbers_match = (
      audit.get("file_count") == gt["file_count"]
      and audit.get("raw_rows") == gt["raw_rows"]
      and audit.get("empty_rows") == gt["empty_rows"]
      and audit.get("anomaly_rows") == gt["anomaly_rows"]
      and audit.get("duplicate_rows") == gt["duplicate_rows"]
      and audit.get("valid_rows") == gt["valid_rows"]
      and (
          gt["raw_rows"] - gt["empty_rows"] - gt["anomaly_rows"] - gt["duplicate_rows"]
          == gt["valid_rows"]
      )
      and abs(float(audit.get("expected_amount_sum", -1.0)) - gt["expected_amount_sum"]) < 1e-4
      and audit.get("valid_order_ids") == gt["valid_order_ids"]
      and len(anomalies_list) == gt["anomaly_rows"]
      and sorted(str(a.get("source_file", "")) for a in anomalies_list)
      == sorted(gt["anomaly_sources"])
  )

  v.check(
      "第三轮样本边界验收：fixtures 三份脏表对账数值、有效单号与异常清单 100% 吻合",
      numbers_match,
      f"请按 store_east.csv -> channel_live.csv -> partner_south.csv 重新核对 JSON 对账单（预期原始 {gt['raw_rows']} 行、空行 {gt['empty_rows']}、异常 {gt['anomaly_rows']}、去重 {gt['duplicate_rows']}、有效 {gt['valid_rows']} 行，正常假设金额合计 {gt['expected_amount_sum']:.2f}，并列出全部 {gt['anomaly_rows']} 条异常记录及来源文件名）。",
  )

  v.finish()


if __name__ == "__main__":
  main()
