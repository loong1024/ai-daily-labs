from __future__ import annotations
import math
import re


def tokenize_zh_code(text: str) -> list[str]:
  codes = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+|[A-Za-z0-9]{2,}", text.upper())
  zh_chars = re.findall(r"[\u4e00-\u9fff]", text)
  bigrams = [zh_chars[i] + zh_chars[i + 1] for i in range(len(zh_chars) - 1)]
  return codes + bigrams + zh_chars


def dense_rank(docs: list[dict], query_obj: dict) -> list[str]:
  same = [d["id"] for d in docs if d["sem_group"] == query_obj["sem_group"]]
  other = [d["id"] for d in docs if d["sem_group"] != query_obj["sem_group"]]
  return same + other


def bm25_rank(docs: list[dict], query: str) -> list[str]:
  q_toks = tokenize_zh_code(query)
  doc_toks = {d["id"]: tokenize_zh_code(d["text"]) for d in docs}
  n_docs = len(docs)
  avgdl = sum(len(t) for t in doc_toks.values()) / max(1, n_docs)

  scores: dict[str, float] = {}
  for d in docs:
    did = d["id"]
    toks = doc_toks[did]
    dl = len(toks)
    s = 0.0
    for qt in set(q_toks):
      df = sum(1 for tlist in doc_toks.values() if qt in tlist)
      if df == 0:
        continue
      idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
      tf = toks.count(qt)
      s += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * dl / avgdl))
    scores[did] = s
  return [d["id"] for d in sorted(docs, key=lambda x: scores[x["id"]], reverse=True)]


def rrf_hybrid_rerank(docs: list[dict], query_obj: dict, k: int = 60) -> list[str]:
  d_list = dense_rank(docs, query_obj)
  b_list = bm25_rank(docs, query_obj["q"])
  rrf: dict[str, float] = {d["id"]: 0.0 for d in docs}
  for r, did in enumerate(d_list, 1):
    rrf[did] += 1.0 / (k + r)
  for r, did in enumerate(b_list, 1):
    rrf[did] += 1.0 / (k + r)

  # 交叉精排（Cross-Encoder 特征模拟）：精确代号完全匹配 + 语义簇一致性联合打分
  exact_codes = re.findall(r"[A-Za-z0-9]+-[A-Za-z0-9-]+", query_obj["q"].upper())
  doc_map = {d["id"]: d for d in docs}
  for did in rrf:
    txt_up = doc_map[did]["text"].upper()
    if any(c in txt_up for c in exact_codes):
      rrf[did] += 0.05
    if doc_map[did]["sem_group"] == query_obj["sem_group"]:
      rrf[did] += 0.01
  return sorted(rrf.keys(), key=lambda x: rrf[x], reverse=True)
