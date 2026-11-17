#!/usr/bin/env python3
"""S1-M08 实验验收脚本：纯中文双盲互换盲测、四维量化对比与事前验尸排雷校验。"""

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


def _extract_xml_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def _swap_alpha_beta(prompt_text: str) -> str:
    alpha = _extract_xml_tag(prompt_text, "plan_alpha")
    beta = _extract_xml_tag(prompt_text, "plan_beta")
    if not alpha or not beta:
        return prompt_text
    swapped = re.sub(
        r"<plan_alpha>.*?</plan_alpha>",
        lambda _: f"<plan_alpha>\n{beta}\n</plan_alpha>",
        prompt_text,
        count=1,
        flags=re.DOTALL,
    )
    swapped = re.sub(
        r"<plan_beta>.*?</plan_beta>",
        lambda _: f"<plan_beta>\n{alpha}\n</plan_beta>",
        swapped,
        count=1,
        flags=re.DOTALL,
    )
    return swapped


def _mock_ab_reviewer(messages: list[dict[str, str]]) -> str:
    prompt = "\n".join(m.get("content", "") for m in messages)
    alpha = _extract_xml_tag(prompt, "plan_alpha")
    beta = _extract_xml_tag(prompt, "plan_beta")
    has_constraints = ("1,500" in prompt or "1500" in prompt) and ("4 小时" in prompt or "4小时" in prompt)
    has_bias = any(b in prompt for b in ["我个人更偏向", "新潮高大上", "偷懒的老办法"])

    if not alpha or not beta or not has_constraints or has_bias:
        return "两个方案各有千秋，排在前面的方案看着更顺眼，建议结合团队实际情况灵活选择即可。"

    if ("899" in alpha or "699" in alpha or "托管" in alpha) and ("1,850" in beta or "1850" in beta):
        winner_slot = "<plan_alpha>（托管式成熟知识库 SaaS + 标准 API 网关）"
    elif ("899" in beta or "699" in beta or "托管" in beta) and ("1,850" in alpha or "1850" in alpha):
        winner_slot = "<plan_beta>（托管式成熟知识库 SaaS + 标准 API 网关）"
    else:
        winner_slot = "各有千秋"

    return (
        "1. 隐含假设：托管方案依赖跨页 PDF 解析准确率；自建集群依赖超预算批复与专职排障时间。\n"
        "2. 事前验尸：托管方案死于复杂表格切碎答错；自建方案死于月超支（1,850 > 1,500）及大促索引崩溃无人修。\n"
        "3. 维度对比：实现复杂度（低 vs 高）、故障排查难度（低 vs 极高）、边际成本（899 vs 1,850）、演进退出成本（可控导出 vs 高沉没成本）。\n"
        f"4. 有条件推荐：唯一推荐 {winner_slot}；一旦跨页表格实测准确率低于 80% 或合规禁止公有 SaaS 且预算提至 3,500 元以上，则推翻本结论改选另一方案。"
    )


def _safe_chat_complete(messages: list[dict[str, str]]) -> str:
    try:
        return chat_complete(messages, mock_fn=_mock_ab_reviewer, temperature=0.0)
    except Exception:
        return _mock_ab_reviewer(messages)


def _detect_underlying_winner(reply: str, alpha_text: str, beta_text: str) -> str:
    tail = reply[-320:] if len(reply) > 320 else reply
    if "各有千秋" in tail:
        return "fence_sitting"
    if "托管" in tail and ("SaaS" in tail or "网关" in tail):
        return "saas"
    if "<plan_alpha>" in tail:
        return "saas" if "托管" in alpha_text else "k8s"
    if "<plan_beta>" in tail:
        return "saas" if "托管" in beta_text else "k8s"
    return "unknown"


