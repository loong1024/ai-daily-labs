"""S4-M07 起点沙箱脚本（含四处待加固的基线缺陷）。

请结合 README.md 与 verify.py 的诊断提示，逐项补全四道物理安全边界：
1. read_workspace_file：限制只能读取 workspace_root 内部文件，越界抛出 PermissionError。
2. build_isolated_env / probe_subprocess_env：白名单过滤环境变量，杜绝测试密钥透传。
3. render_safe_preview_html：注入严格 CSP 响应头并拦截 http/https 等外链图片。
4. run_guarded_tool_loop：对连续相同报错启用硬熔断（超过 max_repeats 立即停机并写审计日志）。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping

SAFE_ENV_ALLOWLIST: tuple[str, ...] = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def read_workspace_file(workspace_root: pathlib.Path, requested_path: str) -> str:
  """读取工作区内指定文件。

  TODO(边界1)：当前直接拼接路径读取，未校验解析后的真实路径是否仍在 workspace_root 内！
  """
  target = pathlib.Path(workspace_root) / requested_path
  return target.read_text(encoding="utf-8")


def build_isolated_env(
    host_env: Mapping[str, str],
    extra_allowlist: Iterable[str] = (),
) -> dict[str, str]:
  """构造传给子进程的隔离环境变量字典。

  TODO(边界2)：当前直接复制了全量 host_env，导致 FAKE_PROD_KEY 等敏感变量泄露到子进程！
  """
  _ = extra_allowlist
  return dict(host_env)


def probe_subprocess_env(
    workspace_root: pathlib.Path,
    host_env: Mapping[str, str],
) -> dict[str, str]:
  """在工作区目录启动受限子进程并返回其可见的 os.environ 快照。"""
  child_env = build_isolated_env(host_env)
  proc = subprocess.run(
      [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
      cwd=str(pathlib.Path(workspace_root).resolve()),
      env=child_env,
      capture_output=True,
      text=True,
      check=True,
      timeout=10,
  )
  return json.loads(proc.stdout.strip())


def render_safe_preview_html(markdown_text: str) -> str:
  """将 Markdown 片段渲染为本地 HTML 预览页。

  TODO(边界3)：
  1. 缺少 <meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self';">；
  2. 未对正文做 HTML 转义，且直接把外链 URL 渲染进了 <img src="...">。
  """

  def _img_repl(match: re.Match[str]) -> str:
    alt_text, raw_url = match.group(1), match.group(2).strip()
    return f'<img alt="{alt_text}" src="{raw_url}" />'

  rendered_body = _MD_IMAGE_RE.sub(_img_repl, markdown_text)
  return (
      "<!DOCTYPE html>\n"
      "<html lang=\"zh-CN\">\n"
      "<head><meta charset=\"utf-8\"><title>Preview</title></head>\n"
      f"<body>\n<article>{rendered_body}</article>\n</body>\n"
      "</html>"
  )


def run_guarded_tool_loop(
    planned_calls: list[dict[str, Any]],
    tool_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
    max_repeats: int = 2,
) -> dict[str, Any]:
  """执行工具调用序列，配备连续重复报错硬熔断器。

  TODO(边界4)：当前未统计连续相同错误签名，即使连续报错超过 max_repeats 仍把队列跑完，且未写审计日志！
  """
  _ = max_repeats
  executed_count = 0
  outputs: list[dict[str, Any]] = []
  audit_log: list[dict[str, Any]] = []

  for step_idx, call in enumerate(planned_calls, 1):
    tool_name = str(call.get("tool", ""))
    args = dict(call.get("args", {}))
    executed_count += 1
    res = tool_fn(tool_name, args)
    outputs.append({"step": step_idx, "tool": tool_name, "result": res})

  return {
      "halted": False,
      "halt_reason": None,
      "executed_count": executed_count,
      "outputs": outputs,
      "audit_log": audit_log,
  }
