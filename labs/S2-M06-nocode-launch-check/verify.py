#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file, use_solution


def main() -> int:
    v = LabVerifier("S2-M06", "零代码自动化通用上线体检与排雷验收")
    doc_path = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md")
    fixture_path = LAB_DIR / "fixtures" / "workflow_draft_and_runs.json"

    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        text = doc_path.read_text(encoding="utf-8")
    except Exception as exc:
        v.check("体检文档与测试集读取", False, f"读取失败：{exc}")
        return v.finish()

    submissions = fixture.get("drill_submissions", [])
    dims = ["触发", "数据", "LLM 节点", "错误处理", "人工审批", "密钥与成本", "故障演练"]
    checked_count = text.count("[x]") + text.count("[X]")
    v.check(
        "七维体检表逐项勾选闭环",
        len(submissions) >= 6 and all(d in text for d in dims) and checked_count >= 14,
        "请补齐【触发/数据/LLM 节点/错误处理/人工审批/密钥与成本/故障演练】全部七个维度并完成至少 14 项 [x] 勾选。",
    )

    dedup_ok = (
        "SUB-2026-001" in text
        and any(k in text for k in ("查重", "去重", "幂等"))
        and any(k in text for k in ("自触发", "仅新增"))
    )
    v.check(
        "演练一：连点去重与防写回自触发",
        dedup_ok,
        "请针对 SUB-2026-001 连交两次补充按单号/邮箱去重规则，并将触发条件收窄以防止写回再次触发自身。",
    )

    null_ok = (
        "SUB-2026-002" in text
        and "待人工核对" in text
        and "SUB-2026-003" in text
        and "其他/不确定" in text
    )
    v.check(
        "演练二：空值乱码分流与分类兜底",
        null_ok,
        "请明确将空日期乱码单 SUB-2026-002 转入“待人工核对”，并为模糊意图单 SUB-2026-003 配置“其他/不确定”兜底。",
    )

    ops_ok = (
        "SUB-2026-004" in text
        and "SUB-2026-005" in text
        and any(k in text for k in ("失败告警", "告警通知"))
        and any(k in text for k in ("人工确认", "一次性审批"))
        and any(k in text for k in ("消费上限", "月度封顶"))
        and "凭证库" in text
    )
    v.check(
        "演练三：故障告警、人工卡点与凭证消费封顶",
        ops_ok,
        "请补齐 SUB-2026-004 失败告警、SUB-2026-005 群发前一次性人工确认、移入加密凭证库及月度消费上限设置。",
    )

    return v.finish()


if __name__ == "__main__":
    main()
