#!/usr/bin/env python3
"""S0-M06 AI 图文发布前 20 分钟避坑自查 —— 自动化验收脚本。"""

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


def _mock_compliance_auditor(messages: list[dict[str, str]]) -> str:
  prompt = messages[-1].get("content", "")
  covers_4d = (
      ("隐私" in prompt or "脱敏" in prompt)
      and ("商用" in prompt or "许可" in prompt)
      and ("肖像" in prompt or "版权" in prompt)
      and ("标注" in prompt or "标识" in prompt or "合成" in prompt)
  )
  if covers_4d:
    return (
        "合规审查拦截报告：\n"
        "1. 数据与隐私：检测到客户姓名、手机号、金额、测试密钥及 EXIF 定位未脱敏，且未关闭模型训练开关。\n"
        "2. 模型与工具许可：免费体验版与 FLUX.1-dev Non-Commercial 严禁淘宝海报商用，需升级商用版并换用 Apache-2.0 模型。\n"
        "3. 版权与相似性：撞脸演员肖像且使用未授权方正字体，需改用非真人插画与免费可商用字体并保留提示词记录。\n"
        "4. 标注与透明：须在小红书自主声明勾选 AI 生成合成内容标识，并删除未经核实的减脂临床断言。"
    )
  return "这篇文案语气挺活泼的，没有明显违禁骂人词汇，可以直接发布。"


