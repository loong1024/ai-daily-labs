#!/usr/bin/env python3
"""S0-M03 原子主张拆解与交叉核查 —— 自动化验收脚本。"""

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


def strip_html_comments(text: str) -> str:
  return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def extract_section(md_text: str, part_tag: str) -> str:
  """提取指定 '## Part X' 章节内容，直至下一个 '## Part ' 标题或文件末尾。"""
  lines = md_text.splitlines()
  capturing = False
  buf: list[str] = []
  for line in lines:
    stripped = line.strip()
    if re.match(r"^##\s+Part\s+\d+\b", stripped):
      if capturing:
        break
      if stripped.startswith(part_tag):
        capturing = True
        continue
    elif capturing:
      buf.append(line)
  return strip_html_comments("\n".join(buf))


def _mock_fact_checker(messages: list[dict[str, str]]) -> str:
  prompt = messages[-1].get("content", "")
  has_atomic = "原子主张" in prompt and "非事实" in prompt
  bans_url = any(k in prompt for k in ["不要编造", "严禁", "禁止"]) and any(
      k in prompt for k in ["链接", "网址", "http"]
  )
  if has_atomic and bans_url:
    return (
        "### 非事实分离\n"
        "- 建议从内部制度问答试点：非事实（行动建议）。\n\n"
        "| 编号 | 主张 | 类型 | 风险 | 时效性 | 建议核查方法 | 应查找的一手来源类型 |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| C1 | 78.6% 制造业民企上线排程智能体 | 数字 | 高 | 是 | 查官方统计报告原文（待核实） | CNNIC 官网 |\n"
        "| C2 | 斯坦福陈志远团队白皮书称 45 天回本 | 引用 | 高 | 是 | 我不确定该白皮书是否存在，查学术库 | Stanford HAI 官网 |\n\n"
        "### 优先核查前三条\n"
        "1. C2 白皮书与学者出处；2. C1 78.6% 统计口径；3. C4 暂行办法修订日期。"
    )
  return (
      "这段初稿基本准确，参考核实网址如下：\n"
      "1. https://www.stanford-hai-report-fake.org/2025/apac-agent.pdf\n"
      "2. http://www.cnnic-stats-example.cn/2025/agent-report"
  )


