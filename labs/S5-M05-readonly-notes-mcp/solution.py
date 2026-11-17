"""S5-M05 标准参考实现：选型决策树 + 纯只读本地笔记 MCP 服务（含分页、硬截断与无污染 Stdio）。"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

MAX_SUMMARY_CHARS = 100
MAX_NOTE_CHARS = 400


def recommend_integration_mode(scenario: dict[str, Any]) -> dict[str, str]:
  """按三层 ROI 决策树给出工具形态选型结论及理由。"""
  multi_client = bool(scenario.get("multi_client", False))
  high_freq = bool(scenario.get("high_frequency", False))
  off_the_shelf = bool(scenario.get("off_the_shelf_available", False))
  custom_rules = bool(scenario.get("custom_domain_rules", False))

  if not multi_client or not high_freq:
    return {
        "mode": "cli_or_skill",
        "reason": "仅单端或低频一次性场景，优先编写轻量本地 CLI 脚本或项目内 Skill，无需承担 MCP 服务维护成本。",
    }
  if off_the_shelf and not custom_rules:
    return {
        "mode": "off_the_shelf_mcp",
        "reason": "虽需跨多客户端高频复用，但无特殊业务裁剪规则，直接安装成熟现成只读 MCP 插件即可。",
    }
  return {
      "mode": "custom_readonly_mcp",
      "reason": "需跨多客户端高频共享且必须强制执行定制摘要分页、标签聚合或长度截断规则，适合自建最小只读 MCP。",
  }


def _compact_summary(text: str, max_len: int = MAX_SUMMARY_CHARS) -> str:
  cleaned = " ".join(text.split())
  if len(cleaned) <= max_len:
    return cleaned
  return cleaned[: max_len - 3] + "..."


class ReadonlyNotesMCPServer:
  """纯只读、环境变量驱动、带分页与防爆截断保护的本地笔记 MCP 服务。"""

  def __init__(self, notes_dir: pathlib.Path | None = None) -> None:
    if notes_dir is not None:
      resolved_dir = pathlib.Path(notes_dir).resolve()
    else:
      env_val = os.environ.get("NOTES_DIR", "").strip()
      if not env_val:
        raise RuntimeError(
            "未配置环境变量 NOTES_DIR：请在启动配置中通过环境变量注入只读笔记目录路径，禁止硬编码本地路径。"
        )
      resolved_dir = pathlib.Path(env_val).resolve()

    if not resolved_dir.is_dir():
      raise FileNotFoundError(f"NOTES_DIR 指向的目录不存在：{resolved_dir}")

    self.notes_dir = resolved_dir
    corpus_file = self.notes_dir / "notes_corpus.json"
    notes: list[dict[str, Any]] = []
    if corpus_file.is_file():
      notes.extend(json.loads(corpus_file.read_text(encoding="utf-8")))
    for md_file in sorted(self.notes_dir.glob("*.md")):
      notes.append({
          "id": md_file.stem,
          "title": md_file.stem,
          "updated_at": "2026-11-01T00:00:00Z",
          "tags": ["markdown"],
          "content": md_file.read_text(encoding="utf-8"),
      })
    self._notes = sorted(
        notes,
        key=lambda item: (str(item.get("updated_at", "")), str(item.get("id", ""))),
        reverse=True,
    )

  def list_tools(self) -> list[dict[str, Any]]:
    return [
        {
            "name": "search_notes",
            "description": (
                "按关键词与标签分页检索只读笔记目录，仅返回笔记 id、标题、更新时间、标签与 100 字内摘要及下一页游标。"
                "适用时机：查找相关主题笔记或获取合法 note_id 时优先调用。"
                "边界限制：只读不修改笔记，不返回长篇全文（需读正文请拿到 id 后调用 get_note）。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "大小写不敏感的搜索关键词，默认空字符串匹配全部"},
                    "tag": {"type": "string", "description": "可选标签过滤（如 incident、mcp、agent）"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                        "description": "单页返回条数，取值范围 1~10",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "分页游标（传入上一页返回的 next_cursor 数字字符串，首页留空）",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_note",
            "description": (
                "按笔记 id 分段读取单篇只读笔记正文（强制单次最多返回 400 字符，超长自动截断并给出续读 offset）。"
                "适用时机：已知明确 note_id（如 note-003）需阅读详细内容时调用。"
                "边界限制：只读无写入能力；若未知合法 id 请先调用 search_notes，切勿盲猜编号。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "目标笔记唯一编号，例如 note-003"},
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "正文起始字符偏移量，用于分段续读长笔记",
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_NOTE_CHARS,
                        "default": 300,
                        "description": "期望读取字符数，服务端硬上限为 400",
                    },
                },
                "required": ["note_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_tags",
            "description": (
                "列出知识库全部笔记标签及各标签下的笔记篇数统计。"
                "适用时机：用户询问有哪些分类标签、标签分布或不确定可用 tag 名称时调用。"
                "边界限制：只读聚合统计，不返回具体笔记正文或摘要。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]

  def search_notes(
      self,
      query: str = "",
      tag: str | None = None,
      limit: int = 5,
      cursor: str | None = None,
  ) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 10):
      raise ValueError("参数 limit 必须为 1~10 之间的整数，请调整 limit 后重试。")

    offset = 0
    if cursor is not None and str(cursor).strip() != "":
      raw_cur = str(cursor).strip()
      if not raw_cur.isdigit():
        raise ValueError(f"游标 cursor='{cursor}' 格式非法，请传入上一页返回的 next_cursor 数字字符串或留空。")
      offset = int(raw_cur)

    q_norm = (query or "").strip().lower()
    tag_norm = tag.strip().lower() if isinstance(tag, str) and tag.strip() else None

    matched: list[dict[str, Any]] = []
    for n in self._notes:
      note_tags = [str(t) for t in n.get("tags", [])]
      if tag_norm and tag_norm not in [t.lower() for t in note_tags]:
        continue
      if q_norm and q_norm not in n["title"].lower() and q_norm not in n["content"].lower():
        continue
      matched.append(n)

    page = matched[offset : offset + limit]
    items = [
        {
            "id": n["id"],
            "title": n["title"],
            "updated_at": n["updated_at"],
            "tags": list(n.get("tags", [])),
            "summary": _compact_summary(str(n.get("content", "")), MAX_SUMMARY_CHARS),
        }
        for n in page
    ]
    next_cursor = str(offset + limit) if (offset + limit) < len(matched) else None
    return {
        "items": items,
        "total": len(matched),
        "next_cursor": next_cursor,
    }

  def get_note(
      self,
      note_id: str,
      offset: int = 0,
      max_chars: int = 300,
  ) -> dict[str, Any]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
      raise ValueError("参数 offset 必须为大于等于 0 的整数。")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
      raise ValueError("参数 max_chars 必须为正整数。")

    effective_max = min(max_chars, MAX_NOTE_CHARS)
    target = next((n for n in self._notes if n["id"] == note_id), None)
    if target is None:
      raise ValueError(
          f"未找到编号为 '{note_id}' 的笔记；请先调用 search_notes 检索获取合法的笔记 id。"
      )

    full_text = str(target.get("content", ""))
    chunk = full_text[offset : offset + effective_max]
    next_pos = offset + len(chunk)
    truncated = next_pos < len(full_text)
    next_offset = next_pos if truncated else None
    hint = (
        f"正文总长 {len(full_text)} 字符，受单次 {MAX_NOTE_CHARS} 字符硬上限保护已截断；"
        f"如需继续阅读剩余部分，请调用 get_note(note_id='{note_id}', offset={next_offset})。"
        if truncated
        else "已返回到笔记末尾。"
    )
    return {
        "id": target["id"],
        "title": target["title"],
        "updated_at": target["updated_at"],
        "tags": list(target.get("tags", [])),
        "content_chunk": chunk,
        "total_chars": len(full_text),
        "truncated": truncated,
        "next_offset": next_offset,
        "hint": hint,
    }

  def list_tags(self) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for n in self._notes:
      for t in n.get("tags", []):
        counts[str(t)] = counts.get(str(t), 0) + 1
    ranked = [
        {"tag": tag_name, "count": cnt}
        for tag_name, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {"tags": ranked, "total_tags": len(ranked)}

  def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
      return {
          "jsonrpc": "2.0",
          "id": req_id,
          "result": {
              "protocolVersion": "2024-11-05",
              "capabilities": {"tools": {}},
              "serverInfo": {"name": "readonly-notes-mcp", "version": "1.0.0"},
          },
      }

    if method == "tools/list":
      return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools()}}

    if method == "tools/call":
      name = params.get("name", "")
      args = params.get("arguments") or {}
      try:
        if name == "search_notes":
          data = self.search_notes(**args)
        elif name == "get_note":
          data = self.get_note(**args)
        elif name == "list_tags":
          data = self.list_tags()
        else:
          return {
              "jsonrpc": "2.0",
              "id": req_id,
              "error": {"code": -32602, "message": f"未知或禁止访问的工具：{name}（本服务严格只读）"},
          }
      except (TypeError, ValueError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"参数或调用错误：{exc}"}],
                "isError": True,
            },
        }

      return {
          "jsonrpc": "2.0",
          "id": req_id,
          "result": {
              "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
              "isError": False,
          },
      }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def dispatch_stdio_line(server: ReadonlyNotesMCPServer, raw_line: str) -> str:
  """处理单行 Stdio JSON-RPC 请求：调试日志严格写往 stderr，stdout 保持 100% 纯净 JSON。"""
  req = json.loads(raw_line)
  print(f"[readonly-notes-mcp] handling method={req.get('method')} id={req.get('id')}", file=sys.stderr)
  resp = server.handle_jsonrpc(req)
  out_line = json.dumps(resp, ensure_ascii=False)
  sys.stdout.write(out_line + "\n")
  sys.stdout.flush()
  return out_line


def _deterministic_router_mock(messages: list[dict[str, str]]) -> str:
  payload = json.loads(messages[-1]["content"])
  text = str(payload.get("user_query", ""))
  tools = payload.get("tools", [])
  valid_names = {t.get("name") for t in tools if len(str(t.get("description", ""))) >= 25}

  note_id_match = re.search(r"\b(note-\d{3,})\b", text, flags=re.IGNORECASE)
  if note_id_match and "get_note" in valid_names:
    return json.dumps(
        {"tool": "get_note", "arguments": {"note_id": note_id_match.group(1).lower()}},
        ensure_ascii=False,
    )

  if ("有哪些标签" in text or "每个标签" in text or "标签分布" in text) and "list_tags" in valid_names:
    return json.dumps({"tool": "list_tags", "arguments": {}}, ensure_ascii=False)

  args: dict[str, Any] = {}
  tag_match = re.search(r"标签为\s*([a-zA-Z0-9_-]+)", text)
  if tag_match:
    args["tag"] = tag_match.group(1).lower()

  limit_match = re.search(r"前\s*(\d+)\s*条", text)
  if limit_match:
    args["limit"] = int(limit_match.group(1))

  ascii_kw = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
  filtered_kw = [w for w in ascii_kw if w.lower() != args.get("tag")]
  if filtered_kw:
    args["query"] = filtered_kw[0]
  elif " tag" not in text and "tag" not in args:
    args["query"] = text[:12]

  return json.dumps({"tool": "search_notes", "arguments": args}, ensure_ascii=False)


def route_natural_language_query(
    server: ReadonlyNotesMCPServer,
    user_query: str,
) -> dict[str, Any]:
  """借助完备的工具 Description 与 Schema，将自然语言提问路由到精确的只读工具调用。"""
  tools_meta = server.list_tools()
  messages = [
      {
          "role": "system",
          "content": (
              "你是 MCP 客户端工具路由器。请严格依据提供的只读工具定义，从用户自然语言问题中选择最匹配的 1 个工具，"
              "仅输出 JSON 对象：{\"tool\": \"工具名\", \"arguments\": {...}}。"
          ),
      },
      {
          "role": "user",
          "content": json.dumps({"user_query": user_query, "tools": tools_meta}, ensure_ascii=False),
      },
  ]
  raw = chat_complete(messages, response_json=True, mock_fn=_deterministic_router_mock)
  return json.loads(raw)
