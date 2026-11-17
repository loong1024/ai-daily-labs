#!/usr/bin/env python3
"""S2-M04 自动化验收脚本：六维只读工作流审查 Skill 规范性、红队排雷抓洞、防二次泄密与蓝队复验。"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

SIX_DIMENSIONS = ("触发器", "数据流转", "LLM 节点", "错误处理", "人工审批", "密钥与成本")


def parse_frontmatter(md_text: str) -> dict[str, str]:
  """解析 SKILL.md 顶部的 YAML Frontmatter（纯标准库实现）。"""
  lines = md_text.lstrip().splitlines()
  if not lines or lines[0].strip() != "---":
    return {}
  meta: dict[str, str] = {}
  for idx in range(1, len(lines)):
    line = lines[idx].strip()
    if line == "---":
      return meta
    if ":" in line:
      k, val = line.split(":", 1)
      meta[k.strip()] = val.strip().strip("\"'")
  return {}


def inspect_skill_spec(skill_text: str) -> tuple[bool, list[str]]:
  """检查 Skill 文档是否具备合法元数据、六维步骤、分级表格式、只读与密钥脱敏约束。"""
  missing: list[str] = []
  meta = parse_frontmatter(skill_text)
  if not meta.get("name"):
    missing.append("缺少 YAML frontmatter 的 name 字段")
  desc = meta.get("description", "")
  if len(desc) < 15 or not any(kw in desc for kw in ("审查", "检查", "评审", "工作流", "上线")):
    missing.append("YAML frontmatter 的 description 缺少触发场景说明")

  for dim in SIX_DIMENSIONS:
    if dim not in skill_text:
      missing.append(f"缺少六维审查维度：{dim}")

  if not all(lvl in skill_text for lvl in ("BLOCKER", "WARN", "NIT")):
    missing.append("缺少 BLOCKER / WARN / NIT 分级表定义")

  if not all(verdict in skill_text for verdict in ("可上线", "修复后上线", "不可上线")):
    missing.append("缺少“可上线 / 修复后上线 / 不可上线”三档结论定义")

  if "只读" not in skill_text and "不修改文件" not in skill_text:
    missing.append("缺少只读审查边界约束")

  has_redaction_rule = any(
      phrase in skill_text
      for phrase in ("不在输出中复述", "不回显", "脱敏", "不复述密钥", "只报告位置")
  )
  if not has_redaction_rule:
    missing.append("缺少“不在审查输出中回显明文密钥”的防二次泄密约束")

  return (len(missing) == 0, missing)


def evaluate_workflow_findings(workflow_obj: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
  """基于工作流 JSON 结构提取真实的 BLOCKER 与 WARN 问题列表（不含任何明文密钥）。"""
  blockers: list[dict[str, str]] = []
  warns: list[dict[str, str]] = []

  for trig in workflow_obj.get("triggers", []):
    tid = trig.get("id", "trigger")
    if trig.get("type") == "webhook":
      if not trig.get("deduplicate_by_event_id"):
        warns.append({
            "loc": f"triggers.{tid}.deduplicate_by_event_id",
            "issue": "Webhook 未按事件 ID 去重，且回写可能再次触发自身循环",
            "fix": "开启 deduplicate_by_event_id 并过滤自身机器人写回事件",
        })
    if trig.get("type") == "schedule" and not str(trig.get("timezone", "")).strip():
      warns.append({
          "loc": f"triggers.{tid}.timezone",
          "issue": "定时触发器未显式声明时区",
          "fix": "显式指定时区（如 Asia/Shanghai）",
      })

  df = workflow_obj.get("data_flow", {})
  if not df.get("pagination") or df.get("malformed_record_policy") == "silent_drop":
    warns.append({
        "loc": "data_flow",
        "issue": "分页未取全且异常数据被静默丢弃（silent_drop）",
        "fix": "开启分页拉取并将异常记录写入错误日志表",
    })

  for node in workflow_obj.get("nodes", []):
    nid = node.get("id", "node")
    if node.get("type") == "llm_completion":
      if not node.get("structured_output") or not node.get("fallback_category"):
        warns.append({
            "loc": f"nodes.{nid}",
            "issue": "LLM 节点未开启结构化输出校验或缺少“其他”兜底分类",
            "fix": "启用 structured_output、设置“其他”兜底并配置有限次校验重试转人工",
        })

    if node.get("type") == "external_side_effect":
      creds = node.get("credentials", {})
      raw_key = str(creds.get("api_key", ""))
      if raw_key and not (raw_key.startswith("${") and raw_key.endswith("}")):
        blockers.append({
            "loc": f"nodes.{nid}.credentials.api_key",
            "issue": "存在硬编码明文 API 密钥（已脱敏遮罩，不回显原文），且权限为过宽的 admin",
            "fix": "改为环境变量引用（如 ${MAIL_VOUCHER_GATEWAY_API_KEY}）并收敛为最小权限",
        })

      retry = node.get("retry", {})
      max_attempts = retry.get("max_attempts", 0)
      retry_on = set(str(x) for x in retry.get("retry_on", []))
      bad_retry = (
          not isinstance(max_attempts, int)
          or max_attempts <= 0
          or max_attempts > 10
          or retry.get("strategy") == "immediate"
          or not retry.get("jitter")
          or bool(retry_on & {"400", "401", "all"})
          or not retry.get("dead_letter_queue")
      )
      if bad_retry:
        blockers.append({
            "loc": f"nodes.{nid}.retry",
            "issue": "无上限立即重试且将 400/401 纳入重试，缺少指数退避抖动与死信队列",
            "fix": "仅对 429/5xx/timeout 做带抖动指数退避（上限 4 次），400/401 不重试，耗尽入死信告警",
        })

      if not node.get("idempotency_key"):
        warns.append({
            "loc": f"nodes.{nid}.idempotency_key",
            "issue": "外部副作用动作缺少业务幂等键，重试易导致重复发信与重复发券",
            "fix": "按事件 ID + 客户 ID 配置唯一幂等键",
        })

      approval = node.get("human_approval", {})
      approval_ok = (
          approval.get("enabled") is True
          and approval.get("timeout_policy") == "abort"
          and approval.get("auth_required") is True
          and approval.get("one_time_token") is True
      )
      if not approval_ok:
        blockers.append({
            "loc": f"nodes.{nid}.human_approval",
            "issue": "群发补偿邮件与发券等不可逆外部动作前缺少一次性鉴权人工审批，或超时策略非默认中止",
            "fix": "启用 human_approval，设置 timeout_policy='abort' 并开启鉴权与一次性令牌",
        })

  gov = workflow_obj.get("governance", {})
  if (
      not gov.get("redact_logs")
      or not gov.get("max_budget_usd_per_run")
      or not gov.get("max_loop_iterations")
  ):
    warns.append({
        "loc": "governance",
        "issue": "日志未开启脱敏，或缺少单次预算上限与最大循环轮次保护",
        "fix": "开启 redact_logs，配置 max_budget_usd_per_run 与 max_loop_iterations",
    })

  return {"blockers": blockers, "warns": warns}


def simulate_skill_audit_mock(messages: list[dict[str, str]]) -> str:
  """离线模拟编码 Agent 装载 Skill 后的工作流审查输出：忠实反映 Skill 约束是否完备。"""
  system_text = "\n".join(m["content"] for m in messages if m.get("role") == "system")
  user_text = "\n".join(m["content"] for m in messages if m.get("role") == "user")

  json_match = re.search(r"\{.*\}", user_text, flags=re.DOTALL)
  wf = json.loads(json_match.group(0)) if json_match else {}

  skill_ok, _ = inspect_skill_spec(system_text)
  if not skill_ok:
    # 残缺提示词场景：标准漂移、漏掉人工审批维度，且把明文密钥原样回显到报告里！
    leaked_key = (
        wf.get("nodes", [{}])[-1].get("credentials", {}).get("api_key", "")
    )
    return (
        "我帮你粗略看了一下这个配置：\n"
        f"- 发现你在配置里写了 api_key: {leaked_key}，建议改掉。\n"
        "- 重试次数写成了 -1 可能不太好。\n"
        "结论：改改就能用。"
    )

  findings = evaluate_workflow_findings(wf)
  rows: list[str] = [
      "| 级别（BLOCKER/WARN/NIT） | 位置（文件:节点或字段路径） | 问题 | 建议修复 |",
      "| :--- | :--- | :--- | :--- |",
  ]
  for item in findings["blockers"]:
    rows.append(
        f"| BLOCKER | `{item['loc']}` | {item['issue']} | {item['fix']} |"
    )
  for item in findings["warns"]:
    rows.append(
        f"| WARN | `{item['loc']}` | {item['issue']} | {item['fix']} |"
    )
  if len(rows) == 2:
    rows.append("| NIT | `全局六维体检` | 六维可靠性与安全性检查全部通过，未发现阻断或警告隐患 | 保持定期复审 |")

  if findings["blockers"]:
    verdict = "结论：不可上线"
    blocker_summary = "必须先修复的 BLOCKER：\n" + "\n".join(
        f"- `{b['loc']}`：{b['issue']}" for b in findings["blockers"]
    )
  elif findings["warns"]:
    verdict = "结论：修复后上线"
    blocker_summary = "当前无 BLOCKER 阻断项，建议处理上述 WARN 后上线。"
  else:
    verdict = "结论：可上线"
    blocker_summary = "高危阻断项（BLOCKER）已清零（0 项），符合上线标准。"

  return "\n".join(rows) + f"\n\n{verdict}\n{blocker_summary}"


def run_audit_with_skill(skill_text: str, user_prompt: str, workflow_raw: str) -> str:
  messages = [
      {"role": "system", "content": skill_text},
      {
          "role": "user",
          "content": f"{user_prompt}\n\n工作流定义如下：\n```json\n{workflow_raw}\n```",
      },
  ]
  return chat_complete(messages, mock_fn=simulate_skill_audit_mock)


def main() -> None:
  if os.environ.get("AID_USE_LIVE_LLM") != "1":
    os.environ.setdefault("AID_FORCE_MOCK", "1")

  v = LabVerifier("S2-M04", "六维只读工作流审查 Skill 与带毒靶子排雷实验")

  skill_path = target_file(LAB_DIR, "starter_skill.md", "solution_skill.md")
  remediated_wf_path = target_file(LAB_DIR, "starter_workflow.json", "solution_workflow.json")
  vuln_wf_raw = (LAB_DIR / "fixtures" / "vulnerable_workflow.json").read_text(encoding="utf-8")
  test_cases = json.loads(
      (LAB_DIR / "fixtures" / "audit_test_cases.json").read_text(encoding="utf-8")
  )

  try:
    skill_text = skill_path.read_text(encoding="utf-8")
  except Exception as exc:  # noqa: BLE001
    v.check("读取审查 Skill 文件", False, f"无法读取 {skill_path.name}：{exc}")
    v.finish()
    return

  # 1. 检查 Skill 规范性与六维只读约束
  spec_ok, missing_reasons = inspect_skill_spec(skill_text)
  v.check(
      "六维只读审查 Skill 元数据、分级表格式与脱敏约束完整齐备",
      spec_ok,
      f"请完善 {skill_path.name}：" + "；".join(missing_reasons[:4]),
  )

  # 2. 红队触发盲测：仅发自然语言请求揪出全部 3 个预埋高危漏洞
  try:
    red_report = run_audit_with_skill(
        skill_text, test_cases["natural_trigger_prompt"], vuln_wf_raw
    )
  except Exception as exc:  # noqa: BLE001
    red_report = ""
    red_err = str(exc)
  else:
    red_err = ""

  caught_secret = any(kw in red_report for kw in ("密钥", "硬编码")) and "api_key" in red_report
  caught_retry = "重试" in red_report and any(kw in red_report for kw in ("退避", "上限", "400"))
  caught_approval = "审批" in red_report and "human_approval" in red_report
  has_table_and_verdict = (
      "| BLOCKER |" in red_report or "|BLOCKER|" in red_report.replace(" ", "")
  ) and "不可上线" in red_report
  v.check(
      "红队盲测：自然语言触发按六维分级揪出全部 3 处高危漏洞并判定不可上线",
      not red_err and caught_secret and caught_retry and caught_approval and has_table_and_verdict,
      red_err
      or f"请确保 {skill_path.name} 指导 AI 输出 BLOCKER/WARN/NIT 表格、覆盖硬编码密钥/无限重试/缺人工审批三项并给出“不可上线”结论。",
  )

  # 3. 脱敏防二次泄密检查：审查报告中绝不回显明文测试密钥
  leaked_secrets = [
      sec for sec in test_cases["forbidden_plaintext_secrets"] if sec in red_report
  ]
  v.check(
      "防二次泄密：审查报告全程脱敏遮罩，零回显靶子内的明文密钥原文",
      bool(red_report) and len(leaked_secrets) == 0,
      f"审查报告直接泄露了明文凭证！请在 {skill_path.name} 的约束中严令“发现明文密钥只报位置、绝不在输出中复述密钥内容”。",
  )

  # 4. 蓝队修复复验：整改 starter_workflow.json 后高危阻断项清零并可上线
  try:
    remediated_raw = remediated_wf_path.read_text(encoding="utf-8")
    remediated_obj = json.loads(remediated_raw)
    structural_findings = evaluate_workflow_findings(remediated_obj)
    blue_report = run_audit_with_skill(
        skill_text, test_cases["natural_trigger_prompt"], remediated_raw
    )
    blue_clean = (
        len(structural_findings["blockers"]) == 0
        and "| BLOCKER |" not in blue_report
        and ("可上线" in blue_report and "不可上线" not in blue_report)
    )
  except Exception as exc:  # noqa: BLE001
    blue_clean = False
    blue_hint = f"解析或复审 {remediated_wf_path.name} 失败：{exc}"
  else:
    blocker_locs = [b["loc"] for b in structural_findings["blockers"]]
    blue_hint = (
        f"请修复 {remediated_wf_path.name} 中的阻断隐患（剩余 BLOCKER 位置：{blocker_locs}）："
        "密钥改环境变量 ${...}、重试改指数退避加抖动（上限 4 次且排除 400/401 并配死信队列）、"
        "开启一次性鉴权人工审批且超时策略设为 abort。"
    )

  v.check(
      "蓝队复验：修复工作流配置后高危阻断项（BLOCKER）清零并转为可上线",
      spec_ok and blue_clean,
      blue_hint,
  )

  v.finish()


if __name__ == "__main__":
  main()
