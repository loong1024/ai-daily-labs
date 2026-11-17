"""P0-M01 实验起点（Starter）：模拟文档转 Markdown 清洗与开源全家桶分工映射。

请按 README.md 指引改进以下三个核心函数，并运行 `python3 verify.py` 验证进度。
"""

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


def clean_office_to_markdown(raw_text: str) -> str:
  """将带排版噪音的办公文档导出文本清洗为结构化 Markdown。

  TODO 改进目标：
  1. 剔除办公噪音行：`=== 页眉... ===`、`=== 页脚... ===`、`--- 第 X 页 / 共 Y 页 ---`、`【机密水印...】`，
     并去除全角缩进空格 `\\u3000`。
  2. 还原标题与列表层级：
     - `文档标题：XXX` -> `# XXX`
     - `一、XXX` / `二、XXX` 等中文一级序号标题 -> `## XXX`
     - `● XXX` / `▪ XXX` 项目符号 -> `- XXX`
  3. 还原竖线表格：将 `[表格开始]` 与 `[表格结束]` 之间以制表符 `\\t` 分隔的行，
     转换为标准 Markdown 竖线表格（首行表头 + `| --- | ... |` 分隔行 + 数据行）。
  """
  # 当前基线缺陷：原样返回未清洗的杂乱文本，导致页眉水印残留且表格未转为 Markdown 竖线格式
  return raw_text.strip()


def classify_toolchain_capabilities(capabilities: list[dict[str, str]]) -> dict[str, str]:
  """区分开源 AI 全家桶上下游职责边界。

  输入每个元素包含 `id`、`title`、`description`。
  返回值应为 `{capability_id: "markitdown" | "open_webui"}`：
  - `"markitdown"`：负责前置文档预处理（剥离排版样式/页眉水印、还原 # 标题与 | 竖线表格、降低上下文损耗）
  - `"open_webui"`：负责中央交互工作台（多模型统一接入切换、挂载知识库检索、沉淀团队提示词预设）
  """
  # TODO 改进目标：根据每项能力的职责描述，准确归入 "markitdown" 或 "open_webui"
  # 当前基线缺陷：误以为聊天界面能包办一切，把所有能力全部归到了 open_webui
  return {item["id"]: "open_webui" for item in capabilities}


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
  """对比原始杂乱文本与清洗后 Markdown 投喂给大模型后的问答结果。"""
  # TODO 改进目标：统计被剥离的噪音行数 `noise_lines_removed`，确保传入清洗后的 markdown_text 完成对比
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
      "noise_lines_removed": 0,
      "raw_answer": raw_answer,
      "markdown_answer": md_answer,
  }
