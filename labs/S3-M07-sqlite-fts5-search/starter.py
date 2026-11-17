"""S3-M07 不装 ES 补齐关键词检索：单文件 SQLite FTS5（Starter 待修复版）。

当前存在 3 处典型缺陷：
1. search_keywords 中误把 FTS5 内置 bm25(chunks_fts) 当成正数按 DESC 降序排，导致相关性越高的排越后；
2. 未处理 trigram 分词器的“>=3 字符”门槛，查询“超时”“权限”“死锁”等 2 字中文短词直接返回 0 条；
3. rrf_fusion 未做双路倒数排名累加，仅原样截取了纯向量候选，导致精确报错码与专有型号排不进前 3 名。
"""

from __future__ import annotations

import sqlite3
from typing import Any


def build_fts_index(conn: sqlite3.Connection, chunks: list[dict[str, Any]]) -> None:
  """在单文件/内存 SQLite 中创建元数据表与 FTS5 trigram 全文虚拟表。"""
  conn.executescript(
      """
      DROP TABLE IF EXISTS chunks_meta;
      DROP TABLE IF EXISTS chunks_fts;
      CREATE TABLE chunks_meta (
        rowid INTEGER PRIMARY KEY,
        chunk_id TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        body TEXT NOT NULL
      );
      CREATE VIRTUAL TABLE chunks_fts USING fts5(
        title,
        body,
        tokenize='trigram'
      );
      """
  )
  for idx, item in enumerate(chunks, start=1):
    conn.execute(
        "INSERT INTO chunks_meta(rowid, chunk_id, title, body) VALUES (?, ?, ?, ?)",
        (idx, item["chunk_id"], item["title"], item["body"]),
    )
    conn.execute(
        "INSERT INTO chunks_fts(rowid, title, body) VALUES (?, ?, ?)",
        (idx, item["title"], item["body"]),
    )
  conn.commit()


def _quote_fts_phrase(term: str) -> str:
  """用双引号包裹查询短语，避免连字符 - 等字符触发 FTS5 语法错误。"""
  return '"' + term.replace('"', '""') + '"'


def search_keywords(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 20,
) -> list[dict[str, Any]]:
  """执行 SQLite FTS5 关键词检索（待修复 bm25 排序方向与 <3 字符短词兜底）。"""
  clean_q = (query or "").strip()
  if not clean_q:
    return []

  id_map = {
      row[0]: row[1]
      for row in conn.execute("SELECT rowid, chunk_id FROM chunks_meta").fetchall()
  }

  # TODO(缺陷 1 & 2)：
  # 1) bm25(chunks_fts) 返回负值（越小越相关），此处误用了 DESC 降序！
  # 2) 当 clean_q 长度 < 3（如中文双字词“超时”“权限”）时，trigram 会返回 0 条，需补充 LIKE 兜底！
  rows = conn.execute(
      """
      SELECT rowid, title, bm25(chunks_fts) AS bm25_score
      FROM chunks_fts
      WHERE chunks_fts MATCH ?
      ORDER BY bm25(chunks_fts) DESC
      LIMIT ?
      """,
      (_quote_fts_phrase(clean_q), top_k),
  ).fetchall()

  return [
      {
          "chunk_id": id_map[rowid],
          "title": title,
          "score": float(bm25_score),
          "source": "fts5",
      }
      for rowid, title, bm25_score in rows
  ]


def rrf_fusion(
    keyword_ids: list[str],
    vector_ids: list[str],
    k: int = 60,
    top_k: int = 10,
) -> list[tuple[str, float]]:
  """使用倒数排名融合（RRF）合并关键词路与向量路前 20 名结果。"""
  # TODO(缺陷 3)：请按 1-based 排名累加 score += 1.0 / (k + rank) 并降序排列
  _ = (keyword_ids, k)
  return [(cid, 0.0) for cid in vector_ids[:top_k]]


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    vector_top20: list[str],
    top_k: int = 10,
) -> list[str]:
  """组合 SQLite 关键词召回与向量召回，返回融合后的 chunk_id 列表。"""
  kw_hits = search_keywords(conn, query, top_k=20)
  kw_ids = [item["chunk_id"] for item in kw_hits]
  fused = rrf_fusion(kw_ids, vector_top20[:20], k=60, top_k=top_k)
  return [cid for cid, _ in fused]
