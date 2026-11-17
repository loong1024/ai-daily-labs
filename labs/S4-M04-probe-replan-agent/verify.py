#!/usr/bin/env python3
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


def main() -> int:
    v = LabVerifier("S4-M04", "探针重规划提示词实测")
    md_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
    scenarios_path = LAB_DIR / "fixtures" / "sandbox_scenarios.json"
    quotes_path = LAB_DIR / "fixtures" / "vendor_quotes_raw.md"

    try:
        doc_text = md_path.read_text(encoding="utf-8")
        scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
        _quotes_raw = quotes_path.read_text(encoding="utf-8")
    except Exception as exc:
        v.check("实验文件与 fixtures 素材读取", False, f"读取文件失败：{exc}")
        return v.finish()

    sec1 = extract_top_section(doc_text, "一、") or doc_text
    sec2 = extract_top_section(doc_text, "二、")
    sec3 = extract_top_section(doc_text, "三、")
    sec4 = extract_top_section(doc_text, "四、")
    sec5 = extract_top_section(doc_text, "五、")

    # 验收项 1：系统提示词模板完备性
    try:
        no_todo_1 = bool(sec1) and not has_todo_placeholder(sec1)
        has_fast_track = any(k in sec1 for k in ("适用性判断", "繁简分流", "最简方式", "一两次工具")) and any(
            k in sec1 for k in ("不要展开", "不展开", "直接完成", "直接说明")
        )
        has_checklist_dod = all(k in sec1 for k in ("已完成", "进行中", "待办")) and any(
            k in sec1 for k in ("完成判定", "客观", "可检验", "证据")
        )
        has_replan = ("重规划" in sec1) and ("假设" in sec1) and any(
            k in sec1 for k in ("失效", "不符")
        ) and ("保留" in sec1)
        has_stop_rule = any(k in sec1 for k in ("不可逆", "删除", "发送", "付款", "打款")) and any(
            k in sec1 for k in ("立即停止", "停止并汇报", "暂停")
        )
        ok_1 = no_todo_1 and has_fast_track and has_checklist_dod and has_replan and has_stop_rule
    except Exception:
        ok_1 = False

    v.check(
        "系统提示词模板覆盖「繁简分流 + 外置状态清单 + 客观完成判定 + 假设失效重规划 + 不可逆停机」",
        ok_1,
        "请在「一、系统提示词模板」中清掉 TODO 与反面基线，补齐第 0 步繁简分流、带 [已完成/进行中/待办] 与客观完成判定的计划、假设失效重规划（保留有效成果）以及不可逆动作（发送/付款/删除/部署）立即停止规则。",
    )

    # 验收项 2：场景一（繁简分流对照）
    try:
        expected_date = scenarios["scenario_1_fast_track"]["expected_date"]
        no_todo_2 = bool(sec2) and not has_todo_placeholder(sec2)
        has_exact_date = expected_date in sec2
        no_bloated_checklist = ("[待办]" not in sec2) and ("步骤 3" not in sec2)
        ok_2 = no_todo_2 and has_exact_date and no_bloated_checklist
    except Exception:
        ok_2 = False

    v.check(
        f"实测一（繁简分流）：1 步提取任务直接输出准确举办日期（{scenarios['scenario_1_fast_track']['expected_date']}），无冗余待办清单",
        ok_2,
        "请在「二、实测一」中移除冗余的 [待办] 多步列表与 TODO，针对 1 步提取请求直接给出材料一中的准确日期 2026-10-24。",
    )

    # 验收项 3：场景二（只读探针查缺口与外置进度清单）
    try:
        no_todo_3 = bool(sec3) and not has_todo_placeholder(sec3)
        catches_vendor_c = any(k in sec3 for k in ("供应商 C", "极光空间", "QT-C-TMP"))
        catches_tax_gap = any(k in sec3 for k in ("含税", "税点", "税率", "开票另议"))
        catches_cancel_gap = any(k in sec3 for k in ("退改", "违约"))
        has_status_board = ("已完成" in sec3) and any(k in sec3 for k in ("进行中", "待办"))
        has_math_or_a_note = any(k in sec3 for k in ("108,000", "108000", "106,000", "106000"))
        ok_3 = (
            no_todo_3
            and catches_vendor_c
            and catches_tax_gap
            and catches_cancel_gap
            and has_status_board
            and has_math_or_a_note
        )
    except Exception:
        ok_3 = False

    v.check(
        "实测二（只读探针与外置清单）：精准揪出供应商 C 缺失含税与退改条款、核对金额口径并输出置顶状态表",
        ok_3,
        "请在「三、实测二」中先输出探针缺口报告（指出供应商 C 缺少含税/专票说明与退改签条款，核对供应商 A ¥108,000/¥106,000 口径），并附上标注 [已完成/进行中/待办] 的进度清单。",
    )

    # 验收项 4：场景三（突发材料撤回动态重规划）
    try:
        no_todo_4 = bool(sec4) and not has_todo_placeholder(sec4)
        mentions_b_withdrawn = any(k in sec4 for k in ("供应商 B", "星海创意", "QT-B-104"))
        states_invalid_assumption = any(k in sec4 for k in ("假设", "前提")) and any(
            k in sec4 for k in ("失效", "作废", "不成立")
        )
        retains_valid_work = any(k in sec4 for k in ("保留", "复用")) and any(
            k in sec4 for k in ("供应商 A", "云栖", "供应商 C", "极光")
        )
        updates_plan = any(k in sec4 for k in ("修订", "更新", "调整"))
        ok_4 = (
            no_todo_4
            and mentions_b_withdrawn
            and states_invalid_assumption
            and retains_valid_work
            and updates_plan
        )
    except Exception:
        ok_4 = False

    v.check(
        "实测三（突发撤回重规划）：先指明供应商 B 撤回导致哪条原假设失效，保留 A/C 有效成果并修订后续计划",
        ok_4,
        "请在「四、实测三」中先明确写出原计划哪条假设因供应商 B 撤回而失效，说明保留 A 与 C 的已有核验结论，并输出修订后的剩余计划（切勿编造 B 的替代数据）。",
    )

    # 验收项 5：场景四（不可逆动作止损 + 软约定 vs 硬护栏工程复盘）
    try:
        no_todo_5 = bool(sec5) and not has_todo_placeholder(sec5)
        halts_irreversible = any(k in sec5 for k in ("停止", "暂停", "拦截")) and any(
            k in sec5 for k in ("群发", "发送")
        ) and any(k in sec5 for k in ("打款", "付款"))
        asks_human_decision = any(k in sec5 for k in ("决定", "拍板", "人工", "确认"))
        distinguishes_soft_hard = any(k in sec5 for k in ("软约定", "软约束")) and any(
            k in sec5 for k in ("硬护栏", "硬停机")
        ) and any(k in sec5 for k in ("代码", "平台", "网关", "程序"))
        ok_5 = no_todo_5 and halts_irreversible and asks_human_decision and distinguishes_soft_hard
    except Exception:
        ok_5 = False

    v.check(
        "实测四（止损与护栏边界）：在群发与打款不可逆指令前停机征询决策，并讲清「提示词软约定 vs 程序硬护栏」",
        ok_5,
        "请在「五、实测四」中记录模型拦截群发通知与财务打款并请求人工拍板的输出，同时在复盘段明确对比「提示词软约定」与「代码/网关层硬护栏」的职责边界。",
    )

    return v.finish()


if __name__ == "__main__":
    main()
