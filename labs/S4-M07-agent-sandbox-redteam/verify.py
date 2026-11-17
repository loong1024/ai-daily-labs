#!/usr/bin/env python3
"""S4-M07 自动化红绿验收脚本：四道物理边界安全压测。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
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
  mod_name = f"s4_m07_{mod_path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def _mock_tool_executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
  if tool_name == "query_log_archive" and args.get("day") == "2026-99-99":
    return {"ok": False, "error": "INVALID_DATE_RANGE"}
  return {"ok": True, "data": f"{tool_name}:done"}


def main() -> int:
  v = LabVerifier("S4-M07", "让 Agent 夜间无人值守怕删库泄密？四道物理边界安全压测")
  cases = json.loads((LAB_DIR / "fixtures" / "sandbox_cases.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块语法与导入检查", False, f"导入目标文件失败：{exc}")
    return v.finish()

  with tempfile.TemporaryDirectory(prefix="aid_s4_m07_") as tmp_root_str:
    tmp_root = pathlib.Path(tmp_root_str)
    workspace_dir = tmp_root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    for rel_p, text in cases["workspace_files"].items():
      fp = workspace_dir / rel_p
      fp.parent.mkdir(parents=True, exist_ok=True)
      fp.write_text(text, encoding="utf-8")

    outside_paths: list[pathlib.Path] = []
    for rel_p, text in cases["outside_files"].items():
      fp = tmp_root / rel_p
      fp.write_text(text, encoding="utf-8")
      outside_paths.append(fp)

    # 1. 边界一：工作区目录越界隔离
    try:
      path_ok = True
      for item in cases["path_cases"]:
        req_p = item["requested_path"]
        expect_allowed = item["expect_allowed"]
        if expect_allowed:
          content = mod.read_workspace_file(workspace_dir, req_p)
          if content != cases["workspace_files"][req_p]:
            path_ok = False
        else:
          try:
            _ = mod.read_workspace_file(workspace_dir, req_p)
            path_ok = False
          except PermissionError:
            pass
      # 额外测试工作区外绝对路径拦截
      try:
        _ = mod.read_workspace_file(workspace_dir, str(outside_paths[0]))
        path_ok = False
      except PermissionError:
        pass

      v.check(
          "边界 1 · 工作区目录隔离（区内正常读取，../ 与区外绝对路径 100% 拒绝）",
          path_ok,
          "请在 read_workspace_file 中通过 Path.resolve() 与 is_relative_to(root_resolved) 拦截一切跳出工作区的路径并抛出 PermissionError。",
      )
    except Exception as exc:
      v.check(
          "边界 1 · 工作区目录隔离（区内正常读取，../ 与区外绝对路径 100% 拒绝）",
          False,
          f"执行路径边界测试时抛出未预期异常：{exc}",
      )

    # 2. 边界二：子进程环境变量白名单脱敏
    try:
      host_env = dict(cases["mock_host_env"])
      sub_env = mod.probe_subprocess_env(workspace_dir, host_env)
      forbidden_keys = {"FAKE_PROD_KEY", "DB_PASSWORD", "CLOUD_ADMIN_TOKEN"}
      leaked_keys = forbidden_keys.intersection(sub_env.keys())
      serialized_env = json.dumps(sub_env, ensure_ascii=False)
      has_fake_secret_val = "FAKE_TEST_KEY_DO_NOT_USE_" in serialized_env
      env_ok = (
          isinstance(sub_env, dict)
          and sub_env.get("PATH") == host_env["PATH"]
          and len(leaked_keys) == 0
          and not has_fake_secret_val
      )
      v.check(
          "边界 2 · 子进程凭证隔离（保留基础 PATH，敏感环境变量 0 残留）",
          env_ok,
          "请在 build_isolated_env 中启用严格白名单过滤（仅透传 PATH/LANG/LC_ALL/SYSTEMROOT），切勿直接透传全量 host_env。",
      )
    except Exception as exc:
      v.check(
          "边界 2 · 子进程凭证隔离（保留基础 PATH，敏感环境变量 0 残留）",
          False,
          f"执行子进程环境探测时报错：{exc}",
      )

    # 3. 边界三：CSP 响应头与外链图片阻断
    try:
      rendered = mod.render_safe_preview_html(cases["markdown_samples"]["mixed_preview"])
      lower_html = rendered.lower()
      has_csp_meta = (
          'http-equiv="content-security-policy"' in lower_html
          and "default-src 'self'" in lower_html
          and "img-src 'self'" in lower_html
      )
      img_srcs = re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', rendered, flags=re.IGNORECASE)
      keeps_local_img = "assets/topology.png" in img_srcs
      blocks_external_img = all(
          not s.lower().startswith(("http://", "https://", "//")) for s in img_srcs
      )
      escapes_raw_script = "<script>" not in lower_html
      csp_ok = has_csp_meta and keeps_local_img and blocks_external_img and escapes_raw_script
      v.check(
          "边界 3 · 预览页 CSP 防护与外链阻断（含 CSP 头、保留本地图、0 外链 img 请求）",
          csp_ok,
          "请在 HTML <head> 加入 Content-Security-Policy (default-src 'self'; img-src 'self')，转义正文 HTML，并将 http/https 外链图片替换为拦截占位标签。",
      )
    except Exception as exc:
      v.check(
          "边界 3 · 预览页 CSP 防护与外链阻断（含 CSP 头、保留本地图、0 外链 img 请求）",
          False,
          f"渲染 HTML 预览页时报错：{exc}",
      )

    # 4. 边界四：工具连续异常硬熔断与审计日志
    try:
      loop_cfg = cases["tool_loop_cases"]
      max_rep = int(loop_cfg["max_repeats"])
      runaway_res = mod.run_guarded_tool_loop(
          loop_cfg["runaway_calls"], _mock_tool_executor, max_repeats=max_rep
      )
      healthy_res = mod.run_guarded_tool_loop(
          loop_cfg["healthy_calls"], _mock_tool_executor, max_repeats=max_rep
      )

      audit_entries = runaway_res.get("audit_log", [])
      has_trip_audit = isinstance(audit_entries, list) and any(
          "CIRCUIT" in str(entry.get("event", "")).upper()
          or "TRIP" in str(entry.get("event", "")).upper()
          or "HALT" in str(entry.get("event", "")).upper()
          for entry in audit_entries
          if isinstance(entry, dict)
      )
      breaker_ok = (
          runaway_res.get("halted") is True
          and 2 <= int(runaway_res.get("executed_count", 0)) <= max_rep + 1
          and has_trip_audit
          and healthy_res.get("halted") is False
          and int(healthy_res.get("executed_count", 0)) == len(loop_cfg["healthy_calls"])
      )
      v.check(
          "边界 4 · 连续相同报错硬熔断与审计留痕（达阈值立即停机，正常恢复不误杀）",
          breaker_ok,
          "请在 run_guarded_tool_loop 中统计连续相同错误签名；当连续报错超过 max_repeats 时立刻返回 halted=True 且写入含 CIRCUIT_BREAKER_TRIPPED 事件的 audit_log；成功调用时重置计数。",
      )
    except Exception as exc:
      v.check(
          "边界 4 · 连续相同报错硬熔断与审计留痕（达阈值立即停机，正常恢复不误杀）",
          False,
          f"执行工具熔断测试时报错：{exc}",
      )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
