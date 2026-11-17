#!/usr/bin/env python3
"""S3-M08 Starter：朴素原话直搜基线（含待修复的多轮路由与规划缺陷）。

请结合 README.md 步骤指引改进本文件，使 `python3 verify.py` 全部通过。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete  # noqa: E402

# TODO(Step 2): 升级查询规划提示词契约，显式要求输出：
# - need_retrieval (bool): 闲聊/致谢/纯上文格式转换输出 false 且 sub_queries 为 []
# - standalone_query (str): 结合历史补全代词主语
# - exact_terms (list[str]): 原样保留报错码、函数名、配置项（严禁改大小写或删下划线）
# - sub_queries (list[str]): 跨年/多对象对比拆成 2-3 个正交子查询
# - time_filter ({"after": "YYYY-MM-DD", "before": "YYYY-MM-DD"} | None): 结构化日期过滤
PLANNER_SYSTEM_PROMPT = """你是检索查询改写助手，请直接返回用户原问题。"""


def _naive_cjk_bigrams(text: str) -> set[str]:
  """基线分词缺陷：仅提取中文双字切片，丢弃了英文/下划线报错码与数字年份。"""
  cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
  return {cjk[i : i + 2] for i in range(len(cjk) - 1)} if len(cjk) >= 2 else set()


def build_query_plan(case: dict[str, Any]) -> dict[str, Any]:
  """基线查询规划器（缺陷版本）：
  1. 未识别闲聊/纯翻译请求，一律设置 need_retrieval=True；
  2. 未结合 chat_history 还原“它/上面那个”等指代主语；
  3. 未原样抽取 exact_terms，也未拆分跨年对比 sub_queries；
  4. 未生成结构化 time_filter ({after, before})。
  """
  raw_query = str(case.get("query", "")).strip()
  # TODO(Step 2 & 3): 接入 chat_complete(..., mock_fn=..., response_json=True) 生成合规 JSON 规划
  return {
      "need_retrieval": True,
      "standalone_query": raw_query,
      "exact_terms": [],
      "sub_queries": [raw_query],
      "time_filter": None,
  }


def execute_routed_search(
    case: dict[str, Any],
    kb_chunks: list[dict[str, Any]],
    top_k: int = 2,
) -> dict[str, Any]:
  """基线检索执行器（缺陷版本）：不做门禁短路、不做时间过滤、不做精确分流与 RRF。"""
  plan = build_query_plan(case)\

  # TODO(Step 4):
  # 1. 若 plan["need_retrieval"] 为 False，直接短路返回（retrieval_triggered=False, top_doc_ids=[]）
  # 2. 若 plan["time_filter"] 非空，按 chunk["published_at"] 做元数据时间窗口过滤
  # 3. 若 plan["exact_terms"] 非空，开启精确词检索路（严格匹配原始大小写与下划线）
  # 4. 对 standalone_query、sub_queries 与精确词路结果做并行 RRF (k=60) 融合排序
  q_grams = _naive_cjk_bigrams(plan["standalone_query"])
  scored: list[tuple[float, str]] = []
  for chunk in kb_chunks:
    doc_grams = _naive_cjk_bigrams(f"{chunk['title']} {chunk['content']}")
    overlap = len(q_grams & doc_grams) / max(1, len(q_grams))
    scored.append((overlap, chunk["doc_id"]))

  scored.sort(key=lambda item: item[0], reverse=True)
  top_doc_ids = [doc_id for _, doc_id in scored[: max(1, top_k)]]
  return {
      "plan": plan,
      "retrieval_triggered": True,
      "used_exact_route": False,
      "filtered_chunk_count": len(kb_chunks),
      "top_doc_ids": top_doc_ids,
  }


if __name__ == "__main__":
  kb = json.loads((LAB_DIR / "fixtures" / "kb_chunks.json").read_text(encoding="utf-8"))
  cases = json.loads((LAB_DIR / "fixtures" / "dialog_cases.json").read_text(encoding="utf-8"))
  for item in cases:
    k = max(1, len(item["expected"]["expected_doc_ids"]))
    out = execute_routed_search(item, kb, top_k=k)
    print(f"[{item['case_id']}] top_docs={out['top_doc_ids']} | expected={item['expected']['expected_doc_ids']}")
