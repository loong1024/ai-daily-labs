#!/usr/bin/env python3
"""S5-M04 Starter：双道安全硬护栏脚手架与绕过攻防审计（支持命令行 stdin JSON 单测）。"""

from __future__ import annotations

import json
import sys
from typing import Any


def evaluate_pre_tool_use(
    event: dict[str, Any],
    workspace_root: str = "/workspace/order-service",
) -> dict[str, Any]:
    """第一道护栏：工具调用前（PreToolUse）敏感文件保护与高危命令拦截。

    返回结构：
    {
        "decision": "allow" | "block",
        "exit_code": 0 | 2,
        "reason": str,
        "remediation": str,  # 被拦截时告诉 AI 为什么被拦以及安全的替代做法
    }
    """
    del workspace_root
    tool_name = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input") or {}

    # ❌ 基线缺陷 1：仅对 Read 做了粗暴子串匹配 `".env" in file_path`，
    # 导致合法模板 `.env.example` 被误杀，且漏掉了 Edit/Write、`~/.ssh/id_rsa`、
    # Shell 里的 `cat ./app/../.env.local`、`git push -f`、`git reset --hard`、`rm -rf ~/`、`curl | sh`！
    if tool_name == "Read":
        raw_path = str(tool_input.get("file_path", ""))
        if ".env" in raw_path:
            return {
                "decision": "block",
                "exit_code": 2,
                "reason": "blocked",
                "remediation": "",  # ❌ 基线缺陷 2：未给出可执行的替代建议
            }

    return {
        "decision": "allow",
        "exit_code": 0,
        "reason": "ok",
        "remediation": "",
    }


def run_post_edit_guard(
    changed_files: list[str],
    file_contents: dict[str, str],
    raw_linter_lines: list[str],
    max_summary_lines: int = 5,
) -> dict[str, Any]:
    """第二道护栏：编辑后 / 提交前增量检查与 ≤5 行精简摘要压缩。

    要求：
    1. 仅检查 changed_files 内的文件（严禁把未改动遗留文件的问题算进本次结果）；
    2. 检测改动文件中是否硬编码了明文测试密钥（如 API_SECRET = "FAKE_TEST_KEY_..."）；
    3. 仅提取与 changed_files 相关的 Lint 告警，并将回传摘要 summary_lines 严格控制在 <= max_summary_lines 行。

    返回结构：
    {
        "passed": bool,
        "secret_findings": list[str],
        "summary_lines": list[str],
    }
    """
    del changed_files, file_contents, max_summary_lines
    # ❌ 基线缺陷：未按 changed_files 过滤，且把全部原始 Lint 行原样刷屏回传！
    return {
        "passed": len(raw_linter_lines) == 0,
        "secret_findings": [],
        "summary_lines": list(raw_linter_lines),
    }


def build_bypass_defense_plan(bypass_vectors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """绕过攻防复盘：针对纯文本/正则黑名单防不住的绕过向量，给出原因分析与系统级纵深补救措施。

    每条记录须包含：
    {
        "id": vector["id"],
        "category": vector["category"],
        "why_regex_fails": "说明为什么纯文本关键词/正则匹配难以彻底拦截（>=15字）",
        "isolation_remediation": "对应的目录权限隔离、容器沙箱、临时低权限测试密钥或服务端分支保护措施（>=20字）",
    }
    """
    del bypass_vectors
    # TODO 3：阅读 fixtures/bypass_vectors.json，为至少 3 种（建议全部 4 种）绕过手法编写攻防复盘记录
    return []


def main() -> int:
    """命令行入口：从 stdin 读取单条工具调用 JSON，阻塞时打印原因到 stderr 并返回退出码 2。"""
    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    event = json.loads(raw)
    result = evaluate_pre_tool_use(event)
    if result["decision"] == "block":
        msg = f"[HOOK BLOCKED] {result['reason']}"
        if result.get("remediation"):
            msg += f" | 建议做法：{result['remediation']}"
        print(msg, file=sys.stderr)
        return int(result["exit_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
