#!/usr/bin/env python3
"""S0-M02 Solution：本地小模型采样稳定度、停止控制与窗口遗忘实测标准参考实现。"""

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
  """仿真本地 1.5B 小模型 /api/chat 的采样、停止符截停、长度截断与窗口遗忘机制。"""
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

  num_ctx = int(options.get("num_ctx", 2048))
  visible_prompt = full_prompt[-num_ctx:] if len(full_prompt) > num_ctx else full_prompt
  date_val, amount_val, city_val = _extract_ground_truth(visible_prompt)

  wants_sentinel = STOP_SENTINEL in full_prompt
  sentinel_str = STOP_SENTINEL if wants_sentinel else ""
  chatter = "\n备注：以上为自动抽取的差旅报销字段，如需换算税额请继续提问。"

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
  """构造带严格字段契约、闭合标记与完整采样/窗口参数的 /api/chat 请求负载。"""
  system_prompt = (
      "你是严谨的财务结构化信息抽取助手。"
      "请从用户文本中提取 date(YYYY-MM-DD)、amount(纯数字浮点数)、city(城市名)，"
      f"若上下文中未出现对应字段请填 null。只输出紧凑 JSON 对象并在末尾紧跟 {STOP_SENTINEL} 结束。"
  )
  options: dict[str, Any] = {
      "temperature": temperature,
      "top_p": top_p,
      "num_predict": num_predict,
      "num_ctx": num_ctx,
  }
  if seed is not None:
    options["seed"] = seed
  if stop:
    options["stop"] = list(stop)

  return {
      "model": model,
      "stream": False,
      "messages": [
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": memo_text},
      ],
      "options": options,
  }


def compute_drift_rate(outputs: list[str]) -> float:
  """计算多次采样输出的波动率：(唯一输出种数 - 1) / max(总次数 - 1, 1)。"""
  if len(outputs) <= 1:
    return 0.0
  return round((len(set(outputs)) - 1) / (len(outputs) - 1), 4)


def _cloud_mock_extractor(messages: list[dict[str, str]]) -> str:
  joined = "\n".join(m.get("content", "") for m in messages)
  date_val, amount_val, city_val = _extract_ground_truth(joined)
  return json.dumps({"date": date_val, "amount": amount_val, "city": city_val}, ensure_ascii=False)


def measure_sampling_stability(
    memo_text: str,
    temperatures: tuple[float, ...] = (0.0, 0.7, 1.2),
    runs_per_temp: int = 5,
) -> dict[str, Any]:
  """实测三档 temperature 各 5 次的抽取波动率，验证 seed 复现性并对照云端温度=0 表现。"""
  runs_by_temp: dict[float, list[str]] = {}
  drift_by_temp: dict[float, float] = {}

  for temp in temperatures:
    batch_outputs: list[str] = []
    for _ in range(runs_per_temp):
      payload = build_ollama_chat_payload(
          memo_text,
          temperature=temp,
          top_p=0.9 if temp > 0 else 1.0,
          seed=None,
          num_predict=160,
          stop=[STOP_SENTINEL],
          num_ctx=4096,
      )
      resp = simulate_local_slm_chat(payload)
      batch_outputs.append(resp["message"]["content"].strip())
    runs_by_temp[temp] = batch_outputs
    drift_by_temp[temp] = compute_drift_rate(batch_outputs)

  temp_zero_parsed: dict[str, Any] | None = None
  if 0.0 in runs_by_temp and runs_by_temp[0.0]:
    temp_zero_parsed = json.loads(runs_by_temp[0.0][0])

  seed_42_outputs = [
      simulate_local_slm_chat(
          build_ollama_chat_payload(
              memo_text,
              temperature=0.7,
              top_p=0.9,
              seed=42,
              num_predict=160,
              stop=[STOP_SENTINEL],
              num_ctx=4096,
          )
      )["message"]["content"].strip()
      for _ in range(3)
  ]
  seed_99_output = simulate_local_slm_chat(
      build_ollama_chat_payload(
          memo_text,
          temperature=0.7,
          top_p=0.9,
          seed=99,
          num_predict=160,
          stop=[STOP_SENTINEL],
          num_ctx=4096,
      )
  )["message"]["content"].strip()

  cloud_reply = chat_complete(
      [
          {
              "role": "system",
              "content": "提取 date(YYYY-MM-DD)、amount(float)、city(str)，仅输出 JSON 对象。",
          },
          {"role": "user", "content": memo_text},
      ],
      mock_fn=_cloud_mock_extractor,
      temperature=0.0,
      response_json=True,
  ).strip()

  seed_reproducible = (
      len(seed_42_outputs) == 3
      and len(set(seed_42_outputs)) == 1
      and seed_42_outputs[0] != seed_99_output
  )

  return {
      "runs_by_temp": runs_by_temp,
      "drift_by_temp": drift_by_temp,
      "temp_zero_parsed": temp_zero_parsed,
      "seed_42_outputs": seed_42_outputs,
      "seed_99_output": seed_99_output,
      "seed_reproducible": seed_reproducible,
      "cloud_temp_zero_output": cloud_reply,
  }


