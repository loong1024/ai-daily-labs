#!/usr/bin/env python3
"""S0-M10 实验验收脚本：看图纠错（先抄录防脑补）与日常贴资料 30 秒三步脱敏实测。"""

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


def _extract_section(md_text: str, section_num: str) -> str:
    pattern = rf"^##\s*{re.escape(section_num)}[、.．\s].*?(?=^##\s*[一二三四五六七八九十\d]+[、.．\s]|\Z)"
    match = re.search(pattern, md_text, flags=re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def _mock_vision_audit(messages: list[dict[str, str]]) -> str:
    prompt_text = "\n".join(m.get("content", "") for m in messages)
    has_row_copy = ("逐行" in prompt_text and "抄录" in prompt_text)
    has_unclear_rule = "[看不清]" in prompt_text
    if has_row_copy and has_unclear_rule:
        return (
            "【逐行抄录核对（第 2–5 行）】\n"
            "- 第 2 行 | 所属大区：华东大区 | 渠道分部/仓点：直营一组-上海仓 | 账面应结金额：136,000 | 核定退货扣款：7,600 | 实收净结算：128,400\n"
            "- 第 3 行 | 所属大区：华东大区（合并承接） | 渠道分部/仓点：苏南分部-苏州仓 | 账面应结金额：98,500 | 核定退货扣款：4,300 | 实收净结算：94,200\n"
            "- 第 4 行 | 所属大区：华东大区（合并承接） | 渠道分部/仓点：苏南分部-昆山仓 | 账面应结金额：82,000 | 核定退货扣款：[看不清] | 实收净结算：[看不清]\n"
            "- 第 5 行 | 所属大区：华东大区 | 渠道分部/仓点：浙北分部-杭州仓 | 账面应结金额：164,200 | 核定退货扣款：8,200 | 实收净结算：156,000\n\n"
            "【加总结论】\n"
            "- 已核实清晰行（第 2、3、5 行）实收净结算合计：378,600 元。\n"
            "- 待人工复核项：第 4 行（苏南分部-昆山仓）含 [看不清] 单元格，未计入自动合计。"
        )
    return (
        "已直接为您算出整张表各项合计：第 3 行串列读取为 4,300 元，"
        "第 4 行昆山仓模糊处为您估算扣款 1,800 元（实收 80,200 元），合计 458,800 元。"
    )


def _safe_chat_complete(messages: list[dict[str, str]]) -> str:
    try:
        return chat_complete(messages, mock_fn=_mock_vision_audit, temperature=0.0)
    except Exception:
        return _mock_vision_audit(messages)


def main() -> None:
    v = LabVerifier("S0-M10", "发截图读表总串行、怕泄密？看图纠错与脱敏实测")

    try:
        target_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
        snippets_path = LAB_DIR / "fixtures" / "sensitive_snippets.json"
        table_path = LAB_DIR / "fixtures" / "ocr_trap_table.md"

        if not target_path.is_file():
            v.check("目标实验文件存在性检查", False, f"未找到 {target_path.name}，请确认文件路径完整。")
            v.finish()
            return

        md_text = target_path.read_text(encoding="utf-8")
        fixture_data = json.loads(snippets_path.read_text(encoding="utf-8"))
        table_text = table_path.read_text(encoding="utf-8")
    except Exception as exc:
        v.check("实验素材与目标文件加载", False, f"读取文件异常：{exc}")
        v.finish()
        return

    sec1 = _extract_section(md_text, "一") or md_text
    sec2 = _extract_section(md_text, "二") or md_text
    sec3 = _extract_section(md_text, "三") or md_text
    sec4 = _extract_section(md_text, "四") or md_text

    # Check 1: 敏感词零残留 + 换真名/缩数字脱敏到位
    try:
        forbidden_leaks: list[str] = fixture_data.get("forbidden_raw_leaks", [])
        found_leaks = [item for item in forbidden_leaks if item in md_text]
        alias_tokens = ["甲公司", "乙公司", "某客户", "某连锁", "林某", "周某", "陈某", "张某"]
        alias_hits = sum(1 for tok in alias_tokens if tok in sec2)
        scale_tokens = ["同比例缩放", "按比例缩放", "占位", "已脱敏", "[凭证已移除]"]
        scale_hits = sum(1 for tok in scale_tokens if tok in sec2)

        passed_c1 = (len(found_leaks) == 0) and (alias_hits >= 3) and (scale_hits >= 2)
        leak_preview = "、".join(found_leaks[:5])
        v.check(
            "业务文本三步脱敏红线（清零真实公司名/姓名/手机号/底价与测试凭证）",
            passed_c1,
            (
                f"当前文件仍残留未脱敏敏感信息（如：{leak_preview}）或缺少脱敏占位替换。"
                "请按「换真名（甲公司/林某）+ 缩数字或占位符（同比例缩放/[合同底价占位]/[联系电话已脱敏]/[凭证已移除]）」彻底清理第二节。"
            ),
        )
    except Exception as exc:
        v.check("业务文本三步脱敏红线（清零真实公司名/姓名/手机号/底价与测试凭证）", False, f"校验异常：{exc}")

    # Check 2: 30秒三步口诀与隐私训练开关自检清单
    try:
        checked_count = len(re.findall(r"^\s*-\s*\[[xX]\]", sec3, flags=re.MULTILINE))
        unchecked_count = len(re.findall(r"^\s*-\s*\[\s\]", sec3, flags=re.MULTILINE))
        has_step_name = any(k in md_text for k in ["换真名", "甲公司", "某客户"])
        has_step_num = any(k in md_text for k in ["缩数字", "同比例缩放", "按比例缩放", "占位符"])
        has_step_privacy = any(k in md_text for k in ["数据控制", "改进模型", "临时无痕", "无痕会话", "训练开关", "查开关"])

        passed_c2 = (
            checked_count >= 4
            and unchecked_count == 0
            and has_step_name
            and has_step_num
            and has_step_privacy
        )
        v.check(
            "30 秒三步脱敏清单与隐私训练开关核查完备性",
            passed_c2,
            (
                f"当前第三节已完成勾选 {checked_count} 项、未完成空白项 {unchecked_count} 项。"
                "请补齐「换真名、缩数字、查开关（设置→数据控制/隐私→关闭允许将对话用于改进模型或开启临时无痕会话）」及识图裁剪检查项，并全部核实勾选为 [x]。"
            ),
        )
    except Exception as exc:
        v.check("30 秒三步脱敏清单与隐私训练开关核查完备性", False, f"校验异常：{exc}")

    # Check 3: 读表防算错黄金指令要素
    try:
        has_crop = any(k in sec1 for k in ["局部裁剪", "裁剪局部", "第 2–5 行", "第 2-5 行", "2–5 行", "2-5 行"])
        has_verbatim_copy = ("逐行" in sec1) and ("抄录" in sec1) and ("列名" in sec1)
        has_unclear_token = "[看不清]" in sec1
        has_order_rule = any(k in sec1 for k in ["核对无误后再", "先逐行", "先抄录", "再做加总"])

        passed_c3 = has_crop and has_verbatim_copy and has_unclear_token and has_order_rule
        v.check(
            "传表格截图防算错核心指令（局部裁剪 + 先逐行抄录列名与数值 + [看不清] 拒猜）",
            passed_c3,
            (
                "请在第一节读表提问模板中明确写入："
                "1) 只局部裁剪关键行（如第 2–5 行）而非直传超过 15 行的整图；"
                "2) 要求 AI 先逐行原样抄录【列名+数值】并注意合并单元格承接；"
                "3) 规定任何模糊单元格必须标为“[看不清]”，核对无误后再做加总计算。"
            ),
        )
    except Exception as exc:
        v.check("传表格截图防算错核心指令（局部裁剪 + 先逐行抄录列名与数值 + [看不清] 拒猜）", False, f"校验异常：{exc}")

    # Check 4: 结合 ocr_trap_table.md 跑通 chat_complete 识图防脑补沙盒实测
    try:
        audit_cfg = fixture_data["table_audit"]
        required_token = audit_cfg["required_unclear_token"]
        messages = [
            {"role": "system", "content": "你是严谨的表格核对助手，严格遵照用户的读表指令处理表格文本切片。"},
            {
                "role": "user",
                "content": f"{sec1}\n\n【待核对局部表格切片（第 2–5 行）】\n{table_text}",
            },
        ]
        sim_reply = _safe_chat_complete(messages)
        normalized_reply = sim_reply.replace(",", "")
        has_all_clear_nums = all(
            val.replace(",", "") in normalized_reply for val in audit_cfg["clear_net_values"]
        )
        caught_blurry = (required_token in sec1) and (required_token in sim_reply) and (
            audit_cfg["blurry_branch"] in sim_reply or "昆山" in sim_reply
        )

        passed_c4 = has_all_clear_nums and caught_blurry
        mode_tag = "参考答案" if use_solution() else "当前模板"
        v.check(
            "复杂表格识图沙盒实测（合并格对齐抄录 + 第 4 行反光盲区拦截）",
            passed_c4,
            (
                f"使用{mode_tag}驱动表格核对时未能拦截反光幻觉或漏抄清晰行数值。"
                "请确保第一节指令明确要求逐行抄录第 2–5 行【列名+数值】并将模糊处强制标为“[看不清]”，避免模型脑补昆山仓退货扣款。"
            ),
        )
    except Exception as exc:
        v.check("复杂表格识图沙盒实测（合并格对齐抄录 + 第 4 行反光盲区拦截）", False, f"沙盒运行异常：{exc}")

    # Check 5: 第四节两轮实测对照记录完备性
    try:
        sec4_norm = sec4.replace(",", "")
        has_failure_diag = (
            any(k in sec4 for k in ["合并单元格", "合并格", "串行", "串列"])
            and any(k in sec4 for k in ["脑补", "反光", "瞎猜", "捏造"])
        )
        has_clear_total = "378600" in sec4_norm
        has_pending_flag = ("[看不清]" in sec4) and ("昆山" in sec4)

        passed_c5 = has_failure_diag and has_clear_total and has_pending_flag
        v.check(
            "整图直传 vs 局部裁剪两轮对照复盘记录完整性",
            passed_c5,
            (
                "请在第四节完整记录两轮实测对比：1) 点明整图直传的「合并单元格串行」与「反光模糊数脑补」两大翻车点；"
                "2) 写明第 2、3、5 清晰行实收合计（378,600 元），并将第 4 行苏南分部-昆山仓标为“[看不清]”单独挂起复核。"
            ),
        )
    except Exception as exc:
        v.check("整图直传 vs 局部裁剪两轮对照复盘记录完整性", False, f"校验异常：{exc}")

    v.finish()


if __name__ == "__main__":
    main()
