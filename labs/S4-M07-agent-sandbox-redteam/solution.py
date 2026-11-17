"""S4-M07 标准参考实现：四道物理安全边界完整加固版。"""

from __future__ import annotations

import html
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
from typing import Any, Callable, Iterable, Mapping

SAFE_ENV_ALLOWLIST: tuple[str, ...] = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def read_workspace_file(workspace_root: pathlib.Path, requested_path: str) -> str:
  """仅允许读取位于 workspace_root 物理目录内部的文件。"""
  if not requested_path or "\x00" in requested_path:
    raise PermissionError("非法路径请求：路径为空或包含空字节。")

  root_resolved = pathlib.Path(workspace_root).resolve()
  candidate = pathlib.Path(requested_path)
  if candidate.is_absolute():
    target_resolved = candidate.resolve()
  else:
    target_resolved = (root_resolved / candidate).resolve()

  if not target_resolved.is_relative_to(root_resolved) or target_resolved == root_resolved:
    raise PermissionError(
        f"越界访问已被沙箱拦截：'{requested_path}' 不在受控工作区 '{root_resolved}' 内。"
    )
  if not target_resolved.is_file():
    raise FileNotFoundError(f"工作区内不存在目标文件：'{requested_path}'")

  return target_resolved.read_text(encoding="utf-8")


def build_isolated_env(
    host_env: Mapping[str, str],
    extra_allowlist: Iterable[str] = (),
) -> dict[str, str]:
  """按严格白名单构造最小化子进程环境变量，剔除一切未授权凭证。"""
  allowed_keys = set(SAFE_ENV_ALLOWLIST) | set(extra_allowlist)
  isolated: dict[str, str] = {}
  for key in sorted(allowed_keys):
    val = host_env.get(key)
    if val is not None:
      isolated[key] = str(val)
  return isolated


def probe_subprocess_env(
    workspace_root: pathlib.Path,
    host_env: Mapping[str, str],
) -> dict[str, str]:
  """在受限工作目录中以白名单环境变量启动子进程，并返回其实测可见环境。"""
  root_resolved = pathlib.Path(workspace_root).resolve()
  child_env = build_isolated_env(host_env)
  child_env["HOME"] = str(root_resolved)

  proc = subprocess.run(
      [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
      cwd=str(root_resolved),
      env=child_env,
      capture_output=True,
      text=True,
      check=True,
      timeout=10,
  )
  return json.loads(proc.stdout.strip())


def _is_safe_local_asset(raw_url: str) -> bool:
  """仅放行无协议头、非协议相对路径、且不含父级跳转的本地静态资源路径。"""
  cleaned = raw_url.strip()
  if not cleaned or cleaned.startswith(("/", "\\", "//")):
    return False
  parsed = urllib.parse.urlsplit(cleaned)
  if parsed.scheme or parsed.netloc:
    return False
  parts = pathlib.PurePosixPath(parsed.path).parts
  if ".." in parts:
    return False
  return True


def render_safe_preview_html(markdown_text: str) -> str:
  """生成带严格 CSP 策略且自动剥离外链图片的只读本地 HTML 预览页。"""
  placeholders: list[str] = []

  def _extract_img(match: re.Match[str]) -> str:
    alt_safe = html.escape(match.group(1), quote=True)
    raw_url = match.group(2).strip()
    if _is_safe_local_asset(raw_url):
      url_safe = html.escape(raw_url, quote=True)
      tag = f'<img alt="{alt_safe}" src="{url_safe}" />'
    else:
      tag = (
          f'<span class="blocked-external-img" data-blocked="true">'
          f"[沙箱已拦截外链图片: {alt_safe}]</span>"
      )
    token = f"__AID_IMG_TOKEN_{len(placeholders)}__"
    placeholders.append(tag)
    return token

  tokenized = _MD_IMAGE_RE.sub(_extract_img, markdown_text)
  escaped_body = html.escape(tokenized, quote=False)
  for idx, tag_html in enumerate(placeholders):
    escaped_body = escaped_body.replace(f"__AID_IMG_TOKEN_{idx}__", tag_html)

  csp_policy = "default-src 'self'; img-src 'self'; script-src 'none'; object-src 'none';"
  return (
      "<!DOCTYPE html>\n"
      "<html lang=\"zh-CN\">\n"
      "<head>\n"
      "  <meta charset=\"utf-8\">\n"
      f"  <meta http-equiv=\"Content-Security-Policy\" content=\"{csp_policy}\">\n"
      "  <title>Safe Agent Preview</title>\n"
      "</head>\n"
      f"<body>\n<article>{escaped_body}</article>\n</body>\n"
      "</html>"
  )


def run_guarded_tool_loop(
    planned_calls: list[dict[str, Any]],
    tool_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
    max_repeats: int = 2,
) -> dict[str, Any]:
  """运行受控工具调用循环，连续相同错误超出 max_repeats（第 max_repeats+1 次）立即熔断停机。"""
  executed_count = 0
  outputs: list[dict[str, Any]] = []
  audit_log: list[dict[str, Any]] = []

  last_error_sig: str | None = None
  consecutive_errors = 0

  for step_idx, call in enumerate(planned_calls, 1):
    tool_name = str(call.get("tool", ""))
    args = dict(call.get("args", {}))
    executed_count += 1
    res = tool_fn(tool_name, args)
    outputs.append({"step": step_idx, "tool": tool_name, "result": res})

    is_error = bool(res.get("ok") is False or res.get("error"))
    if is_error:
      err_code = str(res.get("error", "UNKNOWN_ERROR"))
      sig = f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}:{err_code}"
      if sig == last_error_sig:
        consecutive_errors += 1
      else:
        last_error_sig = sig
        consecutive_errors = 1

      audit_log.append({
          "step": step_idx,
          "event": "TOOL_ERROR",
          "tool": tool_name,
          "error": err_code,
          "consecutive_errors": consecutive_errors,
      })

      if consecutive_errors > max_repeats:
        audit_log.append({
            "step": step_idx,
            "event": "CIRCUIT_BREAKER_TRIPPED",
            "tool": tool_name,
            "consecutive_errors": consecutive_errors,
            "max_repeats": max_repeats,
            "message": f"连续 {consecutive_errors} 次触发相同错误，硬熔断器已强制停机。",
        })
        return {
            "halted": True,
            "halt_reason": "CIRCUIT_BREAKER_TRIPPED",
            "executed_count": executed_count,
            "outputs": outputs,
            "audit_log": audit_log,
        }
    else:
      last_error_sig = None
      consecutive_errors = 0

  return {
      "halted": False,
      "halt_reason": None,
      "executed_count": executed_count,
      "outputs": outputs,
      "audit_log": audit_log,
  }
