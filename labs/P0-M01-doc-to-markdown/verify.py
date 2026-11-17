#!/usr/bin/env python3
"""P0-M01 自动化验收脚本：验证文档转 Markdown 清洗质量、工具链分工映射与问答对比实测。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: F401


def _has_aligned_pipe_table(md_text: str) -> bool:
  table_lines = [
      ln.strip()
      for ln in md_text.splitlines()
      if ln.strip().startswith("|") and ln.strip().endswith("|")
  ]
  if len(table_lines) < 4:
    return False
  has_sep = any(re.match(r"^\|\s*---", ln) for ln in table_lines)
  equal_cols = len({ln.count("|") for ln in table_lines}) == 1 and table_lines[0].count("|") >= 4
  return has_sep and equal_cols


def main() -> None:
  v = LabVerifier("P0-M01", "看懂开源 AI 全家桶：文档转 Markdown 与工作台")

  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  raw_review_path = LAB_DIR / "fixtures" / "raw_quarterly_review.txt"
  corpus_path = LAB_DIR / "fixtures" / "messy_office_docs.json"

  try:
    raw_review = raw_review_path.read_text(encoding="utf-8")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("p0_m01_candidate", mod_path)
    if spec is None or spec.loader is None:
      raise RuntimeError(f"无法创建模块加载器：{mod_path.name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    required_fns = ("clean_office_to_markdown", "classify_toolchain_capabilities", "compare_qa_accuracy")
    loaded_ok = all(callable(getattr(mod, fn, None)) for fn in required_fns) and len(corpus.get("docs", [])) >= 5
    v.check(
        "实验模块与脱敏办公语料加载",
        loaded_ok,
        f"请确保 {mod_path.name} 保留 clean_office_to_markdown、classify_toolchain_capabilities、compare_qa_accuracy 三个函数签名。",
    )
  except Exception as exc:
    v.check("实验模块与脱敏办公语料加载", False, f"加载 {mod_path.name} 或 fixtures 失败：{exc}")
    v.finish()
    return

  # 指标 2：办公排版噪音剥离
  cleaned_review = ""
  try:
    cleaned_review = str(mod.clean_office_to_markdown(raw_review))
    cleaned_docs = [str(mod.clean_office_to_markdown(d["raw_text"])) for d in corpus["docs"]]
    forbidden_tokens = (
        "=== 页眉",
        "=== 页脚",
        "【机密水印",
        "第 1 页 / 共",
        "第 2 页 / 共",
        "\u3000",
        "[表格开始]",
        "[表格结束]",
    )
    all_outputs = [cleaned_review, *cleaned_docs]
    no_noise = all(not any(tok in out for tok in forbidden_tokens) for out in all_outputs)
    core_kept = "季度复盘摘要" in cleaned_review and "短视频流" in cleaned_review
    v.check(
        "办公排版噪音剥离（清除页眉页脚、机密水印与全角缩进）",
        no_noise and core_kept,
        "请在 clean_office_to_markdown 中剔除 `=== 页眉/页脚 ===`、`--- 第 X 页 / 共 Y 页 ---`、`【机密水印...】`、`[表格开始/结束]` 标记与全角空格 `\\u3000`，同时保留正文数据。",
    )
  except Exception as exc:
    cleaned_docs = []
    v.check(
        "办公排版噪音剥离（清除页眉页脚、机密水印与全角缩进）",
        False,
        f"调用 clean_office_to_markdown 抛出异常：{exc}",
    )

  # 指标 3：Markdown 层级标题与竖线表格还原
  try:
    all_outputs = [cleaned_review, *cleaned_docs] if cleaned_docs else []
    structure_ok = bool(all_outputs) and all(
        bool(re.search(r"(?m)^#\s+\S+", out))
        and bool(re.search(r"(?m)^##\s+\S+", out))
        and _has_aligned_pipe_table(out)
        and "●" not in out
        and "▪" not in out
        for out in all_outputs
    )
    bullet_ok = bool(re.search(r"(?m)^-\s+搜索落地页", cleaned_review))
    v.check(
        "Markdown 结构还原（# 标题层级、- 列表与对齐 | 竖线表格）",
        structure_ok and bullet_ok,
        "请把 `文档标题：` 转为 `# `，中文大标题 `一、...` 转为 `## `，`●`/`▪` 转为 `- `，并将制表符分隔的表格还原为含 `| --- |` 分隔行的标准竖线表格。",
    )
  except Exception as exc:
    v.check(
        "Markdown 结构还原（# 标题层级、- 列表与对齐 | 竖线表格）",
        False,
        f"检查 Markdown 结构时发生异常：{exc}",
    )

  # 指标 4：MarkItDown 与 Open WebUI 上下游职责映射
  try:
    cap_inputs = [
        {"id": item["id"], "title": item["title"], "description": item["description"]}
        for item in corpus["toolchain_capabilities"]
    ]
    pred_map = mod.classify_toolchain_capabilities(cap_inputs)
    expected_map = {item["id"]: item["expected_tool"] for item in corpus["toolchain_capabilities"]}
    mismatches = [
        cid for cid, exp_tool in expected_map.items() if not isinstance(pred_map, dict) or pred_map.get(cid) != exp_tool
    ]
    v.check(
        "开源 AI 全家桶上下游分工映射（MarkItDown 净菜层 vs Open WebUI 工作台层）",
        len(mismatches) == 0,
        f"职责归类仍有偏差（未命中项：{mismatches}）：格式剥离/表格还原/降低上下文损耗归属 `markitdown`，多模型切换/知识库挂载/提示词预设归属 `open_webui`。",
    )
  except Exception as exc:
    v.check(
        "开源 AI 全家桶上下游分工映射（MarkItDown 净菜层 vs Open WebUI 工作台层）",
        False,
        f"调用 classify_toolchain_capabilities 抛出异常：{exc}",
    )

  # 指标 5：结构化清洗前后问答准确度对比
  try:
    benchmark = corpus["qa_benchmark"]
    qa_report = mod.compare_qa_accuracy(raw_review, cleaned_review, benchmark["question"])
    md_ans = str(qa_report.get("markdown_answer", "")) if isinstance(qa_report, dict) else ""
    keywords_hit = all(kw in md_ans for kw in benchmark["expected_keywords"])
    report_ok = (
        isinstance(qa_report, dict)
        and qa_report.get("is_clean_markdown") is True
        and int(qa_report.get("noise_lines_removed", 0)) >= 4
        and keywords_hit
    )
    v.check(
        "结构化投喂前后问答准确度实测（准确提炼最低转化率渠道与卡点）",
        report_ok,
        "请确保 compare_qa_accuracy 统计实际剥离的噪音行数（>=4 行），且清洗后的 Markdown 能让模型准确提取短视频流（9%）与搜索广告（18%）及对应卡点。",
    )
  except Exception as exc:
    v.check(
        "结构化投喂前后问答准确度实测（准确提炼最低转化率渠道与卡点）",
        False,
        f"调用 compare_qa_accuracy 抛出异常：{exc}",
    )

  v.finish()


if __name__ == "__main__":
  main()
