"""S5-M05 起点代码：待排坑与补全的本地笔记 MCP 服务模板。

当前存在 5 处典型工程缺陷，请结合 README.md 与 verify.py 逐一修复：
1. recommend_integration_mode：盲目对所有场景推荐自建 MCP，未区分脚本/现成插件/自建边界。
2. ReadonlyNotesMCPServer：硬编码回退路径、暴露了危险的 delete_note 写入工具，且工具描述过于简略。
3. dispatch_stdio_line：使用 print(...) 把调试日志输出到了 stdout，直接污染 JSON-RPC 通信流。
4. search_notes / get_note：未做标签过滤、游标分页、100 字摘要限制与 400 字正文硬截断防爆。
5. route_natural_language_query：工具描述与路由解析粗糙，无法根据自然语言精准命中只读工具与参数。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

_ = chat_complete

MAX_SUMMARY_CHARS = 100
MAX_NOTE_CHARS = 400
HARDCODED_FALLBACK_DIR = "/Users/demo_user/private_notes"


def recommend_integration_mode(scenario: dict[str, Any]) -> dict[str, str]:
  """根据场景特征判定应采用 cli_or_skill、off_the_shelf_mcp 还是 custom_readonly_mcp。

  TODO(1)：当前不论什么场景一律返回 custom_readonly_mcp（盲目造轮子）！
  """
  _ = scenario
  return {
      "mode": "custom_readonly_mcp",
      "reason": "默认全部自建 MCP 服务",
  }


class ReadonlyNotesMCPServer:
  """本地笔记 MCP 服务（起点版含待修复隐患）。"""

  def __init__(self, notes_dir: pathlib.Path | None = None) -> None:
    # TODO(2a)：禁止使用硬编码个人路径回退；应严格读取环境变量 NOTES_DIR，未配置时抛出清晰提示。
    raw_dir = str(notes_dir) if notes_dir is not None else os.environ.get("NOTES_DIR", HARDCODED_FALLBACK_DIR)
    self.notes_dir = pathlib.Path(raw_dir)
    corpus_file = self.notes_dir / "notes_corpus.json"
    if corpus_file.is_file():
      self._notes: list[dict[str, Any]] = json.loads(corpus_file.read_text(encoding="utf-8"))
    else:
      self._notes = []

  def list_tools(self) -> list[dict[str, Any]]:
    # TODO(2b)：移除任何非只读工具（如 delete_note），并补全详尽描述（做什么、何时用、不能做什么）与参数约束！
    return [
        {"name": "search_notes", "description": "搜笔记", "inputSchema": {"type": "object"}},
        {"name": "get_note", "description": "读笔记", "inputSchema": {"type": "object"}},
        {"name": "list_tags", "description": "列标签", "inputSchema": {"type": "object"}},
        {"name": "delete_note", "description": "删除指定笔记", "inputSchema": {"type": "object"}},
    ]

  def search_notes(
      self,
      query: str = "",
      tag: str | None = None,
      limit: int = 5,
      cursor: str | None = None,
  ) -> dict[str, Any]:
    """按关键词与标签分页搜索笔记摘要。

    TODO(4a)：当前忽略了 tag、limit 范围校验(1~10)、cursor 游标分页，且直接把长正文塞进 summary！
    """
    _ = (tag, limit, cursor)
    q = query.lower().strip()
    items = []
    for n in self._notes:
      if not q or q in n["title"].lower() or q in n["content"].lower():
        items.append({
            "id": n["id"],
            "title": n["title"],
            "updated_at": n["updated_at"],
            "tags": n["tags"],
            "summary": n["content"],
        })
    return {"items": items, "total": len(items), "next_cursor": None}

  def get_note(
      self,
      note_id: str,
      offset: int = 0,
      max_chars: int = 300,
  ) -> dict[str, Any]:
    """按 ID 分段读取单篇笔记正文。

    TODO(4b)：当前未实施 MAX_NOTE_CHARS=400 硬上限截断，也未在找不到 ID 时返回引导调用 search_notes 的提示！
    """
    _ = (offset, max_chars)
    for n in self._notes:
      if n["id"] == note_id:
        return {
            "id": n["id"],
            "title": n["title"],
            "content_chunk": n["content"],
            "total_chars": len(n["content"]),
            "truncated": False,
            "next_offset": None,
            "hint": "",
        }
    raise KeyError(note_id)

  def list_tags(self) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for n in self._notes:
      for t in n.get("tags", []):
        counts[t] = counts.get(t, 0) + 1
    ranked = [{"tag": k, "count": v} for k, v in sorted(counts.items())]
    return {"tags": ranked, "total_tags": len(ranked)}

  def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "tools/list":
      return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools()}}

    if method == "tools/call":
      name = params.get("name")
      args = params.get("arguments") or {}
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
            "error": {"code": -32602, "message": f"未知或禁止调用的工具: {name}"},
        }
      return {
          "jsonrpc": "2.0",
          "id": req_id,
          "result": {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": False},
      }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"未知方法: {method}"}}


def dispatch_stdio_line(server: ReadonlyNotesMCPServer, raw_line: str) -> str:
  """模拟 MCP stdio 传输层处理单行 JSON-RPC 输入并向 stdout 写出单行响应。

  TODO(3)：下面这行调试 print 直接打到了默认 stdout，会导致客户端 JSON 解析当场崩溃！请改为输出到 sys.stderr。
  """
  req = json.loads(raw_line)
  print(f"[DEBUG] recv mcp method={req.get('method')}")
  resp = server.handle_jsonrpc(req)
  out_line = json.dumps(resp, ensure_ascii=False)
  sys.stdout.write(out_line + "\n")
  sys.stdout.flush()
  return out_line


def route_natural_language_query(
    server: ReadonlyNotesMCPServer,
    user_query: str,
) -> dict[str, Any]:
  """根据工具元数据将用户自然语言提问路由为 {'tool': ..., 'arguments': {...}}。

  TODO(5)：当前未结合完善的只读工具 Schema 与 chat_complete 进行精准意图识别与参数抽取！
  """
  _ = (server, user_query)
  return {"tool": "search_notes", "arguments": {"query": ""}}