def main() -> int:
  v = LabVerifier("S0-M06", "AI 图文发布前四维避坑自查")

  try:
    md_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
    pack = json.loads(
        (LAB_DIR / "fixtures" / "pending_campaign_pack.json").read_text(encoding="utf-8")
    )
    _rules_doc = (LAB_DIR / "fixtures" / "platform_and_license_rules.md").read_text(
        encoding="utf-8"
    )
    content = md_path.read_text(encoding="utf-8")
  except Exception as exc:
    v.check("实验工作区与 fixtures 素材读取", False, f"读取文件失败：{exc}")
    return v.finish()

  part1 = extract_section(content, "## Part 1")
  part2 = extract_section(content, "## Part 2")
  part3 = extract_section(content, "## Part 3")
  part4 = extract_section(content, "## Part 4")

  # Check 1: 四维合规自查提示词结构完整性
  try:
    dim_privacy = ("隐私" in part1) and ("脱敏" in part1) and ("EXIF" in part1 or "训练" in part1)
    dim_license = ("许可" in part1 or "服务条款" in part1) and ("商用" in part1)
    dim_copyright = (
        ("版权" in part1 or "相似" in part1 or "雷同" in part1)
        and ("肖像" in part1 or "字体" in part1)
        and ("提示词" in part1)
    )
    dim_label = ("标注" in part1 or "标识" in part1) and ("合成" in part1) and ("事实" in part1)
    c1_ok = dim_privacy and dim_license and dim_copyright and dim_label
  except Exception:
    c1_ok = False

  v.check(
      "Part 1 合规审查提示词完整覆盖『数据隐私 / 工具许可 / 版权相似性 / 标注透明』四维要点",
      c1_ok,
      "请扩充 Part 1 审查提示词，完整纳入：1) 隐私/密钥脱敏、EXIF 清理与训练开关；2) 工具服务条款与开源许可证商用边界；3) 肖像/商用字体排雷、相似性检索与提示词留痕；4) 平台 AI 合成标注与禁包装未核实事实。",
  )

  # Check 2: 通用四维自查清单全部完成勾选标记
  try:
    unchecked_boxes = re.findall(r"(?:^\s*[-*]?\s*\[\s*\]|□)", part2, flags=re.MULTILINE)
    completed_items = [
        ln
        for ln in part2.splitlines()
        if ("[x]" in ln.lower() or "☑" in ln) and ("通过" in ln or "不适用" in ln)
    ]
    has_all_headers = all(
        h in part2 for h in ["数据与隐私", "模型与工具许可", "输出版权与相似性", "标注与透明"]
    )
    c2_ok = len(unchecked_boxes) == 0 and len(completed_items) >= 10 and has_all_headers
  except Exception:
    c2_ok = False

  v.check(
      "Part 2 四维合规自查清单已全部标记『通过』或『不适用』，无遗漏未勾选项",
      c2_ok,
      "请逐项核查 Part 2 的全部清单项，将所有『□』或『[ ]』改为『- [x] 通过（整改说明）』或『- [x] 不适用（原因说明）』，确保至少 10 项全部闭环。",
  )

  # Check 3: 账号等级商用边界一句话结论、开源许可证替换与关闭训练开关
  try:
    no_todo_p3 = "TODO" not in part3 and len(part3) >= 80
    identifies_free_ban = (
        ("免费" in part3)
        and any(k in part3 for k in ["不允许", "严禁", "禁止", "不可"])
        and ("商用" in part3)
    )
    provides_license_fix = any(
        k in part3 for k in ["企业商用版", "Pro Commercial", "商用授权"]
    ) and any(k in part3 for k in ["schnell", "Apache-2.0", "商业许可"])
    confirms_training_off = ("训练" in part3) and ("关闭" in part3)
    c3_ok = no_todo_p3 and identifies_free_ban and provides_license_fix and confirms_training_off
  except Exception:
    c3_ok = False

  v.check(
      "Part 3 清晰给出账号等级与开源模型商用边界一句话结论，并落实关闭训练开关",
      c3_ok,
      "请在 Part 3 移除 TODO，用一句话明确指出『免费体验版与 FLUX.1-dev 非商用许可不允许本次商用』，给出升级『企业商用版』与切换『FLUX.1-schnell（Apache-2.0）』方案，并记录『关闭模型训练』开关。",
  )

  # Check 4: 待发图文定稿已完成隐私/密钥脱敏、字体肖像排雷与虚假临床断言清理
  try:
    leaked_pii = [tok for tok in pack["sensitive_tokens_must_redact"] if tok in part4]
    leaked_claims = [tok for tok in pack["unverified_claim_tokens"] if tok in part4]
    leaked_infringe = [tok for tok in pack["infringement_risk_tokens"] if tok in part4]
    has_safe_assets = (
        any(f in part4 for f in ["思源黑体", "阿里巴巴普惠体", "普惠体", "免费可商用字体"])
        and any(v in part4 for v in ["插画", "不含真实人物", "非真人", "无真人肖像"])
        and ("EXIF" in part4)
    )
    c4_ok = (
        len(part4) >= 120
        and "TODO" not in part4
        and not leaked_pii
        and not leaked_claims
        and not leaked_infringe
        and has_safe_assets
    )
  except Exception:
    leaked_pii = ["解析异常"]
    leaked_claims = []
    leaked_infringe = []
    c4_ok = False

  all_leaks = leaked_pii + leaked_claims + leaked_infringe
  leak_msg = f"（仍残留风险项：{', '.join(all_leaks)}）" if all_leaks else ""
  v.check(
      "Part 4 待发定稿已彻底脱敏个人信息与测试密钥，清除撞脸肖像、侵权字体与未核实临床数字",
      c4_ok,
      f"请整改 Part 4 定稿{leak_msg}：删净客户姓名/电话/金额/身份证号段/测试密钥与『降低 42% 体脂率』虚假断言，改为非真人原创插画、阿里巴巴普惠体/思源黑体，并注明已清除图片 EXIF 定位。",
  )

  # Check 5: 平台 AI 合成标注落地 + 审查提示词沙盒实测
  try:
    combined_34 = f"{part3}\n{part4}"
    has_platform_disclosure = ("勾选" in combined_34) and (
        "自主声明" in combined_34 or "AI 生成" in combined_34 or "AI 辅助生成" in combined_34
    )
    pack_summary = json.dumps(pack["draft_visual_and_copy"], ensure_ascii=False)
    rendered = (
        part1.replace("{粘贴待审查素材包摘要}", pack_summary)
        if "{粘贴待审查素材包摘要}" in part1
        else f"{part1}\n\n{pack_summary}"
    )
    reply = chat_complete(
        [{"role": "user", "content": rendered}],
        mock_fn=_mock_compliance_auditor,
        temperature=0.0,
    )
    audit_catches_risks = (
        ("隐私" in reply or "脱敏" in reply)
        and ("商用" in reply or "许可" in reply or "授权" in reply)
        and ("标注" in reply or "声明" in reply or "标识" in reply or "AI" in reply)
    )
    c5_ok = has_platform_disclosure and audit_catches_risks
  except Exception:
    c5_ok = False

  v.check(
      "平台 AI 合成声明准确勾选，且 Part 1 审查提示词通过沙盒风险拦截实测",
      c5_ok,
      "请在 Part 3/Part 4 明确记录在发布页【自主声明】『勾选』AI 生成/辅助生成内容标识，并在正文保留显式说明，同时确保 Part 1 提示词能拦截隐私、商用与标注风险。",
  )

  return v.finish()


if __name__ == "__main__":
  main()
