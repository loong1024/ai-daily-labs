#!/usr/bin/env python3
"""S1-M10 起点代码（待改造半成品）：会议纪要商机五要素抽取器。

当前缺陷：
1. 直接按前 350 字硬截断长转写稿，漏掉了中后段的竞品对比与会末下一步行动；
2. 采样温度设为 0.8，且包含主观拍脑袋的 win_probability（成交率打分）；
3. 客户未透露明确预算时，模型顺嘴瞎编了“约 50 万元”；
4. 缺少对 exact_quote 原话子串与 [MM:SS] 时间戳真实性的确定性硬核验。
"""

from __future__ import annotations

import json
from typing import Any

from shared.aid_lab import chat_complete

FIVE_FIELDS = ("budget", "decision_maker", "pain_points", "competitors", "next_steps")


def _naive_mock(messages: list[dict[str, str]]) -> str:
    return json.dumps({
        "meeting_id": "MTG-01",
        "win_probability": "85%（客户意向极高）",
        "budget": {"status": "VERIFIED", "value": "预计约 50 万元", "timestamp": "18:99", "exact_quote": "客户表示预算很充足大概五十万"},
        "decision_maker": {"status": "VERIFIED", "value": "陈志远", "timestamp": "14:15", "exact_quote": "业务侧立项拍板我这边就能定"},
        "pain_points": {"status": "VERIFIED", "value": "手工合表慢", "timestamp": "08:20", "exact_quote": "手工合并12家代工厂的Excel交期表"},
        "competitors": {"status": "UNVERIFIED", "value": "未核实", "timestamp": "", "exact_quote": ""},
        "next_steps": {"status": "UNVERIFIED", "value": "未核实", "timestamp": "", "exact_quote": ""}
    }, ensure_ascii=False)


def clean_and_chunk_transcript(meeting: dict[str, Any], chunk_size: int = 4) -> list[str]:
    # TODO: 过滤纯设备调试/堵车寒暄/倒茶咖啡闲聊，保留全部业务发言并按窗口分块覆盖全文（勿截断后半场！）
    raw = "\n".join(f"[{u['ts']}] {u['speaker']}：{u['text']}" for u in meeting.get("utterances", []))
    return [raw[:350]]


def verify_crm_card(card: dict[str, Any], meeting: dict[str, Any]) -> dict[str, Any]:
    # TODO: 1) 严禁存在 win_probability / 成交率 等主观打分字段；
    #       2) 对每个 status == "VERIFIED" 的要素，硬核验 timestamp 真实存在于转写稿且 exact_quote（≥8字）是对应发言的逐字子串！
    #       3) 对 status == "UNVERIFIED" 的要素，确认 value == "未核实"。
    return card


def extract_crm_deal_card(meeting: dict[str, Any]) -> dict[str, Any]:
    chunks = clean_and_chunk_transcript(meeting)
    prompt = "请总结以下会议纪要并预测成交率：\n" + "\n".join(chunks)
    raw = chat_complete(
        [{"role": "user", "content": prompt}],
        mock_fn=_naive_mock,
        temperature=0.8,
        response_json=True,
    )
    card = json.loads(raw)
    return verify_crm_card(card, meeting)
