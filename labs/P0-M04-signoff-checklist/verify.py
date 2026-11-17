#!/usr/bin/env python3
"""P0-M04 严谨场景防翻车：AI 初稿外发前 5 项人工签字核查单 - 自动化验收脚本。"""

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
      while buf and buf[-1].strip() in ("", "---"):
        buf.pop()
      sections[current_title] = "\n".join(buf).strip()
      current_title = line[3:].strip()
      buf = []
    else:
      buf.append(line)
  while buf and buf[-1].strip() in ("", "---"):
    buf.pop()
  sections[current_title] = "\n".join(buf).strip()
  return sections


def find_section(sections: dict[str, str], keywords: list[str]) -> str:
  for kw in keywords:
    for title, body in sections.items():
      if title != "__preamble__" and kw in title:
        return body
  return ""


def run_optional_ai_coach(final_draft: str) -> None:
  if "--ai-coach" not in sys.argv:
    return
  mode_name = "参考终稿" if use_solution() else "当前初稿"
  review = chat_complete(
      [
          {
              "role": "system",
              "content": "你是严谨的企业法务与公关审校官，请用两句话点评该对外客户函件是否还有越权承诺或机械味。",
          },
          {"role": "user", "content": final_draft[:1200]},
      ],
      mock_fn=lambda _: (
          f"[离线审校模拟 - {mode_name}] 请重点核查恢复时间口径是否唯一、SLA 抵扣比例是否严格等于审批值 10%，并确认正文零敏感内网信息。"
      ),
  )
  print(f"\n💡 AI 审校教练点评：{review}\n")


