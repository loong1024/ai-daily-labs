#!/usr/bin/env python3
"""S0-M11 自动化量化验收脚本（支持默认测 starter.py 红灯提示与 --solution 绿灯验收）。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_target_module() -> ModuleType:
  path = target_file(LAB_DIR, "starter.py", "solution.py")
  mod_name = f"s0_m11_{path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块：{path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> int:
  v = LabVerifier(
      "S0-M11",
      "多渠道海量用户差评吐槽（VoC）归因：逐条低温打标与批次质量暴雷预警",
  )

  try:
    mod = _load_target_module()
    reviews = mod.load_voc_reviews()
  except Exception as exc:
    v.check("加载 VoC 批处理模块与 30 条多渠道差评样本", False, f"模块加载或读取 fixtures 失败：{exc}")
    return v.finish()

  # 验收项 1：低温采样参数（temperature == 0.0）与缺省批次防脑补规则（UNKNOWN）
  try:
    temp_val = getattr(mod, "DEFAULT_TAG_TEMPERATURE", None)
    sample_with_batch = next(r for r in reviews if r["review_id"] == "VOC-16")
    sample_no_batch = next(r for r in reviews if r["review_id"] == "VOC-22")
    res_with = mod.tag_single_review(sample_with_batch)
    res_no = mod.tag_single_review(sample_no_batch)
    schema_ok = (
        temp_val == 0.0
        and res_with.get("product_model") == "AeroBuds Pro"
        and res_with.get("defect_part") == "bluetooth_disconnect"
        and res_with.get("batch_code") == "B111"
        and res_no.get("product_model") == "AeroBuds Pro"
        and res_no.get("defect_part") == "bluetooth_disconnect"
        and res_no.get("batch_code") == "UNKNOWN"
    )
    v.check(
        "低温稳态采样（DEFAULT_TAG_TEMPERATURE=0.0）与缺省批次强标 UNKNOWN 拒脑补",
        bool(schema_ok),
        "请将 DEFAULT_TAG_TEMPERATURE 设为 0.0，并在 build_tagging_messages 的 system 提示词中明确列出标准故障枚举值与“未提批次号必须填 UNKNOWN”。",
    )
  except Exception as exc:
    v.check(
        "低温稳态采样（DEFAULT_TAG_TEMPERATURE=0.0）与缺省批次强标 UNKNOWN 拒脑补",
        False,
        f"单条打标校验异常（{exc}），请检查 build_tagging_messages 与 tag_single_review 返回结构。",
    )

  # 验收项 2：30 条多语种多渠道差评逐条独立打标闭环（中英文统一映射同一标准故障枚举）
  tagged_rows = []
  try:
    tagged_rows = mod.tag_reviews_batch(reviews)
    by_id = {r.get("review_id"): r for r in tagged_rows if isinstance(r, dict)}
    batch_ok = (
        len(tagged_rows) == 30
        and len(by_id) == 30
        and by_id.get("VOC-17", {}).get("defect_part") == "bluetooth_disconnect"
        and by_id.get("VOC-17", {}).get("batch_code") == "B111"
        and by_id.get("VOC-19", {}).get("defect_part") == "bluetooth_disconnect"
        and by_id.get("VOC-30", {}).get("defect_part") == "shipping_box"
    )
    v.check(
        "30 条中英多渠道差评逐条独立打标闭环（避开整包投喂末尾近因偏差）",
        bool(batch_ok),
        "请重构 tag_reviews_batch：改为逐条循环调用 tag_single_review，确保 Amazon/Reddit 英文差评与国内渠道中文差评统一映射至同一标准枚举。",
    )
  except Exception as exc:
    v.check(
        "30 条中英多渠道差评逐条独立打标闭环（避开整包投喂末尾近因偏差）",
        False,
        f"批量打标执行出错（{exc}），请检查 tag_reviews_batch 返回列表结构。",
    )

  # 验收项 3：纯 Python 确定性双周环比聚合精准锁定 B111 蓝牙断连暴雷簇
  spikes = []
  try:
    spikes = mod.detect_batch_quality_spikes(tagged_rows) if tagged_rows else []
    spike_ok = (
        len(spikes) == 1
        and spikes[0].product_model == "AeroBuds Pro"
        and spikes[0].defect_part == "bluetooth_disconnect"
        and spikes[0].prev_count == 1
        and spikes[0].curr_count == 8
        and abs(spikes[0].growth_ratio - 7.0) < 1e-6
        and spikes[0].suspect_batch == "B111"
        and spikes[0].batch_hit_count == 7
    )
    v.check(
        "Python 确定性环比聚合揪出新批次暴雷（AeroBuds Pro 蓝牙断连 W1=1 -> W2=8，锁定 B111）",
        bool(spike_ok),
        "请完善 detect_batch_quality_spikes：统计 W1 与 W2 各 (product_model, defect_part) 频次，核验 AeroBuds Pro 蓝牙断连从 1 飙升至 8（+700%）且 B111 命中 7 例。",
    )
  except Exception as exc:
    v.check(
        "Python 确定性环比聚合揪出新批次暴雷（AeroBuds Pro 蓝牙断连 W1=1 -> W2=8，锁定 B111）",
        False,
        f"批次暴雷环比统计出错（{exc}），请检查 SpikeAlert 字段与计数逻辑。",
    )

  # 验收项 4：渲染可直接发给硬件质量团队的 Markdown 暴雷预警简报
  try:
    report_md = mod.render_alert_report(spikes)
    report_ok = (
        isinstance(report_md, str)
        and all(tok in report_md for tok in ("AeroBuds Pro", "bluetooth_disconnect", "B111", "700%"))
        and "|" in report_md
    )
    v.check(
        "输出含问题机型、故障部件、环比增幅（+700%）与疑似批次 B111 的 Markdown 预警简报",
        bool(report_ok),
        "请完善 render_alert_report：生成包含 AeroBuds Pro、bluetooth_disconnect、+700% 及批次 B111 冻结建议的 Markdown 表格简报。",
    )
  except Exception as exc:
    v.check(
        "输出含问题机型、故障部件、环比增幅（+700%）与疑似批次 B111 的 Markdown 预警简报",
        False,
        f"渲染预警简报出错（{exc}），请检查 render_alert_report 实现。",
    )

  return v.finish()


if __name__ == "__main__":
  main()
