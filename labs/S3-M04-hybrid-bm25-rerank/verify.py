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


def mrr_at_k(rankings: list[list[str]], golds: list[str]) -> float:
  total = 0.0
  for rk, g in zip(rankings, golds):
    if g in rk:
      total += 1.0 / (rk.index(g) + 1)
  return total / max(1, len(golds))


def main() -> None:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S3-M04", "近似型号与报错码总漏召回？混合检索与中文重排实测")
  fx = json.loads((LAB_DIR / "fixtures" / "eval_corpus.json").read_text(encoding="utf-8"))
  mod = load_mod(target_file(LAB_DIR, "starter.py", "solution.py"))
  docs, qs = fx["docs"], fx["queries"]

  dense_res = [mod.dense_rank(docs, q) for q in qs]
  bm25_res = [mod.bm25_rank(docs, q["q"]) for q in qs]
  hyb_res = [mod.rrf_hybrid_rerank(docs, q) for q in qs]
  golds = [q["gold"] for q in qs]

  dense_mrr = mrr_at_k(dense_res, golds)
  hyb_mrr = mrr_at_k(hyb_res, golds)

  code_top1 = (bm25_res[0][0] == "D2") and (bm25_res[1][0] == "D4") and (bm25_res[2][0] == "D6")
  v.check(
      "中文+代号分词 BM25 精准咬死报错码（ERR-4091-LOCK）与近似型号（HX-920B / GX-904B）全部 Top-1 命中",
      code_top1,
      "在 bm25_rank() 中完整保留连字符型号/故障码 Token（防拆碎混淆 A/B 尾缀）并计算 IDF 加权词频。",
  )

  all_top1 = [r[0] for r in hyb_res] == golds
  v.check(
      f"BM25 + 稠密向量 RRF 融合精排在近似型号参数选型、故障码与口语同义问句上全部 Top-1 命中（MRR: {dense_mrr:.2f} -> {hyb_mrr:.2f}）",
      all_top1 and hyb_mrr > dense_mrr,
      "融合 dense_rank 与 bm25_rank 的倒数秩得分 1/(k+rank)，并对精确型号与语义簇一致项做重排加分。",
  )
  v.finish()


if __name__ == "__main__":
  main()
