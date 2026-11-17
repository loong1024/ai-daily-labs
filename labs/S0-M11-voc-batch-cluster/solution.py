"""S0-M11 标准参考实现（Solution）：多渠道海量用户差评（VoC）逐条低温打标与批次质量暴雷预警。"""

from __future__ import annotations

from collections import Counter
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

# 严谨批量打标：采样温度固定为 0.0，最大化跨中英评论的枚举一致性
DEFAULT_TAG_TEMPERATURE = 0.0


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
  """构造锁定枚举集合与缺省拒猜规则的单条打标消息。"""
  system_prompt = (
      "你是消费硬件质量团队的结构化打标器。请严格依据单条用户评论提取 JSON 对象，仅包含以下三个字段：\n"
      f"1. product_model：必须严格从 {list(ALLOWED_MODELS)} 中二选一/三选一，无法判断填 UNKNOWN；\n"
      f"2. defect_part：必须严格从 {list(ALLOWED_DEFECTS)} 中挑选唯一主故障标签；\n"
      "3. batch_code：仅提取评论原文明确出现的批次号（如 B109、B111）；原文未明确提及时必须填 \"UNKNOWN\"，严禁猜测脑补！"
  )
  user_prompt = (
      f"评论编号：{review['review_id']}\n"
      f"渠道：{review['channel']}（语种：{review['lang']}）\n"
      f"评论原文：{review['raw_text']}"
  )
  return [
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": user_prompt},
  ]


def tag_single_review(review: dict[str, Any], *, temperature: float | None = None) -> dict[str, Any]:
  """对单条评论执行 temperature=0 独立无状态抽取并校验枚举合法性。"""
  temp = DEFAULT_TAG_TEMPERATURE if temperature is None else temperature
  msgs = build_tagging_messages(review)
  raw_resp = chat_complete(msgs, mock_fn=_make_voc_mock(temp), temperature=temp, response_json=True)
  parsed = json.loads(raw_resp)

  model = str(parsed.get("product_model", "UNKNOWN")).strip()
  if model not in ALLOWED_MODELS:
    model = "UNKNOWN"

  defect = str(parsed.get("defect_part", "other")).strip()
  if defect not in ALLOWED_DEFECTS:
    defect = "other"

  batch_code = str(parsed.get("batch_code", "UNKNOWN")).strip() or "UNKNOWN"
  return {
      "review_id": review["review_id"],
      "week": review["week"],
      "channel": review["channel"],
      "lang": review["lang"],
      "product_model": model,
      "defect_part": defect,
      "batch_code": batch_code,
  }


def tag_reviews_batch(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """逐条独立调用低温打标，消除超长上下文近因偏差并保障中英标签对齐。"""
  return [tag_single_review(r, temperature=DEFAULT_TAG_TEMPERATURE) for r in reviews]


def detect_batch_quality_spikes(
    tagged_rows: list[dict[str, Any]],
    *,
    prev_week: str = "W1",
    curr_week: str = "W2",
    min_curr_count: int = 5,
    min_growth_ratio: float = 2.0,
) -> list[SpikeAlert]:
  """使用确定性 Python 聚合计算周环比飙升故障，杜绝让大模型心算占比。"""
  prev_counter: Counter[tuple[str, str]] = Counter()
  curr_counter: Counter[tuple[str, str]] = Counter()
  curr_batches: dict[tuple[str, str], Counter[str]] = {}

  for row in tagged_rows:
    key = (row.get("product_model", "UNKNOWN"), row.get("defect_part", "other"))
    if key[0] == "UNKNOWN" or key[1] == "other":
      continue
    wk = row.get("week")
    if wk == prev_week:
      prev_counter[key] += 1
    elif wk == curr_week:
      curr_counter[key] += 1
      bcode = str(row.get("batch_code", "UNKNOWN"))
      if bcode != "UNKNOWN":
        curr_batches.setdefault(key, Counter())[bcode] += 1

  alerts: list[SpikeAlert] = []
  for key, curr_c in curr_counter.items():
    prev_c = prev_counter.get(key, 0)
    growth = (curr_c - prev_c) / max(1, prev_c)
    if curr_c >= min_curr_count and growth >= min_growth_ratio:
      batch_counts = curr_batches.get(key, Counter())
      if batch_counts:
        suspect_batch, hit_count = batch_counts.most_common(1)[0]
      else:
        suspect_batch, hit_count = "UNKNOWN", 0
      alerts.append(
          SpikeAlert(
              product_model=key[0],
              defect_part=key[1],
              prev_count=prev_c,
              curr_count=curr_c,
              growth_ratio=round(growth, 2),
              suspect_batch=suspect_batch,
              batch_hit_count=hit_count,
          )
      )

  alerts.sort(key=lambda a: (a.curr_count, a.growth_ratio), reverse=True)
  return alerts


def render_alert_report(spikes: list[SpikeAlert]) -> str:
  """渲染面向硬件质量与供应链团队的批次暴雷预警 Markdown 简报。"""
  if not spikes:
    return "暂无批次质量预警。"

  lines = [
      "# 多渠道用户之声（VoC）批次质量暴雷预警简报",
      "",
      "| 机型 | 故障部件 | W1 基线 | W2 本周 | 环比增幅 | 疑似暴雷批次 |",
      "| :--- | :--- | :---: | :---: | :---: | :--- |",
  ]
  for s in spikes:
    pct = int(round(s.growth_ratio * 100))
    lines.append(
        f"| {s.product_model} | {s.defect_part} | {s.prev_count} | {s.curr_count} "
        f"| +{pct}% ({s.prev_count} -> {s.curr_count}) | {s.suspect_batch} ({s.batch_hit_count}例指认) |"
    )
  top = spikes[0]
  lines.extend([
      "",
      f"**紧急处置建议**：立即冻结仓库及渠道在途的 `{top.product_model}` 批次 `{top.suspect_batch}` 出货，"
      f"抽检该批次固件蓝牙射频稳定性并准备定向换货通道。",
  ])
  return "\n".join(lines) + "\n"


if __name__ == "__main__":
  all_reviews = load_voc_reviews()
  tagged = tag_reviews_batch(all_reviews)
  found_spikes = detect_batch_quality_spikes(tagged)
  print(render_alert_report(found_spikes))
