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
  v = LabVerifier("S3-M01", "本地笔记增量索引：哈希同步防旧块残留")
  fx = json.loads((LAB_DIR / "fixtures" / "notes_state.json").read_text(encoding="utf-8"))
  mod = load_mod(target_file(LAB_DIR, "starter.py", "solution.py"))

  conn = mod.init_db()
  stat1 = mod.sync_notes(conn, fx["v1_files"])
  stat2 = mod.sync_notes(conn, fx["v2_files"])

  inc_ok = (stat1.get("embedded_docs") == 3) and (stat2.get("embedded_docs") == 1) and (stat2.get("deleted_docs") == 1)
  v.check(f"SHA-256 增量同步精准跳过未改动笔记（二次同步重算={stat2.get('embedded_docs')}篇，清理删除={stat2.get('deleted_docs')}篇）",
          inc_ok, "在 sync_notes() 中比对 docs 表 sha256，未变动文件直接跳过，已删文件清理 docs 与 chunks。")

  hits_price = mod.search_top_k(conn, fx["queries"][0]["q"], k=5)
  joined_price = " ".join(h["text"] for h in hits_price)
  no_stale_price = ("149 元/月" in joined_price) and ("99 元/月" not in joined_price)
  v.check("修改笔记后旧版切片零残留（检索结果含新价 149 元/月 且不含作废旧价 99 元/月）",
          no_stale_price, "重算变动文件前必须先执行 DELETE FROM chunks WHERE doc_id = ? 原子清除旧切片。")

  hits_del = mod.search_top_k(conn, fx["queries"][1]["q"], k=5)
  joined_del = " ".join(h["text"] for h in hits_del)
  no_deleted = "10.0.0.1" not in joined_del
  v.check("已删除笔记（legacy_vpn.md）切片从索引中彻底级联清除",
          no_deleted, "对比数据库已有 doc_id 与当前文件集差集，删除已移除文档的全部切片。")
  v.finish()


if __name__ == "__main__":
  main()
