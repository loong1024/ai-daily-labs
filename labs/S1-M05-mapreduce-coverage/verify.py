#!/usr/bin/env python3
"""S1-M05 验收脚本：校验长文档分块便利贴提示词模板、[C01]-[C12] 覆盖率核对表、5 大靶子溯源与冲突保留。"""

from __future__ import annotations

import json
import pathlib
import re
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def main() -> None:
  v = LabVerifier("S1-M05", "长文档分块便利贴抽取与块覆盖率核对实战")
  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  fixture_meta = json.loads(
      (LAB_DIR / "fixtures" / "golden_targets_and_oneshot_baseline.json").read_text(encoding="utf-8")
  )

  try:
    text = doc_path.read_text(encoding="utf-8")
  except Exception as exc:
    v.check("目标方案文件可正常读取", False, f"无法读取 {doc_path.name}：{exc}")
    v.finish()
    return

  has_map_stage = ("Map" in text or "贴便利贴" in text) and (
      "无相关内容" in text or "空块" in text
  )
  has_reduce_stage = ("Reduce" in text or "主题归并" in text) and any(
      kw in text for kw in ("严禁擅自", "并列展示", "并列保留")
  )
  v.check(
      "具备 Map 逐块抽取与 Reduce 保冲突归并两阶段结构化提示词模板",
      has_map_stage and has_reduce_stage,
      "请在方案中补充阶段一 Map 提示词（含固定表头与空块标注“无相关内容”规则）及阶段二 Reduce 提示词（强制附 [Cxx] 编号并禁止擅自抹平跨章节矛盾）。",
  )

  all_chunks: list[str] = fixture_meta["all_chunks"]
  empty_chunks: list[str] = fixture_meta["empty_chunks"]
  missing_chunks = [cid for cid in all_chunks if f"[{cid}]" not in text]

  lines = text.splitlines()
  empty_audited_ok = True
  for ec in empty_chunks:
    ec_lines = [ln for ln in lines if ec in ln]
    if not any(
        any(marker in ln for marker in ("无相关内容", "无实质业务", "空块"))
        for ln in ec_lines
    ):
      empty_audited_ok = False

  v.check(
      f"[C01]–[C12] 全量块覆盖率核对闭环（缺失块 {len(missing_chunks)} 个，C04/C08 空块显式审计={empty_audited_ok}）",
      len(missing_chunks) == 0 and empty_audited_ok,
      f"请补齐覆盖率核对表，确保 [C01]–[C12] 全部登记（当前缺失：{missing_chunks or '无'}），且 [C04]、[C08] 明确标记为“无相关内容”。",
  )

  missed_targets: list[str] = []
  for tgt in fixture_meta["golden_targets"]:
    cid = tgt["chunk_id"]
    kws: list[str] = tgt["required_keywords"]
    matching_blocks = [
        para
        for para in re.split(r"\n\s*\n|\n(?=- |\* |\d+\.)", text)
        if f"[{cid}]" in para and all(k in para for k in kws)
    ]
    if not matching_blocks:
      missed_targets.append(f"{tgt['target_id']}([{cid}] 需含 {', '.join(kws)})")

  conflict = fixture_meta["conflict_pair"]
  conflict_preserved = any(
      conflict["sales_figure"] in sec
      and conflict["supply_figure"] in sec
      and f"[{conflict['sales_chunk']}]" in sec
      and f"[{conflict['supply_chunk']}]" in sec
      for sec in text.split("\n## ")
  )
  v.check(
      f"5 大黄金靶子精确溯源命中且跨章节产能冲突并列保留（未命中靶子：{len(missed_targets)} 个）",
      len(missed_targets) == 0 and conflict_preserved,
      f"请在最终笔记中补齐未命中或漏标出处的靶子 {missed_targets}，并在同一冲突小节并列展示 [C03] 6.5 万台与 [C07] 4.8 万台（缺口 1.7 万台）。",
  )

  comparison_sections = [
      sec
      for sec in text.split("\n## ")
      if ("一次性总结" in sec and ("盲区" in sec or "对比" in sec))
  ]
  has_blindspot_audit = bool(comparison_sections) and all(
      tag in comparison_sections[-1] for tag in ("[C09]", "[C10]", "[C12]")
  )
  v.check(
      "产出“分块归并 vs 一次性总结”盲区对比清单（明确指出 C09/C10/C12 后半段漏项）",
      has_blindspot_audit,
      "请新增“分块归并 vs 一次性总结”对比章节，逐条列出一次性总结遗漏的后半段关键块（[C09] 违约金、[C10] 140 欧元保税仓附加费、[C12] 双签死线）。",
  )

  v.finish()


if __name__ == "__main__":
  main()
