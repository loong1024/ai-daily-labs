"""S0-M11 实验起点（Starter）：多渠道海量用户差评吐槽（VoC）逐条低温打标与批次质量暴雷预警。

请按 README.md 指引修复以下 4 处典型工程缺陷，并运行 `python3 verify.py` 验证进度：
1. 将打标采样温度 `DEFAULT_TAG_TEMPERATURE` 从发散的 0.9 调至稳态 0.0，并在 `build_tagging_messages` 中锁死允许的枚举值与缺省 `"UNKNOWN"` 拒猜规则；
2. 将 `tag_reviews_batch` 从“整包塞进一次对话总结”重构为“逐条独立低温抽取结构化 JSON”；
3. 在 `detect_batch_quality_spikes` 中用纯 Python 确定性统计 W1 -> W2 环比飙升的（机型, 故障部件）组合及高频暴雷批次；
4. 在 `render_alert_report` 中输出清晰的 Markdown 批次质量预警简报。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

ALLOWED_MODELS = ("AeroBuds Pro", "AeroBuds Lite", "AeroWatch S")
ALLOWED_DEFECTS = (
    "bluetooth_disconnect",
    "battery_drain",
    "ear_tip_fit",
    "case_hinge",
    "app_sync",
    "shipping_box",
    "mic_muffled",
)

# TODO 1a：当前采样温度过高（0.9），会导致批量打标用词漂移；请改为 0.0
DEFAULT_TAG_TEMPERATURE = 0.9


@dataclass(frozen=True)
class SpikeAlert:
  product_model: str
  defect_part: str
  prev_count: int
  curr_count: int
  growth_ratio: float
  suspect_batch: str
  batch_hit_count: int


def load_voc_reviews(jsonl_path: pathlib.Path | None = None) -> list[dict[str, Any]]:
  path = jsonl_path or (LAB_DIR / "fixtures" / "voc_reviews_30.jsonl")
  rows: list[dict[str, Any]] = []
  for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line:
      rows.append(json.loads(line))
  return rows


def _make_voc_mock(temperature: float):
  """离线确定性回放器：真实还原整包塞入近因偏差、高温标签漂移与缺省乱猜批次三大翻车现象。"""
  def _mock(messages: list[dict[str, str]]) -> str:
    sys_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    usr_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")

    # 反模式 1：一次性塞入多条评论总结 -> 触发末尾近因偏差（只盯最后几条快递盒与耳塞吐槽）
    if usr_text.count("VOC-") > 1 or "全部评论列表" in usr_text:
      return "大家主要抱怨 AeroBuds Lite 快递外包装盒有压痕折痕，以及硅胶耳塞偏硬不够舒服，整体产品质量稳定。"

    # 识别机型
    if "AeroBuds Pro" in usr_text:
      model = "AeroBuds Pro"
    elif "AeroBuds Lite" in usr_text:
      model = "AeroBuds Lite"
    elif "AeroWatch S" in usr_text:
      model = "AeroWatch S"
    else:
      model = "UNKNOWN"

    # 识别故障部件（支持中英双语特征）
    low = usr_text.lower()
    if any(k in low for k in ("蓝牙", "断连", "断音", "bluetooth", "disconnect", "drops out", "dropping")):
      defect = "bluetooth_disconnect"
    elif any(k in low for k in ("续航", "掉电", "耗电", "没电", "battery", "drains")):
      defect = "battery_drain"
    elif any(k in low for k in ("耳塞", "胀痛", "滑出", "ear tip", "silicone tips")):
      defect = "ear_tip_fit"
    elif any(k in low for k in ("转轴", "盖子", "hinge", "creaks")):
      defect = "case_hinge"
    elif any(k in low for k in ("同步", "app", "sync")):
      defect = "app_sync"
    elif any(k in low for k in ("麦克风", "收音", "风噪", "microphone", "muffled")):
      defect = "mic_muffled"
    elif any(k in low for k in ("外包装", "快递", "纸箱", "压瘪", "外盒", "shipping box", "outer packaging")):
      defect = "shipping_box"
    else:
      defect = "other"

    # 反模式 2：高温采样或未给枚举约束 -> 标签自由发散漂移，下游 Python 无法稳定 group-by
    has_enum_lock = all(tok in sys_text for tok in ("bluetooth_disconnect", "battery_drain", "AeroBuds Pro"))
    if temperature > 0.2 or not has_enum_lock:
      drift_map = {
          "bluetooth_disconnect": "蓝牙老断连问题",
          "battery_drain": "电池不太耐用",
          "ear_tip_fit": "耳帽戴着疼",
          "shipping_box": "包装压了",
      }
      defect = drift_map.get(defect, defect)

    # 提取批次号（如 B108 / B109 / B110 / B111）
    batch_match = re.search(r"\b(B\d{3})\b", usr_text)
    if batch_match:
      batch_code = batch_match.group(1)
    else:
      # 反模式 3：未明确要求缺省标 UNKNOWN -> 模型顺口脑补假批次号 B999
      batch_code = "UNKNOWN" if "UNKNOWN" in sys_text else "B999"

    return json.dumps(
        {
            "product_model": model,
            "defect_part": defect,
            "batch_code": batch_code,
        },
        ensure_ascii=False,
    )

  return _mock



def build_tagging_messages(review: dict[str, Any]) -> list[dict[str, str]]:
  """构造单条差评的结构化打标消息列表。"""
  # TODO 1b：当前提示词既未锁死 ALLOWED_MODELS / ALLOWED_DEFECTS 枚举值，也未规定无批次号必须填 "UNKNOWN"
  return [
      {"role": "system", "content": "请帮我看看这条评论在抱怨什么，返回 JSON。"},
      {"role": "user", "content": f"[{review['review_id']}] {review['raw_text']}"},
  ]


def tag_single_review(review: dict[str, Any], *, temperature: float | None = None) -> dict[str, Any]:
  """对单条评论执行低温 JSON 结构化打标。"""
  temp = DEFAULT_TAG_TEMPERATURE if temperature is None else temperature
  msgs = build_tagging_messages(review)
  raw_resp = chat_complete(msgs, mock_fn=_make_voc_mock(temp), temperature=temp, response_json=True)
  parsed = json.loads(raw_resp)
  return {
      "review_id": review["review_id"],
      "week": review["week"],
      "channel": review["channel"],
      "lang": review["lang"],
      "product_model": str(parsed.get("product_model", "UNKNOWN")),
      "defect_part": str(parsed.get("defect_part", "other")),
      "batch_code": str(parsed.get("batch_code", "UNKNOWN")),
  }


def tag_reviews_batch(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """批量处理全部多语种差评。"""
  # TODO 2：当前基线犯了典型大忌——把 30 条中英差评整包塞进同一次提问问“大家抱怨啥”，
  # 既触发末尾近因偏差漏掉中段新批次断连簇，又无法产出逐条对齐的结构化记录！请改为逐条调用 tag_single_review。
  joined = "\n".join(f"{r['review_id']}: {r['raw_text']}" for r in reviews)
  naive_msgs = [
      {"role": "system", "content": "你是客服主管，请总结大家都在抱怨啥。"},
      {"role": "user", "content": f"全部评论列表：\n{joined}"},
  ]
  _ = chat_complete(naive_msgs, mock_fn=_make_voc_mock(DEFAULT_TAG_TEMPERATURE), temperature=DEFAULT_TAG_TEMPERATURE)
  return []


def detect_batch_quality_spikes(
    tagged_rows: list[dict[str, Any]],
    *,
    prev_week: str = "W1",
    curr_week: str = "W2",
    min_curr_count: int = 5,
    min_growth_ratio: float = 2.0,
) -> list[SpikeAlert]:
  """用纯 Python 确定性统计环比暴涨的（机型, 故障部件）异常簇，并定位高频疑似暴雷批次。"""
  # TODO 3：请按 (product_model, defect_part) 统计 prev_week 与 curr_week 数量，
  # 计算 growth_ratio = (curr_count - prev_count) / max(1, prev_count)，
  # 筛选 curr_count >= min_curr_count 且 growth_ratio >= min_growth_ratio 的异常项，
  # 并找出 curr_week 该异常簇中出现最多的非 "UNKNOWN" 批次号作为 suspect_batch。
  _ = (tagged_rows, prev_week, curr_week, min_curr_count, min_growth_ratio)
  return []


def render_alert_report(spikes: list[SpikeAlert]) -> str:
  """将检测到的批次异常簇渲染为可读性强的 Markdown 质量预警简报。"""
  # TODO 4：输出包含表头（机型、故障部件、W1 基线、W2 本周、环比增幅、疑似暴雷批次）及拦截建议的 Markdown 简报
  if not spikes:
    return "暂无批次质量预警。"
  return ""
