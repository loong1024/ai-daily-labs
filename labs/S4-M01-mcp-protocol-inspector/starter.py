#!/usr/bin/env python3
"""S4-M01 Starter：MCP 三类原语拆解、Filesystem 沙箱守卫与 Schema 防呆体检。

当前基线存在 3 处典型工程缺陷，请结合 README.md 与 verify.py 提示逐步修复：
1. build_primitive_comparison_table 把三类原语的控制主体全部写成了 "model"，且漏掉了 Resource URI 与错误观测；
2. evaluate_filesystem_access 仅做了脆弱的字符串 startswith 判断，无法拦截 ../ 穿越、同名前缀目录欺骗、软链逃逸与只读写入；
3. build_schema_upgrade_plan 直接原样返回粗糙 Schema，未做命名去重、参数 enum 下拉化与分页上限约束。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any


def build_primitive_comparison_table(traces: list[dict[str, Any]]) -> dict[str, Any]:
  """解析 MCP Inspector 抓包记录，生成三类原语对照数据、错误观测与反模式诊断。"""
  rows: list[dict[str, Any]] = []
  for item in traces:
    if item.get("stage") != "primitive_call":
      continue
    req = item.get("request", {})
    method = req.get("method", "")
    params = req.get("params", {})
    # TODO(1): 区分 tools/call、resources/read、prompts/get 的真实控制方（model / application / user），
    # 并正确提取 Resource 的 uri、请求摘要、响应摘要与职责边界说明。
    rows.append({
        "primitive": method,
        "jsonrpc_method": method,
        "controller": "model",
        "controller_zh": "模型调用",
        "identifier": params.get("name", ""),
        "request_summary": json.dumps(params, ensure_ascii=False),
        "response_summary": "ok",
        "boundary_rule": "待补充",
    })

  # TODO(2): 提取 stage == "error_probe" 的 JSON-RPC 错误码（如 -32602）及 stage == "anti_pattern" 的反模式建议
  return {
      "rows": rows,
      "error_observations": [],
      "anti_patterns": [],
  }


def evaluate_filesystem_access(
    requested_path: str | pathlib.Path,
    allowed_roots: list[str | pathlib.Path],
    *,
    operation: str = "read",
    read_only: bool = True,
) -> dict[str, Any]:
  """模拟 MCP Filesystem Server 目录白名单与只读权限校验。"""
  req_str = str(requested_path)
  # TODO(3): 修复下方高危字符串前缀校验！
  # 需使用 Path.resolve() + is_relative_to() 拦截：
  # - ../ 目录穿越 (OUTSIDE_ALLOWLIST)
  # - 同名前缀兄弟目录如 /tmp/mcp-demo-secrets (OUTSIDE_ALLOWLIST)
  # - 沙箱内指向外部文件的符号链接逃逸 (SYMLINK_ESCAPE)
  # - read_only=True 时的写操作 (READ_ONLY_VIOLATION)
  allowed = any(req_str.startswith(str(root)) for root in allowed_roots)
  return {
      "requested_path": req_str,
      "resolved_path": req_str,
      "operation": operation,
      "allowed": allowed,
      "reason_code": "OK" if allowed else "OUTSIDE_ALLOWLIST",
      "message": "放行" if allowed else "路径不在允许目录内",
  }


def build_schema_upgrade_plan(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """体检已连接的工具 Schema，对存在坏味道的工具输出防呆重构方案。"""
  # TODO(4): 挑出命名宽泛重叠、缺少 enum 下拉约束、缺少分页上限与返回精简边界的 3 个工具，
  # 输出 before_name、after_name、issues、boundary_note、upgraded_schema 与 foolproof_example。
  upgrades: list[dict[str, Any]] = []
  for tool in tools[:3]:
    upgrades.append({
        "before_name": tool["name"],
        "after_name": tool["name"],
        "issues": [],
        "boundary_note": "",
        "upgraded_schema": tool.get("inputSchema", {}),
        "foolproof_example": {},
    })
  return upgrades


def render_inspector_report(
    primitive_report: dict[str, Any],
    sandbox_records: list[dict[str, Any]],
    schema_upgrades: list[dict[str, Any]],
) -> str:
  """汇总渲染 Markdown 版《MCP 三类原语对照与安全体检报告》。"""
  # TODO(5): 输出完整包含《MCP 三类原语对照记录表》、沙箱放行与拒绝记录、3 个工具改进前后 Schema 清单的 Markdown 文本。
  return f"# MCP 体检草稿\n记录条数: {len(primitive_report.get('rows', []))}\n"
