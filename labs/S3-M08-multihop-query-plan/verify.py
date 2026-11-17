#!/usr/bin/env python3
"""S3-M08 自动化验收脚本：验证多轮查询路由、精确词保真、结构化时间过滤与并行 RRF 召回。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file  # noqa: E402

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_target_module(module_path: pathlib.Path) -> Any:
  spec = importlib.util.spec_from_file_location("s3_m08_target", module_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块: {module_path}")
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S3-M08", "多轮追问查询路由与结构化规划")
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  kb_chunks = json.loads((LAB_DIR / "fixtures" / "kb_chunks.json").read_text(encoding="utf-8"))
  cases = json.loads((LAB_DIR / "fixtures" / "dialog_cases.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module(mod_path)
    results_by_id: dict[str, dict[str, Any]] = {}
    for case in cases:
      expected_docs = case["expected"]["expected_doc_ids"]
      top_k = max(1, len(expected_docs))
      results_by_id[case["case_id"]] = mod.execute_routed_search(case, kb_chunks, top_k=top_k)
  except Exception as exc:  # noqa: BLE001
    v.check(
        "模块加载与 5 组多轮样本执行无异常",
        False,
        f"执行 {mod_path.name} 时抛出异常：{exc}。请确保 build_query_plan 与 execute_routed_search 返回结构完整。",
    )
    return v.finish()

  # 验收项 1：闲聊问候短路跳过检索
  c05 = results_by_id.get("C05_chitchat_skip", {})
  c05_plan = c05.get("plan", {})
  chitchat_ok = (
      c05_plan.get("need_retrieval") is False
      and c05_plan.get("sub_queries") == []
      and c05.get("retrieval_triggered") is False
      and c05.get("top_doc_ids") == []
  )
  v.check(
      "闲聊与纯格式指令 100% 跳过检索（need_retrieval=false 且触发检索 0 次）",
      chitchat_ok,
      "C05 闲聊致谢样本仍触发了检索或 sub_queries 非空；请在规划器中输出 need_retrieval=false 并在 execute_routed_search 开头直接短路返回。",
  )

  # 验收项 2：多轮指代还原、跨年对比拆分与报错码零篡改分流
  c01 = results_by_id.get("C01_pronoun_followup", {})
  c02 = results_by_id.get("C02_exact_error_code", {})
  c03 = results_by_id.get("C03_year_comparison", {})

  c01_standalone = str(c01.get("plan", {}).get("standalone_query", ""))
  c02_exact = c02.get("plan", {}).get("exact_terms", [])
  c03_subs = c03.get("plan", {}).get("sub_queries", [])

  pronoun_ok = "UpstreamPool" in c01_standalone
  exact_ok = (
      isinstance(c02_exact, list)
      and "ERR_502_TIMEOUT" in c02_exact
      and "check_keepalive_idle" in c02_exact
      and bool(c02.get("used_exact_route"))
  )
  split_ok = (
      isinstance(c03_subs, list)
      and len(c03_subs) >= 2
      and any("2025" in str(s) for s in c03_subs)
      and any("2026" in str(s) for s in c03_subs)
  )
  v.check(
      "多轮指代主语还原、跨年子查询拆解及 exact_terms 零篡改精确路由",
      pronoun_ok and exact_ok and split_ok,
      f"当前状态：C01补全UpstreamPool={pronoun_ok}，C02精确词保真并走精确路={exact_ok}（当前 exact_terms={c02_exact}），C03拆出2025/2026双子查询={split_ok}（当前 sub_queries={c03_subs}）。",
  )

  # 验收项 3：结构化 time_filter 日期格式合规并在元数据层过滤过期归档
  c03_tf = c03.get("plan", {}).get("time_filter")
  c04 = results_by_id.get("C04_recent_single_hop", {})
  c04_tf = c04.get("plan", {}).get("time_filter")

  def _valid_tf(tf: Any, exp_after: str, exp_before: str) -> bool:
    return (
        isinstance(tf, dict)
        and bool(DATE_RE.match(str(tf.get("after", ""))))
        and bool(DATE_RE.match(str(tf.get("before", ""))))
        and tf.get("after") == exp_after
        and tf.get("before") == exp_before
    )

  tf_ok = (
      _valid_tf(c03_tf, "2025-01-01", "2026-12-31")
      and _valid_tf(c04_tf, "2026-01-01", "2026-12-31")
      and int(c03.get("filtered_chunk_count", len(kb_chunks))) < len(kb_chunks)
      and int(c04.get("filtered_chunk_count", len(kb_chunks))) < len(kb_chunks)
      and "DOC-AUTH-2023" not in c03.get("top_doc_ids", [])
      and "DOC-VEC-2024" not in c04.get("top_doc_ids", [])
  )
  v.check(
      "结构化 time_filter ({after, before}) 合规生成并过滤历史废弃归档",
      tf_ok,
      f"请确保 C03/C04 输出规范 {{'after': 'YYYY-MM-DD', 'before': 'YYYY-MM-DD'}} 并按 published_at 过滤旧切片（当前 C03 time_filter={c03_tf}, C04 time_filter={c04_tf}）。",
  )

  # 验收项 4：开启并行 RRF 后全部 4 组检索题出处覆盖率达 100%
  hit_docs = 0
  total_expected = 0
  missed_details: list[str] = []
  for case in cases:
    exp_ids = case["expected"]["expected_doc_ids"]
    if not exp_ids:
      continue
    got_ids = set(results_by_id[case["case_id"]].get("top_doc_ids", []))
    for doc_id in exp_ids:
      total_expected += 1
      if doc_id in got_ids:
        hit_docs += 1
      else:
        missed_details.append(f"{case['case_id']} 漏召回 {doc_id}（实得 {sorted(got_ids)}）")

  coverage = hit_docs / max(1, total_expected)
  v.check(
      f"并行 RRF 多路融合出处覆盖率达标（当前命中 {hit_docs}/{total_expected}，覆盖率 {coverage:.0%}）",
      hit_docs == total_expected,
      "存在搜偏或漏召回：" + "；".join(missed_details) + "。请将 standalone_query、sub_queries 与精确词检索结果通过 RRF(k=60) 融合排序。",
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
