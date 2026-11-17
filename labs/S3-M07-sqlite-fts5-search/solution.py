"""S3-M07 不装 ES 补齐关键词检索：单文件 SQLite FTS5（Solution 标准参考实现）。"""

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
  """用双引号包裹查询短语，避免连字符 - 等特殊符号触发 FTS5 语法错误。"""
  return '"' + term.replace('"', '""') + '"'


def search_keywords(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 20,
) -> list[dict[str, Any]]:
  """执行 SQLite FTS5 关键词检索：支持 >=3 字符 bm25 升序排序与 <3 字符中文短词 LIKE 兜底。"""
  clean_q = (query or "").strip()
  if not clean_q:
    return []

  terms = [t for t in clean_q.split() if t]
  long_terms = [t for t in terms if len(t) >= 3]
  short_terms = [t for t in terms if len(t) < 3]

  id_map = {
      row[0]: row[1]
      for row in conn.execute("SELECT rowid, chunk_id FROM chunks_meta").fetchall()
  }

  results: list[dict[str, Any]] = []
  seen_ids: set[str] = set()

  if long_terms:
    fts_expr = " OR ".join(_quote_fts_phrase(t) for t in long_terms)
    rows = conn.execute(
        """
        SELECT rowid, title, bm25(chunks_fts) AS bm25_score
        FROM chunks_fts
        WHERE chunks_fts MATCH ?
        ORDER BY bm25(chunks_fts) ASC
        LIMIT ?
        """,
        (fts_expr, top_k),
    ).fetchall()
    for rowid, title, bm25_score in rows:
      cid = id_map[rowid]
      seen_ids.add(cid)
      results.append({
          "chunk_id": cid,
          "title": title,
          "score": float(bm25_score),
          "source": "fts5",
      })

  # 对 <3 字符的中文双字词/单字词（或 FTS 未命中的短查询）执行 LIKE 兜底，标题命中优先
  if short_terms or not results:
    fallback_terms = short_terms if short_terms else terms
    for term in fallback_terms:
      if len(results) >= top_k:
        break
      pattern = f"%{term}%"
      like_rows = conn.execute(
          """
          SELECT chunk_id, title
          FROM chunks_meta
          WHERE title LIKE ? OR body LIKE ?
          ORDER BY CASE WHEN title LIKE ? THEN 0 ELSE 1 END, length(body) ASC, rowid ASC
          LIMIT ?
          """,
          (pattern, pattern, pattern, top_k),
      ).fetchall()
      for cid, title in like_rows:
        if cid not in seen_ids and len(results) < top_k:
          seen_ids.add(cid)
          results.append({
              "chunk_id": cid,
              "title": title,
              "score": -0.5,
              "source": "like_fallback",
          })

  return results


def rrf_fusion(
    keyword_ids: list[str],
    vector_ids: list[str],
    k: int = 60,
    top_k: int = 10,
) -> list[tuple[str, float]]:
  """15 行 RRF 混合排序：按 score += 1 / (k + rank) 合并关键词与向量双路排名。"""
  scores: dict[str, float] = {}
  first_seen: dict[str, int] = {}
  order = 0
  for ranked_list in (keyword_ids, vector_ids):
    for rank, cid in enumerate(ranked_list, start=1):
      scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
      if cid not in first_seen:
        first_seen[cid] = order
        order += 1
  ranked = sorted(scores.items(), key=lambda x: (-x[1], first_seen[x[0]]))
  return ranked[:top_k]


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
