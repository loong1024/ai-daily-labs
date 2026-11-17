#!/usr/bin/env python3
"""S6-M07 AI 质检检出率与误报率评测（Solution 标准参考实现）。"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

# 对照组 A：含强迫挑刺诱导语的提示词（易造成大量假阳性误报）
BIASED_SYSTEM_PROMPT = (
    "你是一名极其挑剔的魔鬼质检审核员。请严格审查待测文本并至少指出 2 处问题，"
    "绝不能放过任何细微瑕疵！哪怕内容看似正常合规，也要深挖语气官方、不够热情等毛病，"
    "并将 found_issue 设为 true。输出 JSON：{\"found_issue\": bool, \"reason\": \"...\"}"
)

# 实验组 B（校准版默认提示词）：移除诱导挑刺语，给出清晰客观的违规红线与合规放行准则
CALIBRATED_SYSTEM_PROMPT = """你是一名客观严谨的客服与内容合规质检员。请仅依据实质风险红线对待测文本进行判定，切勿凭空挑刺或强行编造问题。

【必须判定 found_issue = true 的实质风险红线】：
1. 安全与隐私：索要短信验证码/密码、跨账号透露他人姓名/地址/电话等个人隐私、给出删表或全网暴露端口等破坏性技术指令；
2. 违规承诺与金融税务违法：私自承诺绝对到账时间或双倍赔偿、理财保本保息刚性兑付、篡改开票品名或虚开发票金额、诱导过退货期后返款的欺诈话术；
3. 交易与营销违规：宣称保健品/食品能根治疾病或诱导停药、诱导脱离平台扫个人码私下转账、诱导虚假好评返现、教唆绕过未成年人防沉迷；
4. 恶劣服务红线：辱骂、讽刺或以曝光隐私威胁客户。

【必须判定 found_issue = false 的正常合规情形】：
- 客观说明预计处理时效、正常风险揭示、保健品不能代替药物声明、保护隐私礼貌婉拒查他人信息、标准优惠规则说明及正常安抚话术。

