"""S3-M05 拒绝凭感觉调参：建 30 题双层回归评测基线（Starter 待修复版）。

当前存在 4 处典型工程缺陷，请结合 README.md 与 verify.py 提示逐步完善：
1. compute_retrieval_metrics 把 5 道无答案拒答题混入了检索分母，且只检查了 Top-1 而未算 Recall@5 与 MRR；
2. evaluate_rag_run 未剥离无答案题，导致拒答回答被算进 response_relevancy 拉低均值，且未统计 refusal_accuracy；
3. calibrate_judge_alignment 尚未实现 10 题人工抽检对齐与偏差统计；
4. compare_configs 尚未实现单变量修改前后的指标波动对比。
"""

from __future__ import annotations

import json
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
  """无 API Key 时的确定性轻量裁判模拟，保证离线 30 秒可复现评测闭环。"""
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
  """计算确定性检索层指标（Recall@k 与 MRR）。"""
  # TODO(缺陷 1)：当前直接用全部 30 题做分母，且只判断了第 1 名是否命中，漏算前 k 召回与 MRR 倒数排名！
  if not items:
    return {"answerable_count": 0, "recall_at_5": 0.0, "mrr": 0.0}

  top1_hits = 0
  for item in items:
    retrieved = item.get(retrieved_key, [])[:k]
    if retrieved and retrieved[0] == item.get("gold_chunk_id"):
      top1_hits += 1

  naive_score = round(top1_hits / len(items), 4)
  return {
      "answerable_count": len(items),
      "recall_at_5": naive_score,
      "mrr": naive_score,
  }


def evaluate_rag_run(
    items: list[dict[str, Any]],
    retrieved_key: str = "retrieved_chunks",
    answer_key: str = "model_answer",
) -> dict[str, Any]:
  """运行双层评测：拆出检索层、生成层（仅 25 道有答案题）与独立拒答准确率（5 道无答案题）。"""
  retrieval = compute_retrieval_metrics(items, retrieved_key=retrieved_key, k=5)

  # TODO(缺陷 2)：把无答案拒答题也混进生成指标求平均，且未独立计算 5 道拒答题的 refusal_accuracy！
  faith_scores: list[float] = []
  rel_scores: list[float] = []
  per_item: list[dict[str, Any]] = []

  for item in items:
    ans = item.get(answer_key, "")
    scores = judge_generation_item(item["question"], item.get("contexts_text", ""), ans)
    faith_scores.append(scores["faithfulness"])
    rel_scores.append(scores["response_relevancy"])
    per_item.append({
        "id": item["id"],
        "unanswerable": bool(item.get("unanswerable", False)),
        "faithfulness": scores["faithfulness"],
        "response_relevancy": scores["response_relevancy"],
        "machine_pass": 1 if scores["faithfulness"] >= 0.7 else 0,
    })

  return {
      "retrieval": retrieval,
      "generation": {
          "evaluated_count": len(items),
          "faithfulness": round(sum(faith_scores) / len(faith_scores), 4),
          "response_relevancy": round(sum(rel_scores) / len(rel_scores), 4),
      },
      "refusal": {
          "unanswerable_count": 0,
          "correct_refusals": 0,
          "refusal_accuracy": None,
      },
      "per_item": per_item,
  }


def calibrate_judge_alignment(
    per_item: list[dict[str, Any]],
    human_samples: list[dict[str, Any]],
) -> dict[str, Any]:
  """对齐 10 题人工抽检结果，统计自动裁判与人工标准的一致率及偏差。"""
  # TODO(缺陷 3)：请按题目 id 对齐 per_item["machine_pass"] 与 human_samples["human_pass"]
  return {
      "sample_size": 0,
      "agreement_rate": 0.0,
      "mean_bias": 0.0,
      "discrepant_ids": [],
  }


def compare_configs(
    baseline_report: dict[str, Any],
    experiment_report: dict[str, Any],
) -> dict[str, Any]:
  """对比参数修改前后的双层指标变化，识别是否发生回归退步。"""
  # TODO(缺陷 4)：计算 recall_at_5_delta、mrr_delta、faithfulness_delta 与 regression_detected
  return {}
