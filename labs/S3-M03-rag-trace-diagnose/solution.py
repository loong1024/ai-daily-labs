from __future__ import annotations


def diagnose_rag_trace(trace: dict) -> dict:
  tid = trace["trace_id"]
  gold = trace.get("gold_chunk_id")
  if not gold:
    return {
        "trace_id": tid,
        "root_layer": "NEED_GROUND_TRUTH",
        "evidence": "缺少 gold_chunk_id 期望出处真值，需先确认知识库源文档是否收录该信息，严禁盲猜。",
    }
  if gold not in set(trace.get("indexed_chunks", [])):
    return {"trace_id": tid, "root_layer": "INGESTION_MISSING", "evidence": f"{gold} 未进入索引库 indexed_chunks"}
  if trace.get("chunk_corrupted"):
    return {"trace_id": tid, "root_layer": "INGESTION_PARSE", "evidence": f"{gold} 虽已入库但双栏/表格解析损坏 chunk_corrupted=True"}
  if gold not in set(trace.get("retrieved_top20", [])):
    q_orig, q_rew = trace.get("question", ""), trace.get("rewritten_query", "")
    if "ERR_" in q_orig and "ERR_" not in q_rew:
      return {"trace_id": tid, "root_layer": "QUERY_REWRITE", "evidence": f"rewritten_query 丢失精确报错码：{q_orig} -> {q_rew}"}
    return {"trace_id": tid, "root_layer": "RETRIEVAL_RECALL", "evidence": f"{gold} 未进入 retrieved_top20"}
  if gold not in set(trace.get("reranked_top5", [])):
    return {"trace_id": tid, "root_layer": "RERANK_CUTOFF", "evidence": f"{gold} 在 retrieved_top20 命中但在 reranked_top5 被截断淘汰"}
  return {
      "trace_id": tid,
      "root_layer": "GENERATION_FAITHFULNESS",
      "evidence": f"{gold} 已进入 reranked_top5，但最终 answer 与原文上下文不一致",
  }
