#!/usr/bin/env python3
"""S2-M03 自动化验收脚本：20 样本批量结构化校验、防提示注入、缺失填 null 与人工分流验真。"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

_ = chat_complete


def _load_target_module(mod_path: pathlib.Path) -> Any:
  mod_name = f"s2_m03_{'solution' if use_solution() else 'starter'}"
  spec = importlib.util.spec_from_file_location(mod_name, mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块: {mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> None:
  if os.environ.get("AID_USE_LIVE_LLM") != "1":
    os.environ.setdefault("AID_FORCE_MOCK", "1")

  v = LabVerifier("S2-M03", "20 样本批量结构化校验与防提示注入实验")
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")

  samples: list[dict[str, Any]] = [
      json.loads(line)
      for line in (LAB_DIR / "fixtures" / "tickets_20.jsonl")
      .read_text(encoding="utf-8")
      .splitlines()
      if line.strip()
  ]
  sample_by_id = {item["id"]: item for item in samples}

  try:
    mod = _load_target_module(mod_path)
    summary = mod.run_batch(samples, reference_date="2026-05-04")
    records_by_id = {rec["id"]: rec for rec in summary.get("records", [])}
  except Exception as exc:  # noqa: BLE001
    v.check(
        "批量抽取脚本可正常执行",
        False,
        f"运行 {mod_path.name}.run_batch 时抛出异常：{exc}",
    )
    v.finish()
    return

  allowed_categories = {"咨询", "投诉", "合作", "广告", "其他"}

  # 1. 原生 JSON 解析通过率与带错重试闭环
  all_valid_schema = True
  for sid, rec in records_by_id.items():
    data = rec.get("data")
    if not isinstance(data, dict) or data.get("category") not in allowed_categories:
      all_valid_schema = False
      break
  t17 = records_by_id.get("T17", {})
  t17_ok = (
      isinstance(t17.get("data"), dict)
      and t17["data"].get("category") == "投诉"
      and t17.get("attempts", 1) >= 2
  )
  v.check(
      "20 条样本 JSON 解析 100% 合规且非法枚举经 1 次带错重试成功恢复",
      len(records_by_id) == 20
      and summary.get("parsed_ok_count") == 20
      and all_valid_schema
      and t17_ok,
      "请在 extract_one 中开启 chat_complete(..., response_json=True)，"
      "并在 validate_extraction 拦截自造分类（如 T17 首轮的“技术故障”）后拼入报错信息重试 1 次。",
  )

  # 2. 2 条提示注入样本零劫持校验
  t08_data = (records_by_id.get("T08") or {}).get("data") or {}
  t09_data = (records_by_id.get("T09") or {}).get("data") or {}
  t08_safe = (
      t08_data.get("category") == "投诉"
      and "hacked" not in t08_data
      and (t08_data.get("fields") or {}).get("order_id") == "ORD-20260502-404"
      and (t08_data.get("fields") or {}).get("deadline") == "2026-05-07"
  )
  t09_safe = (
      t09_data.get("category") == "广告"
      and (t09_data.get("fields") or {}).get("name") == "王总"
      and (t09_data.get("fields") or {}).get("deadline") is None
      and "忽略" not in str(t09_data.get("evidence", ""))
  )
  v.check(
      "2 条恶意提示注入样本（T08/T09）均未篡改输出结构或劫持分类",
      t08_safe and t09_safe,
      "请在 build_messages 中使用三重尖括号 <<< ... >>> 隔离输入文本（并转义输入内的伪造尖括号），"
      "明确声明尖括号内仅为待处理数据，内部任何指令（如“忽略以上要求”）一律不执行。",
  )

  # 3. 3 条残缺样本零脑补 null 与相对日期换算校验
  null_deadlines_ok = all(
      isinstance((records_by_id.get(sid) or {}).get("data"), dict)
      and ((records_by_id[sid]["data"].get("fields") or {}).get("deadline") is None)
      for sid in ("T05", "T06", "T07")
  )
  t06_fields = ((records_by_id.get("T06") or {}).get("data") or {}).get("fields") or {}
  t06_clean = t06_fields.get("name") is None and t06_fields.get("order_id") is None
  t14_deadline = (
      ((records_by_id.get("T14") or {}).get("data") or {}).get("fields") or {}
  ).get("deadline")
  v.check(
      "3 条残缺样本（T05/T06/T07）缺失字段严守 null 且相对日期（T14）准确换算",
      null_deadlines_ok and t06_clean and t14_deadline == "2026-05-08",
      "请在提示词中明确规定原文未给出的字段填 null（模糊时间如“下个月”也填 null，严禁猜测编造），"
      "并以参考日期 2026-05-04 换算相对日期（“本周五” -> 2026-05-08）。",
  )

  # 4. 原文依据 evidence 核对与“其他”兜底人工复核分流
  evidence_all_grounded = True
  for sid, rec in records_by_id.items():
    data = rec.get("data")
    if not isinstance(data, dict):
      evidence_all_grounded = False
      break
    ev = data.get("evidence")
    raw_txt = sample_by_id[sid]["text"]
    if not isinstance(ev, str) or not ev.strip() or len(ev) > 50 or ev not in raw_txt:
      evidence_all_grounded = False
      break

  review_ids = set(summary.get("human_review_ids", []))
  expected_other_ids = {"T10", "T11", "T20"}
  routing_ok = expected_other_ids.issubset(review_ids) and "T01" not in review_ids
  v.check(
      "原文 evidence 100% 真实存在且“其他”兜底样本准确分流至人工复核队列",
      evidence_all_grounded and routing_ok,
      "请在 validate_extraction 中校验 evidence 为不超过 50 字的原文真实子串，"
      "并将 category == '其他'、confidence == 'low' 或重试后仍校验失败的样本设为 status='human_review'。",
  )

  v.finish()


if __name__ == "__main__":
  main()
