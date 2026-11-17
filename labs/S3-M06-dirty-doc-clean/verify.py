#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def main() -> int:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S3-M06", "脏文档别直接入库！5 份硬骨头样本入库前体检")

  fixture = json.loads(
      (LAB_DIR / "fixtures" / "dirty_docs_preview.json").read_text(encoding="utf-8")
  )
  docs = fixture["documents"]

  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  try:
    content = doc_path.read_text(encoding="utf-8")
  except Exception as exc:
    v.check("工作台文档读取", False, f"无法读取 {doc_path.name}：{exc}")
    return v.finish()

  # 验收 1：“解析 · 切分 · 元数据”三段自检清单与核心防坑规则完整性
  required_concepts = {
      "解析层阶段": ("解析",),
      "切分层阶段": ("切分",),
      "元数据阶段": ("元数据",),
      "双栏防串行": ("双栏",),
      "扫描件OCR与隔离": ("OCR", "隔离"),
      "页眉页脚剥离": ("页眉", "页脚"),
      "长表格保留表头": ("表头",),
      "禁止拦腰截断句子": ("截断",),
      "块首文档章节上下文": ("章节",),
      "生效年份与失效标记": ("年份", "失效"),
  }
  missing_concepts = [
      label
      for label, tokens in required_concepts.items()
      if not all(tok in content for tok in tokens)
  ]
  v.check(
      "“解析 · 切分 · 元数据”三段式入库前自检清单完整性",
      len(missing_concepts) == 0 and "TODO" not in content,
      f"当前缺失关键核验要素：{missing_concepts}（或仍残留未完成的 TODO 标记）。请补齐解析、切分、元数据三段清单。",
  )

  # 验收 2：5 份硬骨头样本全覆盖、新旧制度版本标签区分及污损扫描页隔离登记
  missing_docs = [
      d["doc_id"] for d in docs if d["doc_id"] not in content or d["filename"] not in content
  ]
  has_years = all(yr in content for yr in ("2026", "2025", "2022"))
  has_version_distinction = ("现行有效" in content) and (
      "已失效" in content or "已被替代" in content or "已废止" in content
  )
  has_scan_quarantine = ("DOC-03" in content) and ("隔离" in content) and ("第 4 页" in content or "第4页" in content)

  meta_ok = (
      len(missing_docs) == 0
      and has_years
      and has_version_distinction
      and has_scan_quarantine
  )
  v.check(
      "5 份样本元数据台账完整性（区分 2026 现行有效与 2022 已失效版本 + 污损页隔离）",
      meta_ok,
      f"缺失样本引用={missing_docs}，年份齐全={has_years}，新旧状态区分={has_version_distinction}，DOC-03 第4页隔离登记={has_scan_quarantine}。",
  )

  # 验收 3：15 个预览切片独立可读性、表格块保表头与原始脏片段拦截
  chunk_pattern = re.compile(
      r"\*\*CHUNK-(0[1-9]|1[0-5])\*\*[：:]\s*(.+?)(?=\n-\s*\*\*CHUNK-|\n###\s|\Z)",
      re.DOTALL,
  )
  found_chunks = {m.group(1): m.group(2).strip() for m in chunk_pattern.finditer(content)}

  all_forbidden = [
      frag for d in docs for frag in d.get("forbidden_dirty_fragments", [])
  ]
  leaked_dirty = [
      frag
      for frag in all_forbidden
      if any(frag in body for body in found_chunks.values())
  ]

  breadcrumb_ok = len(found_chunks) == 15 and all(
      ("[" in body and ">" in body and "]" in body and len(body) >= 45)
      for body in found_chunks.values()
  )
  table_chunks_ok = all(
      idx in found_chunks
      and "职级" in found_chunks[idx]
      and ("旺季上限" in found_chunks[idx] or "淡季上限" in found_chunks[idx])
      for idx in ("04", "05", "06")
  )

  chunks_pass = (
      len(found_chunks) == 15
      and breadcrumb_ok
      and table_chunks_ok
      and len(leaked_dirty) == 0
  )
  v.check(
      "15 个修复后黄金切片抽检（带 [文档名 > 章节] 上下文、表格块保表头、零脏残片泄漏）",
      chunks_pass,
      f"已识别有效切片数={len(found_chunks)}/15，块首面包屑完整={breadcrumb_ok}，DOC-02 表格块保表头={table_chunks_ok}，残留未清洗脏串={leaked_dirty}。",
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
