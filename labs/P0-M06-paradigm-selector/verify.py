#!/usr/bin/env python3
"""P0-M06 选型决策演练：Prompt、知识库、工作流与 Agent - 自动化验收脚本。"""

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


def split_h2_sections(md_text: str) -> dict[str, str]:
  sections: dict[str, str] = {}
  current_title = "__preamble__"
  buf: list[str] = []
  for line in md_text.splitlines():
    if line.startswith("## "):
      sections[current_title] = "\n".join(buf).strip()
      current_title = line[3:].strip()
      buf = []
    else:
      buf.append(line)
  sections[current_title] = "\n".join(buf).strip()
  return sections


def find_section(sections: dict[str, str], keywords: list[str]) -> str:
  for title, body in sections.items():
    if any(k in title for k in keywords):
      return body
  return ""


def extract_case_blocks(sec_text: str) -> dict[str, str]:
  header_re = re.compile(
      r"(?m)^(?:\s*(?:#{1,4}|\|?)\s*(?:[-*]\s*)?\*{0,2})题\s*([A-D])(?![A-Za-z0-9])"
  )
  matches = list(header_re.finditer(sec_text))
  blocks: dict[str, str] = {}
  for idx, m in enumerate(matches):
    letter = m.group(1)
    start = m.start()
    end = matches[idx + 1].start() if idx + 1 < len(matches) else len(sec_text)
    if letter not in blocks:
      blocks[letter] = sec_text[start:end].strip()
  return blocks


def extract_choice_and_reason(block: str) -> tuple[str, str]:
  choice_match = re.search(
      r"首选(?:方案)?层级\*{0,2}[：:]\s*([^\n]+)", block
  )
  reason_match = re.search(
      r"(?:边界理由|不选[^\n：:]*理由)\*{0,2}[：:]\s*([^\n]+(?:\n(?![-*#]).+)*)",
      block,
  )
  if choice_match:
    choice = choice_match.group(1).strip()
    reason = reason_match.group(1).strip() if reason_match else block
    return choice, reason
  # 兼容 Markdown 表格行写法：| 题 A | L1 精调 Prompt | 边界理由... |
  if "|" in block:
    cells = [c.strip() for c in block.split("|") if c.strip()]
    if len(cells) >= 3:
      return cells[1], " ".join(cells[2:])
  lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
  choice = lines[1] if len(lines) > 1 else block[:40]
  reason = " ".join(lines[2:]) if len(lines) > 2 else ""
  return choice, reason


def run_optional_ai_coach(raw_doc: str) -> None:
  if "--ai-coach" not in sys.argv:
    return
  tag = "标准参考版" if use_solution() else "当前演练版"
  comment = chat_complete(
      [
          {
              "role": "system",
              "content": "你是企业 AI 首席架构师，请用两句话点评该四阶技术选型文档是否守住了反过度设计原则。",
          },
          {"role": "user", "content": raw_doc[:1400]},
      ],
      mock_fn=lambda _: (
          f"[离线架构师互评 - {tag}] 请牢记“先试 Prompt、缺资料补 RAG、定工序走 Workflow、动态探路才上 Agent + MCP”的最小够用铁律。"
      ),
  )
  print(f"\n💡 AI 架构师互评：{comment}\n")


