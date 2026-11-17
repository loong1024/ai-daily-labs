"""P0-M01 标准参考实现（Solution）：模拟 MarkItDown 文档净化与 Open WebUI 协同问答。"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

_NOISE_PATTERNS = (
    re.compile(r"^===\s*页[眉脚][：:].*===$"),
    re.compile(r"^---\s*第\s*\d+\s*页\s*/\s*共\s*\d+\s*页\s*---$"),
    re.compile(r"^【机密水印[：:].*】$"),
)
_DOC_TITLE_RE = re.compile(r"^(?:文档标题|【主标题】)[：:]\s*(.+)$")
_SECTION_HEADER_RE = re.compile(r"^[一二三四五六七八九十]+、\s*(.+)$")
_BULLET_RE = re.compile(r"^[●▪•]\s*(.+)$")


def _is_noise_line(line: str) -> bool:
  return any(pattern.match(line) for pattern in _NOISE_PATTERNS)


def _render_pipe_table(rows: list[list[str]]) -> list[str]:
  if not rows:
    return []
  col_count = max(len(r) for r in rows)
  normalized = [r + [""] * (col_count - len(r)) for r in rows]
  header = "| " + " | ".join(normalized[0]) + " |"
  separator = "| " + " | ".join(["---"] * col_count) + " |"
  body = ["| " + " | ".join(row) + " |" for row in normalized[1:]]
  return [header, separator, *body]


def clean_office_to_markdown(raw_text: str) -> str:
  """剥离办公排版噪音，还原 # 层级标题、无序列表与标准 Markdown 竖线表格。"""
  output_lines: list[str] = []
  in_table = False
  table_rows: list[list[str]] = []

  for raw_line in raw_text.splitlines():
    line = raw_line.replace("\u3000", " ").strip()
    if _is_noise_line(line):
      continue

    if line == "[表格开始]":
      in_table = True
      table_rows = []
      continue

    if line == "[表格结束]":
      in_table = False
      output_lines.extend(_render_pipe_table(table_rows))
      table_rows = []
      continue

    if in_table:
      if not line:
        continue
      cells = (
          [c.strip() for c in line.split("\t")]
          if "\t" in line
          else [c.strip() for c in re.split(r"\s{2,}", line)]
      )
      table_rows.append(cells)
      continue

    title_match = _DOC_TITLE_RE.match(line)
    if title_match:
      output_lines.append(f"# {title_match.group(1).strip()}")
      continue

    section_match = _SECTION_HEADER_RE.match(line)
    if section_match:
      output_lines.append(f"## {section_match.group(1).strip()}")
      continue

    bullet_match = _BULLET_RE.match(line)
    if bullet_match:
      output_lines.append(f"- {bullet_match.group(1).strip()}")
      continue

    output_lines.append(line)

  if table_rows:
    output_lines.extend(_render_pipe_table(table_rows))

  joined = "\n".join(output_lines)
  cleaned = re.sub(r"\n{3,}", "\n\n", joined).strip()
  return f"{cleaned}\n" if cleaned else ""


def classify_toolchain_capabilities(capabilities: list[dict[str, str]]) -> dict[str, str]:
  """将能力卡片准确映射至前置文档清洗层（markitdown）与交互工作台层（open_webui）。"""
  markitdown_keywords = (
      "剥离",
      "页眉",
      "视觉样式",
      "竖线表格",
      "# 标题",
      "格式标签",
      "水印",
      "上下文开销",
      "纯文本结构",
  )
  open_webui_keywords = (
      "多模型",
      "Ollama",
      "切换",
      "知识集合",
      "知识库",
      "挂载",
      "检索",
      "提示词",
      "快捷指令",
      "工作台",
  )

  mapping: dict[str, str] = {}
  for item in capabilities:
    text = f"{item.get('title', '')} {item.get('description', '')}"
    md_score = sum(1 for kw in markitdown_keywords if kw in text)
    ui_score = sum(1 for kw in open_webui_keywords if kw in text)
    mapping[item["id"]] = "markitdown" if md_score >= ui_score else "open_webui"
  return mapping


