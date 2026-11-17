#!/usr/bin/env python3
"""S5-M07 量化验收脚本：核验只读 Skill 权限硬约束、≤30 行输出契约、源码行号 100% 真实性与对照记录表。"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

READONLY_TOOLS = {"Read", "Grep", "Glob", "LS", "View"}
FORBIDDEN_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "Bash", "Terminal", "Execute", "Delete"}
COORD_RE = re.compile(r"([A-Za-z0-9_./-]+\.py):L(\d+)(?:\s*\(`?([A-Za-z_][A-Za-z0-9_]*)`?\))?")


def _parse_frontmatter(md_text: str) -> tuple[dict[str, Any], str]:
  """纯标准库解析 Markdown 顶部 YAML Frontmatter。"""
  stripped = md_text.lstrip()
  if not stripped.startswith("---\n"):
    return {}, md_text
  end_idx = stripped.find("\n---\n", 4)
  if end_idx == -1:
    return {}, md_text
  raw_yaml = stripped[4:end_idx]
  body = stripped[end_idx + 5 :]

  meta: dict[str, Any] = {}
  current_list_key: str | None = None
  for raw_line in raw_yaml.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    if line.startswith("- ") and current_list_key:
      meta.setdefault(current_list_key, []).append(line[2:].strip().strip("\"'"))
      continue
    current_list_key = None
    if ":" not in line:
      continue
    key, val = line.split(":", 1)
    key = key.strip()
    val = val.strip()
    if not val:
      current_list_key = key
      meta[key] = []
    elif val.startswith("[") and val.endswith("]"):
      items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
      meta[key] = items
    elif val.isdigit():
      meta[key] = int(val)
    else:
      meta[key] = val.strip("\"'")
  return meta, body


def _extract_scout_brief(md_text: str) -> str:
  m = re.search(r"```scout-brief\r?\n(.*?)\r?\n```", md_text, flags=re.DOTALL)
  return m.group(1) if m else ""


def _extract_markdown_table_rows(md_text: str) -> list[list[str]]:
  rows: list[list[str]] = []
  for line in md_text.splitlines():
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
      continue
    cells = [c.strip() for c in s.strip("|").split("|")]
    if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
      continue
    rows.append(cells)
  return rows


def main() -> None:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S5-M07", "只读侦察子会话降噪对照实验（权限约束 + ≤30行精确坐标 + 对照表）")

  doc_path = target_file(LAB_DIR, "starter.md", "solution.md")
  mini_repo = LAB_DIR / "fixtures" / "mini_repo"
  traces = json.loads((LAB_DIR / "fixtures" / "session_traces.json").read_text(encoding="utf-8"))

  try:
    md_text = doc_path.read_text(encoding="utf-8")
    meta, _ = _parse_frontmatter(md_text)
  except Exception as exc:
    v.check("读取目标 Skill 文档", False, f"读取 {doc_path.name} 失败：{exc}")
    v.finish()
    return

  # Check 1: 工具级只读权限硬约束 + 触发边界描述
  allowed = set(meta.get("allowed-tools", [])) if isinstance(meta.get("allowed-tools"), list) else set()
  desc = str(meta.get("description", ""))
  max_lines_cfg = meta.get("max-output-lines", 999)
  has_negative_boundary = ("不要用于" in desc or "不适用于" in desc or "勿用于" in desc) and "单文件" in desc
  readonly_ok = bool(
      meta.get("name") == "codebase-scout"
      and allowed
      and allowed.issubset(READONLY_TOOLS)
      and not (allowed & FORBIDDEN_WRITE_TOOLS)
      and isinstance(max_lines_cfg, int)
      and max_lines_cfg <= 30
      and has_negative_boundary
  )
  v.check(
      "YAML Frontmatter 已实施工具级只读白名单（allowed-tools 剔除写/执行权限）且明确适用边界",
      readonly_ok,
      "请在顶部 Frontmatter 配置 allowed-tools: [Read, Grep, Glob]（移除 Write/Bash 等写权限）、设置 max-output-lines: 30，并在 description 中补充“不要用于已知精确单文件的小型直接编辑”。",
  )

  # Check 2: 侦察摘要严格 ≤30 行且包含三大契约章节、无大段源码倾倒
  brief = _extract_scout_brief(md_text)
  brief_lines = brief.splitlines()
  required_sections = ("[核心调用链]", "[现有约定与测试参考]", "[潜在耦合与禁区]")
  has_all_sections = all(sec in brief for sec in required_sections)
  has_raw_def_dump = any(ln.lstrip().startswith("def ") for ln in brief_lines)
  ok_check2 = bool(brief and 5 <= len(brief_lines) <= 30 and has_all_sections and not has_raw_def_dump)
  v.check(
      f"侦察返回摘要严格 ≤30 行（当前 {len(brief_lines) if brief else 0} 行）且无源码块倾倒",
      ok_check2,
      "请精简 ```scout-brief 代码块至 ≤30 行，删掉直接拷贝的 def 源码段与无关扫描日志，保留 [核心调用链]、[现有约定与测试参考]、[潜在耦合与禁区] 三节。",
  )

  # Check 3: 逐个打开 fixtures/mini_repo 验证文件路径、行号与符号 100% 真实存在 + 零猜测原则
  coord_matches = list(COORD_RE.finditer(brief))
  invalid_coords: list[str] = []
  distinct_files: set[str] = set()
  for m in coord_matches:
    rel_file, line_str, symbol = m.group(1), m.group(2), m.group(3)
    line_no = int(line_str)
    full_file = mini_repo / rel_file
    if not full_file.is_file():
      invalid_coords.append(f"{rel_file}:L{line_no}（文件不存在）")
      continue
    src_lines = full_file.read_text(encoding="utf-8").splitlines()
    if not (1 <= line_no <= len(src_lines)):
      invalid_coords.append(f"{rel_file}:L{line_no}（超出文件总行数 {len(src_lines)}）")
      continue
    if not symbol:
      invalid_coords.append(f"{rel_file}:L{line_no}（未标注符号名）")
      continue
    window = "\n".join(src_lines[max(0, line_no - 2) : min(len(src_lines), line_no + 1)])
    if symbol not in window:
      invalid_coords.append(f"{rel_file}:L{line_no}（该行附近未找到符号 `{symbol}`）")
      continue
    distinct_files.add(rel_file)

  zero_guess_ok = ("未确认" in brief) and ("auto_retry_webhook" not in brief)
  smoke_run = subprocess.run(
      [
          sys.executable,
          "-c",
          "from models.ledger_entry import run_ledger_smoke_check; assert run_ledger_smoke_check()",
      ],
      env={**os.environ, "PYTHONPATH": str(mini_repo)},
      capture_output=True,
      text=True,
      check=False,
  )
  ok_check3 = bool(
      len(coord_matches) >= 6
      and len(distinct_files) >= 3
      and not invalid_coords
      and zero_guess_ok
      and smoke_run.returncode == 0
  )
  coord_hint = (
      "；".join(invalid_coords[:3])
      if invalid_coords
      else "请核对跨 api/services/models 3 个文件的精确行号，移除臆造的 auto_retry_webhook 并将网关异步重试标为“未确认”。"
  )
  v.check(
      "摘要中所有文件路径、行号与函数/类名经本地逐行核对 100% 真实存在且遵守零猜测原则",
      ok_check3,
      f"坐标核验未通过：{coord_hint}",
  )

  # Check 4: 对照实验记录表完整量化了两组差异且与 session_traces.json 一致
  table_rows = _extract_markdown_table_rows(md_text)
  data_rows = table_rows[1:] if len(table_rows) >= 2 else []
  flat_table = " ".join(" | ".join(r) for r in data_rows)
  ctrl_tokens = str(traces["groups"][0]["main_session_injected_tokens"])
  exp_tokens = str(traces["groups"][1]["main_session_injected_tokens"])
  ok_check4 = bool(
      len(data_rows) >= 2
      and "TODO" not in flat_table
      and "对照组" in flat_table
      and "实验组" in flat_table
      and (ctrl_tokens in flat_table or "14,820" in flat_table)
      and exp_tokens in flat_table
      and "100%" in flat_table
  )
  v.check(
      "对照实验记录表已完整量化主会话噪声体积（14820 vs 420 tokens）与定位轮数差异",
      ok_check4,
      "请根据 fixtures/session_traces.json 填完底部 Markdown 对照表（替换全部 TODO，写明对照组 14820 tokens/68%/9轮/5轮 与实验组 420 tokens/2%/100%/1轮）。",
  )

  v.finish()


if __name__ == "__main__":
  main()
