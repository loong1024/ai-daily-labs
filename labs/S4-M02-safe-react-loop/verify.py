#!/usr/bin/env python3
"""S4-M02 自动化验收脚本：验证参数校验自愈、工具异常恢复、四道硬护栏与 JSONL 轨迹回放。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile
from types import ModuleType
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_module(path: pathlib.Path) -> ModuleType:
  spec = importlib.util.spec_from_file_location("s4_m02_target", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules["s4_m02_target"] = mod
  spec.loader.exec_module(mod)
  return mod


def _prepare_temp_notes(base_dir: pathlib.Path, tag: str) -> tuple[pathlib.Path, pathlib.Path]:
  run_dir = base_dir / tag
  notes_copy = run_dir / "notes"
  shutil.copytree(LAB_DIR / "fixtures" / "notes", notes_copy)
  trace_file = run_dir / "trace.jsonl"
  return notes_copy, trace_file


def main() -> int:
  v = LabVerifier("S4-M02", "最小安全 Agent 工具循环、四道硬护栏与故障注入回放")
  impl_path = target_file(LAB_DIR, "starter.py", "solution.py")

  try:
    mod = _load_module(impl_path)
  except Exception as exc:
    v.check("加载目标实现模块", False, f"导入 {impl_path.name} 失败（{type(exc).__name__}: {exc}），请修复语法或依赖问题。")
    return v.finish()

  scenarios_cfg = json.loads((LAB_DIR / "fixtures" / "fault_scenarios.json").read_text(encoding="utf-8"))
  default_task: str = scenarios_cfg["default_task"]

  with tempfile.TemporaryDirectory(prefix="aid_s4m02_verify_") as tmp_str:
    tmp_base = pathlib.Path(tmp_str)

    # 验收项 1：正常多步收敛 + 高危写操作人工确认门禁 + 长观察 600 字截断护栏
    normal_trace_path: pathlib.Path | None = None
    normal_steps_used = 0
    try:
      notes_ok, trace_ok = _prepare_temp_notes(tmp_base, "normal_approved")
      normal_trace_path = trace_ok
      confirm_calls: list[tuple[str, dict[str, Any]]] = []

      def _approve_hook(name: str, args: dict[str, Any]) -> bool:
        confirm_calls.append((name, dict(args)))
        return True

      res_ok = mod.run_agent_loop(
          default_task,
          notes_ok,
          trace_ok,
          fault_mode="none",
          confirm_fn=_approve_hook,
          max_steps=8,
          max_chars_per_obs=600,
      )
      normal_steps_used = int(res_ok.get("steps_used", 0))
      todo_after_approve = (notes_ok / "todo.md").read_text(encoding="utf-8")
      obs_list = res_ok.get("observations", [])
      obs_truncated_ok = bool(obs_list) and all(len(str(o)) <= 600 for o in obs_list)

      # 对照验证：当人工确认返回 False 时，todo.md 绝不能被偷偷写入
      notes_deny, trace_deny = _prepare_temp_notes(tmp_base, "normal_rejected")
      todo_before_deny = (notes_deny / "todo.md").read_text(encoding="utf-8")
      _ = mod.run_agent_loop(
          default_task,
          notes_deny,
          trace_deny,
          fault_mode="none",
          confirm_fn=lambda _n, _a: False,
          max_steps=8,
          max_chars_per_obs=600,
      )
      todo_after_deny = (notes_deny / "todo.md").read_text(encoding="utf-8")

      passed_normal = (
          res_ok.get("status") == "completed"
          and 2 <= normal_steps_used <= 8
          and "4" in str(res_ok.get("final_answer", ""))
          and len(confirm_calls) >= 1
          and confirm_calls[0][0] == "append_todo"
          and "[high]" in todo_after_approve
          and todo_after_deny == todo_before_deny
          and obs_truncated_ok
      )
      v.check(
          "正常多步任务收敛、写操作前人工确认拦截与 <=600 字长观察截断",
          passed_normal,
          "请确保：① 执行 append_todo 前调用 confirm_fn（返回 False 时严禁落盘）；② truncate_observation 将超 600 字笔记截断至 <=600 字；③ 8 步内输出含运动统计结果的 final_answer。",
      )
    except Exception as exc:
      v.check(
          "正常多步任务收敛、写操作前人工确认拦截与 <=600 字长观察截断",
          False,
          f"运行正常模式抛出未捕获异常（{type(exc).__name__}: {exc}）。",
      )

    # 验收项 2：--mock-fault bad_args 参数校验拦截自愈 & --mock-fault tool_err 异常捕获恢复
    try:
      notes_bad, trace_bad = _prepare_temp_notes(tmp_base, "bad_args")
      res_bad = mod.run_agent_loop(
          default_task,
          notes_bad,
          trace_bad,
          fault_mode="bad_args",
          confirm_fn=lambda _n, _a: True,
          max_steps=8,
      )
      todo_bad = (notes_bad / "todo.md").read_text(encoding="utf-8")
      bad_obs_joined = "\n".join(str(x) for x in res_bad.get("observations", []))

      notes_err, trace_err = _prepare_temp_notes(tmp_base, "tool_err")
      res_err = mod.run_agent_loop(
          default_task,
          notes_err,
          trace_err,
          fault_mode="tool_err",
          confirm_fn=lambda _n, _a: True,
          max_steps=8,
      )
      err_obs_joined = "\n".join(str(x) for x in res_err.get("observations", []))

      healed_ok = (
          res_bad.get("status") == "completed"
          and "SUPER_URGENT" not in todo_bad
          and "[high]" in todo_bad
          and ("校验" in bad_obs_joined or "SCHEMA" in bad_obs_joined or "枚举" in bad_obs_joined)
          and res_err.get("status") == "completed"
          and ("FileNotFoundError" in err_obs_joined or "不存在" in err_obs_joined)
          and "4" in str(res_err.get("final_answer", ""))
      )
      v.check(
          "故障注入自愈：非法参数拦截重填 (bad_args) 与工具异常恢复 (tool_err)",
          healed_ok,
          "请补全 validate_tool_args（拦截非法枚举 SUPER_URGENT 与多余字段 extra_flag 并回传可读报错），并用 try...except 捕获工具 FileNotFoundError 作为观察回传给模型自愈。",
      )
    except Exception as exc:
      v.check(
          "故障注入自愈：非法参数拦截重填 (bad_args) 与工具异常恢复 (tool_err)",
          False,
          f"运行 bad_args / tool_err 故障演练时崩溃（{type(exc).__name__}: {exc}）——切勿让工具或参数错误直接炸毁主循环！",
      )

    # 验收项 3：--mock-fault loop 连续重复调用签名提前熔断与进展输出
    try:
      notes_loop, trace_loop = _prepare_temp_notes(tmp_base, "loop")
      res_loop = mod.run_agent_loop(
          default_task,
          notes_loop,
          trace_loop,
          fault_mode="loop",
          confirm_fn=lambda _n, _a: True,
          max_steps=8,
      )
      steps_loop = int(res_loop.get("steps_used", 99))
      loop_halted = (
          res_loop.get("status") == "halted_guardrail"
          and "duplicate" in str(res_loop.get("stop_reason", "")).lower()
          and steps_loop <= 3
          and bool(str(res_loop.get("partial_progress", "")).strip())
      )
      v.check(
          "死循环熔断 (--mock-fault loop)：连续相同调用签名提前停机并输出阶段进展",
          loop_halted,
          "请在主循环中计算规范化调用签名（工具名+排序后 JSON 参数），连续重复达到阈值时立即触发 duplicate_call_circuit_breaker 停机（步数 <=3）并返回 partial_progress。",
      )
    except Exception as exc:
      v.check(
          "死循环熔断 (--mock-fault loop)：连续相同调用签名提前停机并输出阶段进展",
          False,
          f"运行 loop 故障演练抛出异常（{type(exc).__name__}: {exc}）。",
      )

    # 验收项 4：trace.jsonl 轨迹落盘完整性与 replay_trace 100% 确定性还原
    try:
      replayed = mod.replay_trace(normal_trace_path) if normal_trace_path else []
      required_keys = {"step", "observation", "elapsed_ms", "cumulative_tokens"}
      trace_valid = (
          isinstance(replayed, list)
          and normal_steps_used >= 2
          and len(replayed) == normal_steps_used
          and all(isinstance(r, dict) and required_keys.issubset(r.keys()) for r in replayed)
          and [r["step"] for r in replayed] == list(range(1, normal_steps_used + 1))
      )
      v.check(
          "trace.jsonl 执行轨迹落盘与 replay_trace 100% 全程还原",
          trace_valid,
          "请在每步执行后向 trace_path 写入一行包含 step、call_signature、observation、elapsed_ms、cumulative_tokens 的 JSONL，并在 replay_trace 中逐行解析返回。",
      )
    except Exception as exc:
      v.check(
          "trace.jsonl 执行轨迹落盘与 replay_trace 100% 全程还原",
          False,
          f"解析或回放 trace.jsonl 抛出异常（{type(exc).__name__}: {exc}）。",
      )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