def main() -> int:
  v = LabVerifier("P0-M04", "严谨场景防翻车：AI 初稿外发前 5 项人工签字核查单")
  doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
  sheet_path = LAB_DIR / "fixtures" / "fact_and_policy_sheet.json"

  try:
    raw_text = doc_path.read_text(encoding="utf-8")
    policy = json.loads(sheet_path.read_text(encoding="utf-8"))
  except Exception as exc:
    v.check(
        "工作单与权威事实底表可正常读取",
        False,
        f"无法读取 {doc_path.name} 或 fixtures/fact_and_policy_sheet.json：{exc}",
    )
    return v.finish()

  sections = split_h2_sections(raw_text)
  prompt_sec = find_section(sections, ["受控起草", "提示词", "Prompt", "一、"])
  checklist_sec = find_section(sections, ["核查单", "签字", "二、"])
  hazard_sec = find_section(sections, ["排雷", "隐患", "三、"])
  final_sec = find_section(
      sections, ["正式终稿", "可外发", "外发正式", "终稿", "四、"]
  )

  # 指标 1：5 项人工签字核查单完整且全部打钩确认
  dims: list[str] = policy.get("checklist_dimensions", [])
  missing_dims = [d for d in dims if d not in checklist_sec]
  checked_boxes = re.findall(r"\[[xX]\]", checklist_sec)
  unchecked_boxes = re.findall(r"\[\s\]", checklist_sec)
  check1_ok = (
      not missing_dims
      and len(checked_boxes) >= 5
      and len(unchecked_boxes) == 0
  )
  v.check(
      "完成《5 项人工签字核查单》逐条打钩确认（5/5 已勾选 [x]）",
      check1_ok,
      f"请在 `## 二` 核查单中逐项核实并将全部 `[ ]` 改为 `[x]`（当前已勾选 {len(checked_boxes)} 项，未勾选 {len(unchecked_boxes)} 项"
      + (f"，缺少维度：{missing_dims}" if missing_dims else "")
      + "）。",
  )

  # 指标 2：排雷记录揪出至少 4 类、不少于 3 处具体翻车隐患
  hazard_categories = {
      "事实与法规编造": ["99.999%", "光缆", "国家赔偿条例", "虚构", "编造"],
      "内部地址与客户隐私泄露": [
          "ops-admin",
          "13800138000",
          "张伟",
          "3.8折",
          "底价",
          "FAKE_TEST_KEY",
          "脱敏",
      ],
      "越权免单与绝对化承诺": ["免除", "十倍", "100%", "越权", "过度承诺"],
      "前后时间矛盾与丢单疑虑": ["04:30", "18:00", "矛盾", "自洽", "补单", "丢失"],
      "占位符残留与机械黑话": ["占位符", "星号", "赋能生态", "抓手", "套话"],
  }
  matched_cats = [
      cat
      for cat, kws in hazard_categories.items()
      if any(kw in hazard_sec for kw in kws)
  ]
  hazard_items = re.findall(
      r"(?m)^(?:\s*[-*]\s+|\s*\d+\.|[|]\s*\d+\s*[|])", hazard_sec
  )
  check2_ok = (
      "待排查" not in hazard_sec
      and len(hazard_sec) >= 120
      and len(hazard_items) >= 3
      and len(matched_cats) >= 4
  )
  v.check(
      "初稿隐患排雷深度达标（揪出至少 3 处以上跨维度翻车雷区）",
      check2_ok,
      f"请在 `## 三、初稿隐患排雷记录` 中删除“待排查”占位，分条列出初稿中的事实编造、隐私内网泄露、越权免单承诺、恢复时间矛盾与占位符黑话隐患（当前覆盖维度 {len(matched_cats)}/5：{matched_cats}）。",
  )

  # 指标 3：正式终稿事实数字与补偿承诺严格对齐一手权威底表
  vf = policy["verified_facts"]
  ac = policy["approved_compensation"]
  recipient_short = "远航精密制造"
  has_recipient = recipient_short in final_sec
  has_recovery = vf["actual_recovery_time"] in final_sec
  has_credit = ac["fee_credit_ratio"] in final_sec
  has_data_safe = any(
      kw in final_sec for kw in ["零数据丢失", "无数据丢失", "未发生数据丢失"]
  ) and any(kw in final_sec for kw in ["无需手动", "无需进行任何手动", "无需补单", "无需重推"])

  hit_fabricated = [
      t for t in policy["fabricated_claims_forbidden"] if t in final_sec
  ]
  hit_unauthorized = [
      t for t in ac["unauthorized_promises_forbidden"] if t in final_sec
  ]
  hit_conflicting = [
      t for t in policy["conflicting_times_forbidden"] if t in final_sec
  ]

  check3_ok = (
      len(final_sec) >= 180
      and has_recipient
      and has_recovery
      and has_credit
      and has_data_safe
      and not hit_fabricated
      and not hit_unauthorized
      and not hit_conflicting
  )
  missing_facts_tips: list[str] = []
  if not has_recipient:
    missing_facts_tips.append("收件方全称「远航精密制造有限公司」")
  if not has_recovery:
    missing_facts_tips.append("真实恢复时间「05:35」")
  if not has_credit:
    missing_facts_tips.append("经审批的「10%」当月服务费 SLA 抵扣方案")
  if not has_data_safe:
    missing_facts_tips.append("「零数据丢失、客户无需手动补单」定心丸说明")
  bad_claims = hit_fabricated + hit_unauthorized + hit_conflicting
  v.check(
      "正式终稿事实溯源与权责边界闭环（对齐一手底表，零虚构零越权）",
      check3_ok,
      "请精修 `## 四、可外发正式终稿`："
      + (f"补充 {missing_facts_tips}；" if missing_facts_tips else "")
      + (f"彻底删改虚构/越权/矛盾表述 {bad_claims}。" if bad_claims else ""),
  )

  # 指标 4：正式终稿保密脱敏彻底清零
  leaked_tokens = [
      t for t in policy["sensitive_tokens_forbidden"] if t in final_sec
  ]
  check4_ok = len(final_sec) >= 180 and not leaked_tokens
  v.check(
      "正式终稿保密与隐私脱敏彻底清扫（零内网地址、零测试密钥、零客户隐私底价）",
      check4_ok,
      f"终稿仍残留未脱敏敏感信息：{leaked_tokens}，请从 `## 四、可外发正式终稿` 中彻底清除！"
      if leaked_tokens
      else "请先在 `## 四` 撰写不少于 180 字的正式外发终稿。",
  )

  # 指标 5：正式终稿清除占位符与机械套话，且首节起草提示词具备边界约束
  dirty_format = [
      t for t in policy["mechanical_artifacts_forbidden"] if t in final_sec
  ]
  prompt_guard_kws = ["事实", "严禁", "脱敏", "越权", "占位符", "编造"]
  hit_prompt_guards = [kw for kw in prompt_guard_kws if kw in prompt_sec]
  check5_ok = (
      len(final_sec) >= 180
      and not dirty_format
      and len(prompt_sec) >= 80
      and len(hit_prompt_guards) >= 3
  )
  v.check(
      "正式终稿去机械味清扫（零残留占位符/星号/套话）且起草提示词受控",
      check5_ok,
      (
          f"请清除 `## 四` 终稿中的格式残留或黑话套话：{dirty_format}；"
          if dirty_format
          else ""
      )
      + (
          f"请升级 `## 一、受控起草提示词模板`（不少于 80 字，明确锁定事实来源、脱敏要求、严禁越权承诺与去占位符约束，当前命中约束词 {hit_prompt_guards}）。"
          if len(prompt_sec) < 80 or len(hit_prompt_guards) < 3
          else ""
      ),
  )

  run_optional_ai_coach(final_sec)
  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
