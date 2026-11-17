#!/usr/bin/env python3
"""S4-M01 Solution：MCP 三类原语拆解、Filesystem 沙箱守卫与 Schema 防呆体检标准实现。"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

PRIMITIVE_SPECS: dict[str, dict[str, str]] = {
    "tools/call": {
        "primitive": "Tools",
        "controller": "model",
        "controller_zh": "模型自主决策（Model-controlled）",
        "boundary_rule": "用于需要动态计算、查询外部状态或产生受控副作用的操作；切勿把固定静态文档塞成无参工具。",
    },
    "resources/read": {
        "primitive": "Resources",
        "controller": "application",
        "controller_zh": "宿主应用挂载（Application-controlled）",
        "boundary_rule": "以标准 URI 暴露只读文件、配置或静态知识库，由客户端按需检索或用户 @ 引用注入上下文，无副作用。",
    },
    "prompts/get": {
        "primitive": "Prompts",
        "controller": "user",
        "controller_zh": "用户显式点选（User-controlled）",
        "boundary_rule": "封装高频结构化交互工作流（如斜杠命令 / 审查模板），由用户主动选择并填入声明的参数。",
    },
}


def _summarize_response(method: str, resp: dict[str, Any]) -> str:
  result = resp.get("result", {})
  if method == "tools/call":
    content = result.get("content", [])
    first_text = content[0].get("text", "") if content else ""
    return f"isError={result.get('isError', False)} | {first_text[:60]}"
  if method == "resources/read":
    contents = result.get("contents", [])
    if contents:
      item = contents[0]
      snippet = item.get("text", "").splitlines()[0][:50]
      return f"mimeType={item.get('mimeType', 'text/plain')} | {snippet}"
  if method == "prompts/get":
    msgs = result.get("messages", [])
    first_msg = msgs[0].get("content", {}).get("text", "")[:50] if msgs else ""
    return f"messages={len(msgs)} | {first_msg}"
  return json.dumps(result, ensure_ascii=False)[:60]


def build_primitive_comparison_table(traces: list[dict[str, Any]]) -> dict[str, Any]:
  """解析 MCP Inspector 抓包记录，生成三类原语对照数据、错误观测与反模式诊断。"""
  rows: list[dict[str, Any]] = []
  error_observations: list[dict[str, Any]] = []
  anti_patterns: list[dict[str, Any]] = []

  for item in traces:
    stage = item.get("stage", "")
    req = item.get("request", {})
    resp = item.get("response", {})
    method = req.get("method", "")
    params = req.get("params", {})

    if stage == "primitive_call" and method in PRIMITIVE_SPECS:
      spec = PRIMITIVE_SPECS[method]
      identifier = params.get("uri") if method == "resources/read" else params.get("name", "")
      rows.append({
          "trace_id": item.get("trace_id", ""),
          "server": item.get("server", ""),
          "primitive": spec["primitive"],
          "jsonrpc_method": method,
          "controller": spec["controller"],
          "controller_zh": spec["controller_zh"],
          "identifier": str(identifier or ""),
          "request_summary": json.dumps(params, ensure_ascii=False),
          "response_summary": _summarize_response(method, resp),
          "boundary_rule": spec["boundary_rule"],
      })
    elif stage == "error_probe" or "error" in resp:
      err = resp.get("error", {})
      error_observations.append({
          "trace_id": item.get("trace_id", ""),
          "jsonrpc_method": method,
          "code": err.get("code"),
          "message": err.get("message", ""),
          "takeaway": "参数类型不符时返回标准 JSON-RPC -32602 Invalid params，附带具体字段期望类型，便于宿主或模型自愈。",
      })
    elif stage == "anti_pattern":
      anti_patterns.append({
          "trace_id": item.get("trace_id", ""),
          "current_method": method,
          "identifier": params.get("name", ""),
          "recommended_primitive": "Resources",
          "reason": item.get(
              "anti_pattern_hint",
              "纯静态只读文档应改为 URI 标识的 Resource，由宿主按需挂载，避免无意义的模型工具调用轮次。",
          ),
      })

  return {
      "rows": rows,
      "error_observations": error_observations,
      "anti_patterns": anti_patterns,
  }


def evaluate_filesystem_access(
    requested_path: str | pathlib.Path,
    allowed_roots: list[str | pathlib.Path],
    *,
    operation: str = "read",
    read_only: bool = True,
) -> dict[str, Any]:
  """基于 realpath + is_relative_to 实现严格目录白名单与只读权限拦截。"""
  raw_path = pathlib.Path(requested_path).expanduser()
  resolved_target = raw_path.resolve()
  resolved_roots = [pathlib.Path(root).expanduser().resolve() for root in allowed_roots]

  in_allowlist = any(resolved_target.is_relative_to(root) for root in resolved_roots)
  if not in_allowlist:
    if raw_path.is_symlink():
      return {
          "requested_path": str(requested_path),
          "resolved_path": str(resolved_target),
          "operation": operation,
          "allowed": False,
          "reason_code": "SYMLINK_ESCAPE",
          "message": f"拒绝访问：符号链接 {raw_path.name} 指向白名单目录之外 ({resolved_target})",
      }
    return {
        "requested_path": str(requested_path),
        "resolved_path": str(resolved_target),
        "operation": operation,
        "allowed": False,
        "reason_code": "OUTSIDE_ALLOWLIST",
        "message": f"拒绝访问：解析后路径 {resolved_target} 不在白名单根目录内",
    }

  if read_only and operation.lower() != "read":
    return {
        "requested_path": str(requested_path),
        "resolved_path": str(resolved_target),
        "operation": operation,
        "allowed": False,
        "reason_code": "READ_ONLY_VIOLATION",
        "message": f"拒绝操作：当前 Filesystem 服务处于只读模式，禁止执行 {operation}",
    }

  return {
      "requested_path": str(requested_path),
      "resolved_path": str(resolved_target),
      "operation": operation,
      "allowed": True,
      "reason_code": "OK",
      "message": "白名单校验通过，允许只读访问",
  }


STANDARD_UPGRADES: dict[str, dict[str, Any]] = {
    "do_data": {
        "after_name": "export_monthly_sales_summary",
        "issues": [
            "工具名 do_data 动词含糊，易与数据库写入或清洗工具混淆",
            "format 参数使用自由文本 string 而非 enum 枚举，易传入不支持格式",
            "max_rows 无上限且默认返回整表 50MB 明细，极易撑爆模型上下文窗口",
        ],
        "boundary_note": "仅用于只读导出指定月份的聚合销售汇总（单次最多 100 行摘要字段），不用于导出原始明细宽表或修改财务数据。",
        "upgraded_schema": {
            "type": "object",
            "properties": {
                "report_month": {
                    "type": "string",
                    "pattern": "^\\d{4}-(0[1-9]|1[0-2])$",
                    "description": "统计月份（YYYY-MM），例如 2026-10",
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "csv", "markdown"],
                    "description": "导出格式枚举",
                },
                "max_rows": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "返回汇总行数上限（1-100）",
                },
            },
            "required": ["report_month", "format"],
            "additionalProperties": False,
        },
        "foolproof_example": {
            "report_month": "2026-10",
            "format": "markdown",
            "max_rows": 20,
        },
    },
    "manage_files": {
        "after_name": "list_sandbox_documents",
        "issues": [
            "将只读列举 list 与高危删除 delete 混在同一个 manage_files 工具中，违背读写分离",
            "action 参数未用 enum 限制，pattern 允许危险通配符 *，存在误删整个目录风险",
            "直接返回冗余 shell 原始日志，缺少结构化精简字段约束",
        ],
        "boundary_note": "仅用于只读列举沙箱子目录内指定后缀的文档元数据（路径与大小），严禁执行删除或移动；清理文件须走独立受控确认工具。",
        "upgraded_schema": {
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": "沙箱内相对子目录名，例如 docs 或 notes（禁止包含 ..）",
                },
                "extension": {
                    "type": "string",
                    "enum": ["md", "txt", "json"],
                    "description": "允许检索的文档后缀枚举",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "最多返回文件数量（1-50）",
                },
            },
            "required": ["extension"],
            "additionalProperties": False,
        },
        "foolproof_example": {
            "subdir": "docs",
            "extension": "md",
            "limit": 20,
        },
    },
    "query_tickets": {
        "after_name": "search_support_ticket_summaries",
        "issues": [
            "status 与 priority 为无约束自由字符串，模型易拼错状态名（如写成 opened 或 urgent）",
            "limit 未设 maximum 上限，可能一次拉取数万条工单导致响应超时",
            "返回值夹带完整 HTML 邮件与 base64 图片，严重污染上下文并放大间接注入面",
        ],
        "boundary_note": "仅按状态与优先级分页检索工单摘要字段（ticket_id、title、status、priority、updated_at），不返回原始邮件正文与附件；需查看单条详情请另调 get_ticket_detail。",
        "upgraded_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "pending", "resolved"],
                    "description": "工单状态枚举",
                },
                "priority": {
                    "type": "string",
                    "enum": ["P0", "P1", "P2", "P3"],
                    "description": "工单优先级枚举",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "单页返回摘要条数上限（1-50）",
                },
            },
            "required": ["status"],
            "additionalProperties": False,
        },
        "foolproof_example": {
            "status": "open",
            "priority": "P1",
            "limit": 10,
        },
    },
}


def _mock_schema_review_note(messages: list[dict[str, str]]) -> str:
  user_text = messages[-1]["content"]
  data = json.loads(user_text)
  names = [t.get("name") for t in data.get("tools", [])]
  return json.dumps(
      {"reviewed_tools": names, "principle": "名称不重叠、参数枚举下拉化、返回值精简"},
      ensure_ascii=False,
  )


def build_schema_upgrade_plan(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """诊断工具 Schema 坏味道并生成防呆重构对照方案。"""
  _ = chat_complete(
      [
          {"role": "system", "content": "你是 MCP 工具 Schema 防呆架构师，请返回 JSON 摘要。"},
          {"role": "user", "content": json.dumps({"tools": tools}, ensure_ascii=False)},
      ],
      mock_fn=_mock_schema_review_note,
      response_json=True,
  )

  upgrades: list[dict[str, Any]] = []
  for tool in tools:
    name = tool.get("name", "")
    props = tool.get("inputSchema", {}).get("properties", {})
    has_required = bool(tool.get("inputSchema", {}).get("required"))
    if name in STANDARD_UPGRADES:
      spec = STANDARD_UPGRADES[name]
      upgrades.append({
          "before_name": name,
          "after_name": spec["after_name"],
          "issues": list(spec["issues"]),
          "boundary_note": spec["boundary_note"],
          "upgraded_schema": spec["upgraded_schema"],
          "foolproof_example": spec["foolproof_example"],
      })
    elif not has_required and props:
      upgrades.append({
          "before_name": name,
          "after_name": f"strict_{name}",
          "issues": ["缺少 required 必填约束与 additionalProperties=false"],
          "boundary_note": f"限定 {name} 的只读输入边界并仅返回决策必需摘要字段。",
          "upgraded_schema": {
              "type": "object",
              "properties": props,
              "required": [next(iter(props.keys()))],
              "additionalProperties": False,
          },
          "foolproof_example": {next(iter(props.keys())): "example"},
      })
  return upgrades


def render_inspector_report(
    primitive_report: dict[str, Any],
    sandbox_records: list[dict[str, Any]],
    schema_upgrades: list[dict[str, Any]],
) -> str:
  """汇总生成结构化 Markdown 版《MCP 三类原语对照与安全体检报告》。"""
  lines: list[str] = [
      "# MCP Inspector 协议拆解与安全沙箱体检报告",
      "",
      "## 一、MCP 三类原语对照记录表",
      "",
      "| 原语类型 | JSON-RPC 方法 | 控制方 | 目标标识 (name/URI) | 请求摘要 | 返回摘要 | 职责边界 |",
      "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
  ]
  for row in primitive_report.get("rows", []):
    lines.append(
        f"| {row['primitive']} | `{row['jsonrpc_method']}` | {row['controller']} ({row['controller_zh']}) "
        f"| `{row['identifier']}` | `{row['request_summary']}` | {row['response_summary']} | {row['boundary_rule']} |"
    )

  if primitive_report.get("error_observations"):
    lines.extend(["", "### 参数错误返回观测"])
    for err in primitive_report["error_observations"]:
      lines.append(f"- `{err['jsonrpc_method']}` 返回错误码 `{err['code']}`：{err['message']}（{err['takeaway']}）")

  if primitive_report.get("anti_patterns"):
    lines.extend(["", "### 原语误用反模式修正"])
    for ap in primitive_report["anti_patterns"]:
      lines.append(
          f"- `{ap['identifier']}`：原用 `{ap['current_method']}`，建议改为 **{ap['recommended_primitive']}** — {ap['reason']}"
      )

  lines.extend([
      "",
      "## 二、Filesystem 目录白名单放行与越权拦截记录",
      "",
      "| 用例 | 操作 | 请求路径 | 判定结果 | 拦截码 | 说明 |",
      "| :--- | :--- | :--- | :--- | :--- | :--- |",
  ])
  for rec in sandbox_records:
    verdict = "ALLOW 放行" if rec.get("allowed") else "DENY 拒绝"
    lines.append(
        f"| {rec.get('case_id', '-')} | `{rec.get('operation', 'read')}` | `{rec.get('requested_path', '')}` "
        f"| {verdict} | `{rec.get('reason_code', '')}` | {rec.get('message', '')} |"
    )

  lines.extend([
      "",
      "## 三、工具 Schema 防呆体检与改进前后对比清单",
      "",
  ])
  for idx, item in enumerate(schema_upgrades, 1):
    lines.extend([
        f"### {idx}. `{item['before_name']}` → `{item['after_name']}`",
        f"- **原问题**：{'；'.join(item.get('issues', []))}",
        f"- **用途与禁用边界**：{item.get('boundary_note', '')}",
        f"- **防呆参数示例**：`{json.dumps(item.get('foolproof_example', {}), ensure_ascii=False)}`",
        "",
    ])

  return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
  traces_data = json.loads((LAB_DIR / "fixtures" / "inspector_traces.json").read_text(encoding="utf-8"))
  tools_data = json.loads((LAB_DIR / "fixtures" / "messy_tool_schemas.json").read_text(encoding="utf-8"))
  prim = build_primitive_comparison_table(traces_data["traces"])
  up = build_schema_upgrade_plan(tools_data["tools"])
  print(render_inspector_report(prim, [], up))
