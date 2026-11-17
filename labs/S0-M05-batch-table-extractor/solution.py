#!/usr/bin/env python3
"""S0-M05 Solution：极简批量抽表脚本标准参考实现。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import os
import pathlib
import re
import sys
import tempfile
import time
from typing import Any, Callable

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

DEFAULT_INPUT_CSV = LAB_DIR / "fixtures" / "customer_feedback_15.csv"
OUTPUT_COLUMNS = [
    "feedback_id",
    "submitted_at",
    "channel",
    "customer_tier",
    "status",
    "sentiment",
    "category",
    "urgency",
    "summary",
    "error",
]
REQUIRED_JSON_KEYS = ("sentiment", "category", "urgency", "summary")
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class ApiHttpError(Exception):
  """模拟或封装 HTTP API 状态码异常。"""

  def __init__(self, status_code: int, message: str, retry_after: float | None = None) -> None:
    super().__init__(f"HTTP {status_code}: {message}")
    self.status_code = status_code
    self.message = message
    self.retry_after = retry_after


class AuthConfigError(RuntimeError):
  """当环境变量缺失或收到 401 鉴权失败时立即抛出的配置异常（不重试）。"""


@dataclass
class BatchConfig:
  api_key: str
  model: str = "gpt-4o-mini"
  input_price_per_1m: float = 0.15
  output_price_per_1m: float = 0.60
  max_retries: int = 3
  base_backoff_sec: float = 0.5


def _classify_feedback_rule(content: str) -> dict[str, str]:
  if any(k in content for k in ("专业", "点赞", "顺手")):
    return {"sentiment": "positive", "category": "praise", "urgency": "low", "summary": content[:24]}
  if any(k in content for k in ("扣款", "发票", "账单", "差价")):
    urg = "high" if any(k in content for k in ("重复扣款", "502", "对不上")) else "medium"
    return {"sentiment": "negative" if urg == "high" else "neutral", "category": "billing", "urgency": urg, "summary": content[:24]}
  if any(k in content for k in ("闪退", "乱码", "转圈", "费眼", "延迟", "校验失败")):
    urg = "high" if any(k in content for k in ("闪退", "乱码")) else "medium"
    return {"sentiment": "negative", "category": "bug", "urgency": urg, "summary": content[:24]}
  if any(k in content for k in ("两步验证", "权限")):
    return {"sentiment": "neutral", "category": "account", "urgency": "medium", "summary": content[:24]}
  return {"sentiment": "neutral", "category": "feature", "urgency": "low", "summary": content[:24]}


def create_mock_transport(
    *,
    fail_429_plan: dict[str, int] | None = None,
    retry_after_sec: float | None = None,
    malformed_ids: set[str] | None = None,
    code_fence_ids: set[str] | None = None,
) -> Callable[[dict[str, str], BatchConfig], dict[str, Any]]:
  """构造可注入 401/429/脏 JSON/代码块包裹场景的请求传输函数。"""
  attempts_by_id: dict[str, int] = {}
  plan = dict(fail_429_plan or {})
  bad_json_set = set(malformed_ids or set())
  fenced_set = {"FB-009"} if code_fence_ids is None else set(code_fence_ids)

  def _transport(record: dict[str, str], config: BatchConfig) -> dict[str, Any]:
    key = (config.api_key or "").strip()
    if not key or "INVALID" in key:
      raise ApiHttpError(401, "Unauthorized: API Key 无效或未配置，请检查环境变量 OPENAI_API_KEY")

    fid = record["feedback_id"]
    attempts_by_id[fid] = attempts_by_id.get(fid, 0) + 1
    if attempts_by_id[fid] <= plan.get(fid, 0):
      raise ApiHttpError(429, f"Rate limit exceeded on {fid}", retry_after=retry_after_sec)

    content_text = record.get("content", "")
    seq_num = int(fid.split("-")[1]) if "-" in fid and fid.split("-")[1].isdigit() else 1
    usage = {
        "prompt_tokens": 140 + len(content_text) * 2,
        "completion_tokens": 48 + (seq_num % 5) * 4,
    }

    if fid in bad_json_set:
      return {
          "content": "抱歉，这条账单反馈需要人工核对，暂时无法输出 JSON 结构。",
          "usage": usage,
      }

    label_obj = _classify_feedback_rule(content_text)
    json_str = json.dumps(label_obj, ensure_ascii=False)
    if fid in fenced_set:
      json_str = f"```json\n{json_str}\n```"
    return {"content": json_str, "usage": usage}

  return _transport


def load_config_from_env(*, allow_mock_fallback: bool = False) -> BatchConfig:
  """严格从环境变量加载 API Key、模型与单价假设，绝不在源码硬编码密钥。"""
  raw_key = os.environ.get("OPENAI_API_KEY", "").strip()
  if not raw_key:
    if allow_mock_fallback:
      raw_key = "MOCK_OFFLINE_DEMO_MODE"
    else:
      raise AuthConfigError("401 鉴权失败：未检测到环境变量 OPENAI_API_KEY，请先导出环境变量后再执行。")

  model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
  in_price = float(os.environ.get("AID_INPUT_PRICE_PER_1M", "0.15"))
  out_price = float(os.environ.get("AID_OUTPUT_PRICE_PER_1M", "0.60"))
  return BatchConfig(
      api_key=raw_key,
      model=model,
      input_price_per_1m=in_price,
      output_price_per_1m=out_price,
  )


def call_with_retry(
    record: dict[str, str],
    config: BatchConfig,
    request_fn: Callable[[dict[str, str], BatchConfig], dict[str, Any]],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
  """区分 401 鉴权失败（立即终止）与 429/5xx 瞬态故障（指数退避 + Retry-After 重试）。"""
  attempt = 0
  while True:
    try:
      return request_fn(record, config)
    except ApiHttpError as err:
      if err.status_code == 401:
        raise AuthConfigError(
            f"401 鉴权错误：{err.message}。请立即检查环境变量 OPENAI_API_KEY 是否正确！"
        ) from err
      if err.status_code in RETRYABLE_STATUS_CODES and attempt < config.max_retries:
        delay = (
            float(err.retry_after)
            if err.retry_after is not None
            else config.base_backoff_sec * (2**attempt)
        )
        sleep_fn(delay)
        attempt += 1
        continue
      raise


def parse_extraction_json(raw_text: str) -> tuple[dict[str, str] | None, str | None]:
  """剥离可选 Markdown 代码围栏并安全解析 JSON，单条脏回复返回错误原因而不中断全批。"""
  cleaned = (raw_text or "").strip()
  if not cleaned:
    return None, "empty_response"

  fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
  if fence_match:
    cleaned = fence_match.group(1).strip()

  try:
    obj = json.loads(cleaned)
  except ValueError as exc:
    return None, f"invalid_json: {exc}"

  if not isinstance(obj, dict):
    return None, "json_root_not_object"

  normalized: dict[str, str] = {}
  for key in REQUIRED_JSON_KEYS:
    val = obj.get(key)
    if val is None or not str(val).strip():
      return None, f"missing_field: {key}"
    normalized[key] = str(val).strip()

  return normalized, None


def _compute_cost_usd(prompt_tokens: float, completion_tokens: float, config: BatchConfig) -> float:
  return (
      (prompt_tokens / 1_000_000.0) * config.input_price_per_1m
      + (completion_tokens / 1_000_000.0) * config.output_price_per_1m
  )


def estimate_pilot_budget(
    pilot_usages: list[dict[str, int]],
    total_count: int,
    config: BatchConfig,
) -> dict[str, float]:
  """基于前几条试跑样本的 Token 用量估算全量批处理总 Token 与总费用。"""
  if not pilot_usages or total_count <= 0:
    return {
        "pilot_size": 0,
        "avg_prompt_tokens": 0.0,
        "avg_completion_tokens": 0.0,
        "estimated_total_tokens": 0.0,
        "estimated_total_cost_usd": 0.0,
    }
  n_pilot = len(pilot_usages)
  avg_in = sum(int(u.get("prompt_tokens", 0)) for u in pilot_usages) / n_pilot
  avg_out = sum(int(u.get("completion_tokens", 0)) for u in pilot_usages) / n_pilot
  est_in = avg_in * total_count
  est_out = avg_out * total_count
  return {
      "pilot_size": n_pilot,
      "avg_prompt_tokens": round(avg_in, 2),
      "avg_completion_tokens": round(avg_out, 2),
      "estimated_total_tokens": round(est_in + est_out, 2),
      "estimated_total_cost_usd": round(_compute_cost_usd(est_in, est_out, config), 8),
  }


def _live_or_mock_default_transport() -> Callable[[dict[str, str], BatchConfig], dict[str, Any]]:
  fallback_mock = create_mock_transport()

  def _adapter(record: dict[str, str], config: BatchConfig) -> dict[str, Any]:
    if os.environ.get("AID_FORCE_MOCK") == "1" or config.api_key == "MOCK_OFFLINE_DEMO_MODE":
      return fallback_mock(record, config)
    content_text = record.get("content", "")
    reply = chat_complete(
        [
            {
                "role": "system",
                "content": (
                    "你是客户反馈分类助手。请输出包含 sentiment(positive/neutral/negative)、"
                    "category(billing/bug/feature/praise/account)、urgency(high/medium/low)、"
                    "summary(25字内摘要) 四个字段的 JSON 对象。"
                ),
            },
            {"role": "user", "content": content_text},
        ],
        mock_fn=lambda _msgs: json.dumps(_classify_feedback_rule(content_text), ensure_ascii=False),
        temperature=0.0,
        response_json=True,
    )
    return {
        "content": reply,
        "usage": {
            "prompt_tokens": 140 + len(content_text) * 2,
            "completion_tokens": max(24, len(reply)),
        },
    }

  return _adapter


def run_batch_pipeline(
    csv_path: pathlib.Path,
    output_csv_path: pathlib.Path,
    config: BatchConfig,
    *,
    request_fn: Callable[[dict[str, str], BatchConfig], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
  """执行全量批处理：环境变量鉴权校验 -> 前 5 条试跑预估 -> 容错抽取 -> Token 账单汇总 -> UTF-8-SIG 导出。"""
  if not (config.api_key or "").strip():
    raise AuthConfigError("401 鉴权失败：config.api_key 为空，请配置环境变量 OPENAI_API_KEY。")

  active_fn = request_fn or _live_or_mock_default_transport()
  with csv_path.open("r", encoding="utf-8-sig", newline="") as in_f:
    records = list(csv.DictReader(in_f))

  pilot_target = min(5, len(records))
  pilot_estimate: dict[str, float] = {}
  usage_history: list[dict[str, int]] = []
  rows_out: list[dict[str, str]] = []

  total_prompt_tokens = 0
  total_completion_tokens = 0
  success_count = 0
  failed_count = 0

  for idx, row in enumerate(records, start=1):
    resp = call_with_retry(row, config, active_fn, sleep_fn=sleep_fn)
    usage = resp.get("usage") or {}
    p_tok = int(usage.get("prompt_tokens", 0))
    c_tok = int(usage.get("completion_tokens", 0))
    total_prompt_tokens += p_tok
    total_completion_tokens += c_tok
    usage_history.append({"prompt_tokens": p_tok, "completion_tokens": c_tok})

    if idx == pilot_target:
      pilot_estimate = estimate_pilot_budget(usage_history, len(records), config)

    parsed, err_reason = parse_extraction_json(str(resp.get("content", "")))
    if parsed is not None:
      success_count += 1
      rows_out.append({
          "feedback_id": row["feedback_id"],
          "submitted_at": row["submitted_at"],
          "channel": row["channel"],
          "customer_tier": row["customer_tier"],
          "status": "ok",
          "sentiment": parsed["sentiment"],
          "category": parsed["category"],
          "urgency": parsed["urgency"],
          "summary": parsed["summary"],
          "error": "",
      })
    else:
      failed_count += 1
      rows_out.append({
          "feedback_id": row["feedback_id"],
          "submitted_at": row["submitted_at"],
          "channel": row["channel"],
          "customer_tier": row["customer_tier"],
          "status": "parse_error",
          "sentiment": "",
          "category": "",
          "urgency": "",
          "summary": "",
          "error": err_reason or "parse_error",
      })

  output_csv_path.parent.mkdir(parents=True, exist_ok=True)
  with output_csv_path.open("w", encoding="utf-8-sig", newline="") as out_f:
    writer = csv.DictWriter(out_f, fieldnames=OUTPUT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows_out)

  total_cost_usd = round(_compute_cost_usd(total_prompt_tokens, total_completion_tokens, config), 8)
  return {
      "processed_count": len(rows_out),
      "success_count": success_count,
      "failed_count": failed_count,
      "pilot_estimate": pilot_estimate,
      "total_prompt_tokens": total_prompt_tokens,
      "total_completion_tokens": total_completion_tokens,
      "total_tokens": total_prompt_tokens + total_completion_tokens,
      "total_cost_usd": total_cost_usd,
      "output_csv": str(output_csv_path),
  }


if __name__ == "__main__":
  cfg = load_config_from_env(allow_mock_fallback=True)
  with tempfile.TemporaryDirectory() as tmp_dir:
    out_path = pathlib.Path(tmp_dir) / "feedback_extracted.csv"
    transport = create_mock_transport(fail_429_plan={"FB-003": 2})
    report = run_batch_pipeline(
        DEFAULT_INPUT_CSV,
        out_path,
        cfg,
        request_fn=transport,
        sleep_fn=lambda _s: None,
    )
    print("=== 批量抽表账单与执行汇总 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