def main() -> int:
  v = LabVerifier("S0-M03", "原子主张拆解与交叉核查")

  try:
    md_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
    draft_text = (LAB_DIR / "fixtures" / "ai_draft_article.md").read_text(encoding="utf-8")
    ground_truth = json.loads(
        (LAB_DIR / "fixtures" / "claim_ground_truth.json").read_text(encoding="utf-8")
    )
    content = md_path.read_text(encoding="utf-8")
  except Exception as exc:
    v.check("实验工作区与 fixtures 素材读取", False, f"读取文件失败：{exc}")
    return v.finish()

  part1 = extract_section(content, "## Part 1")
  part2 = extract_section(content, "## Part 2")
  part3 = extract_section(content, "## Part 3")
  part4 = extract_section(content, "## Part 4")

  # Check 1: 提示词模板结构与防编造规则分离
  try:
    has_atomic_nonfact = ("原子主张" in part1) and ("非事实" in part1)
    has_table_spec = all(k in part1 for k in ["表格", "风险", "时效性", "一手来源"]) and ("高" in part1)
    has_anti_fab = (
        any(k in part1 for k in ["我不确定", "待核实"])
        and any(k in part1 for k in ["不要编造", "严禁", "禁止"])
        and any(k in part1 for k in ["链接", "网址", "http"])
    )
    has_priority_rewrite = ("优先核查" in part1) and ("改写" in part1)
    c1_ok = has_atomic_nonfact and has_table_spec and has_anti_fab and has_priority_rewrite
  except Exception as exc:
    c1_ok = False
    part1 = f"解析异常: {exc}"

  v.check(
      "Part 1 核查提示词分离输出格式与防编造规则（原子主张/非事实/禁编链接/优先核查）",
      c1_ok,
      "请在 Part 1 明确规定：拆分『原子主张』、将观点建议标为『非事实』、输出含『风险/时效性/一手来源』的『表格』、不确定写『我不确定/待核实』、『严禁编造具体 http 链接网址』，并要求给出『优先核查』与『改写』建议。",
  )

  # Check 2: AI 生成的主张核查表中无捏造网址且覆盖关键要素
  try:
    urls_in_part2 = re.findall(r"https?://\S+|www\.\S+", part2, flags=re.IGNORECASE)
    table_rows = [
        ln
        for ln in part2.splitlines()
        if ln.strip().startswith("|") and not re.match(r"^\|\s*[-:\s|]+$", ln.strip())
    ]
    has_nonfact_in_p2 = "非事实" in part2
    has_risk_and_orgs = (
        part2.count("高") >= 3
        and ("CNNIC" in part2 or "互联网络信息中心" in part2)
        and ("网信办" in part2)
    )
    has_top3_in_p2 = "优先核查" in part2
    c2_ok = (
        len(urls_in_part2) == 0
        and len(table_rows) >= 6
        and has_nonfact_in_p2
        and has_risk_and_orgs
        and has_top3_in_p2
    )
  except Exception:
    c2_ok = False

  v.check(
      "Part 2 主张核查计划表未夹带任何 http 网址，且完整拆解原子主张与非事实语句",
      c2_ok,
      "请清除 Part 2 中所有 http/https/www 假链接，用 Markdown 表格拆出至少 5 条原子主张（含 CNNIC、网信办等一手机构检索词及『高』风险标记），单独标出『非事实』观点，并列出『优先核查』前三条。",
  )

  # Check 3: 高风险主张人工一手核查记录闭环
  try:
    no_todo_p3 = "TODO" not in part3 and len(part3) >= 100
    dates_found = re.findall(r"202\d-\d{2}-\d{2}", part3)
    official_links = re.findall(r"https?://[^\s)>\]\"']+", part3)
    trap_hits = sum(1 for kw in ["78.6%", "白皮书", "0.015", "2025 年 11 月"] if kw in part3)
    has_verdict_words = any(k in part3 for k in ["证伪", "无法证实"]) and any(
        k in part3 for k in ["删除", "弱化", "更正"]
    )
    c3_ok = (
        no_todo_p3
        and len(dates_found) >= 3
        and len(official_links) >= 1
        and trap_hits >= 3
        and has_verdict_words
    )
  except Exception:
    c3_ok = False

  v.check(
      "Part 3 高风险主张均已记录人工一手核查结论、官方来源链接与核查日期",
      c3_ok,
      "请在 Part 3 移除 TODO，针对高风险条目（78.6%、白皮书、0.015 美元、2025 年 11 月修订等）记录核查结论（证伪/无法证实）、真实一手机构官网链接、核查日期（YYYY-MM-DD）及删除/弱化/更正措施。",
  )

  # Check 4: 终稿改写已彻底清除假数据、假白皮书与失实政策日期
  try:
    forbidden_list: list[str] = ground_truth.get("forbidden_in_final_draft", [])
    leaked_items = [item for item in forbidden_list if item in part4]
    unverified_pct = re.findall(r"\d+(?:\.\d+)?%", part4)
    accurate_policy = ("2023" in part4) and ("生成式人工智能服务管理暂行办法" in part4)
    c4_ok = (
        len(part4) >= 120
        and "TODO" not in part4
        and part4.strip() != draft_text.strip()
        and len(leaked_items) == 0
        and len(unverified_pct) == 0
        and accurate_policy
    )
  except Exception:
    leaked_items = ["解析异常"]
    c4_ok = False

  leak_hint = f"（当前仍残留：{', '.join(leaked_items)}）" if leaked_items else ""
  v.check(
      "Part 4 改写终稿无未经验证的精确统计数字、无捏造白皮书、无失实政策年份",
      c4_ok,
      f"请改写 Part 4 终稿：删除或弱化所有未证实数字与假文献{leak_hint}，并将《生成式人工智能服务管理暂行办法》准确更正为 2023 年施行版本。",
  )

  # Check 5: 使用 chat_complete 实测 Part 1 防编造提示词效果
  try:
    rendered = (
        part1.replace("{粘贴需要核查的文字}", draft_text)
        if "{粘贴需要核查的文字}" in part1
        else f"{part1}\n\n{draft_text}"
    )
    reply = chat_complete(
        [{"role": "user", "content": rendered}],
        mock_fn=_mock_fact_checker,
        temperature=0.0,
    )
    c5_ok = (
        "|" in reply
        and "高" in reply
        and "http://" not in reply.lower()
        and "https://" not in reply.lower()
    )
  except Exception as exc:
    c5_ok = False
    reply = f"调用异常: {exc}"

  v.check(
      "端到端提示词沙盒实测：Part 1 模板驱动模型输出结构化核查表且零捏造 http 网址",
      c5_ok,
      "Part 1 提示词在沙盒测试中仍触发了假网址或未输出风险核查表，请确保在提示词中严禁输出任何包含 http:// 或 https:// 的链接并强制要求 Markdown 表格输出。",
  )

  return v.finish()


if __name__ == "__main__":
  main()
