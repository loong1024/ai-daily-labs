#!/usr/bin/env python3
"""S4-M03 自动化验收脚本：验证六维权限审查 Skill 的触发静默度、维度完备性与高危坏例拦截率。"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file


def parse_skill_markdown(text: str) -> tuple[dict[str, str], str]:
  """使用纯标准库解析 SKILL.md 顶部的 YAML Frontmatter 与正文内容。"""
  stripped = text.lstrip()
  if not stripped.startswith("---"):
    return {}, text
  lines = stripped.splitlines()
  end_idx = None
  for idx in range(1, len(lines)):
    if lines[idx].strip() == "---":
      end_idx = idx
      break
  if end_idx is None:
    return {}, text

  meta: dict[str, str] = {}
  current_key: str | None = None
  for raw in lines[1:end_idx]:
    if not raw.strip() or raw.strip().startswith("#"):
      continue
    if not raw.startswith(" ") and ":" in raw:
      k, v = raw.split(":", 1)
      current_key = k.strip()
      val = v.strip().strip("\"'")
      meta[current_key] = "" if val in {"|", ">"} else val
    elif current_key is not None:
      meta[current_key] = (meta[current_key] + " " + raw.strip()).strip()

  body = "\n".join(lines[end_idx + 1 :]).strip()
  return meta, body


def simulate_skill_router(description: str, user_prompt: str) -> dict[str, Any]:
  """模拟支持 Agent Skills 的客户端根据 frontmatter description 决定是否激活该 Skill。"""
  desc = description.lower()
  prompt = user_prompt.lower()

  overbroad_patterns = ["任何修改", "所有提示词", "通用质量检查", "自动运行", "审查代码、文案"]
  if any(pat in desc for pat in overbroad_patterns):
    return {
        "triggered": True,
        "reason": "description 包含泛化全量触发词，导致任意代码或文案请求均被激活",
    }

  has_tool_scope = any(k in desc for k in ["工具", "tool", "mcp", "schema", "权限"])
  if not has_tool_scope:
    return {"triggered": False, "reason": "description 未声明工具/MCP/权限触发域"}

  prompt_hits_tool_domain = any(
      kw in prompt
      for kw in [
          "mcp",
          "tool",
          "schema",
          "工具定义",
          "工具安全",
          "审查工具",
          "权限安全",
          "权限和注入",
          "最小权限",
      ]
  )
  return {
      "triggered": prompt_hits_tool_domain,
      "reason": "命中工具/MCP/权限审查意图" if prompt_hits_tool_domain else "属于日常文案或普通业务修改，保持静默",
  }


def inspect_skill_capabilities(body: str) -> dict[str, bool]:
  """检查 Skill 正文是否具备六维审查规则、BLOCKER 红线定义与只读约束。"""
  return {
      "dim_naming": ("命名" in body or "名称" in body) and any(
          k in body for k in ["重叠", "何时不该用", "边界", "示例"]
      ),
      "dim_params": "参数" in body
      and any(k in body.lower() for k in ["枚举", "enum"])
      and any(k in body for k in ["通配符", "自由文本", "必填"]),
      "dim_returns": ("返回值" in body or "返回字段" in body) and any(
          k in body for k in ["分页", "截断", "过滤"]
      ),
      "dim_danger": ("危险操作" in body or "写入" in body or "删除" in body) and any(
          k in body.lower() for k in ["预览", "dry-run", "人工确认", "幂等"]
      ),
      "dim_permission": ("最小权限" in body or "权限范围" in body) and any(
          k in body for k in ["下游", "资源范围", "管理员", "凭证"]
      ),
      "dim_injection": ("注入" in body or "不可信" in body) and any(
          k in body for k in ["私密", "外发", "对外通信", "致命三要素", "第三方"]
      ),
      "has_severity_tiers": all(lvl in body for lvl in ["BLOCKER", "MAJOR", "MINOR"]),
      "has_table_spec": "严重级别" in body and "修改建议" in body and "|" in body,
      "has_launch_verdict": "是否建议上线" in body or "建议上线" in body,
      "has_no_guess_rule": ("信息不足" in body or "缺少" in body) and ("不要猜测" in body or "严禁臆测" in body or "补充" in body),
      "has_readonly_rule": any(
          k in body for k in ["不直接改动", "只给出修改建议", "只读审校"]
      )
      and "直接帮用户重写并覆盖" not in body,
  }


def _skill_driven_review_mock(messages: list[dict[str, str]]) -> str:
  """离线确定性审校模拟器：严格依据当前加载的 SKILL.md 规则对输入配置产出审查结果。"""
  skill_text = messages[0]["content"]
  caps = inspect_skill_capabilities(skill_text)
  case = json.loads(messages[-1]["content"])
  case_id = case.get("case_id", "")

  # 若 Skill 本身尚未定义六维标准与 BLOCKER 表格规范，则只能产出粗糙口头意见
  if not (caps["has_severity_tiers"] and caps["has_table_spec"]):
    return "口头检查意见：函数名看着还行，建议给参数多补几句注释。"

  rows: list[str] = []
  missing_notes: list[str] = []

  if case_id == "CASE_HIGH_RISK_ADVERSARIAL":
    if caps["dim_params"] and caps["dim_danger"]:
      rows.append(
          "| BLOCKER | `purge_workspace_files` | 允许危险通配符 `*` 递归物理删除目录且无 Dry-run 预览与人工确认 | 参数约束 & 危险操作 | 移除自由通配符，限定受控子路径枚举，拆分只读预览与宿主人工确认 |"
      )
    if caps["dim_permission"]:
      rows.append(
          "| BLOCKER | `ops-omni-agent (GLOBAL_ADMIN_TOKEN)` | 挂载 `admin:*` 全局管理员全权限令牌，违背最小权限原则 | 权限范围 | 吊销全权限令牌，按只读最小资源范围签发受限凭证并在下游服务端强制鉴权 |"
      )
    if caps["dim_injection"]:
      rows.append(
          "| BLOCKER | `read_private_payroll_db` + `fetch_untrusted_webpage` + `send_external_email` | 同时具备私密薪资访问、不可信外部网页输入与对外发邮件能力（致命三要素），且第三方工具描述暗藏外传指令 | 注入面 | 物理拆分外网抓取与私密库/外发邮件 Agent，移除可疑第三方包并对发信加收件域名白名单与人工审批 |"
      )
    if caps["dim_returns"]:
      rows.append(
          "| MAJOR | `read_private_payroll_db` | 返回整部门未脱敏全量 CSV，缺少字段裁剪与分页上限 | 返回值 | 仅返回必要的脱敏统计摘要字段并增加分页 `limit <= 50` |"
      )
  elif case_id == "CASE_INCOMPLETE_WEBHOOK":
    rows.append(
        "| MAJOR | `post_build_webhook` | 对外发送回调缺少幂等键与目标域名白名单约束 | 危险操作 | 增加 `idempotency_key` 必填字段并在下游校验固定接收端点 |"
    )
    if caps["has_no_guess_rule"]:
      missing_notes.append(
          "信息不足需补充核实：① Webhook 使用的鉴权凭证范围；② 构建消息中是否包含外部 PR 不可信评论内容；③ 失败重试与回滚策略。"
      )
  elif case_id == "CASE_SAFE_READONLY_KB":
    rows.append(
        "| MINOR | `search_architecture_glossary` | 可在返回示例中补充空结果时的标准提示格式 | 返回值 | 在描述中补充空列表返回示例，保持团队文档一致 |"
    )

  has_blocker = any("| BLOCKER |" in r for r in rows)
  verdict = "否（不建议上线，存在 BLOCKER 高危阻断项）" if has_blocker else "是（无 BLOCKER 阻断项，建议按改进项优化后上线）"

  out = [
      "| 严重级别 | 工具 | 问题 | 依据 | 修改建议 |",
      "| :--- | :--- | :--- | :--- | :--- |",
      *rows,
      "",
      f"**是否建议上线**：{verdict}",
      "",
      "**优先修复项（Top 3）**：",
      "1. 立即移除全局管理员凭证与通配符物理删除参数；",
      "2. 拆解私密数据访问、不可信网页输入与对外发信的致命三要素组合；",
      "3. 为所有查询与回调工具补齐枚举约束、分页上限及幂等键。",
  ]
  if missing_notes:
    out.extend(["", "**待补充核实信息（不做猜测）**：", *[f"- {m}" for m in missing_notes]])
  return "\n".join(out)


def _extract_blocker_lines(report_md: str) -> list[str]:
  return [
      line
      for line in report_md.splitlines()
      if "|" in line and re.search(r"\bBLOCKER\b", line, re.IGNORECASE)
  ]


def main() -> int:
  v = LabVerifier("S4-M03", "Agent 工具与 MCP 六维权限审查 Skill 实战验收")
  skill_path = target_file(LAB_DIR, "starter.md", "solution.md")

  try:
    raw_skill = skill_path.read_text(encoding="utf-8")
    meta, body = parse_skill_markdown(raw_skill)
  except Exception as exc:
    v.check("读取并解析目标 Skill 文件", False, f"读取 {skill_path.name} 失败（{type(exc).__name__}: {exc}）。")
    return v.finish()

  router_cases = json.loads((LAB_DIR / "fixtures" / "router_trigger_logs.json").read_text(encoding="utf-8"))
  review_cases = json.loads((LAB_DIR / "fixtures" / "mcp_review_cases.json").read_text(encoding="utf-8"))

  # 验收项 1：Frontmatter 精准触发边界 + 连续 >=3 次普通修改 0 误触发
  desc = meta.get("description", "")
  name = meta.get("name", "")
  has_negative_scope = any(k in desc for k in ["不用于", "不要用于", "仅当", "非普通"])
  pos_reqs = [r for r in router_cases["requests"] if r["expected_trigger"]]
  neg_reqs = [r for r in router_cases["requests"] if not r["expected_trigger"]]

  pos_hits = sum(1 for r in pos_reqs if simulate_skill_router(desc, r["user_prompt"])["triggered"])
  neg_false_triggers = sum(1 for r in neg_reqs if simulate_skill_router(desc, r["user_prompt"])["triggered"])

  routing_ok = (
      name == "agent-tool-review"
      and has_negative_scope
      and pos_hits == len(pos_reqs)
      and len(neg_reqs) >= 3
      and neg_false_triggers == 0
  )
  v.check(
      "YAML Frontmatter 触发收敛与连续日常修改 0 误触发测试",
      routing_ok,
      "请将 frontmatter 的 name 设为 agent-tool-review，description 限定在新增/修改工具 schema、接入第三方 MCP Server 或审查工具权限时激活，并明确写上“不用于审查普通业务代码或日常文案”，消除泛化触发词。",
  )

  # 验收项 2：六维权限审查清单完备性检查
  caps = inspect_skill_capabilities(body)
  six_dims_ok = all(
      caps[k]
      for k in ["dim_naming", "dim_params", "dim_returns", "dim_danger", "dim_permission", "dim_injection"]
  )
  v.check(
      "六维审查清单完整性（命名描述/参数约束/返回值/危险操作/权限范围/注入面）",
      six_dims_ok,
      "请在审查步骤中补齐全部 6 个维度：①命名与禁用边界、②枚举与禁通配符参数约束、③返回值精简与分页截断、④危险操作读写分离与预览/确认/幂等、⑤最小权限凭证与下游强制鉴权、⑥不可信内容注入面与私密+外网+外发致命三要素。",
  )

  # 验收项 3：高危坏例红蓝对抗测试（三大致命风险 100% 标为 BLOCKER + 良性样本无误杀）
  try:
    by_id = {c["case_id"]: c for c in review_cases["cases"]}
    adv_report = chat_complete(
        [
            {"role": "system", "content": raw_skill},
            {"role": "user", "content": json.dumps(by_id["CASE_HIGH_RISK_ADVERSARIAL"], ensure_ascii=False)},
        ],
        mock_fn=_skill_driven_review_mock,
    )
    safe_report = chat_complete(
        [
            {"role": "system", "content": raw_skill},
            {"role": "user", "content": json.dumps(by_id["CASE_SAFE_READONLY_KB"], ensure_ascii=False)},
        ],
        mock_fn=_skill_driven_review_mock,
    )
    incomplete_report = chat_complete(
        [
            {"role": "system", "content": raw_skill},
            {"role": "user", "content": json.dumps(by_id["CASE_INCOMPLETE_WEBHOOK"], ensure_ascii=False)},
        ],
        mock_fn=_skill_driven_review_mock,
    )

    adv_blockers = "\n".join(_extract_blocker_lines(adv_report))
    caught_wildcard_del = any(
        k in adv_blockers for k in ["purge_workspace_files", "通配符", "删除"]
    )
    caught_admin_token = any(
        k in adv_blockers for k in ["GLOBAL_ADMIN_TOKEN", "管理员", "全权限", "admin:*"]
    )
    caught_trifecta = any(
        k in adv_blockers
        for k in ["fetch_untrusted_webpage", "send_external_email", "三要素", "注入", "外发"]
    )
    rejects_launch = any(k in adv_report for k in ["不建议上线", "否（", "禁止上线", "不可上线"])
    safe_zero_blockers = len(_extract_blocker_lines(safe_report)) == 0
    lists_missing_info = any(k in incomplete_report for k in ["补充", "信息不足", "核实"])

    red_blue_ok = (
        caught_wildcard_del
        and caught_admin_token
        and caught_trifecta
        and rejects_launch
        and safe_zero_blockers
        and lists_missing_info
    )
    v.check(
        "高危坏例对抗拦截（通配符删除/全权限令牌/致命三要素 100% 标为 BLOCKER）与良性样本零误杀",
        red_blue_ok,
        "请在输出格式中明确定义 BLOCKER 判定红线（通配符物理删除、全局管理员令牌、不可信输入+私密数据+对外发信三要素叠加），确保高危坏例三项均标 BLOCKER 且不建议上线，同时在信息不足时列出待补充项。",
    )
  except Exception as exc:
    v.check(
        "高危坏例对抗拦截（通配符删除/全权限令牌/致命三要素 100% 标为 BLOCKER）与良性样本零误杀",
        False,
        f"执行红蓝对抗审校测试抛出异常（{type(exc).__name__}: {exc}）。",
    )

  # 验收项 4：结构化表格契约与只读审校安全约束（严禁直接覆盖业务代码/配置）
  constraints_ok = (
      caps["has_severity_tiers"]
      and caps["has_table_spec"]
      and caps["has_launch_verdict"]
      and caps["has_no_guess_rule"]
      and caps["has_readonly_rule"]
  )
  v.check(
      "结构化分级表格契约与只读审校约束（不臆测、不直接改动原代码与配置）",
      constraints_ok,
      "请补充标准表格头（| 严重级别 | 工具 | 问题 | 依据 | 修改建议 |）、BLOCKER/MAJOR/MINOR 说明、是否建议上线结论，并在约束中写明“信息不足不要猜测”及“只给修改建议，不直接改动代码或配置”。",
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
