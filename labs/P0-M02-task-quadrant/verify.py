#!/usr/bin/env python3
"""P0-M02 自动化验收脚本：验证子任务拆解四象限提示词、诊断表颗粒度、人机红线与脱敏试跑结果。"""

from __future__ import annotations

import json
import pathlib
import re
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: F401


def _strip_html_comments(text: str) -> str:
  return re.sub(r"<!--[\s\S]*?-->", "", text)


def _split_h2_sections(md_text: str) -> list[str]:
  clean = _strip_html_comments(md_text)
  parts = re.split(r"(?m)^##\s+", clean)
  return parts[1:] if len(parts) > 1 else [clean]


def _extract_markdown_tables(md_text: str) -> list[list[list[str]]]:
  tables: list[list[list[str]]] = []
  current: list[list[str]] = []
  in_code = False
  for raw_line in _strip_html_comments(md_text).splitlines():
    line = raw_line.strip()
    if line.startswith("```"):
      in_code = not in_code
      continue
    if in_code:
      continue
    if line.startswith("|") and line.endswith("|") and line.count("|") >= 3:
      cells = [c.strip() for c in line.strip("|").split("|")]
      if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c != ""):
        continue
      current.append(cells)
    else:
      if len(current) >= 2:
        tables.append(current)
      current = []
  if len(current) >= 2:
    tables.append(current)
  return tables


