#!/usr/bin/env python3
"""P0-M03 自动化验收脚本：验证三轮控制变量设计、调休券基准精算、幻觉/陷阱审计与场景路由选型。"""

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


def _normalize_mode(text: str) -> str:
  if ("思考" in text) and ("贴原文" in text or "开卷" in text):
    return "贴原文+深度思考模式"
  if ("快速" in text) and ("贴原文" in text or "开卷" in text):
    return "贴原文快速模式"
  if "裸聊" in text or "预训练记忆" in text:
    return "裸聊预训练记忆"
  return text.strip()


def main() -> None:
  v = LabVerifier("P0-M03", "同一问题跑三遍：裸聊记忆、贴原文开卷与思考模式对比")

  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  policy_path = LAB_DIR / "fixtures" / "comp_time_policy.md"
  logs_path = LAB_DIR / "fixtures" / "three_rounds_logs.json"

  try:
    raw_doc = doc_path.read_text(encoding="utf-8")
    doc = _strip_html_comments(raw_doc)
    policy_text = policy_path.read_text(encoding="utf-8")
    logs_fixture = json.loads(logs_path.read_text(encoding="utf-8"))
    sections = _split_h2_sections(raw_doc)
    sec1 = sections[0] if len(sections) >= 1 else doc
    sec2 = sections[1] if len(sections) >= 2 else doc
    sec3 = sections[2] if len(sections) >= 3 else doc
  except Exception as exc:
    v.check("实验文档与测试素材读取", False, f"读取 {doc_path.name} 或 fixtures 失败：{exc}")
    v.finish()
    return

  # 指标 1：三轮控制变量设计完备性
  try:
    has_three_rounds = all(tag in sec1 for tag in ("第一轮", "第二轮", "第三轮"))
    has_blank_isolation = "空白对话" in sec1
    policy_clauses = ("单次延时满 3 小时发 1 张券", "超出部分不累加", "迟到累计达 2 次", "额外加扣 1 张团队统筹券")
    clauses_ok = all(clause in policy_text and clause in sec1 for clause in policy_clauses)
    has_grounding = "仅依据以下细则" in sec1 or "严格仅依据以下" in sec1
    v.check(
        "控制变量实验设计（3 个独立空白对话 + 四条细则完整植入 + 仅据原文作答声明）",
        has_three_rounds and has_blank_isolation and clauses_ok and has_grounding,
        "请在第 1 节写明第一轮（裸聊）、第二轮（贴原文快速模式）、第三轮（贴原文思考模式）均使用独立新建空白对话，并在后两轮完整附上《星火团队调休券细则》四条原文与“严格仅依据以下细则作答”声明。",
    )
  except Exception as exc:
    v.check("控制变量实验设计（3 个独立空白对话 + 四条细则完整植入 + 仅据原文作答声明）", False, f"校验异常：{exc}")

  # 指标 2：调休券核销基准精算
  try:
    has_earned_4 = "共攒 4 张" in sec2 or "持有 4 张" in sec2
    has_cost_5 = "需扣 5 张" in sec2 or "共扣 5 张" in sec2
    has_verdict = "不够用" in sec2 and ("还差 1 张" in sec2 or "差 1 张" in sec2)
    no_false_baseline = "基准结论**：刚好够用" not in sec2 and "基准结论：刚好够用" not in sec2
    v.check(
        "调休券核销基准精算（共攒 4 张、连休 4 天需扣 5 张、结论「不够用，还差 1 张」）",
        has_earned_4 and has_cost_5 and has_verdict and no_false_baseline,
        "请修正第 2 节核算基准：工作日得 2 张 + 周末 4 张折半得 2 张 = 共攒 4 张；连休 4 天超 3 天触发额外加扣 1 张统筹券 = 需扣 5 张；结论应为“不够用，还差 1 张”。",
    )
  except Exception as exc:
    v.check("调休券核销基准精算（共攒 4 张、连休 4 天需扣 5 张、结论「不够用，还差 1 张」）", False, f"算式校验异常：{exc}")

  # 指标 3：第一轮裸聊幻觉拆穿与三大嵌套陷阱审计
  try:
    flags_hallucination = ("编造" in sec2 or "幻觉" in sec2) and sum(
        1 for kw in ("劳动法", "8 小时", "双倍", "全勤奖") if kw in sec2
    ) >= 2
    trap_keywords = [t["keyword"] for t in logs_fixture["benchmark"]["three_traps"]]
    traps_audited = all(kw in sec2 for kw in trap_keywords) and "团队统筹券" in sec2
    v.check(
        "裸聊幻觉拆穿与三处嵌套陷阱审计（超时不累加 / 迟到折半 / 额外加扣 1 张）",
        flags_hallucination and traps_audited,
        "请在第 2 节标出第一轮裸聊凭空编造的假规则（如 8 小时折算、双倍工时、迟到仅扣全勤奖），并完整复盘“超出部分不累加”、“折半计算”、“额外加扣 1 张团队统筹券”三处规则陷阱。",
    )
  except Exception as exc:
    v.check("裸聊幻觉拆穿与三处嵌套陷阱审计（超时不累加 / 迟到折半 / 额外加扣 1 张）", False, f"陷阱审计校验异常：{exc}")

  # 指标 4：三轮实测多维对照表
  try:
    sec2_tables = _extract_markdown_tables(sec2)
    comp_table = max(sec2_tables, key=len) if sec2_tables else []
    comp_rows = comp_table[1:] if len(comp_table) >= 2 else []
    table_text = "\n".join(" | ".join(r) for r in comp_table)
    has_all_rounds = len(comp_rows) >= 3 and all(tag in table_text for tag in ("第一轮", "第二轮", "第三轮"))
    has_three_dims = (
        ("真实性" in table_text or "幻觉" in table_text)
        and ("命中" in table_text or "陷阱" in table_text)
        and ("耗时" in table_text or "等待" in table_text)
    )
    v.check(
        "三轮实测多维对照表（完整对比事实真实性、规则陷阱命中率与等待耗时）",
        has_all_rounds and has_three_dims,
        "请在第 2 节用至少 3 行数据的 Markdown 竖线表格对比第一轮、第二轮、第三轮在“事实真实性、多步规则命中率、等待耗时”三项维度上的表现。",
    )
  except Exception as exc:
    v.check("三轮实测多维对照表（完整对比事实真实性、规则陷阱命中率与等待耗时）", False, f"对照表解析异常：{exc}")

  # 指标 5：六大职场场景模式选型路由表
  try:
    no_blind_thinking = "一律全部打开深度思考模式" not in sec3
    has_three_archetypes = (
        "通识问答" in sec3
        and ("查准资料" in sec3 or "单跳" in sec3)
        and ("复杂多步推理" in sec3 or "嵌套规则" in sec3)
    )
    sec3_tables = _extract_markdown_tables(sec3)
    route_map: dict[str, str] = {}
    for tbl in sec3_tables:
      for row in tbl[1:]:
        joined_row = " | ".join(row)
        sid_match = re.search(r"\b(S[1-6])\b", joined_row)
        if sid_match and len(row) >= 3:
          route_map[sid_match.group(1)] = _normalize_mode(row[2])

    expected_routes = {item["id"]: item["recommended_mode"] for item in logs_fixture["routing_scenarios"]}
    wrong_routes = [sid for sid, exp_mode in expected_routes.items() if route_map.get(sid) != exp_mode]
    v.check(
        "职场六大场景模式选型路由（S1~S6 精准匹配通识裸聊 / 贴原文快查 / 开卷慢思考）",
        no_blind_thinking and has_three_archetypes and len(wrong_routes) == 0,
        f"请在第 3 节总结通识问答、查准资料、复杂多步推理三层选型原则，并用 Markdown 表格准确完成 S1~S6 场景模式匹配（当前未命中：{wrong_routes}）。",
    )
  except Exception as exc:
    v.check("职场六大场景模式选型路由（S1~S6 精准匹配通识裸聊 / 贴原文快查 / 开卷慢思考）", False, f"场景路由检查异常：{exc}")

  v.finish()


if __name__ == "__main__":
  main()
