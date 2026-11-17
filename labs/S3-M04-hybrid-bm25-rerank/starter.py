from __future__ import annotations


def dense_rank(docs: list[dict], query_obj: dict) -> list[str]:
  # 模拟纯稠密向量：能分清大类主题（sem_group），但对同主题内一字之差的报错码/近似型号（如 GX-904A vs GX-904B）区分度弱
  same = [d["id"] for d in docs if d["sem_group"] == query_obj["sem_group"]]
  other = [d["id"] for d in docs if d["sem_group"] != query_obj["sem_group"]]
  return same + other


def bm25_rank(docs: list[dict], query: str) -> list[str]:
  # TODO: 提取连字符错误码/型号（如 ERR-4091-LOCK、HX-920B、GX-904B）与中文双字词，计算 IDF 加权词频排序
  return [d["id"] for d in docs]


def rrf_hybrid_rerank(docs: list[dict], query_obj: dict, k: int = 60) -> list[str]:
  # 缺陷基线：仅返回纯向量排序，尚未融合 bm25_rank 倒数排名（RRF）与精确型号交叉精排加权
  return dense_rank(docs, query_obj)