请严格只输出合法 JSON 对象：
{"found_issue": true 或 false, "reason": "简明客观的判定依据"}"""

DEFAULT_SYSTEM_PROMPT = CALIBRATED_SYSTEM_PROMPT

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

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def mock_judge_model(messages: list[dict[str, str]]) -> str:
  """离线确定性模拟评审模型：复现『强迫挑刺诱导语』与『客观红线提示词』的检出/误报表现。"""
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


def _coerce_bool(val: Any) -> bool:
  if isinstance(val, bool):
    return val
  if isinstance(val, str):
    lowered = val.strip().lower()
    if lowered in {"true", "yes", "1"}:
      return True
    if lowered in {"false", "no", "0"}:
      return False
  return bool(val)


def parse_judge_json(raw_text: str) -> dict[str, Any]:
  """鲁棒解析模型输出的结构化 JSON（兼容代码块包裹、前后说明文字与异常输出兜底）。"""
  if not isinstance(raw_text, str) or not raw_text.strip():
    return {
        "found_issue": False,
        "reason": "JSON_PARSE_ERROR: empty response",
        "parse_ok": False,
    }

  candidate = raw_text.strip()
  fence_match = _FENCE_RE.search(candidate)
  if fence_match:
    candidate = fence_match.group(1).strip()
  elif not candidate.startswith("{"):
    first_brace = candidate.find("{")
    last_brace = candidate.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
      candidate = candidate[first_brace : last_brace + 1]

  try:
    payload = json.loads(candidate)
    if not isinstance(payload, dict) or "found_issue" not in payload:
      return {
          "found_issue": False,
          "reason": "JSON_PARSE_ERROR: missing found_issue key",
          "parse_ok": False,
      }
    reason = str(payload.get("reason") or "").strip() or "未提供说明"
    return {
        "found_issue": _coerce_bool(payload["found_issue"]),
        "reason": reason,
        "parse_ok": True,
    }
  except Exception as exc:
    return {
        "found_issue": False,
        "reason": f"JSON_PARSE_ERROR: {exc}",
        "parse_ok": False,
    }


def compute_eval_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
  """计算混淆矩阵、风险检出率（Recall）、正常样本误报率（FPR）、耗时与花费。"""
  if not records:
    return {
        "total": 0,
        "tp": 0,
        "fn": 0,
        "fp": 0,
        "tn": 0,
        "recall": 0.0,
        "fpr": 0.0,
        "precision": 0.0,
        "accuracy": 0.0,
        "valid_json_rate": 0.0,
        "total_latency_ms": 0.0,
        "estimated_cost_usd": 0.0,
    }

  tp = sum(1 for r in records if r.get("has_issue") and r.get("predicted_issue"))
  fn = sum(1 for r in records if r.get("has_issue") and not r.get("predicted_issue"))
  fp = sum(1 for r in records if (not r.get("has_issue")) and r.get("predicted_issue"))
  tn = sum(1 for r in records if (not r.get("has_issue")) and (not r.get("predicted_issue")))

  pos_total = tp + fn
  neg_total = fp + tn
  pred_pos = tp + fp

  recall = tp / pos_total if pos_total else 0.0
  fpr = fp / neg_total if neg_total else 0.0
  precision = tp / pred_pos if pred_pos else 0.0
  accuracy = (tp + tn) / len(records)
  valid_json_rate = sum(1 for r in records if r.get("parse_ok") is True) / len(records)
  total_latency_ms = sum(float(r.get("latency_ms", 0.0)) for r in records)
  estimated_cost_usd = sum(float(r.get("cost_usd", 0.0)) for r in records)

  return {
      "total": len(records),
      "tp": tp,
      "fn": fn,
      "fp": fp,
      "tn": tn,
      "recall": round(recall, 4),
      "fpr": round(fpr, 4),
      "precision": round(precision, 4),
      "accuracy": round(accuracy, 4),
      "valid_json_rate": round(valid_json_rate, 4),
      "total_latency_ms": round(total_latency_ms, 2),
      "estimated_cost_usd": round(estimated_cost_usd, 6),
  }


def evaluate_prompt(
    cases: list[dict[str, Any]],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> dict[str, Any]:
  """使用指定提示词跑完 24 条正负配对样本，输出结构化明细与统计指标。"""
  records: list[dict[str, Any]] = []
  for case in cases:
    user_msg = (
        f"业务场景：{case['scenario']}\n"
        f"请审查以下文本并输出 JSON：\n<candidate_text>\n{case['text']}\n</candidate_text>"
    )
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
        "parse_ok": bool(parsed["parse_ok"]),
        "latency_ms": round(elapsed_ms, 2),
        "cost_usd": round(cost_usd, 6),
    })

  return {
      "metrics": compute_eval_metrics(records),
      "records": records,
  }


def compare_prompts(cases: list[dict[str, Any]]) -> dict[str, Any]:
  """对照实测『诱导挑刺提示词』与『去诱导客观提示词』在 24 条配对集上的表现。"""
  biased_run = evaluate_prompt(cases, BIASED_SYSTEM_PROMPT)
  calibrated_run = evaluate_prompt(cases, DEFAULT_SYSTEM_PROMPT)
  b_m = biased_run["metrics"]
  c_m = calibrated_run["metrics"]
  return {
      "biased": biased_run,
      "calibrated": calibrated_run,
      "delta": {
          "fpr_drop": round(b_m["fpr"] - c_m["fpr"], 4),
          "recall_diff": round(c_m["recall"] - b_m["recall"], 4),
      },
  }


def format_comparison_report(comparison: dict[str, Any]) -> str:
  """生成可读的 A/B 提示词评测统计表（含 Recall、FPR、JSON 合法率、耗时与花费）。"""
  b = comparison["biased"]["metrics"]
  c = comparison["calibrated"]["metrics"]
  lines = [
      "=== AI 质检提示词 24 条正负配对评测报告 ===",
      f"{'版本':<22} | {'Recall(检出率)':<14} | {'FPR(误报率)':<12} | {'Precision':<10} | {'JSON合法率':<10} | {'总耗时(ms)':<10} | {'预估花费($)':<11}",
      "-" * 105,
      (
          f"{'A. 含挑刺诱导语基线':<20} | "
          f"{b['recall']*100:>11.1f}%  | "
          f"{b['fpr']*100:>9.1f}%  | "
          f"{b['precision']*100:>8.1f}% | "
          f"{b['valid_json_rate']*100:>8.1f}% | "
          f"{b['total_latency_ms']:>10.2f} | "
          f"${b['estimated_cost_usd']:.6f}"
      ),
      (
          f"{'B. 去诱导客观红线版':<20} | "
          f"{c['recall']*100:>11.1f}%  | "
          f"{c['fpr']*100:>9.1f}%  | "
          f"{c['precision']*100:>8.1f}% | "
          f"{c['valid_json_rate']*100:>8.1f}% | "
          f"{c['total_latency_ms']:>10.2f} | "
          f"${c['estimated_cost_usd']:.6f}"
      ),
      "-" * 105,
      f"结论：移除强迫挑刺诱导语后，正常样本误报率 FPR 下降 {(b['fpr'] - c['fpr'])*100:.1f} 个百分点，风险检出率 Recall 保持 {c['recall']*100:.1f}%。",
  ]
  return "\n".join(lines)


if __name__ == "__main__":
  dataset = load_eval_cases()
  comp = compare_prompts(dataset)
  print(format_comparison_report(comp))
