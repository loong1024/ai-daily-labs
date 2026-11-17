#!/usr/bin/env python3
"""S0-M02 Starter：本地小模型采样稳定度、停止控制与窗口遗忘实测。

请根据 README.md 指引修复下方标记为 TODO 的 5 处逻辑，然后运行 verify.py 验收。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.request
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

FIXTURE_PATH = LAB_DIR / "fixtures" / "expense_memos.json"
STOP_SENTINEL = "</JSON>"

# ============================================================================
# 本地小模型 /api/chat 物理行为仿真底座（请勿删除，用于无 GPU/离线环境复现引擎机制）
# ============================================================================
_UNSEEDED_SEQ = 0
_CITIES = ("深圳", "杭州", "成都", "武汉", "上海", "南京", "苏州", "北京", "广州")


def _extract_ground_truth(visible_text: str) -> tuple[str | None, float | None, str | None]:
  date_val: str | None = None
  m_date = re.search(r"(20\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})日?", visible_text)
  if m_date:
    date_val = f"{int(m_date.group(1)):04d}-{int(m_date.group(2)):02d}-{int(m_date.group(3)):02d}"

  amount_val: float | None = None
  m_amt = re.search(r"(?:人民币|支出|实付|结算|共计|合计|金额[：:]?\s*|¥)\s*([0-9][0-9,]*(?:\.\d+)?)", visible_text)
  if m_amt:
    amount_val = round(float(m_amt.group(1).replace(",", "")), 2)

  city_val: str | None = None
  for city in _CITIES:
    if city in visible_text:
      city_val = city
      break
  return date_val, amount_val, city_val


def simulate_local_slm_chat(payload: dict[str, Any]) -> dict[str, Any]:
  """仿真本地 1.5B 小模型 /api/chat 的四大物理特性：
  1. 默认 num_ctx=2048，超长提示词保留尾部、静默截断卷首；
  2. temperature=0 贪婪稳定输出，temperature>0 时随温度升高格式漂移加剧，固定 seed 可复现；
  3. 遇到 options.stop 中的闭合标记立即停下，否则在末尾附带礼貌性废话；
  4. 达到 options.num_predict 上限时强制截断并返回 done_reason='length'。
  """
  global _UNSEEDED_SEQ
  if os.environ.get("AID_USE_LIVE_OLLAMA") == "1" and os.environ.get("OLLAMA_MODEL"):
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
      return json.loads(resp.read().decode("utf-8"))

  messages = payload.get("messages", [])
  options = payload.get("options") or {}
  full_prompt = "\n".join(str(m.get("content", "")) for m in messages)

  # 1) 上下文滑动窗口：本地轻量模型未显式指定 num_ctx 时默认 2048
  num_ctx = int(options.get("num_ctx", 2048))
  visible_prompt = full_prompt[-num_ctx:] if len(full_prompt) > num_ctx else full_prompt
  date_val, amount_val, city_val = _extract_ground_truth(visible_prompt)

  wants_sentinel = STOP_SENTINEL in full_prompt
  sentinel_str = STOP_SENTINEL if wants_sentinel else ""
  chatter = "\n备注：以上为自动抽取的差旅报销字段，如需换算税额请继续提问。"

  # 2) 温度与随机种子采样行为
  temp = float(options.get("temperature", 0.8))
  seed = options.get("seed", None)
  canonical = json.dumps(
      {"date": date_val, "amount": amount_val, "city": city_val},
      ensure_ascii=False,
  )

  if temp <= 0.0:
    raw_text = f"{canonical}{sentinel_str}{chatter}"
  else:
    amt_num = 0.0 if amount_val is None else amount_val
    variants = [
        canonical,
        json.dumps({"date": date_val, "amount": f"¥{amt_num:,.2f}", "city": city_val}, ensure_ascii=False),
        json.dumps({"date": (date_val or "").replace("-", "/"), "amount": f"{amt_num}元", "city": city_val}, ensure_ascii=False),
        json.dumps({"city": city_val, "date": date_val, "amount": round(amt_num)}, ensure_ascii=False),
        json.dumps({"date": date_val, "amount": f"RMB {amt_num:.2f}", "city": f"{city_val}市" if city_val else None}, ensure_ascii=False),
        json.dumps({"date": date_val, "amount": amt_num, "city": city_val, "currency": "CNY"}, ensure_ascii=False),
        json.dumps({"日期": date_val, "金额": f"{amt_num:.2f}元", "城市": city_val}, ensure_ascii=False),
        json.dumps({"date": date_val, "amount": f"约{int(round(amt_num))}元", "city": city_val}, ensure_ascii=False),
    ]
    if seed is not None:
      idx = (int(seed) * 7 + int(round(temp * 10))) % len(variants)
    else:
      call_no = _UNSEEDED_SEQ
      _UNSEEDED_SEQ += 1
      if temp < 1.0:
        cycle = (0, 1, 0, 2, 1)
        idx = cycle[call_no % len(cycle)]
      else:
        idx = (call_no + 3) % len(variants)
    raw_text = f"{variants[idx]}{sentinel_str}{chatter}"

  # 3) num_predict 输出长度硬上限（按约 1 token ≈ 2 字符折算）与 stop 序列截停
  num_predict = int(options.get("num_predict", 128))
  max_chars = max(1, num_predict * 2)
  stops = options.get("stop") or []

  earliest_stop: int | None = None
  for stop_tok in stops:
    if stop_tok:
      pos = raw_text.find(stop_tok)
      if pos != -1 and (earliest_stop is None or pos < earliest_stop):
        earliest_stop = pos

  if earliest_stop is not None and earliest_stop <= max_chars:
    final_content = raw_text[:earliest_stop]
    done_reason = "stop"
  elif len(raw_text) > max_chars:
    final_content = raw_text[:max_chars]
    done_reason = "length"
  else:
    final_content = raw_text
    done_reason = "stop"

  return {
      "model": payload.get("model", "qwen2.5:1.5b"),
      "message": {"role": "assistant", "content": final_content},
      "done": True,
      "done_reason": done_reason,
      "prompt_eval_count": len(visible_prompt),
  }


# ============================================================================
# 待完善的实验核心函数（Starter 基线版含典型工程缺陷）
# ============================================================================


def load_fixture() -> dict[str, Any]:
  return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_ollama_chat_payload(
    memo_text: str,
    *,
    model: str = "qwen2.5:1.5b",
    temperature: float = 0.0,
    top_p: float = 1.0,
    seed: int | None = 42,
    num_predict: int = 160,
    stop: list[str] | None = None,
    num_ctx: int = 4096,
) -> dict[str, Any]:
  """构造标准 /api/chat 请求体。"""
  # TODO 1: 当前基线既未要求输出后紧跟 </JSON> 闭合标记，也漏传了 temperature/seed/stop/num_ctx 参数！
  return {
      "model": model,
      "stream": False,
      "messages": [
          {"role": "user", "content": f"请从下文抽取日期、金额、城市：{memo_text}"},
      ],
      "options": {
          "temperature": 0.8,
      },
  }


def compute_drift_rate(outputs: list[str]) -> float:
  """计算多次采样输出的波动率：(唯一输出种数 - 1) / max(总次数 - 1, 1)。"""
  if len(outputs) <= 1:
    return 0.0
  return round((len(set(outputs)) - 1) / (len(outputs) - 1), 4)


def measure_sampling_stability(
    memo_text: str,
    temperatures: tuple[float, ...] = (0.0, 0.7, 1.2),
    runs_per_temp: int = 5,
) -> dict[str, Any]:
  """测试三档 temperature 各跑 runs_per_temp 次的波动率，并验证固定/更换 seed 与云端对照。"""
  # TODO 2:
  # 1) 遍历 temperatures，每档在 seed=None, stop=[STOP_SENTINEL] 下连跑 runs_per_temp 次，记录 runs_by_temp 与 drift_by_temp；
  # 2) 在 temperature=0.7 下固定 seed=42 连跑 3 次，再换 seed=99 跑 1 次，验证 seed_reproducible；
  # 3) 调用 shared.aid_lab.chat_complete(..., temperature=0.0, mock_fn=...) 获取云端温度=0 稳态对照。
  _ = (memo_text, temperatures, runs_per_temp, chat_complete)
  return {
      "runs_by_temp": {},
      "drift_by_temp": {},
      "temp_zero_parsed": None,
      "seed_42_outputs": [],
      "seed_99_output": "",
      "seed_reproducible": False,
      "cloud_temp_zero_output": "",
  }


def diagnose_truncation_and_stop(memo_text: str) -> dict[str, Any]:
  """复现 num_predict 过小导致半途截断，并验证配置 stop=[STOP_SENTINEL] 精准停下。"""
  # TODO 3:
  # - truncated_case: num_predict=10, stop=None -> 复现 done_reason == 'length' 且 JSON 解析失败
  # - clean_stop_case: num_predict=160, stop=[STOP_SENTINEL] -> 精准停在 </JSON> 前并解析为字典
  bad_payload = build_ollama_chat_payload(memo_text, temperature=0.0, num_predict=160, stop=None)
  resp = simulate_local_slm_chat(bad_payload)
  raw_content = resp["message"]["content"]
  parsed = None
  valid = False
  try:
    parsed = json.loads(raw_content)
    valid = True
  except ValueError:
    valid = False

  return {
      "truncated_case": {
          "content": raw_content,
          "done_reason": resp["done_reason"],
          "is_truncated": False,
          "json_valid": valid,
      },
      "clean_stop_case": {
          "content": raw_content,
          "done_reason": resp["done_reason"],
          "is_truncated": resp["done_reason"] == "length",
          "json_valid": valid,
          "parsed_data": parsed,
      },
  }


def compose_long_memo(long_spec: dict[str, Any]) -> str:
  filler = "\n".join([long_spec["filler_block"]] * int(long_spec["repeat_count"]))
  return f"{long_spec['critical_header']}\n{filler}\n{long_spec['tail_question']}"


def diagnose_context_window_forgetting(long_spec: dict[str, Any]) -> dict[str, Any]:
  """复现默认 num_ctx=2048 丢弃长文卷首金额，并调大 num_ctx=4096 验证找回。"""
  long_text = compose_long_memo(long_spec)
  # TODO 4: 当前两次调用都用了默认小窗口，尚未在 expanded_ctx_case 中传入 num_ctx=4096 找回卷首信息！
  small_resp = simulate_local_slm_chat(
      build_ollama_chat_payload(long_text, temperature=0.0, stop=[STOP_SENTINEL], num_ctx=2048)
  )
  expanded_resp = simulate_local_slm_chat(
      build_ollama_chat_payload(long_text, temperature=0.0, stop=[STOP_SENTINEL], num_ctx=2048)
  )
  try:
    small_data = json.loads(small_resp["message"]["content"])
  except ValueError:
    small_data = {}
  try:
    expanded_data = json.loads(expanded_resp["message"]["content"])
  except ValueError:
    expanded_data = {}

  expected = long_spec["expected"]
  return {
      "prompt_length": len(long_text),
      "small_ctx_data": small_data,
      "expanded_ctx_data": expanded_data,
      "header_forgotten_in_small_ctx": small_data.get("amount") is None,
      "header_recovered_in_expanded_ctx": expanded_data == expected,
  }


def build_selection_matrix(profiles: list[dict[str, Any]]) -> dict[str, Any]:
  """围绕准确率、响应速度、数据隐私、成本费用四维生成本地 vs 云端选型结论表。"""
  # TODO 5: 补齐 accuracy / speed / privacy / cost 四维 Markdown 表格与高敏/公开大批量场景推荐路由
  lines = ["| 方案 | 成本 |", "| --- | --- |"]
  for p in profiles:
    lines.append(f"| {p['display_name']} | ${p['cost_per_1k_calls_usd']:.2f}/千次 |")
  return {
      "dimensions": ["cost"],
      "markdown_table": "\n".join(lines),
      "recommendations": {},
  }


if __name__ == "__main__":
  data = load_fixture()
  sample_text = data["short_memos"][0]["text"]
  print("当前为 starter.py 基线版，请运行 python3 verify.py 查看待修复清单。")
  print("示例负载：", build_ollama_chat_payload(sample_text))
