#!/usr/bin/env python3
"""S1-M10 标准参考实现：销售与项目会议转写稿提纯、商机五要素低温抽取与原话时间戳硬核验。"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.aid_lab import chat_complete

FIVE_FIELDS = ("budget", "decision_maker", "pain_points", "competitors", "next_steps")
FORBIDDEN_SUBJECTIVE_KEYS = {"win_probability", "deal_score", "close_rate", "主观成交率", "成交率"}

FILLER_PATTERNS = (
    "听得清吗",
    "高架太堵",
    "茶水给大家",
    "投影转接头",
    "手冲咖啡豆",
    "消防演练的短会",
    "电梯里断了一下",
)


def is_filler_utterance(text: str) -> bool:
    business_anchors = ("预算", "拍板", "会签", "卡点", "痛点", "断货", "对比", "竞品", "下一步", "报价单", "总经理", "演示视频")
    if any(b in text for b in business_anchors):
        return False
    return any(p in text for p in FILLER_PATTERNS)


def clean_and_chunk_transcript(meeting: dict[str, Any], chunk_size: int = 3) -> list[str]:
    """剔除纯设备寒暄口水话，按发言边界分块并保留 [MM:SS] 时间戳，确保 45 分钟首尾 100% 覆盖。"""
    kept_lines: list[str] = []
    for u in meeting.get("utterances", []):
        txt = str(u.get("text", "")).strip()
        if not txt or is_filler_utterance(txt):
            continue
        kept_lines.append(f"[{u['ts']}] {u['speaker']}：{txt}")

    if not kept_lines:
        return []

    chunks: list[str] = []
    step = max(1, chunk_size)
    for idx in range(0, len(kept_lines), step):
        block = kept_lines[idx : idx + step]
        chunk_tag = f"CHUNK-{len(chunks) + 1:02d}"
        chunks.append(f"<{chunk_tag}>\n" + "\n".join(block) + f"\n</{chunk_tag}>")
    return chunks


def _deterministic_crm_mock(messages: list[dict[str, str]]) -> str:
    prompt = "\n".join(m.get("content", "") for m in messages)
    if "MTG-01" in prompt and "41:10" in prompt and "29:50" in prompt:
        return json.dumps({
            "meeting_id": "MTG-01",
            "budget": {
                "status": "UNVERIFIED",
                "value": "未核实",
                "timestamp": "19:05",
                "exact_quote": "预算这块集团财务还在做下半年总盘子切分，今天真给不出任何准数",
            },
            "decision_maker": {
                "status": "VERIFIED",
                "value": "供应链副总裁陈志远与集团信息安全部总监赵敏联合会签",
                "timestamp": "14:15",
                "exact_quote": "最终合同签字必须由我和集团信息安全部总监赵敏两个人联合会签才能过投委会",
            },
            "pain_points": {
                "status": "VERIFIED",
                "value": "每周手工合并12家代工厂Excel交期表耗时两天半，曾漏看预警致华东总仓断货三天",
                "timestamp": "08:20",
                "exact_quote": "跟单员每周要手工合并12家代工厂的Excel交期表耗掉整整两天半，上个月还因为漏看一行延误预警导致华东总仓断货三天",
            },
            "competitors": {
                "status": "VERIFIED",
                "value": "同步对比帆软定制报表方案与现用头部ERP原厂供应链协同插件",
                "timestamp": "29:50",
                "exact_quote": "技术组正在同步对比帆软定制报表方案，还有现用头部ERP原厂自带的供应链协同插件",
            },
            "next_steps": {
                "status": "VERIFIED",
                "value": "本周五17:00前发私有化安全架构白皮书与200坐席阶梯报价单，下周三下午两点双方信安技术评审",
                "timestamp": "41:10",
                "exact_quote": "本周五17:00前把私有化安全架构白皮书和200坐席阶梯报价单发到吴工邮箱，下周三下午两点安排双方信息安全团队做线上技术评审",
            },
        }, ensure_ascii=False)

    if "MTG-02" in prompt and "21:40" in prompt:
        return json.dumps({
            "meeting_id": "MTG-02",
            "budget": {
                "status": "UNVERIFIED",
                "value": "未核实",
                "timestamp": "12:20",
                "exact_quote": "采购预算没定，市面上其他家系统我也还没开始看",
            },
            "decision_maker": {
                "status": "VERIFIED",
                "value": "总经理刘总（下月出差归来听汇报拍板）",
                "timestamp": "12:20",
                "exact_quote": "最终拍板肯定得等我们总经理刘总下月出差回来听汇报",
            },
            "pain_points": {
                "status": "VERIFIED",
                "value": "85家门店督导巡店发微信群照片，月底无法统计冷链温控整改超时",
                "timestamp": "05:45",
                "exact_quote": "我们85家门店督导巡店全发微信群照片，月底根本没法统计哪家冷链温控整改超时",
            },
            "competitors": {
                "status": "UNVERIFIED",
                "value": "未核实",
                "timestamp": "12:20",
                "exact_quote": "采购预算没定，市面上其他家系统我也还没开始看",
            },
            "next_steps": {
                "status": "VERIFIED",
                "value": "明天中午前发送连锁药房GSP冷链巡检标准演示视频供周会评估",
                "timestamp": "21:40",
                "exact_quote": "明天中午前先发一份连锁药房GSP冷链巡检标准演示视频给我",
            },
        }, ensure_ascii=False)

    raise ValueError("输入转写稿分块不完整，缺少关键后半场切片。")


def verify_crm_card(card: dict[str, Any], meeting: dict[str, Any]) -> dict[str, Any]:
    """代码端硬核验：拦截主观成交率字段、核查未核实出口、逐字比对原话子串与 [MM:SS] 时间戳。"""
    if not isinstance(card, dict):
        raise ValueError("CRM 商机卡片必须是 JSON 对象")

    bad_keys = FORBIDDEN_SUBJECTIVE_KEYS.intersection(card.keys())
    if bad_keys:
        raise ValueError(f"严禁输出主观臆测成交率字段：{sorted(bad_keys)}")

    ts_to_text: dict[str, list[str]] = {}
    for u in meeting.get("utterances", []):
        ts = str(u.get("ts", "")).strip()
        ts_to_text.setdefault(ts, []).append(str(u.get("text", "")))

    for field in FIVE_FIELDS:
        item = card.get(field)
        if not isinstance(item, dict):
            raise ValueError(f"缺少商机要素结构化对象：{field}")
        status = item.get("status")
        val = str(item.get("value", "")).strip()
        ts = str(item.get("timestamp", "")).strip()
        quote = str(item.get("exact_quote", "")).strip()

        if status not in ("VERIFIED", "UNVERIFIED"):
            raise ValueError(f"{field}.status 非法：{status}")

        if status == "UNVERIFIED":
            if val != "未核实":
                raise ValueError(f"{field} 处于 UNVERIFIED 状态时，value 必须严格为 '未核实'（当前：{val}）")
            if ts and quote:
                if ts not in ts_to_text or not any(quote in src for src in ts_to_text[ts]):
                    raise ValueError(f"{field} 附带的参考原话或时间戳在原纪要中不存在：{ts} / {quote}")
        else:
            if not val or val == "未核实":
                raise ValueError(f"{field} 标为 VERIFIED 但缺少有效提取值")
            if not re.fullmatch(r"\d{2}:\d{2}", ts) or ts not in ts_to_text:
                raise ValueError(f"{field} 时间戳 [{ts}] 格式非法或不在原始会议转写稿中")
            if len(quote) < 8 or not any(quote in src for src in ts_to_text[ts]):
                raise ValueError(f"{field} 的 exact_quote 未通过原话逐字子串硬核验：[{ts}] {quote!r}")

    return card


def build_extraction_messages(meeting_id: str, chunks: list[str]) -> list[dict[str, str]]:
    system_prompt = (
        "你是客观严谨的 B2B 销售 CRM 结构化提纯助手。\n"
        "铁律：1. 仅提取五大客观商机要素（budget, decision_maker, pain_points, competitors, next_steps）；\n"
        "2. 严禁输出 win_probability 等主观成交率预测；\n"
        "3. 客户未明确给出数字或事实的要素，status 必须填 UNVERIFIED 且 value 填 '未核实'，绝不瞎猜预算；\n"
        "4. 所有 VERIFIED 要素必须附带原纪要精确 [MM:SS] 时间戳与逐字不改的客户原话子串 exact_quote（≥8字）。"
    )
    user_prompt = (
        f"会议编号：{meeting_id}\n"
        "请综合以下已去噪的全时段会议分块，输出严格符合五要素规范的 JSON：\n"
        + "\n\n".join(chunks)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def extract_crm_deal_card(meeting: dict[str, Any]) -> dict[str, Any]:
    chunks = clean_and_chunk_transcript(meeting, chunk_size=3)
    messages = build_extraction_messages(str(meeting.get("id", "")), chunks)
    raw = chat_complete(
        messages,
        mock_fn=_deterministic_crm_mock,
        temperature=0.0,
        response_json=True,
    )
    card = json.loads(raw)
    return verify_crm_card(card, meeting)
