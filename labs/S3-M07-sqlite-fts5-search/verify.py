#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def _load_target_module():
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  spec = importlib.util.spec_from_file_location("s3_m07_target", mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块: {mod_path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def main() -> int:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S3-M07", "不装 ES 补齐关键词检索：单文件 SQLite FTS5")

  chunks = json.loads((LAB_DIR / "fixtures" / "kb_chunks.json").read_text(encoding="utf-8"))
  eval_queries = json.loads(
      (LAB_DIR / "fixtures" / "eval_queries.json").read_text(encoding="utf-8")
  )

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块加载与语法检查", False, f"导入模块失败：{exc}")
    return v.finish()

  with tempfile.TemporaryDirectory() as tmp_dir:
    db_file = pathlib.Path(tmp_dir) / "single_file_kb.sqlite3"
    conn = sqlite3.connect(str(db_file))

    # 验收 1：单文件 SQLite FTS5 trigram 建表与 bm25() 负值升序排列
    try:
      mod.build_fts_index(conn, chunks)
      ddl_row = conn.execute(
          "SELECT sql FROM sqlite_master WHERE name='chunks_fts'"
      ).fetchone()
      ddl_sql = (ddl_row[0] if ddl_row else "").lower()

      bm25_hits = mod.search_keywords(conn, "分布式锁续期", top_k=10)
      hit_ids = [h["chunk_id"] for h in bm25_hits]
      scores = [float(h["score"]) for h in bm25_hits]

      bm25_ok = (
          "fts5" in ddl_sql
          and "trigram" in ddl_sql
          and "C08" in hit_ids
          and "C19" in hit_ids
          and hit_ids.index("C08") < hit_ids.index("C19")
          and scores[0] < 0
          and scores == sorted(scores)
      )
      bm25_err = f"当前“分布式锁续期”命中顺序={hit_ids}，bm25分数={scores}。"
    except Exception as exc:
      bm25_ok = False
      bm25_err = f"运行异常：{exc}。"

    v.check(
        "单文件 SQLite FTS5 trigram 建表与 bm25() 升序排列（C08 排在 C19 之前）",
        bm25_ok,
        f"{bm25_err}注意 SQLite FTS5 的 bm25(chunks_fts) 返回负值，越小越相关，SQL 必须使用 ORDER BY bm25(chunks_fts) ASC。",
    )

    # 验收 2：>=3 字符报错码/型号精准召回 + 2 字中文短词兜底零空结果
    try:
      miss_cases: list[str] = []
      for item in eval_queries:
        hits = mod.search_keywords(conn, item["query"], top_k=10)
        got_ids = [h["chunk_id"] for h in hits]
        if not any(exp_id in got_ids for exp_id in item["expected_ids"]):
          miss_cases.append(f"{item['query']}(返回:{got_ids[:3]})")
      short_ok = len(miss_cases) == 0
      short_err = f"未命中的查询={miss_cases}。"
    except Exception as exc:
      short_ok = False
      short_err = f"运行异常：{exc}。"

    v.check(
        "精确报错码与 2 字中文短词全召回（消除 trigram 双字词 0 命中陷阱）",
        short_ok,
        f"{short_err}trigram 分词器对长度 <3 字符的查询词（如“超时”“权限”“死锁”）会返回 0 条，请增加参数化 LIKE '%词%' 兜底。",
    )

    # 验收 3：15 行 RRF（k=60）融合排序，使报错码与专有型号全部稳定进入 Top 3
    try:
      unit_fused = mod.rrf_fusion(["A", "B"], ["C", "A"], k=60, top_k=3)
      unit_dict = dict(unit_fused)
      formula_ok = (
          len(unit_fused) >= 2
          and unit_fused[0][0] == "A"
          and abs(unit_dict.get("A", 0.0) - (1.0 / 61 + 1.0 / 62)) < 1e-6
      )

      out_of_top3: list[str] = []
      for item in eval_queries:
        top3 = mod.hybrid_search(conn, item["query"], item["vector_top20"], top_k=3)
        if not any(exp_id in top3 for exp_id in item["expected_ids"]):
          out_of_top3.append(f"{item['query']}->Top3={top3}")

      rrf_ok = formula_ok and len(out_of_top3) == 0
      rrf_err = f"RRF 公式校验={formula_ok}，未进前 3 名的查询={out_of_top3}。"
    except Exception as exc:
      rrf_ok = False
      rrf_err = f"运行异常：{exc}。"

    v.check(
        "15 行 RRF（k=60）双路融合排序（精确报错码、专有型号与双字短词全部进入前 3 名）",
        rrf_ok,
        f"{rrf_err}请在 rrf_fusion 中按 1-based 排名对关键词路与向量路累加 1.0 / (60 + rank) 并按总分降序返回。",
    )

    conn.close()

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
