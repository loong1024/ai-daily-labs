#!/usr/bin/env python3
"""S0-M09 六要素+样板改写对照实验 —— 自动化验收脚本。"""

from __future__ import annotations

import difflib
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


def extract_subsection(section_text: str, sub_prefix: str) -> str:
  """提取 '### 4.1' 等三级子标题下的内容。"""
  lines = section_text.splitlines()
  capturing = False
  buf: list[str] = []
  for line in lines:
    stripped = line.strip()
    if stripped.startswith("### "):
      if capturing:
        break
      if stripped.startswith(sub_prefix):
        capturing = True
        continue
    elif capturing:
      buf.append(line)
  return strip_html_comments("\n".join(buf))


def split_paragraphs(prose: str) -> list[str]:
  cleaned = prose.strip().strip("`").strip()
  blocks = [b.strip() for b in re.split(r"\n\s*\n", cleaned) if b.strip()]
  if len(blocks) == 1 and "\n" in blocks[0]:
    lines = [ln.strip() for ln in blocks[0].splitlines() if ln.strip()]
    if len(lines) >= 2:
      return lines
  return blocks


def _mock_six_element_writer(messages: list[dict[str, str]]) -> str:
  prompt = messages[-1].get("content", "")
  has_six = (
      ("读者" in prompt or "周敏" in prompt)
      and ("85%" in prompt or "沙箱" in prompt)
      and ("180" in prompt and "240" in prompt)
      and ("样板" in prompt or "示范" in prompt)
      and any(w in prompt for w in ["赋能", "抓手", "高度重视"])
  )
  if has_six:
    return (
        "周敏好，同步下支付接口联调排期调整：原定周三（11月18日）的联调交付顺延至周五（11月20日）14:00前完成。"
        "因网关沙箱昨晚升级验签规则，目前核心接口已完成85%，仅剩退款回调待补测。\n\n"
        "这次顺延不影响下周三（11月25日）正式灰度上线。今晚18:00前我们先开放查询与下单沙箱，供贵方前端先行对接主流程。\n\n"
        "麻烦帮忙确认下，贵方前端同学周五14:00-16:00能否预留2小时集中走查退款回调？谢啦！"
    )
  return (
      "尊敬的合作方您好，我司对本次项目联调高度重视，因技术调整将延期两天，团队正全力以赴推进生态闭环，敬请谅解为盼！"
  )


