#!/usr/bin/env python3
"""S1-M10 实验验收脚本：销售会议转写稿去噪分块、五要素低温抽取、未核实锁与原话时间戳子串硬核验。"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_mod(path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location("s1_m10_mod", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    v = LabVerifier("S1-M10", "销售与项目会议转写稿提纯：商机五要素抽取与客户原话时间戳硬核验")
    mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
    data = json.loads((LAB_DIR / "fixtures" / "meeting_transcripts.json").read_text(encoding="utf-8"))
    meetings = data["meetings"]
    mtg1, mtg2 = meetings[0], meetings[1]

    try:
        src_text = mod_path.read_text(encoding="utf-8")
        mod = _load_mod(mod_path)
    except Exception as exc:
        v.check("目标模块加载检查", False, f"导入 {mod_path.name} 失败：{exc}")
        v.finish()
        return

    # Check 1: 口水话去噪与全时段分块覆盖（不截断第41分钟收尾待办）
    try:
        chunks = mod.clean_and_chunk_transcript(mtg1)
        joined = "\n".join(chunks)
        removed_filler = ("手冲咖啡豆" not in joined) and ("高架太堵" not in joined)
        kept_tail = ("29:50" in joined) and ("41:10" in joined) and ("200坐席" in joined)
        passed_c1 = isinstance(chunks, list) and len(chunks) >= 2 and removed_filler and kept_tail
        v.check(
            "45 分钟长纪要口水话去噪与全时段分块覆盖（剥离堵车/咖啡闲聊且完整保留 [29:50] 与 [41:10] 后半场内容）",
            passed_c1,
            "请完善 clean_and_chunk_transcript：剔除纯寒暄调试废话，切勿按前 350 字硬截断，需按发言分块覆盖至 [41:10] 会末待办。",
        )
    except Exception as exc:
        v.check("45 分钟长纪要口水话去噪与全时段分块覆盖（剥离堵车/咖啡闲聊且完整保留 [29:50] 与 [41:10] 后半场内容）", False, f"运行异常：{exc}")

    # Check 2: 低温采样（temperature=0.0）与禁打主观成交率
    try:
        uses_zero_temp = ("temperature=0.0" in src_text or "temperature = 0.0" in src_text) and ("temperature=0.8" not in src_text)
        card1 = mod.extract_crm_deal_card(mtg1)
        no_win_prob = isinstance(card1, dict) and all(
            k not in card1 for k in ("win_probability", "deal_score", "close_rate", "成交率")
        )
        passed_c2 = uses_zero_temp and no_win_prob
        v.check(
            "无状态 API 低温确定性抽取（temperature=0.0）且彻底移除主观成交率打分字段",
            passed_c2,
            "请将 chat_complete 调用设为 temperature=0.0，并在输出与校验器中严禁出现 win_probability 等主观猜测成交率字段。",
        )
    except Exception as exc:
        card1 = {}
        v.check("无状态 API 低温确定性抽取（temperature=0.0）且彻底移除主观成交率打分字段", False, f"运行异常：{exc}")

    # Check 3: 未提预算诚实标 UNVERIFIED / "未核实" 严禁脑补金额
    try:
        b1 = card1.get("budget", {}) if isinstance(card1, dict) else {}
        card2 = mod.extract_crm_deal_card(mtg2)
        b2 = card2.get("budget", {}) if isinstance(card2, dict) else {}
        c2 = card2.get("competitors", {}) if isinstance(card2, dict) else {}
        passed_c3 = (
            b1.get("status") == "UNVERIFIED"
            and b1.get("value") == "未核实"
            and b2.get("status") == "UNVERIFIED"
            and b2.get("value") == "未核实"
            and c2.get("status") == "UNVERIFIED"
            and c2.get("value") == "未核实"
        )
        v.check(
            "缺据项防脑补锁（客户未透露明确预算或竞品时强制标 UNVERIFIED / '未核实'，零编造金额）",
            passed_c3,
            "MTG-01 预算未定、MTG-02 预算与竞品均未定，必须严格输出 status='UNVERIFIED' 且 value='未核实'，严禁瞎猜 '50万元'。",
        )
    except Exception as exc:
        card2 = {}
        v.check("缺据项防脑补锁（客户未透露明确预算或竞品时强制标 UNVERIFIED / '未核实'，零编造金额）", False, f"运行异常：{exc}")

    # Check 4: 商机五要素完整性与精确时间戳命中（含会末 [41:10] 下一步）
    try:
        exp1 = mtg1["expected"]
        ts_ok = all(
            isinstance(card1.get(f), dict)
            and card1[f].get("status") == "VERIFIED"
            and card1[f].get("timestamp") == exp_ts
            for f, exp_ts in exp1["verified_timestamps"].items()
        )
        kw_ok = (
            all(k in card1["decision_maker"]["value"] for k in exp1["decision_maker_keywords"])
            and all(k in card1["pain_points"]["value"] for k in exp1["pain_points_keywords"])
            and all(k in card1["competitors"]["value"] for k in exp1["competitors_keywords"])
            and all(k in card1["next_steps"]["value"] for k in exp1["next_steps_keywords"])
        )
        passed_c4 = ts_ok and kw_ok
        v.check(
            "商机五要素全覆盖抽取（精准命中拍板人会签、断货痛点、[29:50] 竞品与 [41:10] 下一步待办）",
            passed_c4,
            "请确保 MTG-01 的 decision_maker(14:15)、pain_points(08:20)、competitors(29:50)、next_steps(41:10) 全部准确抽取并绑定正确时间戳。",
        )
    except Exception as exc:
        v.check("商机五要素全覆盖抽取（精准命中拍板人会签、断货痛点、[29:50] 竞品与 [41:10] 下一步待办）", False, f"校验异常：{exc}")

    # Check 5: verify_crm_card 代码级原话逐字子串与伪造时间戳硬拦截测试
    try:
        blocked_tampered_quote = False
        blocked_fake_ts = False
        blocked_win_rate = False

        if isinstance(card1, dict) and "decision_maker" in card1:
            bad_quote_card = copy.deepcopy(card1)
            bad_quote_card["decision_maker"]["status"] = "VERIFIED"
            bad_quote_card["decision_maker"]["timestamp"] = "14:15"
            bad_quote_card["decision_maker"]["exact_quote"] = "陈总表示他一个人签字就能直接打款不需要安全部管"
            try:
                mod.verify_crm_card(bad_quote_card, mtg1)
            except ValueError:
                blocked_tampered_quote = True

            bad_ts_card = copy.deepcopy(card1)
            bad_ts_card["pain_points"]["status"] = "VERIFIED"
            bad_ts_card["pain_points"]["timestamp"] = "99:99"
            try:
                mod.verify_crm_card(bad_ts_card, mtg1)
            except ValueError:
                blocked_fake_ts = True

            bad_subj_card = copy.deepcopy(card1)
            bad_subj_card["win_probability"] = "90%"
            try:
                mod.verify_crm_card(bad_subj_card, mtg1)
            except ValueError:
                blocked_win_rate = True

        passed_c5 = blocked_tampered_quote and blocked_fake_ts and blocked_win_rate
        v.check(
            "代码端确定性硬核验器（篡改 1 句客户原话、伪造时间戳或夹带主观成交率均当场抛出 ValueError 拦截）",
            passed_c5,
            "请完善 verify_crm_card(card, meeting)：1) 拦截 win_probability 等主观字段；2) 校验 timestamp 存在于原纪要；3) 校验 exact_quote（≥8字）必须是该时间戳发言的逐字子串，不匹配立即 raise ValueError。",
        )
    except Exception as exc:
        v.check("代码端确定性硬核验器（篡改 1 句客户原话、伪造时间戳精确匹配均当场抛出 ValueError 拦截）", False, f"校验异常：{exc}")

    v.finish()


if __name__ == "__main__":
    main()
