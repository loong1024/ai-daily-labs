from __future__ import annotations


def diagnose_rag_trace(trace: dict) -> dict:
  # 缺陷基线：不看中间证据链，一律拍脑袋归咎于生成大模型不够强！
  return {
      "trace_id": trace["trace_id"],
      "root_layer": "GENERATION_FAITHFULNESS",
      "evidence": "猜测模型能力不足",
  }
