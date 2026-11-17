#!/usr/bin/env python3
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
from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def extract_top_section(markdown_text: str, section_prefix: str) -> str:
    """按顶层标题（## 一、... ~ ## 五、...）提取对应章节内容。"""
    lines = markdown_text.splitlines()
    captured: list[str] = []
    in_section = False
    top_heading_re = re.compile(r"^##\s+[一二三四五1-5][、\.]")
    for line in lines:
        stripped = line.strip()
        if top_heading_re.match(stripped):
            if section_prefix in stripped:
                in_section = True
                continue
            if in_section:
                break
        if in_section:
            captured.append(line)
    return "\n".join(captured).strip()


def has_todo_placeholder(text: str) -> bool:
    return bool(re.search(r"\bTODO\b|待填写|当前反面基线", text, flags=re.IGNORECASE))


def extract_json_blocks(markdown_text: str) -> list[dict[str, Any]]:
    blocks = re.findall(r"```json\s*(.*?)```", markdown_text, flags=re.DOTALL | re.IGNORECASE)
    parsed: list[dict[str, Any]] = []
    for raw in blocks:
        try:
            obj = json.loads(raw.strip())
            if isinstance(obj, dict):
                parsed.append(obj)
        except Exception:
            continue
    return parsed


def is_valid_agent_card(card: dict[str, Any]) -> bool:
    name = card.get("name")
    url = card.get("url")
    auth = card.get("authentication")
    skills = card.get("skills")

    if not isinstance(name, str) or not name.strip() or "TODO" in name.upper():
        return False
    if not isinstance(url, str) or not url.strip().startswith(("https://", "http://")):
        return False
    if not isinstance(auth, dict):
        return False
    schemes = auth.get("schemes")
    if not isinstance(schemes, list) or not schemes or not all(isinstance(s, str) and s.strip() for s in schemes):
        return False
    if not isinstance(skills, list) or not skills:
        return False
    for sk in skills:
        if not isinstance(sk, dict):
            return False
        sk_id = sk.get("id")
        sk_desc = sk.get("description")
        if not isinstance(sk_id, str) or not sk_id.strip() or "TODO" in sk_id.upper():
            return False
        if not isinstance(sk_desc, str) or not sk_desc.strip() or "TODO" in sk_desc.upper():
            return False
    return True