def inspect_markdown_quality(md_text: str) -> dict[str, bool]:
  """检查文本是否已具备干净的 Markdown 标题、竖线表格且无办公页眉水印。"""
  has_h1 = bool(re.search(r"(?m)^#\s+\S+", md_text))
  has_h2 = bool(re.search(r"(?m)^##\s+\S+", md_text))
  has_pipe_sep = bool(re.search(r"(?m)^\|\s*---", md_text))
  noise_tokens = ("=== 页眉", "=== 页脚", "【机密水印", "第 1 页 / 共", "第 2 页 / 共", "[表格开始]")
  noise_free = not any(tok in md_text for tok in noise_tokens)
  return {
      "has_h1": has_h1,
      "has_h2": has_h2,
      "has_pipe_table": has_pipe_sep,
      "noise_free": noise_free,
      "is_clean_markdown": has_h1 and has_h2 and has_pipe_sep and noise_free,
  }


def _deterministic_qa_mock(messages: list[dict[str, str]]) -> str:
  """离线确定性问答模拟器：反映杂乱排版与干净 Markdown 竖线表格的解析准确度差异。"""
  user_content = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
  quality = inspect_markdown_quality(user_content)
  if not quality["is_clean_markdown"]:
    return "输入文档存在页眉水印干扰且缺少标准竖线表格，表格列发生错位，仅识别到私域社群 31%，漏读最低转化渠道。"

  rows: list[tuple[int, str, str, str]] = []
  for line in user_content.splitlines():
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
      continue
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 4 or "---" in cells[0]:
      continue
    pct_match = re.search(r"(\d+)\s*%", cells[2])
    if pct_match:
      rows.append((int(pct_match.group(1)), cells[0], cells[2], cells[3]))

  rows.sort(key=lambda item: item[0])
  if len(rows) >= 2:
    first, second = rows[0], rows[1]
    return (
        f"转化率最低的两个渠道依次为："
        f"1. {first[1]}（转化率 {first[2]}，主要卡点：{first[3]}）；"
        f"2. {second[1]}（转化率 {second[2]}，主要卡点：{second[3]}）。"
    )
  return "未能从表格中解析出足够的渠道转化率数据。"


def compare_qa_accuracy(raw_text: str, markdown_text: str, question: str) -> dict[str, Any]:
  """对比原始杂乱文本与清洗后 Markdown 投喂给大模型后的问答准确度与降噪统计。"""
  raw_noise_count = sum(
      1 for raw_line in raw_text.splitlines() if _is_noise_line(raw_line.replace("\u3000", " ").strip())
  )
  remaining_noise_count = sum(
      1 for md_line in markdown_text.splitlines() if _is_noise_line(md_line.replace("\u3000", " ").strip())
  )
  noise_lines_removed = max(0, raw_noise_count - remaining_noise_count)

  raw_messages = [
      {"role": "system", "content": "你是严谨的经营分析助手，请严格依据提供的文档回答。"},
      {"role": "user", "content": f"【参考文档】\n{raw_text}\n\n【问题】\n{question}"},
  ]
  md_messages = [
      {"role": "system", "content": "你是严谨的经营分析助手，请严格依据提供的 Markdown 文档回答。"},
      {"role": "user", "content": f"【参考文档】\n{markdown_text}\n\n【问题】\n{question}"},
  ]

  raw_answer = chat_complete(raw_messages, mock_fn=_deterministic_qa_mock)
  md_answer = chat_complete(md_messages, mock_fn=_deterministic_qa_mock)
  quality = inspect_markdown_quality(markdown_text)

  return {
      "is_clean_markdown": quality["is_clean_markdown"],
      "noise_lines_removed": noise_lines_removed,
      "raw_answer": raw_answer,
      "markdown_answer": md_answer,
  }
