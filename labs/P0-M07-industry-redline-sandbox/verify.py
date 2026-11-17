#!/usr/bin/env python3
"""P0-M07 八大行业 AI 提效立项沙盘：高收益切入点与高危红线分拣实战 - 自动化验收脚本。"""

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

VALID_BUCKETS = ("GREEN_QUICK_WIN", "YELLOW_NEED_HITL", "RED_FORBIDDEN")


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
  for kw in keywords:
    for title, body in sections.items():
      if title != "__preamble__" and kw in title:
        return body
  return ""


def extract_markdown_tables(md_text: str) -> list[list[list[str]]]:
  tables: list[list[list[str]]] = []
  current: list[list[str]] = []
  in_code = False
  for raw_line in md_text.splitlines():
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


def inspect_prompt_guardrails(prompt_text: str) -> dict[str, bool]:
  has_three_buckets = all(b in prompt_text for b in VALID_BUCKETS)
  has_quadrant = any(k in prompt_text for k in ("高频", "频率", "四象限")) and any(
      k in prompt_text for k in ("核验", "验真", "检查对错")
  )
  has_privacy_redline = "脱敏" in prompt_text and any(
      k in prompt_text for k in ("公网", "隐私", "薪资", "底价")
  )
  has_domain_redline = any(k in prompt_text for k in ("处方", "医师", "医疗")) and any(
      k in prompt_text for k in ("判例", "法条", "权威", "溯源")
  )
  has_hitl_and_safety = any(
      k in prompt_text for k in ("人工", "签字", "终审", "复核", "HITL")
  ) and any(k in prompt_text for k in ("产线", "急停", "联锁", "打款"))
  no_reckless_bypass = (
      "不需要考虑人工复核" not in prompt_text
      and "不用管脱敏" not in prompt_text
      and "尽量全部归类为 `GREEN_QUICK_WIN`" not in prompt_text
  )
  return {
      "three_buckets": has_three_buckets,
      "quadrant": has_quadrant,
      "privacy_redline": has_privacy_redline,
      "domain_redline": has_domain_redline,
      "hitl_and_safety": has_hitl_and_safety,
      "no_reckless_bypass": no_reckless_bypass,
  }


def evaluate_prompt_on_fixtures(prompt_text: str, proposals: list[dict]) -> dict[str, str]:
  """调用 chat_complete 执行分拣提示词（支持离线确定性 Mock 与真实模型 JSON 模式无缝切换）。"""

  def deterministic_mock(messages: list[dict[str, str]]) -> str:
    sys_prompt = messages[0]["content"]
    guards = inspect_prompt_guardrails(sys_prompt)
    decisions: dict[str, str] = {}
    for item in proposals:
      pid = item["id"]
      exp = item["expected_bucket"]
      if not guards["no_reckless_bypass"] or not guards["three_buckets"]:
        decisions[pid] = "GREEN_QUICK_WIN"
        continue
      if exp == "RED_FORBIDDEN":
        if pid == "DP-09" and not guards["privacy_redline"]:
          decisions[pid] = "GREEN_QUICK_WIN"
        elif pid in ("DP-07", "DP-08") and not guards["domain_redline"]:
          decisions[pid] = "YELLOW_NEED_HITL"
        elif pid == "DP-10" and not guards["hitl_and_safety"]:
          decisions[pid] = "YELLOW_NEED_HITL"
        else:
          decisions[pid] = "RED_FORBIDDEN"
      elif exp == "YELLOW_NEED_HITL":
        decisions[pid] = "YELLOW_NEED_HITL" if guards["hitl_and_safety"] else "GREEN_QUICK_WIN"
      else:
        decisions[pid] = "GREEN_QUICK_WIN" if guards["quadrant"] else "YELLOW_NEED_HITL"
    return json.dumps({"decisions": decisions}, ensure_ascii=False)

  compact_cases = [
      {"id": p["id"], "department": p["department"], "proposal": p["proposal"]}
      for p in proposals
  ]
  user_payload = (
      "请严格按系统提示词的分拣标准，对以下 10 条提议逐条分类，仅输出 JSON 对象 "
      '{"decisions": {"DP-01": "GREEN_QUICK_WIN", ...}}：\n'
      + json.dumps(compact_cases, ensure_ascii=False, indent=2)
  )
  raw_resp = chat_complete(
      [
          {"role": "system", "content": prompt_text},
          {"role": "user", "content": user_payload},
      ],
      mock_fn=deterministic_mock,
      temperature=0.0,
      response_json=True,
  )
  cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_resp.strip(), flags=re.I)
  parsed = json.loads(cleaned)
  if isinstance(parsed.get("decisions"), dict):
    return {str(k): str(v).strip() for k, v in parsed["decisions"].items()}
  return {str(k): str(v).strip() for k, v in parsed.items() if str(k).startswith("DP-")}


