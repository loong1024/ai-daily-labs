"""S3-M05 拒绝凭感觉调参：建 30 题双层回归评测基线（Solution 标准参考实现）。"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from shared.aid_lab import chat_complete

REFUSAL_KEYWORDS = (
    "未收录",
    "未包含",
    "无法回答",
    "无法提供",
    "暂无相关",
    "不在知识库",
    "未检索到",
    "未在片段中",
)


def is_refusal_answer(answer: str) -> bool:
  """判断模型回答是否属于明确拒答。"""
  text = (answer or "").strip()
  return any(kw in text for kw in REFUSAL_KEYWORDS)


def _offline_judge_mock(messages: list[dict[str, str]]) -> str:
  """无 API Key 时的确定性轻量裁判模拟，保证离线可复现评测闭环。"""
  payload = json.loads(messages[-1]["content"])
  answer = payload.get("answer", "")
  context = payload.get("contexts_text", "")

  if is_refusal_answer(answer):
    return json.dumps({"faithfulness": 1.0, "response_relevancy": 0.0})

  hallucination_markers = ("未经证实猜测", "免审批直批", "扣除部门绩效分")
  if any(m in answer and m not in context for m in hallucination_markers):
    return json.dumps({"faithfulness": 0.15, "response_relevancy": 0.65})

  return json.dumps({"faithfulness": 0.95, "response_relevancy": 0.92})


def judge_generation_item(question: str, contexts_text: str, answer: str) -> dict[str, float]:
  """调用轻量裁判模型评估单条有答案题的忠实度与答案相关性。"""
  messages = [
      {
          "role": "system",
          "content": (
              "你是严谨的 RAG 评测裁判。请根据给定的检索上下文与问题，对模型回答打分，"
              "仅输出 JSON：{\"faithfulness\": 0~1浮点, \"response_relevancy\": 0~1浮点}。"
          ),
      },
      {
          "role": "user",
          "content": json.dumps(
              {"question": question, "contexts_text": contexts_text, "answer": answer},
              ensure_ascii=False,
          ),
      },
  ]
  raw = chat_complete(messages, mock_fn=_offline_judge_mock, temperature=0.0, response_json=True)
  parsed = json.loads(raw)
  return {
      "faithfulness": float(parsed["faithfulness"]),
      "response_relevancy": float(parsed["response_relevancy"]),
  }


def compute_retrieval_metrics(
    items: list[dict[str, Any]],
    retrieved_key: str = "retrieved_chunks",
    k: int = 5,
) -> dict[str, Any]:
  """仅对库内有答案题（unanswerable == False）计算确定性 Recall@k 与 MRR。"""
  answerable = [item for item in items if not item.get("unanswerable", False)]
  if not answerable:
    return {"answerable_count": 0, "recall_at_5": 0.0, "mrr": 0.0}

  hits = 0
  rr_sum = 0.0
  for item in answerable:
    gold_id = item.get("gold_chunk_id")
    candidates = item.get(retrieved_key, [])[:k]
    if gold_id in candidates:
      hits += 1
      rank = candidates.index(gold_id) + 1
      rr_sum += 1.0 / rank

  total = len(answerable)
  return {
      "answerable_count": total,
      "recall_at_5": round(hits / total, 4),
      "mrr": round(rr_sum / total, 4),
  }


def evaluate_rag_run(
    items: list[dict[str, Any]],
    retrieved_key: str = "retrieved_chunks",
    answer_key: str = "model_answer",
) -> dict[str, Any]:
  """运行双层评测：拆出检索层、生成层（仅 25 道有答案题）与独立拒答准确率（5 道无答案题）。"""
  retrieval = compute_retrieval_metrics(items, retrieved_key=retrieved_key, k=5)

  faith_scores: list[float] = []
  rel_scores: list[float] = []
  unanswerable_count = 0
  correct_refusals = 0
  per_item: list[dict[str, Any]] = []

  for item in items:
    ans = item.get(answer_key, "")
    is_unanswerable = bool(item.get("unanswerable", False))
    refused = is_refusal_answer(ans)

    if is_unanswerable:
      unanswerable_count += 1
      passed = 1 if refused else 0
      correct_refusals += passed
      per_item.append({
          "id": item["id"],
          "unanswerable": True,
          "refused": refused,
          "faithfulness": None,
          "response_relevancy": None,
          "machine_pass": passed,
      })
    else:
      scores = judge_generation_item(item["question"], item.get("contexts_text", ""), ans)
      faith = scores["faithfulness"]
      rel = scores["response_relevancy"]
      faith_scores.append(faith)
      rel_scores.append(rel)
      passed = 1 if (faith >= 0.7 and rel >= 0.7 and not refused) else 0
      per_item.append({
          "id": item["id"],
          "unanswerable": False,
          "refused": refused,
          "faithfulness": faith,
          "response_relevancy": rel,
          "machine_pass": passed,
      })

  eval_count = len(faith_scores)
  return {
      "retrieval": retrieval,
      "generation": {
          "evaluated_count": eval_count,
          "faithfulness": round(sum(faith_scores) / eval_count, 4) if eval_count else 0.0,
          "response_relevancy": round(sum(rel_scores) / eval_count, 4) if eval_count else 0.0,
      },
      "refusal": {
          "unanswerable_count": unanswerable_count,
          "correct_refusals": correct_refusals,
          "refusal_accuracy": (
              round(correct_refusals / unanswerable_count, 4) if unanswerable_count else 0.0
          ),
      },
      "per_item": per_item,
  }


def calibrate_judge_alignment(
    per_item: list[dict[str, Any]],
    human_samples: list[dict[str, Any]],
) -> dict[str, Any]:
  """对齐 10 题人工抽检结果，计算机器裁判与人工核验的一致率及平均偏差。"""
  by_id = {entry["id"]: entry for entry in per_item}
  matched = 0
  agreements = 0
  bias_sum = 0.0
  discrepant_ids: list[str] = []

  for sample in human_samples:
    qid = sample["id"]
    if qid not in by_id:
      continue
    matched += 1
    machine_val = int(by_id[qid]["machine_pass"])
    human_val = int(sample["human_pass"])
    if machine_val == human_val:
      agreements += 1
    else:
      discrepant_ids.append(qid)
    bias_sum += machine_val - human_val

  if matched == 0:
    return {
        "sample_size": 0,
        "agreement_rate": 0.0,
        "mean_bias": 0.0,
        "discrepant_ids": [],
    }

  return {
      "sample_size": matched,
      "agreement_rate": round(agreements / matched, 4),
      "mean_bias": round(bias_sum / matched, 4),
      "discrepant_ids": discrepant_ids,
  }


def compare_configs(
    baseline_report: dict[str, Any],
    experiment_report: dict[str, Any],
) -> dict[str, Any]:
  """对比单变量修改前后的指标波动方向，输出回归预警。"""
  base_ret = baseline_report["retrieval"]
  exp_ret = experiment_report["retrieval"]
  base_gen = baseline_report["generation"]
  exp_gen = experiment_report["generation"]
  base_ref = baseline_report["refusal"]
  exp_ref = experiment_report["refusal"]

  recall_delta = round(exp_ret["recall_at_5"] - base_ret["recall_at_5"], 4)
  mrr_delta = round(exp_ret["mrr"] - base_ret["mrr"], 4)
  faith_delta = round(exp_gen["faithfulness"] - base_gen["faithfulness"], 4)
  rel_delta = round(exp_gen["response_relevancy"] - base_gen["response_relevancy"], 4)
  refusal_delta = round(
      (exp_ref["refusal_accuracy"] or 0.0) - (base_ref["refusal_accuracy"] or 0.0), 4
  )

  regression_detected = any(d < -0.02 for d in (recall_delta, mrr_delta, faith_delta, rel_delta))
  return {
      "recall_at_5_delta": recall_delta,
      "mrr_delta": mrr_delta,
      "faithfulness_delta": faith_delta,
      "response_relevancy_delta": rel_delta,
      "refusal_accuracy_delta": refusal_delta,
      "regression_detected": regression_detected,
  }


def save_baseline_snapshot(report: dict[str, Any], out_path: pathlib.Path) -> None:
  """将核心回归基线保存为 JSON 文件。"""
  snapshot = {
      "config": {"chunk_size": 500, "top_k": 5},
      "retrieval": report["retrieval"],
      "generation": report["generation"],
      "refusal": report["refusal"],
  }
  out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
