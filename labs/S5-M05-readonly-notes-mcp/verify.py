#!/usr/bin/env python3
"""S5-M05 自动化红绿验收脚本：只读本地笔记 MCP 补全与排坑。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

_ = (chat_complete, use_solution)


def _load_target_module() -> Any:
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  mod_name = f"s5_m05_{mod_path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> int:
  v = LabVerifier("S5-M05", "进阶选修：基于模板补全只读本地笔记MCP并排坑")
  scenarios_data = json.loads((LAB_DIR / "fixtures" / "scenarios.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块语法与导入检查", False, f"导入目标文件失败：{exc}")
    return v.finish()

  # 1. 技术选型决策树校验
  try:
    mismatches: list[str] = []
    for sc in scenarios_data["decision_scenarios"]:
      decision = mod.recommend_integration_mode(sc)
      got_mode = decision.get("mode") if isinstance(decision, dict) else None
      reason = str(decision.get("reason", "")).strip() if isinstance(decision, dict) else ""
      if got_mode != sc["expected_mode"] or len(reason) < 10:
        mismatches.append(f"{sc['id']}(期望={sc['expected_mode']}, 实际={got_mode})")
    v.check(
        "检查 1 · 技术选型决策树（准确区分 CLI/Skill、现成 MCP 与自建只读 MCP 场景）",
        len(mismatches) == 0,
        f"选型判定存在偏差：{mismatches}。请按『非多端高频用脚本/Skill → 无定制规则用现成 MCP → 多端高频且有定制规则才自建』实现。",
    )
  except Exception as exc:
    v.check(
        "检查 1 · 技术选型决策树（准确区分 CLI/Skill、现成 MCP 与自建只读 MCP 场景）",
        False,
        f"调用 recommend_integration_mode 时报错：{exc}",
    )

  with tempfile.TemporaryDirectory(prefix="aid_s5_m05_") as tmp_dir_str:
    tmp_notes_dir = pathlib.Path(tmp_dir_str) / "vault"
    tmp_notes_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LAB_DIR / "fixtures" / "notes_corpus.json", tmp_notes_dir / "notes_corpus.json")

    prev_env = os.environ.get("NOTES_DIR")
    try:
      # 先验证未设置 NOTES_DIR 时不回退到硬编码路径
      os.environ.pop("NOTES_DIR", None)
      missing_env_rejected = False
      try:
        _ = mod.ReadonlyNotesMCPServer(notes_dir=None)
      except (RuntimeError, ValueError, FileNotFoundError):
        missing_env_rejected = True

      # 设置合法 NOTES_DIR 初始化实例
      os.environ["NOTES_DIR"] = str(tmp_notes_dir)
      server = mod.ReadonlyNotesMCPServer(notes_dir=None)

      # 2. 纯只读接口边界与描述规范
      tools = server.list_tools()
      tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
      expected_readonly = {"search_notes", "get_note", "list_tags"}
      has_write_tools = any(
          kw in name.lower() for name in tool_names for kw in ("delete", "write", "create", "update", "remove")
      )
      rich_descriptions = all(
          len(str(t.get("description", "")).strip()) >= 30 for t in tools if isinstance(t, dict)
      )
      readonly_ok = (
          missing_env_rejected
          and set(tool_names) == expected_readonly
          and not has_write_tools
          and rich_descriptions
      )
      v.check(
          "检查 2 · 纯只读边界与环境变量解耦（无写入/删除接口、强制 NOTES_DIR 配置、描述完整）",
          readonly_ok,
          "请删除 delete_note 等写操作工具，移除硬编码目录回退（未设 NOTES_DIR 时报错提示），并为 3 个只读工具补充包含用途/时机/边界的完整 description。",
      )

      # 3. Stdio 通道零 stdout 污染检查
      out_buf = io.StringIO()
      err_buf = io.StringIO()
      raw_req = json.dumps({"jsonrpc": "2.0", "id": 101, "method": "tools/list", "params": {}})
      with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        _ = mod.dispatch_stdio_line(server, raw_req)

      stdout_raw = out_buf.getvalue().strip()
      stderr_raw = err_buf.getvalue().strip()
      stdout_lines = [ln for ln in stdout_raw.splitlines() if ln.strip()]
      parsed_stdout = None
      if len(stdout_lines) == 1:
        try:
          parsed_stdout = json.loads(stdout_lines[0])
        except json.JSONDecodeError:
          parsed_stdout = None

      stdio_ok = (
          isinstance(parsed_stdout, dict)
          and parsed_stdout.get("id") == 101
          and "tools" in parsed_stdout.get("result", {})
          and len(stderr_raw) > 0
      )
      v.check(
          "检查 3 · Stdio 协议纯净度排坑（stdout 严格单行 JSON 零日志污染，调试日志输出至 stderr）",
          stdio_ok,
          "请将 dispatch_stdio_line 中的 print(...) 改为 print(..., file=sys.stderr)，确保 stdout 仅输出合法 JSON-RPC 单行响应。",
      )

      # 4. 分页检索、100 字摘要限制与 400 字正文硬截断防爆
      page1 = server.search_notes(query="", tag="incident", limit=2, cursor=None)
      p1_items = page1.get("items", [])
      next_cur = page1.get("next_cursor")
      page2 = server.search_notes(query="", tag="incident", limit=2, cursor=next_cur) if next_cur else {"items": []}
      p2_items = page2.get("items", [])

      all_summaries_short = len(p1_items) == 2 and all(
          len(str(it.get("summary", ""))) <= 100 and "content" not in it for it in (p1_items + p2_items)
      )
      pagination_distinct = (
          next_cur is not None
          and len(p2_items) >= 1
          and {it["id"] for it in p1_items}.isdisjoint({it["id"] for it in p2_items})
      )

      # 压测超大 max_chars 请求是否被服务端 400 字符硬上限拦截
      note_part1 = server.get_note("note-003", offset=0, max_chars=9999)
      chunk1 = str(note_part1.get("content_chunk", ""))
      next_off = note_part1.get("next_offset")
      trunc_ok = (
          0 < len(chunk1) <= 400
          and note_part1.get("truncated") is True
          and isinstance(next_off, int)
          and next_off == len(chunk1)
          and "offset" in str(note_part1.get("hint", ""))
      )
      if trunc_ok and isinstance(next_off, int):
        note_part2 = server.get_note("note-003", offset=next_off, max_chars=400)
        trunc_ok = len(str(note_part2.get("content_chunk", ""))) > 0 and (
            chunk1 + str(note_part2.get("content_chunk", ""))
        ).startswith(chunk1)

      # 检查不存在 ID 的友好错误提示
      bad_id_resp = server.handle_jsonrpc({
          "jsonrpc": "2.0",
          "id": 102,
          "method": "tools/call",
          "params": {"name": "get_note", "arguments": {"note_id": "note-999"}},
      })
      bad_id_res = bad_id_resp.get("result", {})
      bad_id_helpful = (
          bad_id_res.get("isError") is True
          and "search_notes" in str(bad_id_res.get("content", [{}])[0].get("text", ""))
      )

      v.check(
          "检查 4 · 摘要分页与正文硬截断防爆（摘要<=100字、游标翻页不重不漏、正文<=400字分段续读）",
          all_summaries_short and pagination_distinct and trunc_ok and bad_id_helpful,
          "请实现 search_notes 的 tag 过滤、cursor 数字游标与 <=100 字摘要裁剪；在 get_note 强制 min(max_chars, 400) 截断并提供 next_offset 续读指引，未知 ID 返回引导调用 search_notes 的错误文本。",
      )

      # 5. 自然语言提问自动选工具联调
      nl_ok = True
      for item in scenarios_data["natural_language_queries"]:
        routed = mod.route_natural_language_query(server, item["query"])
        if not isinstance(routed, dict) or routed.get("tool") != item["expected_tool"]:
          nl_ok = False
          break
        got_args = routed.get("arguments") or {}
        for k, exp_v in item["expected_args"].items():
          if k == "query":
            if str(exp_v).lower() not in str(got_args.get("query", "")).lower():
              nl_ok = False
          elif got_args.get(k) != exp_v:
            nl_ok = False

      v.check(
          "检查 5 · 自然语言选工具联调（不点名工具名称，准确路由至 list_tags / search_notes / get_note）",
          nl_ok,
          "请完善 route_natural_language_query（结合 server.list_tools() 与 chat_complete(..., mock_fn=...)），准确识别标签盘点、按标签/关键词分页搜索与按 note_id 读取正文三类意图。",
      )
    except Exception as exc:
      v.check(
          "服务端核心能力综合验收",
          False,
          f"运行只读笔记 MCP 验收时抛出未预期异常：{exc}",
      )
    finally:
      if prev_env is None:
        os.environ.pop("NOTES_DIR", None)
      else:
        os.environ["NOTES_DIR"] = prev_env

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
