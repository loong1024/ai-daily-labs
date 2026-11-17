from __future__ import annotations
import ast
import hashlib
import json
import math
import re
import sqlite3


def local_embed(text: str) -> list[float]:
  buckets = [0.0] * 16
  for tok in re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text.lower()):
    h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
    buckets[h % 16] += 1.0
  norm = math.sqrt(sum(x * x for x in buckets)) or 1.0
  return [x / norm for x in buckets]


def init_db() -> sqlite3.Connection:
  conn = sqlite3.connect(":memory:")
  conn.execute("CREATE TABLE docs (doc_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
  conn.execute("CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, text TEXT NOT NULL, vec TEXT NOT NULL)")
  return conn


def sync_notes(conn: sqlite3.Connection, current_files: dict[str, str]) -> dict[str, int]:
  existing = dict(conn.execute("SELECT doc_id, sha256 FROM docs").fetchall())
  embedded_docs = 0
  deleted_docs = 0

  with conn:
    # 1. 清理磁盘已删除笔记及其关联切片
    for old_id in set(existing.keys()) - set(current_files.keys()):
      conn.execute("DELETE FROM chunks WHERE doc_id = ?", (old_id,))
      conn.execute("DELETE FROM docs WHERE doc_id = ?", (old_id,))
      deleted_docs += 1

    # 2. 按 SHA-256 指纹仅对新增或改动的笔记做原子级先删后插
    for doc_id, content in current_files.items():
      digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
      if existing.get(doc_id) == digest:
        continue
      conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
      for para in [p.strip() for p in content.split("\n\n") if p.strip()]:
        vec = json.dumps(local_embed(para))
        conn.execute("INSERT INTO chunks(doc_id, text, vec) VALUES (?, ?, ?)", (doc_id, para, vec))
      conn.execute("INSERT OR REPLACE INTO docs(doc_id, sha256) VALUES (?, ?)", (doc_id, digest))
      embedded_docs += 1

  return {"embedded_docs": embedded_docs, "deleted_docs": deleted_docs}


def search_top_k(conn: sqlite3.Connection, query: str, k: int = 5) -> list[dict]:
  qv = local_embed(query)
  rows = conn.execute("SELECT doc_id, text, vec FROM chunks").fetchall()
  scored = []
  for doc_id, text, vec_str in rows:
    v = json.loads(vec_str) if vec_str.startswith("[") else ast.literal_eval(vec_str)
    sim = sum(a * b for a, b in zip(qv, v))
    scored.append({"doc_id": doc_id, "text": text, "score": sim})
  scored.sort(key=lambda x: x["score"], reverse=True)
  return scored[:k]
