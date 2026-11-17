#!/usr/bin/env python3
"""S4-M02 Starter：最小自主 Agent 工具循环骨架（待补全参数校验、四道硬护栏与 JSONL 轨迹）。"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Callable

MAX_STEPS = 8
MAX_CHARS_PER_OBS = 600

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))


def build_tool_registry(notes_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
  """构建本地工具注册表：每个工具 = 名称 + 描述 + JSON Schema + 高危标记 + 实现函数。"""
  root = notes_dir.resolve()

  def list_notes(keyword: str = "") -> str:
    files = sorted(
        p.name for p in root.glob("*.md") if not keyword or keyword.lower() in p.name.lower()
    )
    return json.dumps({"files": files}, ensure_ascii=False)

  def read_note(filename: str) -> str:
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
      raise PermissionError(f"禁止读取目录外路径: {filename}")
    if not target.is_file():
      raise FileNotFoundError(f"笔记文件不存在: {filename}，请先调用 list_notes 查看可用文件列表。")
    return target.read_text(encoding="utf-8")

  def calculator(operation: str, values: list[float]) -> str:
    if operation == "add":
      res = sum(values)
    elif operation == "subtract":
      res = values[0] - sum(values[1:])
    elif operation == "multiply":
      res = 1.0
      for num in values:
        res *= num
    elif operation == "divide":
      res = values[0]
      for num in values[1:]:
        if num == 0:
          raise ValueError("除数不能为 0")
        res /= num
    else:
      raise ValueError(f"不支持的运算: {operation}")
    return json.dumps({"result": res}, ensure_ascii=False)

  def append_todo(item: str, priority: str) -> str:
    todo_path = root / "todo.md"
    existing = todo_path.read_text(encoding="utf-8") if todo_path.is_file() else "# 个人待办清单\n\n"
    line = f"- [{priority}] {item}\n"
    todo_path.write_text(existing.rstrip("\n") + "\n" + line, encoding="utf-8")
    return f"已成功写入待办 (priority={priority}): {item}"

  return {
      "list_notes": {
          "name": "list_notes",
          "description": "列举 notes/ 目录下的 Markdown 笔记文件名（只读）。",
          "high_risk": False,
          "schema": {
              "type": "object",
              "properties": {"keyword": {"type": "string"}},
              "required": [],
              "additionalProperties": False,
          },
          "fn": list_notes,
      },
      "read_note": {
          "name": "read_note",
          "description": "读取 notes/ 目录下指定笔记内容（只读）。",
          "high_risk": False,
          "schema": {
              "type": "object",
              "properties": {"filename": {"type": "string", "minLength": 1}},
              "required": ["filename"],
              "additionalProperties": False,
          },
          "fn": read_note,
      },
      "calculator": {
          "name": "calculator",
          "description": "执行数值统计计算。",
          "high_risk": False,
          "schema": {
              "type": "object",
              "properties": {
                  "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
                  "values": {"type": "array", "items": {"type": "number"}, "minItems": 2},
              },
              "required": ["operation", "values"],
              "additionalProperties": False,
          },
          "fn": calculator,
      },
      "append_todo": {
          "name": "append_todo",
          "description": "向 todo.md 追加一条待办事项（高危写操作，需人工确认）。",
          "high_risk": True,
          "schema": {
              "type": "object",
              "properties": {
                  "item": {"type": "string", "minLength": 3},
                  "priority": {"type": "string", "enum": ["high", "medium", "low"]},
              },
              "required": ["item", "priority"],
              "additionalProperties": False,
          },
          "fn": append_todo,
      },
  }


def validate_tool_args(schema: dict[str, Any], args: Any) -> tuple[bool, str]:
  """按 JSON Schema 校验工具调用参数。"""
  # TODO(1): 实现参数校验（检查 dict 类型、required 必填项、additionalProperties=False、字段类型与 enum 枚举），
  # 失败时返回 (False, "具体可操作的纠错提示")。
  return True, ""


def truncate_observation(text: str, max_chars: int = MAX_CHARS_PER_OBS) -> str:
  """截断超长观察文本，防止单次大返回撑爆上下文。"""
  # TODO(2): 当 len(text) > max_chars 时截断至 <= max_chars 字符，并附带截断说明后缀。
  return text


def _naive_mock_step(turn_idx: int, fault_mode: str) -> dict[str, Any]:
  if fault_mode == "bad_args" and turn_idx == 0:
    return {
        "thought": "直接追加待办",
        "tool_call": {
            "id": "call_1",
            "name": "append_todo",
            "arguments": {
                "item": "本周运动 4 次，下周补齐第 5 次有氧训练",
                "priority": "SUPER_URGENT",
                "extra_flag": True,
            },
        },
        "final_answer": None,
    }
  if fault_mode == "tool_err" and turn_idx == 0:
    return {
        "thought": "尝试读取周记",
        "tool_call": {"id": "call_1", "name": "read_note", "arguments": {"filename": "2026-W11-missing.md"}},
        "final_answer": None,
    }
  if fault_mode == "loop":
    return {
        "thought": "列举笔记",
        "tool_call": {"id": f"call_{turn_idx + 1}", "name": "list_notes", "arguments": {"keyword": "2026"}},
        "final_answer": None,
    }
  plan = [
      {"name": "list_notes", "arguments": {}},
      {"name": "read_note", "arguments": {"filename": "2026-W11-mon-wed.md"}},
      {"name": "read_note", "arguments": {"filename": "2026-W11-thu-sun.md"}},
      {"name": "append_todo", "arguments": {"item": "本周运动共 4 次，下周补齐第 5 次有氧训练", "priority": "high"}},
  ]
  if turn_idx < len(plan):
    step = plan[turn_idx]
    return {
        "thought": f"执行第 {turn_idx + 1} 步",
        "tool_call": {"id": f"call_{turn_idx + 1}", "name": step["name"], "arguments": step["arguments"]},
        "final_answer": None,
    }
  return {
      "thought": "汇总回答",
      "tool_call": None,
      "final_answer": "本周共运动 4 次（周二晨跑、周三力量、周五游泳、周日骑行），已处理补训待办。",
  }


def run_agent_loop(
    task: str,
    notes_dir: pathlib.Path,
    trace_path: pathlib.Path,
    *,
    fault_mode: str = "none",
    confirm_fn: Callable[[str, dict[str, Any]], bool] | None = None,
    max_steps: int = MAX_STEPS,
    max_chars_per_obs: int = MAX_CHARS_PER_OBS,
) -> dict[str, Any]:
  """最小 Agent 主循环（基线半成品：缺参数校验、异常自愈、重复熔断、写前确认与轨迹写入）。"""
  registry = build_tool_registry(notes_dir)
  observations: list[str] = []

  # TODO(3): 补全完整 messages 历史、validate_tool_args 参数拦截回传、try...except 工具异常转观察、
  # 连续相同调用签名熔断、high_risk 写操作前 confirm_fn 人工确认，以及每步写入 trace_path (JSONL)。
  for step_idx in range(max_steps):
    decision = _naive_mock_step(step_idx, fault_mode)
    if decision.get("final_answer"):
      return {
          "status": "completed",
          "stop_reason": "final_answer",
          "final_answer": decision["final_answer"],
          "steps_used": step_idx + 1,
          "observations": observations,
      }
    tc = decision["tool_call"]
    tool = registry[tc["name"]]
    raw_obs = tool["fn"](**tc["arguments"])
    observations.append(truncate_observation(raw_obs, max_chars_per_obs))

  return {
      "status": "max_steps",
      "stop_reason": "max_steps",
      "final_answer": "",
      "steps_used": max_steps,
      "observations": observations,
  }


def replay_trace(trace_path: pathlib.Path) -> list[dict[str, Any]]:
  """读取并还原 trace.jsonl 全程执行轨迹。"""
  # TODO(4): 逐行解析 trace_path 中的 JSONL 记录并返回步骤列表。
  return []


def main() -> int:
  parser = argparse.ArgumentParser(description="S4-M02 最小安全 Agent 闭环实验")
  parser.add_argument("--mock-fault", choices=["none", "bad_args", "tool_err", "loop"], default="none")
  parser.add_argument("--trace-file", type=pathlib.Path, default=pathlib.Path("/tmp/aid_s4m02_trace.jsonl"))
  parser.add_argument("--auto-approve", action="store_true")
  parser.add_argument("--replay", type=pathlib.Path, default=None)
  args = parser.parse_args()

  if args.replay:
    records = replay_trace(args.replay)
    print(f"回放记录数: {len(records)}")
    return 0

  res = run_agent_loop(
      "统计本周运动次数并按需追加待办",
      LAB_DIR / "fixtures" / "notes",
      args.trace_file,
      fault_mode=args.mock_fault,
      confirm_fn=(lambda _name, _args: True) if args.auto_approve else None,
  )
  print(json.dumps(res, ensure_ascii=False, indent=2))
  return 0


if __name__ == "__main__":
  sys.exit(main())
