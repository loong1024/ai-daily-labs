from __future__ import annotations
import hashlib
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
  conn.execute("CREATE TABLE docs (doc_id TEXT PRIMARY KEY, sha256 TEXT)")
  conn.execute("CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, text TEXT, vec TEXT)")
  return conn


def sync_notes(conn: sqlite3.Connection, current_files: dict[str, str]) -> dict[str, int]:
  # 缺陷基线：每次全量重算所有文件，且只追加 INSERT chunks 不删除已修改或已删除文件的旧切片！
  embedded_count = 0
  for doc_id, content in current_files.items():
    for para in [p.strip() for p in content.split("\n\n") if p.strip()]:
      vec = local_embed(para)
      conn.execute("INSERT INTO chunks(doc_id, text, vec) VALUES (?, ?, ?)", (doc_id, para, str(vec)))
    embedded_count += 1
  conn.commit()
  return {"embedded_docs": embedded_count, "deleted_docs": 0}


def search_top_k(conn: sqlite3.Connection, query: str, k: int = 5) -> list[dict]:
  import ast
  qv = local_embed(query)
  rows = conn.execute("SELECT doc_id, text, vec FROM chunks").fetchall()
  scored = []
  for doc_id, text, vec_str in rows:
    v = ast.literal_eval(vec_str)
    sim = sum(a * b for a, b in zip(qv, v))
    scored.append({"doc_id": doc_id, "text": text, "score": sim})
  scored.sort(key=lambda x: x["score"], reverse=True)
  return scored[:k]