def main() -> None:
  v = LabVerifier("P0-M02", "任务拆解四象限：揪出个人前 3 个高收益 AI 提效点")

  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  worklog_path = LAB_DIR / "fixtures" / "role_worklog_samples.json"
  feedback_path = LAB_DIR / "fixtures" / "raw_customer_feedback.md"

  try:
    raw_doc = doc_path.read_text(encoding="utf-8")
    doc = _strip_html_comments(raw_doc)
    worklog_fixture = json.loads(worklog_path.read_text(encoding="utf-8"))
    feedback_raw = feedback_path.read_text(encoding="utf-8")
    sections = _split_h2_sections(raw_doc)
    sec1 = sections[0] if len(sections) >= 1 else doc
    sec2 = sections[1] if len(sections) >= 2 else doc
    sec3 = sections[2] if len(sections) >= 3 else doc
    sec4 = sections[3] if len(sections) >= 4 else doc
  except Exception as exc:
    v.check("实验文档与测试语料读取", False, f"读取 {doc_path.name} 或 fixtures 失败：{exc}")
    v.finish()
    return

  quadrants = ("高收益速赢区", "人机共创区", "顺手优化区", "人工保留区")

  # 指标 1：结构化盘点提示词完备性
  try:
    quantified_tasks = re.findall(
        r"(?m)^\s*\d+[\.、]\s*.+?(?:\d+(?:\.\d+)?)\s*(?:小时|分钟|h|min)",
        sec1,
    )
    has_dimensions = ("可行度" in sec1 or "可行性" in sec1) and ("时间节省" in sec1 or "收益" in sec1)
    has_quadrant_rules = all(q in sec1 for q in quadrants)
    has_atomic_hint = "子任务" in sec1 and sum(
        1 for kw in ("信息搜集", "初稿起草", "格式清洗", "人际沟通", "最终拍板") if kw in sec1
    ) >= 3
    no_unfilled = "【请填写" not in sec1
    v.check(
        "结构化盘点提示词完备性（岗位 + 至少 6 项量化耗时事务 + 三步四象限规则）",
        len(quantified_tasks) >= 6 and has_dimensions and has_quadrant_rules and has_atomic_hint and no_unfilled,
        f"第 1 节当前仅识别到 {len(quantified_tasks)} 项带耗时的编号日常事务（需 >=6 项，标明小时/分钟），并请补齐原子子任务分类、可行度×时间收益两维四象限与前 3 突破口指令。",
    )
  except Exception as exc:
    v.check("结构化盘点提示词完备性（岗位 + 至少 6 项量化耗时事务 + 三步四象限规则）", False, f"校验异常：{exc}")

  # 指标 2：四象限 Markdown 诊断表颗粒度与覆盖度
  diag_rows: list[list[str]] = []
  try:
    sec2_tables = _extract_markdown_tables(sec2)
    if sec2_tables:
      diag_table = max(sec2_tables, key=len)
      diag_rows = diag_table[1:]
    joined_diag = "\n".join(" | ".join(r) for r in diag_rows)
    quadrants_covered = all(q in joined_diag for q in quadrants)
    well_formed_rows = len(diag_rows) >= 6 and all(len(r) >= 5 and len(r[-1]) >= 8 for r in diag_rows)
    v.check(
        "原子子任务四象限诊断表（>= 6 个拆细子任务 + 四象限全覆盖 + 归类依据）",
        well_formed_rows and quadrants_covered,
        f"第 2 节诊断表当前有效子任务行数为 {len(diag_rows)}（需 >=6 行且不少于 5 列），须完整覆盖高收益速赢区、人机共创区、顺手优化区、人工保留区并写明归类依据。",
    )
  except Exception as exc:
    v.check("原子子任务四象限诊断表（>= 6 个拆细子任务 + 四象限全覆盖 + 归类依据）", False, f"解析表格异常：{exc}")

  # 指标 3：人机权责红线拦截（高责签字审批与敏感争议谈判不得交 AI 自动拍板）
  try:
    redline_kws = worklog_fixture["human_only_redlines"]["keywords"]
    redline_rows = [r for r in diag_rows if any(kw in " ".join(r) for kw in redline_kws)]
    redline_safe = (
        len(redline_rows) >= 2
        and all("人工保留区" in " ".join(r) for r in redline_rows)
        and all("AI 全自动" not in " ".join(r) for r in diag_rows)
    )
    v.check(
        "人机职责红线防越权（合同签字审批与退款争议协商严格归入「人工保留区」）",
        redline_safe,
        "请在诊断表中拆出合同签字审批、大客户退款争议当面协商等高担责子任务（至少 2 项），严格归入 `人工保留区`，严禁标记为 `AI 全自动完成`。",
    )
  except Exception as exc:
    v.check("人机职责红线防越权（合同签字审批与退款争议协商严格归入「人工保留区」）", False, f"红线检查异常：{exc}")

  # 指标 4：前 3 高收益突破口行动卡
  try:
    card_headings = re.findall(r"(?m)^###\s+\S+", sec3)
    prompt_count = len(re.findall(r"提问句式", sec3))
    review_count = len(re.findall(r"人工(?:把关|复核)重点", sec3))
    no_lazy_skip = "不用人工复核" not in sec3
    v.check(
        "前 3 高收益突破口行动卡（锁定 Top 3 子任务 + 可复制提问句式 + 人工把关重点）",
        len(card_headings) >= 3 and prompt_count >= 3 and review_count >= 3 and no_lazy_skip,
        "请在第 3 节用 `### ` 小标题列出前 3 个高收益突破口，每张行动卡均须包含 `可直接复制提问句式` 与 `人工把关重点`（各不少于 3 处）。",
    )
  except Exception as exc:
    v.check("前 3 高收益突破口行动卡（锁定 Top 3 子任务 + 可复制提问句式 + 人工把关重点）", False, f"行动卡检查异常：{exc}")

  # 指标 5：排名第 1 子任务基于脱敏语料当场试跑
  try:
    fixture_ids = sorted(set(re.findall(r"FB-\d{2}", feedback_raw)))
    cited_ids = {fid for fid in fixture_ids if fid in sec4}
    no_todo = "TODO" not in sec4 and "待试跑" not in sec4
    flags_high_risk = "FB-06" in sec4 and ("人工核实" in sec4 or "人工复核" in sec4 or "人工保留区" in sec4)
    v.check(
        "排名第 1 子任务真实语料试跑闭环（关联 fixtures/raw_customer_feedback.md 并拦截 FB-06 高敏争议）",
        no_todo and len(cited_ids) >= 6 and flags_high_risk,
        f"请在第 4 节基于 fixtures/raw_customer_feedback.md 完成周报分类汇总试跑（当前引用编号 {len(cited_ids)}/{len(fixture_ids)} 个，需 >=6 个），并将高敏退费争议 `FB-06` 单独列入人工核实清单。",
    )
  except Exception as exc:
    v.check(
        "排名第 1 子任务真实语料试跑闭环（关联 fixtures/raw_customer_feedback.md 并拦截 FB-06 高敏争议）",
        False,
        f"试跑结果校验异常：{exc}",
    )

  v.finish()


if __name__ == "__main__":
  main()
