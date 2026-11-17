#!/usr/bin/env python3
"""S4-M02 Solution：带参数校验、异常自愈、四道硬护栏与 JSONL 轨迹回放的最小安全 Agent。"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time
from typing import Any, Callable

MAX_STEPS = 8
MAX_CHARS_PER_OBS = 600
MAX_REPEAT_CALLS = 2
MAX_TOKEN_BUDGET = 6000

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


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


def _check_json_type(val: Any, expected_type: str) -> bool:
  if expected_type == "string":
    return isinstance(val, str)
  if expected_type == "integer":
    return isinstance(val, int) and not isinstance(val, bool)
  if expected_type == "number":
    return isinstance(val, (int, float)) and not isinstance(val, bool)
  if expected_type == "boolean":
    return isinstance(val, bool)
  if expected_type == "array":
    return isinstance(val, list)
  if expected_type == "object":
    return isinstance(val, dict)
  return True


def validate_tool_args(schema: dict[str, Any], args: Any) -> tuple[bool, str]:
  """按 JSON Schema 子集严格校验工具参数，失败返回可操作的中文修复指引。"""
  if not isinstance(args, dict):
    return False, f"参数必须为 JSON 对象 (dict)，当前收到 {type(args).__name__}"

  props = schema.get("properties", {})
  required = schema.get("required", [])
  for req_key in required:
    if req_key not in args or args[req_key] is None:
      return False, f"缺少必填参数 '{req_key}'（必填项: {required}）"

  if schema.get("additionalProperties") is False:
    unknown = [k for k in args if k not in props]
    if unknown:
      return False, f"存在未声明的多余参数 {unknown}，仅允许字段 {list(props.keys())}"

  for key, val in args.items():
    if key not in props:
      continue
    rule = props[key]
    expected_type = rule.get("type")
    if expected_type and not _check_json_type(val, expected_type):
      return False, f"参数 '{key}' 类型错误：期望 {expected_type}，收到 {type(val).__name__}"
    if "enum" in rule and val not in rule["enum"]:
      return False, f"参数 '{key}' 值 '{val}' 非法，必须为枚举值之一: {rule['enum']}"
    if expected_type == "string" and "minLength" in rule and len(val.strip()) < rule["minLength"]:
      return False, f"参数 '{key}' 长度不足，至少需要 {rule['minLength']} 个有效字符"
    if expected_type == "array":
      if "minItems" in rule and len(val) < rule["minItems"]:
        return False, f"数组参数 '{key}' 至少需要 {rule['minItems']} 个元素"
      item_type = rule.get("items", {}).get("type")
      if item_type and not all(_check_json_type(elem, item_type) for elem in val):
        return False, f"数组参数 '{key}' 内元素类型必须全部为 {item_type}"

  return True, ""


def truncate_observation(text: str, max_chars: int = MAX_CHARS_PER_OBS) -> str:
  """截断超长观察，确保返回长度严格 <= max_chars。"""
  if len(text) <= max_chars:
    return text
  suffix = f" ...[已截断，原长 {len(text)} 字]"
  if max_chars <= len(suffix):
    return text[:max_chars]
  return text[: max_chars - len(suffix)] + suffix


def make_call_signature(tool_name: str, args: Any) -> str:
  try:
    norm_args = json.dumps(args, ensure_ascii=False, sort_keys=True)
  except TypeError:
    norm_args = repr(args)
  return f"{tool_name}:{norm_args}"


def _build_mock_model(fault_mode: str) -> Callable[[list[dict[str, str]]], str]:
  """根据消息历史确定性驱动正常流程或三类故障复现场景。"""

  def _mock_fn(messages: list[dict[str, str]]) -> str:
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    turn_idx = len(tool_msgs)

    if fault_mode == "loop":
      return json.dumps(
          {
              "thought": "继续列举包含 2026 的笔记文件",
              "tool_call": {
                  "id": f"call_{turn_idx + 1}",
                  "name": "list_notes",
                  "arguments": {"keyword": "2026"},
              },
              "final_answer": None,
          },
          ensure_ascii=False,
      )

    if fault_mode == "bad_args":
      if turn_idx == 0:
        return json.dumps(
            {
                "thought": "先直接尝试写入待办",
                "tool_call": {
                    "id": "call_1",
                    "name": "append_todo",
                    "arguments": {
                        "item": "本周运动共 4 次，下周补齐第 5 次有氧训练",
                        "priority": "SUPER_URGENT",
                        "extra_flag": True,
                    },
                },
                "final_answer": None,
            },
            ensure_ascii=False,
        )
      if turn_idx == 1:
        # 观察到上一轮 SCHEMA_INVALID 报错后自动修正枚举与多余参数
        return json.dumps(
            {
                "thought": "根据参数校验报错修正：去掉多余字段 extra_flag，并将 priority 改为合法枚举 high",
                "tool_call": {
                    "id": "call_2",
                    "name": "append_todo",
                    "arguments": {
                        "item": "本周运动共 4 次，下周补齐第 5 次有氧训练",
                        "priority": "high",
                    },
                },
                "final_answer": None,
            },
            ensure_ascii=False,
        )
      return json.dumps(
          {
              "thought": "参数自愈后写入已完成，输出结论",
              "tool_call": None,
              "final_answer": "参数校验报错已自动修正，成功向 todo.md 追加高优先级补训待办（本周运动 4 次）。",
          },
          ensure_ascii=False,
      )

    if fault_mode == "tool_err":
      if turn_idx == 0:
        return json.dumps(
            {
                "thought": "直接猜测文件名读取周记",
                "tool_call": {
                    "id": "call_1",
                    "name": "read_note",
                    "arguments": {"filename": "2026-W11-missing.md"},
                },
                "final_answer": None,
            },
            ensure_ascii=False,
        )
      if turn_idx == 1:
        return json.dumps(
            {
                "thought": "收到文件不存在异常，先调用 list_notes 查看真实文件名",
                "tool_call": {"id": "call_2", "name": "list_notes", "arguments": {}},
                "final_answer": None,
            },
            ensure_ascii=False,
        )
      if turn_idx == 2:
        return json.dumps(
            {
                "thought": "读取周一至周三日记",
                "tool_call": {
                    "id": "call_3",
                    "name": "read_note",
                    "arguments": {"filename": "2026-W11-mon-wed.md"},
                },
                "final_answer": None,
            },
            ensure_ascii=False,
        )
      if turn_idx == 3:
        return json.dumps(
            {
                "thought": "读取周四至周日日记",
                "tool_call": {
                    "id": "call_4",
                    "name": "read_note",
                    "arguments": {"filename": "2026-W11-thu-sun.md"},
                },
                "final_answer": None,
            },
            ensure_ascii=False,
        )
      return json.dumps(
          {
              "thought": "从报错中恢复并读完两篇真实周记，汇总结果",
              "tool_call": None,
              "final_answer": "已从文件不存在报错中恢复：核实本周共运动 4 次（周二晨跑、周三力量、周五游泳、周日骑行）。",
          },
          ensure_ascii=False,
      )

    # fault_mode == "none" 标准多步任务流程
    normal_steps = [
        ("查找 notes 目录下的笔记列表", "list_notes", {}),
        ("读取周一至周三日记统计运动次数", "read_note", {"filename": "2026-W11-mon-wed.md"}),
        ("读取周四至周日日记统计运动次数", "read_note", {"filename": "2026-W11-thu-sun.md"}),
        ("汇总两次周记运动次数 2 + 2", "calculator", {"operation": "add", "values": [2, 2]}),
        (
            "本周运动 4 次不足 5 次，追加高优先级补训待办",
            "append_todo",
            {"item": "本周运动共 4 次，下周补齐第 5 次有氧训练", "priority": "high"},
        ),
    ]
    if turn_idx < len(normal_steps):
      thought, name, arguments = normal_steps[turn_idx]
      return json.dumps(
          {
              "thought": thought,
              "tool_call": {"id": f"call_{turn_idx + 1}", "name": name, "arguments": arguments},
              "final_answer": None,
          },
          ensure_ascii=False,
      )

    last_obs = tool_msgs[-1]["content"] if tool_msgs else ""
    write_note = "人工取消了待办写入" if "拒绝" in last_obs or "取消" in last_obs else "已确认写入补训待办"
    return json.dumps(
        {
            "thought": "统计与待办流程均已完成，如实输出结果",
            "tool_call": None,
            "final_answer": f"统计完成：本周共运动 4 次（周二晨跑、周三力量、周五游泳、周日骑行），距目标差 1 次；{write_note}。",
        },
        ensure_ascii=False,
    )

  return _mock_fn


def _default_cli_confirm(tool_name: str, args: dict[str, Any]) -> bool:
  if not sys.stdin.isatty():
    return False
  ans = input(f"⚠️ 高危写操作确认：是否允许执行 {tool_name}({json.dumps(args, ensure_ascii=False)})？[y/N]: ")
  return ans.strip().lower() in {"y", "yes"}


def _append_trace_line(trace_path: pathlib.Path, record: dict[str, Any]) -> None:
  trace_path.parent.mkdir(parents=True, exist_ok=True)
  with trace_path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
  """运行带四道安全护栏与 JSONL 轨迹记录的最小自主 Agent 主循环。"""
  registry = build_tool_registry(notes_dir)
  trace_path.parent.mkdir(parents=True, exist_ok=True)
  trace_path.write_text("", encoding="utf-8")

  approver = confirm_fn if confirm_fn is not None else _default_cli_confirm
  tool_specs = [
      {"name": t["name"], "description": t["description"], "parameters": t["schema"]}
      for t in registry.values()
  ]
  system_prompt = (
      "你是本地笔记助手，严格输出 JSON 对象：{thought, tool_call, final_answer}。"
      f"可用工具定义：{json.dumps(tool_specs, ensure_ascii=False)}"
  )
  messages: list[dict[str, str]] = [
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": task},
  ]

  mock_driver = _build_mock_model(fault_mode)
  observations: list[str] = []
  completed_summaries: list[str] = []
  cumulative_tokens = 0
  last_signature: str | None = None
  consecutive_repeats = 0
  had_recoverable_error = False
  recovered_after_error = False

  for step in range(1, max_steps + 1):
    t0 = time.perf_counter()
    if fault_mode != "none":
      # 故障注入演练模式使用确定性桩以确保 100% 复现异常分支
      raw_reply = mock_driver(messages)
    else:
      raw_reply = chat_complete(messages, mock_fn=mock_driver, temperature=0.0, response_json=True)

    step_tokens = max(1, (len(messages[-1]["content"]) + len(raw_reply)) // 4)
    cumulative_tokens += step_tokens
    if cumulative_tokens > MAX_TOKEN_BUDGET:
      rec = {
          "step": step,
          "event": "guardrail_halt",
          "tool_name": None,
          "call_signature": None,
          "input_summary": messages[-1]["content"][:80],
          "observation": "超出累计 Token 预算上限，强制停机",
          "is_error": True,
          "guardrail_triggered": "token_budget_exceeded",
          "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
          "tokens_used": step_tokens,
          "cumulative_tokens": cumulative_tokens,
      }
      _append_trace_line(trace_path, rec)
      return {
          "status": "halted_guardrail",
          "stop_reason": "token_budget_exceeded",
          "final_answer": "",
          "partial_progress": "；".join(completed_summaries) or "尚未完成有效工具步骤",
          "steps_used": step,
          "observations": observations,
          "self_healed": recovered_after_error,
      }

    try:
      decision = json.loads(raw_reply)
    except json.JSONDecodeError as exc:
      err_obs = f"ERROR [INVALID_MODEL_JSON]: 模型输出非合法 JSON ({exc})，请按约定格式重发。"
      messages.append({"role": "assistant", "content": raw_reply})
      messages.append({"role": "tool", "content": err_obs})
      observations.append(err_obs)
      had_recoverable_error = True
      _append_trace_line(
          trace_path,
          {
              "step": step,
              "event": "model_format_error",
              "tool_name": None,
              "call_signature": None,
              "input_summary": messages[-3]["content"][:80],
              "observation": err_obs,
              "is_error": True,
              "guardrail_triggered": None,
              "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
              "tokens_used": step_tokens,
              "cumulative_tokens": cumulative_tokens,
          },
      )
      continue

    if not decision.get("tool_call"):
      final_answer = str(decision.get("final_answer") or "")
      _append_trace_line(
          trace_path,
          {
              "step": step,
              "event": "final_answer",
              "tool_name": None,
              "call_signature": None,
              "input_summary": messages[-1]["content"][:80],
              "observation": truncate_observation(final_answer, max_chars_per_obs),
              "is_error": False,
              "guardrail_triggered": None,
              "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
              "tokens_used": step_tokens,
              "cumulative_tokens": cumulative_tokens,
          },
      )
      return {
          "status": "completed",
          "stop_reason": "final_answer",
          "final_answer": final_answer,
          "partial_progress": "；".join(completed_summaries),
          "steps_used": step,
          "observations": observations,
          "self_healed": recovered_after_error,
      }

    tc = decision["tool_call"]
    tool_name = str(tc.get("name", ""))
    tool_args = tc.get("arguments", {})
    signature = make_call_signature(tool_name, tool_args)

    # 护栏 3：连续重复调用签名熔断
    if signature == last_signature:
      consecutive_repeats += 1
    else:
      last_signature = signature
      consecutive_repeats = 1

    if consecutive_repeats >= MAX_REPEAT_CALLS:
      halt_msg = f"检测到连续 {consecutive_repeats} 次重复调用签名 {signature}，判定空转并强制停机。"
      _append_trace_line(
          trace_path,
          {
              "step": step,
              "event": "guardrail_halt",
              "tool_name": tool_name,
              "call_signature": signature,
              "input_summary": messages[-1]["content"][:80],
              "observation": halt_msg,
              "is_error": True,
              "guardrail_triggered": "duplicate_call_circuit_breaker",
              "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
              "tokens_used": step_tokens,
              "cumulative_tokens": cumulative_tokens,
          },
      )
      return {
          "status": "halted_guardrail",
          "stop_reason": "duplicate_call_circuit_breaker",
          "final_answer": "",
          "partial_progress": "；".join(completed_summaries) or "已完成前置只读步骤，因重复调用已安全熔断",
          "steps_used": step,
          "observations": observations,
          "self_healed": recovered_after_error,
      }

    messages.append({"role": "assistant", "content": raw_reply})
    is_err = False
    guardrail_tag: str | None = None

    if tool_name not in registry:
      raw_obs = f"ERROR [UNKNOWN_TOOL]: 未知工具 '{tool_name}'，可用工具为 {list(registry.keys())}"
      is_err = True
      had_recoverable_error = True
    else:
      tool_entry = registry[tool_name]
      valid, err_reason = validate_tool_args(tool_entry["schema"], tool_args)
      if not valid:
        raw_obs = f"ERROR [SCHEMA_INVALID]: 工具 {tool_name} 参数校验未通过 — {err_reason}"
        is_err = True
        had_recoverable_error = True
      elif tool_entry.get("high_risk") and not approver(tool_name, tool_args):
        raw_obs = f"GUARDRAIL [USER_REJECTED]: 人工拒绝执行高危写操作 {tool_name}，未修改任何文件。"
        guardrail_tag = "human_confirmation_rejected"
        completed_summaries.append(f"Step {step}: 用户取消写操作 {tool_name}")
      else:
        try:
          raw_obs = str(tool_entry["fn"](**tool_args))
          if had_recoverable_error:
            recovered_after_error = True
          completed_summaries.append(f"Step {step}: {tool_name} 执行成功")
        except Exception as exc:
          raw_obs = f"ERROR [TOOL_EXCEPTION]: {type(exc).__name__}: {exc}"
          is_err = True
          had_recoverable_error = True

    was_truncated = len(raw_obs) > max_chars_per_obs
    safe_obs = truncate_observation(raw_obs, max_chars_per_obs)
    if was_truncated and guardrail_tag is None:
      guardrail_tag = "observation_truncated"

    observations.append(safe_obs)
    messages.append({"role": "tool", "name": tool_name, "content": safe_obs})
    obs_tokens = max(1, len(safe_obs) // 4)
    cumulative_tokens += obs_tokens

    _append_trace_line(
        trace_path,
        {
            "step": step,
            "event": "tool_execution",
            "call_id": tc.get("id", f"call_{step}"),
            "tool_name": tool_name,
            "call_signature": signature,
            "input_summary": messages[-3]["content"][:80],
            "observation": safe_obs,
            "is_error": is_err,
            "guardrail_triggered": guardrail_tag,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
            "tokens_used": step_tokens + obs_tokens,
            "cumulative_tokens": cumulative_tokens,
        },
    )

  # 护栏 1：触及 MAX_STEPS 硬上限停机
  _append_trace_line(
      trace_path,
      {
          "step": max_steps,
          "event": "guardrail_halt",
          "tool_name": None,
          "call_signature": None,
          "input_summary": "达到最大步数上限",
          "observation": f"达到 MAX_STEPS={max_steps} 上限，停止循环。",
          "is_error": True,
          "guardrail_triggered": "max_steps_exceeded",
          "elapsed_ms": 0.0,
          "tokens_used": 0,
          "cumulative_tokens": cumulative_tokens,
      },
  )
  return {
      "status": "halted_guardrail",
      "stop_reason": "max_steps_exceeded",
      "final_answer": "",
      "partial_progress": "；".join(completed_summaries) or "未在步数上限内收敛",
      "steps_used": max_steps,
      "observations": observations,
      "self_healed": recovered_after_error,
  }


def replay_trace(trace_path: pathlib.Path) -> list[dict[str, Any]]:
  """从 trace.jsonl 逐行解析并还原全程执行轨迹。"""
  if not trace_path.is_file():
    return []
  records: list[dict[str, Any]] = []
  for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line:
      continue
    records.append(json.loads(line))
  return records


def format_replay_report(records: list[dict[str, Any]]) -> str:
  lines = [f"=== Trace 回放（共 {len(records)} 步） ==="]
  for rec in records:
    sig = rec.get("call_signature") or rec.get("event")
    guard = f" [护栏:{rec['guardrail_triggered']}]" if rec.get("guardrail_triggered") else ""
    lines.append(
        f"  Step {rec['step']} | {sig}{guard} | tokens={rec.get('cumulative_tokens', 0)} | {rec.get('observation', '')[:80]}"
    )
  return "\n".join(lines)


def main() -> int:
  parser = argparse.ArgumentParser(description="S4-M02 带四道硬护栏的最小安全 Agent 闭环")
  parser.add_argument("--mock-fault", choices=["none", "bad_args", "tool_err", "loop"], default="none")
  parser.add_argument("--trace-file", type=pathlib.Path, default=pathlib.Path("/tmp/aid_s4m02_trace.jsonl"))
  parser.add_argument("--auto-approve", action="store_true")
  parser.add_argument("--replay", type=pathlib.Path, default=None)
  args = parser.parse_args()

  if args.replay:
    recs = replay_trace(args.replay)
    print(format_replay_report(recs))
    return 0

  with tempfile.TemporaryDirectory(prefix="aid_s4m02_cli_") as tmp_dir:
    sandbox_notes = pathlib.Path(tmp_dir) / "notes"
    sandbox_notes.mkdir(parents=True, exist_ok=True)
    for src in (LAB_DIR / "fixtures" / "notes").glob("*.md"):
      (sandbox_notes / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_agent_loop(
        "读取 notes/ 下本周的日记，统计运动了几次；若不足 5 次则向 todo.md 追加一条高优先级补训待办。",
        sandbox_notes,
        args.trace_file,
        fault_mode=args.mock_fault,
        confirm_fn=(lambda _n, _a: True) if args.auto_approve else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
  return 0


if __name__ == "__main__":
  sys.exit(main())