def diagnose_truncation_and_stop(memo_text: str) -> dict[str, Any]:
  """复现 num_predict 过小导致半途截断，并验证配置 stop=[STOP_SENTINEL] 精准停下。"""
  trunc_payload = build_ollama_chat_payload(
      memo_text,
      temperature=0.0,
      seed=42,
      num_predict=10,
      stop=None,
      num_ctx=4096,
  )
  trunc_resp = simulate_local_slm_chat(trunc_payload)
  trunc_text = trunc_resp["message"]["content"]
  try:
    json.loads(trunc_text)
    trunc_valid = True
  except ValueError:
    trunc_valid = False

  clean_payload = build_ollama_chat_payload(
      memo_text,
      temperature=0.0,
      seed=42,
      num_predict=160,
      stop=[STOP_SENTINEL],
      num_ctx=4096,
  )
  clean_resp = simulate_local_slm_chat(clean_payload)
  clean_text = clean_resp["message"]["content"].strip()
  try:
    clean_parsed = json.loads(clean_text)
    clean_valid = isinstance(clean_parsed, dict)
  except ValueError:
    clean_parsed = None
    clean_valid = False

  return {
      "truncated_case": {
          "content": trunc_text,
          "done_reason": trunc_resp["done_reason"],
          "is_truncated": trunc_resp["done_reason"] == "length",
          "json_valid": trunc_valid,
      },
      "clean_stop_case": {
          "content": clean_text,
          "done_reason": clean_resp["done_reason"],
          "is_truncated": clean_resp["done_reason"] == "length",
          "json_valid": clean_valid,
          "parsed_data": clean_parsed,
      },
  }


def compose_long_memo(long_spec: dict[str, Any]) -> str:
  filler = "\n".join([long_spec["filler_block"]] * int(long_spec["repeat_count"]))
  return f"{long_spec['critical_header']}\n{filler}\n{long_spec['tail_question']}"


def diagnose_context_window_forgetting(long_spec: dict[str, Any]) -> dict[str, Any]:
  """对照默认小窗口 num_ctx=2048 的卷首静默遗忘与扩容 num_ctx=4096 后的完整找回。"""
  long_text = compose_long_memo(long_spec)

  small_resp = simulate_local_slm_chat(
      build_ollama_chat_payload(
          long_text,
          temperature=0.0,
          seed=42,
          num_predict=160,
          stop=[STOP_SENTINEL],
          num_ctx=2048,
      )
  )
  expanded_resp = simulate_local_slm_chat(
      build_ollama_chat_payload(
          long_text,
          temperature=0.0,
          seed=42,
          num_predict=160,
          stop=[STOP_SENTINEL],
          num_ctx=4096,
      )
  )

  small_data = json.loads(small_resp["message"]["content"].strip())
  expanded_data = json.loads(expanded_resp["message"]["content"].strip())
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
  lines = [
      "| 候选方案 | 抽取准确率 | 平均响应速度 | 数据隐私安全 | 千次调用成本 | 适用场景建议 |",
      "| --- | --- | --- | --- | --- | --- |",
  ]
  for p in profiles:
    acc_pct = f"{float(p['accuracy_score']) * 100:.1f}%"
    speed_str = f"{int(p['avg_latency_ms'])} ms/条"
    privacy_str = str(p["privacy_level"])
    cost_val = float(p["cost_per_1k_calls_usd"])
    cost_str = "$0.00（仅本地电费/算力折旧）" if cost_val == 0.0 else f"${cost_val:.2f} / 千次"
    if p["profile_id"] == "local_1_5b_q4":
      scene = "8GB 轻薄本离线处理短篇敏感单据（需设 temperature=0 + stop + 按需调大 num_ctx）"
    elif p["profile_id"] == "local_3b_q4":
      scene = "16GB+ 办公机离线抽取内部法务/薪酬纪要，兼顾隐私与复杂表述准确率"
    else:
      scene = "非涉密或已脱敏的大批量文本、超长百页报告高并发抽取"
    lines.append(f"| {p['display_name']} | {acc_pct} | {speed_str} | {privacy_str} | {cost_str} | {scene} |")

  best_local = max(
      (p for p in profiles if float(p["cost_per_1k_calls_usd"]) == 0.0),
      key=lambda item: float(item["accuracy_score"]),
  )
  best_cloud = max(
      (p for p in profiles if float(p["cost_per_1k_calls_usd"]) > 0.0),
      key=lambda item: float(item["accuracy_score"]),
  )

  return {
      "dimensions": ["accuracy", "speed", "privacy", "cost"],
      "markdown_table": "\n".join(lines),
      "recommendations": {
          "sensitive_internal_memo": {
              "selected_profile": best_local["profile_id"],
              "required_options": {
                  "temperature": 0.0,
                  "stop": [STOP_SENTINEL],
                  "num_ctx": 4096,
              },
              "reason": "高敏纪要严禁出域，本地量化小模型锁死 temperature=0、配置 stop 闭合符并扩容 num_ctx=4096 可稳定离线抽表。",
          },
          "high_volume_public_batch": {
              "selected_profile": best_cloud["profile_id"],
              "required_options": {"temperature": 0.0},
              "reason": "公开或脱敏语料无出域限制，云端低价小模型拥有 128K 大窗口与 98% 准确率，千次仅 $0.24 性价比最高。",
          },
      },
  }


if __name__ == "__main__":
  fixture = load_fixture()
  memo0 = fixture["short_memos"][0]["text"]
  stability = measure_sampling_stability(memo0)
  trunc = diagnose_truncation_and_stop(memo0)
  ctx_diag = diagnose_context_window_forgetting(fixture["long_meeting_memo"])
  matrix = build_selection_matrix(fixture["benchmark_profiles"])

  print("1) 三档温度波动率：", stability["drift_by_temp"], "Seed 可复现：", stability["seed_reproducible"])
  print("2) 截断与精准停止：", trunc["truncated_case"]["done_reason"], "->", trunc["clean_stop_case"]["parsed_data"])
  print("3) 窗口遗忘对照（2048 vs 4096）：", ctx_diag["small_ctx_data"], "->", ctx_diag["expanded_ctx_data"])
  print("\n4) 本地轻量模型 vs 云端小模型四维选型表：\n")
  print(matrix["markdown_table"])