def main() -> None:
    v = LabVerifier("S1-M08", "B2B 供应商与技术方案二选一：双盲位置互换 + 事前验尸选型评审")

    try:
        target_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
        fixture_path = LAB_DIR / "fixtures" / "ab_candidates.json"
        if not target_path.is_file():
            v.check("目标实验文件存在性检查", False, f"未找到 {target_path.name}。")
            v.finish()
            return

        md_text = target_path.read_text(encoding="utf-8")
        fixture_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        primary = next(
            s for s in fixture_data["scenarios"] if s["id"] == fixture_data["primary_scenario_id"]
        )
    except Exception as exc:
        v.check("实验素材与目标文件加载", False, f"读取异常：{exc}")
        v.finish()
        return

    sec1 = _extract_section(md_text, "一")
    sec2 = _extract_section(md_text, "二")
    sec3 = _extract_section(md_text, "三")

    # Check 1: 匿名双盲声明、硬约束与清零倾向性标签
    try:
        has_blind_notice = any(k in sec1 for k in ["外部投稿", "匿名候选方案"]) and any(
            k in sec1 for k in ["无偏好", "请勿猜测或迎合"]
        )
        has_constraints = (
            ("业务目标" in sec1)
            and ("资源与维护约束" in sec1)
            and ("非目标" in sec1)
            and not any(ph in sec1 for ph in ["{goal}", "{constraints}", "{non_goals}", "{plan_a}", "{plan_b}"])
        )
        alpha_body = _extract_xml_tag(sec1, "plan_alpha")
        beta_body = _extract_xml_tag(sec1, "plan_beta")
        has_both_plans = len(alpha_body) >= 30 and len(beta_body) >= 30

        biased_hits = [b for b in primary["biased_framing_examples"] if b in sec1]
        passed_c1 = has_blind_notice and has_constraints and has_both_plans and (len(biased_hits) == 0)
        v.check(
            "纯中文双盲匿名框架（无偏好声明 + 硬约束/非目标 + <plan_alpha>/<plan_beta> 清零主观标签）",
            passed_c1,
            (
                f"第一节需包含外部投稿无偏好声明、填好客观参数的业务目标/资源与维护约束/非目标、<plan_alpha> 与 <plan_beta> 候选块，"
                f"并彻底删除倾向词（当前命中：{biased_hits or '无，但缺少双盲标签或硬约束'}）。"
            ),
        )
    except Exception as exc:
        v.check("纯中文双盲匿名框架（无偏好声明 + 硬约束/非目标 + <plan_alpha>/<plan_beta> 清零主观标签）", False, f"校验异常：{exc}")

    # Check 2: 四步有序评审协议与四维量化指标
    try:
        idx1 = sec1.find("隐含假设")
        idx2 = sec1.find("事前验尸")
        idx3 = sec1.find("对比表")
        idx4 = sec1.find("有条件推荐")
        ordered_4_steps = (-1 < idx1 < idx2 < idx3 < idx4)

        dims = ["实现复杂度", "故障排查难度", "边际成本", "演进退出成本"]
        missing_dims = [d for d in dims if d not in sec1]
        has_reversal_ask = any(k in sec1 for k in ["推翻本结论", "改选另一方案", "什么信号"])

        passed_c2 = ordered_4_steps and (len(missing_dims) == 0) and has_reversal_ask
        v.check(
            "四步结构化评审协议（隐含假设 → 事前验尸 → 四维量化对比表 → 禁端水有条件推荐）",
            passed_c2,
            (
                f"请在第一节严格按顺序写出 4 个评审步骤，补齐对比表四项维度（当前缺失：{missing_dims or '无'}），"
                "并要求给出唯一二选一推荐及“出现什么信号推翻本结论改选另一方案”。"
            ),
        )
    except Exception as exc:
        v.check("四步结构化评审协议（隐含假设 → 事前验尸 → 四维量化对比表 → 禁端水有条件推荐）", False, f"校验异常：{exc}")

    # Check 3: 执行 <plan_alpha>/<plan_beta> 正反两轮互换盲测，检验结论一致性与禁端水
    try:
        prompt_r1 = sec1
        prompt_r2 = _swap_alpha_beta(sec1)
        alpha_r1 = _extract_xml_tag(prompt_r1, "plan_alpha")
        beta_r1 = _extract_xml_tag(prompt_r1, "plan_beta")
        alpha_r2 = _extract_xml_tag(prompt_r2, "plan_alpha")
        beta_r2 = _extract_xml_tag(prompt_r2, "plan_beta")

        reply_r1 = _safe_chat_complete([{"role": "user", "content": prompt_r1}])
        reply_r2 = _safe_chat_complete([{"role": "user", "content": prompt_r2}])

        win_r1 = _detect_underlying_winner(reply_r1, alpha_r1, beta_r1)
        win_r2 = _detect_underlying_winner(reply_r2, alpha_r2, beta_r2)

        sandbox_consistent = (
            bool(alpha_r1 and beta_r1 and prompt_r1 != prompt_r2)
            and win_r1 == "saas"
            and win_r2 == "saas"
        )
        recorded_both_rounds = (
            ("第 1 轮" in sec2)
            and ("第 2 轮" in sec2)
            and ("<plan_alpha>" in sec2 and "<plan_beta>" in sec2)
            and ("灵活选择即可" not in sec2)
            and ("摇摆漂移" not in sec2)
        )

        passed_c3 = sandbox_consistent and recorded_both_rounds
        mode_tag = "参考模板" if use_solution() else "当前模板"
        v.check(
            "甲乙位置互换双盲一致性检验（正反两轮盲测锁定同一方案，拒绝“各有千秋”端水）",
            passed_c3,
            (
                f"{mode_tag}正反互换盲测结果：第 1 轮={win_r1}，第 2 轮={win_r2}。"
                "请确保第一节写清 1,500 元月预算与每周 4 小时兼职维护硬约束，并在第二节真实记录正向（SaaS 为甲）与互换（SaaS 为乙）两轮一致胜出的对照结果。"
            ),
        )
    except Exception as exc:
        v.check("甲乙位置互换双盲一致性检验（正反两轮盲测锁定同一方案，拒绝“各有千秋”端水）", False, f"沙盒运行异常：{exc}")

    # Check 4: 事前验尸高致命风险路径与量化推翻信号
    try:
        has_premortem_detail = (
            any(k in sec3 for k in ["跨页", "表格", "切碎", "解析"])
            and any(k in sec3 for k in ["导出", "涨价", "迁移", "内存溢出", "超支"])
        )
        has_trigger_signal = (
            any(k in sec3 for k in ["推翻", "改选"])
            and any(k in sec3 for k in ["80%", "75%", "准确率", "合规", "3,500", "3500"])
        )

        passed_c4 = has_premortem_detail and has_trigger_signal
        v.check(
            "事前验尸致命风险拆解与可证伪推翻条件（Pre-mortem & Reversal Signal）",
            passed_c4,
            (
                "请在第三节写明半年后系统被废弃的具体死法（如托管 SaaS 跨页复杂 PDF 表格切碎答错、导出元数据锁死 vs 自建集群超支崩溃），"
                "并给出可量化的推翻触发信号（如跨页表格抽测准确率低于 80% 或新增合规红线且预算上调）。"
            ),
        )
    except Exception as exc:
        v.check("事前验尸致命风险拆解与可证伪推翻条件（Pre-mortem & Reversal Signal）", False, f"校验异常：{exc}")

    # Check 5: 课后 30 分钟内可完成的最小排雷验证动作
    try:
        has_timebox = any(k in sec3 for k in ["30 分钟", "30分钟", "25 分钟", "20 分钟"])
        has_concrete_verb = (
            any(k in sec3 for k in ["试用", "上传", "实测"])
            and any(k in sec3 for k in ["全量导出", "导出", "PDF", "工单"])
        )
        not_placeholder = "待补充可执行动作" not in sec3

        passed_c5 = has_timebox and has_concrete_verb and not_placeholder
        v.check(
            "课后 30 分钟最小排雷验证动作可执行性校验",
            passed_c5,
            (
                "请在第三节末尾设计一个课后 30 分钟内即可亲手跑通的排雷小动作（例如：注册免费试用版，上传 5 份复杂跨页退换货 PDF 表格实测 10 个工单问题，并点击全量导出检查文件完整性）。"
            ),
        )
    except Exception as exc:
        v.check("课后 30 分钟最小排雷验证动作可执行性校验", False, f"校验异常：{exc}")

    v.finish()


if __name__ == "__main__":
    main()
