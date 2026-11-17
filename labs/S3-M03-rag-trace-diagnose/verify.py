#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def load_mod(path: pathlib.Path):
  spec = importlib.util.spec_from_file_location("lab_target", path)
  mod = importlib.util.module_from_spec(spec)
  assert spec and spec.loader
  spec.loader.exec_module(mod)
  return mod

def main() -> None:
  v = LabVerifier("S3-M03", "RAG 五层取证排障：Trace 归因与单变量修复")
  traces = json.loads((LAB_DIR / "fixtures" / "rag_traces.json").read_text(encoding="utf-8"))
  mod = load_mod(target_file(LAB_DIR, "starter.py", "solution.py"))

  preds = {t["trace_id"]: mod.diagnose_rag_trace(t) for t in traces}
  known = [t for t in traces if t["expected_layer"] != "NEED_GROUND_TRUTH"]
  exact_hits = sum(1 for t in known if preds[t["trace_id"]].get("root_layer") == t["expected_layer"])
  v.check(f"4 类典型故障（解析损坏 / 改写丢词 / 重排误杀 / 生成读歪）精准归因（命中 {exact_hits}/4）",
          exact_hits == 4,
          "按顺序逐层核验：indexed_chunks/chunk_corrupted -> rewritten_query/retrieved_top20 -> reranked_top5 -> answer。")

  missing_ok = preds["TR-105-MISSING"].get("root_layer") == "NEED_GROUND_TRUTH"
  v.check("缺失期望出处（gold_chunk_id=None）时主动索要真值，零臆测归因",
          missing_ok, "当 gold_chunk_id 为空时返回 NEED_GROUND_TRUTH 提示先补齐期望出处。")

  ev_ok = all(len(str(preds[t["trace_id"]].get("evidence", ""))) >= 12 for t in traces)
  v.check("每条归因结论均附带引用具体 Trace 字段的可核查证据说明",
          ev_ok, "在 evidence 字段写明命中的具体 chunk_id 或字段差异证据。")
  v.finish()


if __name__ == "__main__":
  main()