def main() -> int:
  v = LabVerifier("P0-M06", "选型决策演练：Prompt、知识库、工作流与 Agent")
  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  cases_path = LAB_DIR / "fixtures" / "business_cases.json"

  try:
    raw_text = doc_path.read_text(encoding="utf-8")
    fixture_data = json.loads(cases_path.read_text(encoding="utf-8"))
  except Exception as exc:
    v.check(
        "选型工作单与业务案例素材可正常读取",
        False,
        f"无法读取 {doc_path.name} 或 fixtures/business_cases.json：{exc}",
    )
    return v.finish()

  sections = split_h2_sections(raw_text)
  prompt_sec = find_section(sections, ["提示词", "互评"])
  cases_sec = find_section(sections, ["四道", "场景选型", "选型诊断"])
  review_c_sec = find_section(sections, ["题 C", "专项复盘", "固定工作流"])
  mcp_sec = find_section(sections, ["MCP", "扩展坞"])
  card_sec = find_section(sections, ["选型卡", "个人真实业务"])

  # 指标 1：架构师互评提示词模板完备度
  paradigm_hits = [
      name
      for name, kws in [
          ("Prompt", ["Prompt", "提示词"]),
          ("RAG", ["RAG", "知识库"]),
          ("Workflow", ["Workflow", "工作流"]),
          ("Agent", ["Agent", "智能体"]),
      ]
      if any(kw in prompt_sec for kw in kws)
  ]
  has_light_principle = any(
      kw in prompt_sec for kw in ["由轻到重", "过度设计", "过度工程", "最轻", "最小"]
  )
  check1_ok = (
      len(prompt_sec) >= 100
      and len(paradigm_hits) == 4
      and has_light_principle
  )
  v.check(
      "架构师互评提示词模板完备（明确四阶决策尺基准与反过度设计审查要求）",
      check1_ok,
      f"请扩充 `## 一、技术架构师选型互评提示词模板`（不少于 100 字），完整写入 Prompt / 知识库 RAG / 工作流 Workflow / Agent 四阶标尺与“由轻到重、拒绝过度设计”审查约束（当前覆盖阶梯：{paradigm_hits}）。",
  )

  # 指标 2：四道业务场景题（题 A～题 D）四阶精准匹配与拒绝过度设计边界理由
  blocks = extract_case_blocks(cases_sec)
  case_errors: list[str] = []
  for item in fixture_data["cases"]:
    cid = item["id"]
    block = blocks.get(cid, "")
    if not block:
      case_errors.append(f"缺少题 {cid}")
      continue
    choice, reason = extract_choice_and_reason(block)
    matched_expected = any(
        tok.lower() in choice.lower() for tok in item["accepted_tier_tokens"]
    )
    hit_wrong = [
        tok
        for tok in item["forbidden_tier_tokens_in_choice"]
        if tok.lower() in choice.lower()
    ]
    reason_valid = (
        len(reason) >= 25
        and "待补充" not in reason
        and "待填写" not in reason
    )
    if not matched_expected or hit_wrong:
      case_errors.append(
          f"题 {cid} 首选层级应为 {item['expected_tier']}（当前填写：「{choice}」）"
      )
    elif not reason_valid:
      case_errors.append(
          f"题 {cid} 需补充不少于 25 字的“不选更重或错误方案的边界理由”"
      )

  v.check(
      "四道典型业务场景（题 A～题 D）与四阶方案精准一一匹配并写明边界理由",
      len(case_errors) == 0,
      "请修正 `## 二、四道典型业务场景选型诊断`：" + "；".join(case_errors) + "。",
  )

  # 指标 3：题 C 专项复盘（固定工作流 vs 自由规划 Agent 边界辨析）
  c_dimensions = {
      "确定性与防跳步": ["确定性", "跳步", "稳定", "固定", "按序"],
      "成本与延迟效率": ["成本", "Token", "延迟", "耗时", "多轮"],
      "可观测排错与权限可控": ["排错", "重试", "权限", "可控", "可观测", "误改", "波动"],
  }
  hit_c_dims = [
      dim
      for dim, kws in c_dimensions.items()
      if any(kw in review_c_sec for kw in kws)
  ]
  mentions_both = any(
      kw in review_c_sec for kw in ["工作流", "Workflow"]
  ) and any(kw in review_c_sec for kw in ["Agent", "智能体"])
  check3_ok = (
      "待补充" not in review_c_sec
      and len(review_c_sec) >= 90
      and mentions_both
      and len(hit_c_dims) >= 2
  )
  v.check(
      "题 C 专项复盘透彻（从确定性、成本延迟与权限排错维度辨析 Workflow vs Agent）",
      check3_ok,
      f"请在 `## 三` 深入复盘为何题 C 应选固定工作流而非自由规划 Agent（不少于 90 字，删除“待补充”，至少覆盖确定性、Token 成本延迟、排错权限可控中的 2 个维度，当前命中：{hit_c_dims}）。",
  )

  # 指标 4：MCP 标准扩展坞可接入外部工具与数据源盘点（至少 3 类）
  mcp_category_groups = {
      "文件系统与代码仓库": ["文件", "Filesystem", "Git", "GitHub", "代码"],
      "数据库与数据仓库": ["数据库", "SQL", "PostgreSQL", "SQLite", "BigQuery", "数仓"],
      "日历与协作办公系统": [
          "日历",
          "Calendar",
          "Slack",
          "Notion",
          "飞书",
          "钉钉",
          "邮件",
          "协作",
      ],
      "网页检索与浏览器自动化": [
          "网页",
          "浏览器",
          "搜索",
          "Search",
          "Fetch",
          "Playwright",
      ],
      "研发工单与监控告警": ["Jira", "Linear", "Sentry", "工单", "监控"],
  }
  hit_mcp_cats = [
      cat
      for cat, kws in mcp_category_groups.items()
      if any(kw.lower() in mcp_sec.lower() for kw in kws)
  ]
  check4_ok = (
      "待补充" not in mcp_sec
      and len(mcp_sec) >= 80
      and len(hit_mcp_cats) >= 3
  )
  v.check(
      "准确盘点至少 3 类可通过 MCP 标准接入的外部数据源或工具类型",
      check4_ok,
      f"请在 `## 四` 参考 `fixtures/business_cases.json` 中的 MCP 目录快照，列举并说明至少 3 类外部连接器（如本地文件代码库、数据库数仓、日历协作办公、网页检索浏览器等，当前识别 {len(hit_mcp_cats)} 类：{hit_mcp_cats}）。",
  )

  # 指标 5：个人真实业务三行轻量选型卡结构完整
  tier_line = re.search(r"首选方案层级\*{0,2}[：:]\s*([^\n]+)", card_sec)
  source_line = re.search(
      r"所需数据源(?:与工具)?\*{0,2}[：:]\s*([^\n]+)", card_sec
  )
  human_line = re.search(r"人工复核点\*{0,2}[：:]\s*([^\n]+)", card_sec)

  tier_val = tier_line.group(1).strip() if tier_line else ""
  source_val = source_line.group(1).strip() if source_line else ""
  human_val = human_line.group(1).strip() if human_line else ""

  valid_tier_named = any(
      kw.lower() in tier_val.lower()
      for kw in [
          "l1",
          "l2",
          "l3",
          "l4",
          "prompt",
          "rag",
          "知识库",
          "workflow",
          "工作流",
          "agent",
      ]
  )
  check5_ok = (
      "待填写" not in card_sec
      and valid_tier_named
      and len(tier_val) >= 4
      and len(source_val) >= 8
      and len(human_val) >= 10
  )
  v.check(
      "结合个人真实业务产出完整的三行轻量选型卡（首选层级 + 数据源工具 + 人工复核点）",
      check5_ok,
      "请在 `## 五、个人真实业务三行轻量选型卡` 中删除所有“待填写”，结合你的一项真实工作场景明确填写 `首选方案层级`（L1～L4 之一及简短依据）、`所需数据源与工具` 与 `人工复核点`。",
  )

  run_optional_ai_coach(raw_text)
  return v.finish()


if __name__ == "__main__":
  main()
