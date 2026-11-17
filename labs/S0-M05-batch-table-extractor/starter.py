#!/usr/bin/env python3
"""S0-M05 Starter：极简批量抽表脚本（环境变量鉴权 + 401/429 重试 + Token 账单 + UTF-8-SIG CSV）。

请按 README.md 步骤指引修复下方 TODO 缺陷，运行 python3 verify.py 验证。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import os
import pathlib
import sys
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

# TODO 1: 严禁在源码中硬编码任何 API Key（哪怕是占位测试串也应移除，统一改为从环境变量读取）！
HARDCODED_PLACEHOLDER_KEY = "FAKE_TEST_KEY_DO_NOT_USE_12345"


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


# ============================================================================
# 确定性批处理请求仿真桩（供离线运行与故障注入自动化测试使用，请勿删除）
# ============================================================================


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


# ============================================================================
# 待完善的批处理核心模块（Starter 基线含 4 处典型工程缺陷）
# ============================================================================


def load_config_from_env(*, allow_mock_fallback: bool = False) -> BatchConfig:
  """从环境变量加载配置，严禁硬编码 API Key。"""
  # TODO 1: 移除 HARDCODED_PLACEHOLDER_KEY！只从 os.environ 读取 OPENAI_API_KEY；
  # 若为空且 allow_mock_fallback 为 False，立即抛出带 '401' 提示的 AuthConfigError。
  _ = allow_mock_fallback
  api_key = os.environ.get("OPENAI_API_KEY", HARDCODED_PLACEHOLDER_KEY)
  model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
  return BatchConfig(api_key=api_key, model=model)


def call_with_retry(
    record: dict[str, str],
    config: BatchConfig,
    request_fn: Callable[[dict[str, str], BatchConfig], dict[str, Any]],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
  """带 401 快速失败与 429/5xx 指数退避重试的请求包装器。"""
  # TODO 2:
  # - 遇到 status_code == 401 立即转抛 AuthConfigError（含 '401' 字样），绝不重试；
  # - 遇到 status_code in {429, 500, 502, 503, 504} 时按指数退避重试最多 config.max_retries 次，
  #   若 err.retry_after 不为 None 则优先等待 float(err.retry_after)，否则等待 config.base_backoff_sec * (2 ** attempt)。
  _ = sleep_fn
  return request_fn(record, config)


def parse_extraction_json(raw_text: str) -> tuple[dict[str, str] | None, str | None]:
  """解析模型输出 JSON（需兼容 ```json 代码块，非法 JSON 返回 (None, 错误原因) 不崩溃）。"""
  # TODO 3: 剥离可能存在的 Markdown ```json 围栏，并用 try/except 捕获 JSON 解析异常及校验必填键 REQUIRED_JSON_KEYS
  data = json.loads(raw_text)
  return data, None


def estimate_pilot_budget(
    pilot_usages: list[dict[str, int]],
    total_count: int,
    config: BatchConfig,
) -> dict[str, float]:
  """根据前几条试跑样本的 usage 估算全批总 Token 与总美元花费。"""
  # TODO 4a: 计算 avg_prompt_tokens、avg_completion_tokens、estimated_total_tokens 与 estimated_total_cost_usd
  _ = (pilot_usages, total_count, config)
  return {
      "pilot_size": 0,
      "avg_prompt_tokens": 0.0,
      "avg_completion_tokens": 0.0,
      "estimated_total_tokens": 0.0,
      "estimated_total_cost_usd": 0.0,
  }


def run_batch_pipeline(
    csv_path: pathlib.Path,
    output_csv_path: pathlib.Path,
    config: BatchConfig,
    *,
    request_fn: Callable[[dict[str, str], BatchConfig], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
  """读取输入 CSV -> 试跑前 5 条估算预算 -> 全量抽取容错 -> 统计实付账单 -> 导出 UTF-8-SIG CSV。"""
  # TODO 4b:
  # 1) 校验 config.api_key 非空（为空立即抛 AuthConfigError 含 '401' 提示）；
  # 2) 逐条调用 call_with_retry + parse_extraction_json，单条 JSON 异常标记 status='parse_error' 不中断全批；
  # 3) 累加每条 API 响应的 usage token 与实付总费用，前 5 条跑完后生成 pilot_estimate；
  # 4) 用 utf-8-sig 编码写出 CSV，确保 Excel 直接打开无中文乱码。
  _ = chat_complete
  active_fn = request_fn or create_mock_transport()
  rows_out: list[dict[str, str]] = []

  with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
    reader = list(csv.DictReader(f))

  for row in reader:
    resp = call_with_retry(row, config, active_fn, sleep_fn=sleep_fn)
    parsed, err = parse_extraction_json(resp["content"])
    rows_out.append({
        "feedback_id": row["feedback_id"],
        "submitted_at": row["submitted_at"],
        "channel": row["channel"],
        "customer_tier": row["customer_tier"],
        "status": "ok" if parsed else "parse_error",
        "sentiment": (parsed or {}).get("sentiment", ""),
        "category": (parsed or {}).get("category", ""),
        "urgency": (parsed or {}).get("urgency", ""),
        "summary": (parsed or {}).get("summary", ""),
        "error": err or "",
    })

  with output_csv_path.open("w", encoding="utf-8", newline="") as out_f:
    writer = csv.DictWriter(out_f, fieldnames=OUTPUT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows_out)

  return {
      "processed_count": len(rows_out),
      "success_count": len(rows_out),
      "failed_count": 0,
      "pilot_estimate": {},
      "total_prompt_tokens": 0,
      "total_completion_tokens": 0,
      "total_tokens": 0,
      "total_cost_usd": 0.0,
      "output_csv": str(output_csv_path),
  }


if __name__ == "__main__":
  print("当前为 starter.py 基线版，请运行 python3 verify.py 查看待修复项。")