def main() -> int:
  v = LabVerifier(
      "P0-M07",
      "八大行业 AI 提效立项沙盘：高收益切入点与高危红线分拣实战",
  )
  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  proposals_path = LAB_DIR / "fixtures" / "dept_proposals.json"

  try:
    raw_text = doc_path.read_text(encoding="utf-8")
    fixture_data = json.loads(proposals_path.read_text(encoding="utf-8"))
    proposals: list[dict] = fixture_data["proposals"]
  except Exception as exc:
    v.check(
        "立项沙盘工作单与 10 条部门提议样本加载",
        False,
        f"无法读取 {doc_path.name} 或 fixtures/dept_proposals.json：{exc}",
    )
    return v.finish()

  sections = split_h2_sections(raw_text)
  prompt_sec = find_section(sections, ["立项分拣提示词", "提示词", "一、"])
  table_sec = find_section(sections, ["分拣沙盘表", "沙盘表", "二、"])
  remedy_sec = find_section(sections, ["降级改造", "一票否决", "三、"])

  # 指标 1：四象限评估 + 行业红线分拣提示词完备度
  guards = inspect_prompt_guardrails(prompt_sec)
  missing_guard_names = [
      label
      for key, label in (
          ("three_buckets", "GREEN_QUICK_WIN / YELLOW_NEED_HITL / RED_FORBIDDEN 三档标准"),
          ("quadrant", "高频耗时 × 人类快速核验四象限标尺"),
          ("privacy_redline", "未脱敏隐私/薪资底价禁贴公网模型红线"),
          ("domain_redline", "医疗处方医师审核与法务判例权威溯源红线"),
          ("hitl_and_safety", "工业产线联锁/财务打款人工终审签字红线"),
          ("no_reckless_bypass", "删除盲目全自动放行与跳过人工脱敏的错误指令"),
      )
      if not guards[key]
  ]
  v.check(
      "立项分拣提示词完备度（四象限准入标尺 + 红黄绿三档定义 + 四大行业红线）",
      len(prompt_sec) >= 180 and not missing_guard_names,
      "请完善 `## 一、跨行业 AI 立项分拣提示词`（不少于 180 字），补齐："
      + "、".join(missing_guard_names)
      + "。",
  )

  # 指标 2：通过 chat_complete 试跑分拣提示词验证 10 条提议自动拦截能力
  try:
    sim_decisions = evaluate_prompt_on_fixtures(prompt_sec, proposals)
    mismatched_sim = [
        f"{p['id']}(预期 {p['expected_bucket']}，实得 {sim_decisions.get(p['id'], '未输出')})"
        for p in proposals
        if sim_decisions.get(p["id"]) != p["expected_bucket"]
    ]
    v.check(
        "分拣提示词沙盘试跑验证（对 DP-01～DP-10 模拟评审分档 10/10 准确）",
        len(mismatched_sim) == 0,
        "当前第 1 节提示词规则存在漏洞，沙盘试跑出现误判："
        + "；".join(mismatched_sim[:5])
        + "。请在提示词中补齐三档触发条件与一票否决红线。",
    )
  except Exception as exc:
    v.check(
        "分拣提示词沙盘试跑验证（对 DP-01～DP-10 模拟评审分档 10/10 准确）",
        False,
        f"执行分拣提示词解析失败：{exc}",
    )

  # 指标 3：第 2 节 10 条跨行业部门提议沙盘表全覆盖与精准分档
  tables = extract_markdown_tables(table_sec)
  row_map: dict[str, tuple[str, str]] = {}
  for tbl in tables:
    for row in tbl[1:]:
      joined = " | ".join(row)
      m = re.search(r"\b(DP-(?:0[1-9]|10))\b", joined)
      if m and len(row) >= 4:
        bucket_cell = row[2].strip()
        note_cell = row[3].strip()
        matched_b = next((b for b in VALID_BUCKETS if b in bucket_cell), bucket_cell)
        row_map[m.group(1)] = (matched_b, note_cell)

  table_errors: list[str] = []
  for p in proposals:
    pid = p["id"]
    if pid not in row_map:
      table_errors.append(f"缺少 {pid}")
      continue
    got_bucket, got_note = row_map[pid]
    if got_bucket != p["expected_bucket"]:
      table_errors.append(f"{pid} 应为 {p['expected_bucket']}（当前为 {got_bucket}）")
    elif len(got_note) < 12 or "待填写" in got_note or "直接上线即可" in got_note:
      table_errors.append(f"{pid} 需写明具体风险点与人机护栏（不少于 12 字，删除笼统占位）")

  v.check(
      "10 条跨行业提议分拣沙盘表精准对齐（3 速赢 + 3 受控共创 + 4 红线禁区）",
      len(table_errors) == 0,
      "请修正 `## 二、10 条跨行业部门提议分拣沙盘表`：" + "；".join(table_errors[:6]) + "。",
  )

  # 指标 4：4 条高危红线提议（DP-07～DP-10）零漏放且点明真实风险本质
  red_checks = {
      "DP-07": ("判例", "权威", "幻觉", "编造"),
      "DP-08": ("处方", "医师", "医生", "生命"),
      "DP-09": ("脱敏", "公网", "隐私", "心算", "脚本", "公式"),
      "DP-10": ("联锁", "急停", "产线", "班组长", "带电"),
  }
  red_failures: list[str] = []
  for pid, kws in red_checks.items():
    got_b, got_note = row_map.get(pid, ("", ""))
    if got_b != "RED_FORBIDDEN" or not any(kw in got_note for kw in kws):
      red_failures.append(pid)

  v.check(
      "四大高危禁区零漏放拦截（法务默写判例 / 医疗开处方 / HR 贴薪资表 / 工厂自动停产线）",
      len(red_failures) == 0,
      f"高危提议 {red_failures} 未严格标为 `RED_FORBIDDEN` 或未点明核心红线风险（幻觉假判例、无医师处方权、公网泄密与心算误差、拆除物理安全联锁）。",
  )

  # 指标 5：第 3 节针对全部 4 条 RED_FORBIDDEN 提议给出可落地合规降级改造卡
  remedy_hits = [
      pid
      for pid, kws in (
          ("DP-07", ("裁判文书", "权威", "原文", "律师")),
          ("DP-08", ("预采集", "病历草稿", "预问诊", "执业医师")),
          ("DP-09", ("脱敏", "脚本", "公式", "本地")),
          ("DP-10", ("硬件", "联锁", "只读", "手册", "班组长", "值班长")),
      )
      if pid in remedy_sec and sum(1 for kw in kws if kw in remedy_sec) >= 2
  ]
  v.check(
      "高危提议合规降级改造闭环（DP-07～DP-10 均转化为带护栏的安全辅助方案）",
      "待补充" not in remedy_sec and len(remedy_sec) >= 200 and len(remedy_hits) == 4,
      f"请在 `## 三、高危红线一票否决与降级改造卡` 删除“待补充”，逐条为 DP-07、DP-08、DP-09、DP-10 写出保留人工签字、权威溯源、本地脚本计算与硬件安全联锁的改造方案（当前达标：{remedy_hits}）。",
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