def main() -> int:
  v = LabVerifier("S0-M09", "六要素+样板改写对照实验")

  try:
    md_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
    dataset = json.loads(
        (LAB_DIR / "fixtures" / "communication_scenarios.json").read_text(encoding="utf-8")
    )
    primary_id = dataset["primary_scenario_id"]
    scenario = next(s for s in dataset["scenarios"] if s["id"] == primary_id)
    banned_cliches: list[str] = scenario["banned_cliches"]
    min_len, max_len = scenario["length_range"]
    content = md_path.read_text(encoding="utf-8")
  except Exception as exc:
    v.check("实验工作区与 fixtures 场景素材读取", False, f"读取文件失败：{exc}")
    return v.finish()

  part2 = extract_section(content, "## Part 2")
  part3 = extract_section(content, "## Part 3")
  part4 = extract_section(content, "## Part 4")

  # Check 1: 实验组 B 提示词完整包含六要素与真实个人行文样板
  try:
    has_task = any(k in part2 for k in ["顺延", "延期", "说明"])
    has_audience = ("读者" in part2 or "受众" in part2 or "周敏" in part2) and any(
        k in part2 for k in ["务实", "直接", "客套"]
    )
    has_facts = ("85%" in part2 or "验签" in part2) and ("沙箱" in part2) and (
        "周五" in part2 or "11月20日" in part2 or "11 月 20 日" in part2
    )
    has_structure_len = (
        str(min_len) in part2
        and str(max_len) in part2
        and ("三" in part2 or "3" in part2)
        and ("结论" in part2)
        and ("影响" in part2 or "补救" in part2)
        and ("确认" in part2)
    )
    has_banned_rule = sum(1 for w in banned_cliches if w in part2) >= 3 and any(
        neg in part2 for neg in ["不使用", "严禁", "禁止", "禁用"]
    )
    has_style_sample = ("样板" in part2 or "示范" in part2) and len(part2) >= 280
    c1_ok = (
        has_task
        and has_audience
        and has_facts
        and has_structure_len
        and has_banned_rule
        and has_style_sample
    )
  except Exception:
    c1_ok = False

  v.check(
      "Part 2 实验组 B 提示词完整包含六要素（文体/受众/硬事实/180–240字三短段/禁套话/百字个人样板）",
      c1_ok,
      "请在 Part 2 按六要素补齐：【读者与关系】（务实偏好）、【核心背景与事实】（85%进展/周五时间点/沙箱兜底）、【写作要求】（180–240字、三短段结构、明确列出至少 3 个禁用套话）以及【参考我平时的行文样板】（贴入约 100 字真实消息示范）。",
  )

  # Check 2: 结果 B 满足三短段结构与 180–240 字正向篇幅区间
  try:
    paragraphs = split_paragraphs(part3)
    char_count = sum(len(re.sub(r"\s+", "", p)) for p in paragraphs)
    c2_ok = len(paragraphs) == 3 and (min_len <= char_count <= max_len)
  except Exception:
    paragraphs = []
    char_count = 0
    c2_ok = False

  v.check(
      f"Part 3 结果 B 严格分为三短段且总字数落在 {min_len}–{max_len} 字区间（当前：{len(paragraphs)} 段 / {char_count} 字）",
      c2_ok,
      f"请将 Part 3 调整为空行分隔的 3 个自然段（结论先行 → 影响与补救 → 需对方确认的一件事），并将去空白总字数控制在 {min_len}–{max_len} 字之间（当前为 {len(paragraphs)} 段、{char_count} 字）。",
  )

  # Check 3: 结果 B 零官腔套话且准确传达关键事实与样板口吻
  try:
    hit_cliches = [w for w in banned_cliches if w in part3]
    has_deadline = any(k in part3 for k in ["周五", "11月20日", "11 月 20 日"])
    has_fallback = ("沙箱" in part3) and any(
        k in part3 for k in ["灰度", "11月25日", "11 月 25 日"]
    )
    has_confirm_ask = ("确认" in part3) and any(
        k in part3 for k in ["14:00", "2小时", "2 小时", "走查"]
    )
    c3_ok = len(hit_cliches) == 0 and has_deadline and has_fallback and has_confirm_ask
  except Exception:
    hit_cliches = ["解析异常"]
    c3_ok = False

  cliche_hint = f"（命中了禁用词：{', '.join(hit_cliches)}）" if hit_cliches else ""
  v.check(
      "Part 3 结果 B 未出现任何被禁用的空洞套话，且完整包含新排期、沙箱兜底与走查确认事项",
      c3_ok,
      f"请检查 Part 3 成稿{cliche_hint}：删净『高度重视/全力以赴/赋能/抓手』等官腔词，并确保写明周五（11月20日）新节点、提前开放沙箱不影响 11月25日灰度、以及周五 14:00 预留 2 小时走查确认。",
  )

  # Check 4: 发前定稿微调字数少于全文 20% 且完成 A/B 删改率对比
  try:
    final_b = extract_subsection(part4, "### 4.1")
    review_b = extract_subsection(part4, "### 4.2")
    norm_draft = re.sub(r"\s+", "", part3)
    norm_final = re.sub(r"\s+", "", final_b)
    if norm_draft and norm_final:
      similarity = difflib.SequenceMatcher(None, norm_draft, norm_final).ratio()
      edit_ratio = 1.0 - similarity
    else:
      edit_ratio = 1.0
    has_ab_metrics = (
        "TODO" not in part4
        and any(k in review_b for k in ["对照组", "结果 A", "A 组"])
        and any(k in review_b for k in ["实验组", "结果 B", "B 组"])
        and ("%" in review_b)
    )
    c4_ok = (
        c2_ok
        and c3_ok
        and "TODO" not in final_b
        and len(norm_final) >= 160
        and edit_ratio < 0.20
        and has_ab_metrics
    )
  except Exception:
    edit_ratio = 1.0
    c4_ok = False

  v.check(
      f"Part 4 发前定稿手动微调比例低于 20%（当前微调率：{edit_ratio * 100:.1f}%），并完成 A/B 量化对比",
      c4_ok,
      "请在 Part 3 达标的前提下，将微调后的发前定稿填入『### 4.1 发前定稿』（手动修改幅度须小于 20%），并在『### 4.2』填写对照组 A 与实验组 B 的删改率百分比对比与固定起手式总结。",
  )

  # Check 5: 六要素提示词沙盒生成实测（chat_complete）
  try:
    reply = chat_complete(
        [{"role": "user", "content": part2}],
        mock_fn=_mock_six_element_writer,
        temperature=0.0,
    )
    reply_paras = split_paragraphs(reply)
    reply_cliches = [w for w in ["赋能", "抓手", "高度重视", "全力以赴"] if w in reply]
    reply_has_schedule = any(
        k in reply for k in ["周五", "11月20日", "11 月 20 日", "14:00"]
    )
    c5_ok = len(reply_paras) >= 3 and len(reply_cliches) == 0 and reply_has_schedule
  except Exception:
    c5_ok = False

  v.check(
      "端到端提示词沙盒实测：Part 2 模板一次生成分段清晰、零官腔套话且要素齐全的沟通稿",
      c5_ok,
      "Part 2 提示词在沙盒生成测试中未能稳定产出零套话的三段式沟通稿，请检查是否明确提供了硬事实时间节点、分段要求、禁用套话表与个人历史行文样板。",
  )

  return v.finish()


if __name__ == "__main__":
  main()
