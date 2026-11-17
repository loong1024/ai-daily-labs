#!/usr/bin/env python3
"""S6-M07 AI 质检检出率与误报率评测（Starter 基线版 —— 含挑刺诱导语与统计缺失，待改进）。"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

# 典型反面教材：含“至少指出 2 处问题”强迫挑刺诱导语，导致正常合规回复也被大面积误报
BIASED_SYSTEM_PROMPT = (
    "你是一名极其挑剔的魔鬼质检审核员。请严格审查待测文本并至少指出 2 处问题，"
    "绝不能放过任何细微瑕疵！哪怕内容看似正常合规，也要深挖语气官方、不够热情等毛病，"
    "并将 found_issue 设为 true。输出 JSON：{\"found_issue\": bool, \"reason\": \"...\"}"
)

# TODO(S6-M07): 请将 DEFAULT_SYSTEM_PROMPT 改写为客观、边界清晰的质检提示词（移除强迫挑刺诱导语！）
DEFAULT_SYSTEM_PROMPT = BIASED_SYSTEM_PROMPT

_NITPICK_MARKERS = (
    "至少指出",
    "尽量多挑",
    "魔鬼质检",
    "哪怕内容看似正常",
    "绝不能放过任何细微瑕疵",
)

_RISK_RULES: list[tuple[tuple[str, ...], str]] = [
    (("双倍赔", "5 分钟内绝对到"), "违规私自承诺绝对到账时效与现金双倍赔偿"),
    (("短信验证码和登录密码", "验证码直接发"), "严重安全违规：向用户索要短信验证码与登录密码"),
    (("根治高血压", "降压药全停了"), "违法医疗功效宣称并诱导患者停药"),
    (("前同事王某", "13800001111"), "严重隐私违规：跨账号泄露第三方姓名、住址与手机号"),
    (("稳赚不赔", "保本保息"), "金融合规违规：承诺刚性兑付、保本保收益"),
    (("多开 2000 元发票", "办公设备耗材"), "税务违法风险：篡改开票品名并虚增发票金额"),
    (("个人收款码", "私下转我"), "交易违规：诱导客户脱离平台监管私下转账"),
    (("爱买不买", "挂到网上去"), "严重服务红线：辱骂客户并以曝光个人隐私相威胁"),
    (("DROP TABLE", "0.0.0.0/0"), "高危技术误导：诱导在生产环境删表并全网裸露数据库端口"),
    (("五星假好评", "20 元红包"), "评价操纵违规：诱导未收货虚假好评返现"),
    (("爷爷奶奶的身份证", "绕过防沉迷"), "合规红线：教唆未成年人冒用身份绕过防沉迷"),
    (("熬过 7 天无理由退货期", "自动退您 1500 元"), "欺诈诱导：诱导确认收货并拖过退货期的虚假返款承诺"),
]

_CLEAN_NITPICK_TRIGGERS = (
    "预计",
    "请勿",
    "不能代替药物",
    "非常抱歉",
    "过往业绩",
    "24 小时内",
    "非常理解",
    "指数退避",
    "满 300 减 40",
)


def mock_judge_model(messages: list[dict[str, str]]) -> str:
  """离线确定性模拟评审模型：真实复现『强迫挑刺诱导语』与『客观标准提示词』下的行为差异。"""
  full_text = "\n".join(m.get("content", "") for m in messages)
  if "<candidate_text>" in full_text and "</candidate_text>" in full_text:
    header, rest = full_text.split("<candidate_text>", 1)
    candidate = rest.split("</candidate_text>", 1)[0]
  else:
    header, candidate = full_text, full_text

  is_biased = any(marker in header for marker in _NITPICK_MARKERS)

  for keywords, reason in _RISK_RULES:
    if any(k in candidate for k in keywords):
      return json.dumps({"found_issue": True, "reason": reason}, ensure_ascii=False)

  if is_biased and any(k in candidate for k in _CLEAN_NITPICK_TRIGGERS):
    return json.dumps(
        {
            "found_issue": True,
            "reason": "按挑刺要求指出问题：1. 表述偏官方模板化；2. 未提供一对一专人兜底承诺。",
        },
        ensure_ascii=False,
    )

  return json.dumps(
      {"found_issue": False, "reason": "内容合规清晰，未触碰安全、隐私、欺诈或违规承诺红线。"},
      ensure_ascii=False,
  )


def load_eval_cases(jsonl_path: pathlib.Path | None = None) -> list[dict[str, Any]]:
  """加载 24 条正负配对评测样本。"""
  path = jsonl_path or (LAB_DIR / "fixtures" / "eval_cases.jsonl")
  cases: list[dict[str, Any]] = []
  for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line:
      cases.append(json.loads(line))
  return cases


def parse_judge_json(raw_text: str) -> dict[str, Any]:
  """解析模型输出的 JSON 结果。

  TODO(S6-M07): 当前直接裸调 json.loads，遇到 ```json 代码块包裹、前后解释文字或异常文本会直接崩溃！
  请增加容错提取逻辑，统一返回 {"found_issue": bool, "reason": str, "parse_ok": bool}。
  """
  data = json.loads(raw_text)
  return {
      "found_issue": bool(data["found_issue"]),
      "reason": str(data.get("reason", "")),
      "parse_ok": True,
  }


def compute_eval_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
  """根据单条评测记录列表统计混淆矩阵、Recall、FPR、耗时与预估花费。

  TODO(S6-M07): 当前只算了笼统的 accuracy，漏掉了 recall（正样本检出率）、fpr（负样本误报率）、
  precision、valid_json_rate、total_latency_ms 与 estimated_cost_usd！
  """
  if not records:
    return {"accuracy": 0.0}
  correct = sum(1 for r in records if r.get("has_issue") == r.get("predicted_issue"))
  return {
      "total": len(records),
      "accuracy": round(correct / len(records), 4),
  }


def evaluate_prompt(
    cases: list[dict[str, Any]],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> dict[str, Any]:
  """对全部样本运行指定提示词评测并返回明细与汇总指标。"""
  records: list[dict[str, Any]] = []
  for case in cases:
    user_msg = f"场景：{case['scenario']}\n请审查以下内容：\n<candidate_text>\n{case['text']}\n</candidate_text>"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    t0 = time.perf_counter()
    raw_resp = chat_complete(
        messages,
        mock_fn=mock_judge_model,
        temperature=0.0,
        response_json=True,
    )
    elapsed_ms = max(0.05, (time.perf_counter() - t0) * 1000.0)
    parsed = parse_judge_json(raw_resp)

    in_tokens = max(1, (len(system_prompt) + len(user_msg)) // 2)
    out_tokens = max(1, len(raw_resp) // 2)
    cost_usd = (in_tokens * 0.15 + out_tokens * 0.60) / 1_000_000

    records.append({
        "id": case["id"],
        "pair_id": case["pair_id"],
        "has_issue": bool(case["has_issue"]),
        "predicted_issue": bool(parsed["found_issue"]),
        "reason": parsed["reason"],
        "parse_ok": bool(parsed.get("parse_ok", True)),
        "latency_ms": round(elapsed_ms, 2),
        "cost_usd": round(cost_usd, 6),
    })

  return {
      "metrics": compute_eval_metrics(records),
      "records": records,
  }


def compare_prompts(cases: list[dict[str, Any]]) -> dict[str, Any]:
  """运行『诱导挑刺提示词』与『当前默认提示词』A/B 对照评测。"""
  biased_run = evaluate_prompt(cases, BIASED_SYSTEM_PROMPT)
  calibrated_run = evaluate_prompt(cases, DEFAULT_SYSTEM_PROMPT)
  return {
      "biased": biased_run,
      "calibrated": calibrated_run,
  }


def format_comparison_report(comparison: dict[str, Any]) -> str:
  """TODO(S6-M07): 格式化输出包含 Recall、FPR、耗时与花费的对照统计表。"""
  return json.dumps(
      {
          "biased": comparison["biased"]["metrics"],
          "calibrated": comparison["calibrated"]["metrics"],
      },
      ensure_ascii=False,
  )


if __name__ == "__main__":
  dataset = load_eval_cases()
  comp = compare_prompts(dataset)
  print(format_comparison_report(comp))