def main() -> int:
    v = LabVerifier("S4-M06", "单双架构对比与 A2A 取舍实验")
    doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
    rubric_path = LAB_DIR / "fixtures" / "architecture_rubric.json"
    proposal_path = LAB_DIR / "fixtures" / "flawed_team_proposal.md"

    try:
        doc_text = doc_path.read_text(encoding="utf-8")
        rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
        _proposal_text = proposal_path.read_text(encoding="utf-8")
    except Exception as exc:
        v.check("架构文档与 fixtures 评审标准读取", False, f"读取失败：{exc}")
        return v.finish()

    sec1 = extract_top_section(doc_text, "一、")
    sec2 = extract_top_section(doc_text, "二、")
    sec3 = extract_top_section(doc_text, "三、")
    sec4 = extract_top_section(doc_text, "四、")
    sec5 = extract_top_section(doc_text, "五、")

    # 验收项 1：理论与协议边界辨析（Anthropic vs Cognition、Handoff vs 契约委派、MCP vs A2A）
    try:
        theory_area = f"{sec1}\n{sec2}"
        no_todo_1 = bool(sec1) and bool(sec2) and not has_todo_placeholder(theory_area)
        has_cognition_principles = ("共享上下文" in theory_area) and any(
            k in theory_area for k in ("隐含设计决策", "隐含决策", "行动隐含")
        )
        has_parallel_basis = any(k in theory_area for k in ("广度优先", "独立", "无写冲突", "物理隔离"))
        has_handoff_vs_contract = any(k in theory_area for k in ("Handoff", "交接")) and (
            "契约" in theory_area and any(k in theory_area for k in ("委派", "委托"))
        )
        has_mcp_vs_a2a = (
            ("MCP" in theory_area)
            and ("A2A" in theory_area)
            and any(k in theory_area for k in ("不透明", "Opaque", "黑盒"))
            and any(k in theory_area for k in ("input-required", "需要补充输入", "需要输入"))
        )
        ok_1 = (
            no_todo_1
            and has_cognition_principles
            and has_parallel_basis
            and has_handoff_vs_contract
            and has_mcp_vs_a2a
        )
    except Exception:
        ok_1 = False

    v.check(
        "理论与协议边界：讲清并行/串行判断依据（共享上下文与隐含决策）、Handoff vs 按契约委派，以及 MCP vs A2A（含不透明性与 input-required 状态）",
        ok_1,
        "请在第一、二章节清掉 TODO，写明适合并行与必须单兵串行的依据（含共享上下文与行动隐含决策），区分 Handoff 与按契约委派，并划清本地工具走 MCP、跨部门不透明合规 Agent 走 A2A（含 input-required 状态）。",
    )

    # 验收项 2：真实项目 A/B 双版架构草图及共享状态/交接点标注
    try:
        no_todo_2 = bool(sec3) and not has_todo_placeholder(sec3)
        has_plan_a = any(k in sec3 for k in ("A 版", "方案 A")) and any(
            k in sec3 for k in ("单智能体", "单兵", "Single")
        )
        has_plan_b = any(k in sec3 for k in ("B 版", "方案 B")) and any(
            k in sec3 for k in ("编排者", "Orchestrator")
        ) and any(k in sec3 for k in ("隔离工作区", "worktree", "子智能体", "Sub-Agent"))
        marks_state_and_boundary = ("共享状态" in sec3) and any(
            k in sec3 for k in ("交接点", "契约边界")
        )
        has_diagram_arrows = any(sym in sec3 for sym in ("-->", "->", "▼", "┌", "│"))
        ok_2 = no_todo_2 and has_plan_a and has_plan_b and marks_state_and_boundary and has_diagram_arrows
    except Exception:
        ok_2 = False

    v.check(
        "A/B 双版架构草图：同时绘制单兵串行闭环（A 版）与编排者+隔离工作区多智能体（B 版）简图，并显式标出共享状态与交接点",
        ok_2,
        "请在「三、项目 A/B 双版架构草图」中画出 A 版与 B 版两张流程框图，并在图中明确标注【共享状态】与【交接点/契约边界】。",
    )

    # 验收项 3：四维量化评分矩阵（1–5 分制）
    try:
        required_dims: list[str] = rubric["scoring_dimensions"]
        no_todo_3 = bool(sec4) and not has_todo_placeholder(sec4)
        dim_scored_all = True
        for dim in required_dims:
            matching_lines = [ln for ln in sec4.splitlines() if dim in ln]
            if not matching_lines:
                dim_scored_all = False
                break
            scores = re.findall(r"(?<!\d)[1-5](?:\.\d)?(?!\d)", matching_lines[0])
            if len(scores) < 2:
                dim_scored_all = False
                break
        ok_3 = no_todo_3 and dim_scored_all
    except Exception:
        ok_3 = False

    v.check(
        "四维量化评分表：完整对「子任务可解耦度、上下文共享紧密度、成本与延迟敏感度、调试排障复杂度」给出 A/B 双版 1–5 分打分",
        ok_3,
        "请在「四、四维量化评分表」中将所有 TODO 替换为 1–5 分的具体打分与结合业务约束（120 PR/周、≤35s、≤$0.08）的测算理由。",
    )

    # 验收项 4：明确选型结论与触发架构改选的量化阈值条件
    try:
        no_todo_4 = bool(sec4) and not has_todo_placeholder(sec4)
        has_clear_choice = any(k in sec4 for k in ("选型结论", "最终选型", "坚定选型", "推荐采用")) and (
            "A 版" in sec4 or "单智能体" in sec4
        )
        has_switch_threshold = any(k in sec4 for k in ("阈值", "触发条件", "改选")) and any(
            k in sec4 for k in ("多仓", "微服务", "契约", "Tokens", "预算")
        ) and bool(re.search(r"\d+", sec4))
        ok_4 = no_todo_4 and has_clear_choice and has_switch_threshold
    except Exception:
        ok_4 = False

    v.check(
        "选型拍板与改选阈值：给出明确选型结论，并写清触发从 A 版改选 B 版的具体量化阈值条件",
        ok_4,
        "请在第四章节下方写明最终选型结论（当前常规单仓 PR 选 A 版），并给出触发切换为 B 版多智能体架构的量化条件（如跨仓数量、接口契约冻结、上下文规模与预算/延迟阈值）。",
    )

    # 验收项 5：A2A Agent Card JSON 草案四要素校验
    try:
        target_area = sec5 or doc_text
        cards = extract_json_blocks(target_area)
        ok_5 = any(is_valid_agent_card(c) for c in cards)
    except Exception:
        ok_5 = False

    v.check(
        "A2A Agent Card 草案：输出合法 JSON 且完整包含 name、url、authentication（含 schemes）、skills（含 id 与 description）四要素",
        ok_5,
        "请在「五、外部协办 A2A Agent Card 草案」的 ```json 代码块中补齐合法的 name、url（https://...）、authentication.schemes 数组及非空的 skills（每项含 id 与 description）。",
    )

    return v.finish()


if __name__ == "__main__":
    main()
