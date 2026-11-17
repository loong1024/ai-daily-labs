#!/usr/bin/env python3
"""S3-M08 Solution：带路由门禁、精确词保真、结构化时间过滤与并行 RRF 的查询规划实现。"""

from __future__ import annotations

import json
import math
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete  # noqa: E402

PLANNER_SYSTEM_PROMPT = """你是私域知识库检索查询规划器。请结合当前日期、最近对话历史与用户当前问题，仅输出用于检索路由的严格 JSON 对象（不要直接回答问题）。

输出 JSON Schema 规则：
1. "need_retrieval" (boolean)：若问题属于寒暄致谢（如“你好”“谢谢”）或仅对上文做翻译/润色/格式转换，必须输出 false，且 "sub_queries" 必须为 []；否则输出 true。
2. "standalone_query" (string)：结合最近对话历史消除“它/上面那个/刚说的”等指代词，补全主语形成自包含查询（保留历史中组件与专有名词的原始大小写，如 UpstreamPool）；严禁臆造上下文未出现的专有名词。
3. "exact_terms" (string[])：从当前问题原样抽取报错码（如 ERR_502_TIMEOUT）、函数或配置项名（如 check_keepalive_idle）、版本号、路径等精确词，100% 保留原始大小写与下划线；无则输出 []。
4. "sub_queries" (string[])：need_retrieval 为 false 时输出 []；涉及跨年份（如“去年和今年”）或 A/B 多对象对比时，必须换算具体公历年份（如 2025、2026）拆分为 2-3 条正交子查询；单跳问题输出包含 standalone_query 的单元素数组。
5. "time_filter" (object | null)：若问题含“今年/去年/最新”等时效词，结合当前日期按完整自然年边界换算为 {"after": "YYYY-01-01", "before": "YYYY-12-31"}（如当前 2026 年：“今年/最新”输出 {"after": "2026-01-01", "before": "2026-12-31"}，“去年和今年”输出 {"after": "2025-01-01", "before": "2026-12-31"}）；无时效约束则输出 null。"""

_EXACT_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"
    r"|v\d+(?:\.\d+)+"
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+"
    r")(?![A-Za-z0-9_])"
)
_HISTORY_ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Za-z0-9_]{2,}(?![A-Za-z0-9_])")
_CJK_STOP_RE = re.compile(
    r"那它的|它的|那它|上面那个|刚说的|怎么|如何|什么|哪些|为什么|请问|一下"
)
_CJK_PARTICLES = frozenset("的了呢吗吧啊呀哦嘛")
_CHITCHAT_HINTS = ("谢谢", "感谢", "辛苦了", "再见", "翻成英文", "翻译成英文", "总结上文", "润色上文")
_DOMAIN_INQUIRY_HINTS = (
    "怎么",
    "如何",
    "什么",
    "哪些",
    "对比",
    "为什么",
    "排查",
    "配置",
    "规范",
    "方案",
    "超时",
    "报错",
    "故障",
)


def extract_exact_terms(raw_query: str) -> list[str]:
  """从原始提问中零篡改抽取报错码、下划线函数名、版本号与驼峰组件名。"""
  seen: set[str] = set()
  terms: list[str] = []
  for match in _EXACT_TERM_RE.finditer(raw_query):
    token = match.group(0)
    if token not in seen:
      seen.add(token)
      terms.append(token)
  return terms


def _format_planner_user_prompt(case: dict[str, Any]) -> str:
  today = str(case.get("today", "2026-11-16"))
  history_lines: list[str] = []
  for msg in case.get("chat_history", []):
    role = msg.get("role", "user")
    content = msg.get("content", "")
    history_lines.append(f"- {role}: {content}")
  history_block = "\n".join(history_lines) if history_lines else "（无历史对话）"
  query = str(case.get("query", "")).strip()
  return (
      f"当前日期：{today}\n"
      f"最近对话摘要：\n{history_block}\n\n"
      f"当前用户问题：\n<user_query>\n{query}\n</user_query>"
  )


def _deterministic_mock_planner(messages: list[dict[str, str]]) -> str:
  """离线确定性查询规划器（供无 API Key 环境秒级验真）。"""
  user_text = messages[-1]["content"]
  today_match = re.search(r"当前日期：(\d{4})-\d{2}-\d{2}", user_text)
  this_year = int(today_match.group(1)) if today_match else 2026

  q_match = re.search(r"<user_query>\n(.*?)\n</user_query>", user_text, flags=re.S)
  raw_query = q_match.group(1).strip() if q_match else user_text.strip()

  hist_match = re.search(r"最近对话摘要：\n(.*?)\n\n当前用户问题：", user_text, flags=re.S)
  history_text = hist_match.group(1) if hist_match else ""

  has_chitchat = any(h in raw_query for h in _CHITCHAT_HINTS)
  has_domain_q = any(k in raw_query for k in _DOMAIN_INQUIRY_HINTS)
  if has_chitchat and not has_domain_q:
    return json.dumps(
        {
            "need_retrieval": False,
            "standalone_query": raw_query,
            "exact_terms": [],
            "sub_queries": [],
            "time_filter": None,
        },
        ensure_ascii=False,
    )

  standalone = raw_query
  if any(pronoun in raw_query for pronoun in ("那它的", "它的", "它", "上面那个", "刚说的")):
    entities = _HISTORY_ENTITY_RE.findall(history_text)
    if entities:
      subject = entities[-1]
      if "那它的" in standalone:
        standalone = standalone.replace("那它的", f"{subject} 的", 1)
      elif "它的" in standalone:
        standalone = standalone.replace("它的", f"{subject} 的", 1)
      else:
        standalone = f"{subject} {standalone}"

  exact_terms = extract_exact_terms(raw_query)
  time_filter: dict[str, str] | None = None
  sub_queries: list[str] = [standalone]

  if "去年" in standalone and "今年" in standalone:
    time_filter = {"after": f"{this_year - 1}-01-01", "before": f"{this_year}-12-31"}
    core_topic = standalone
    for prefix in ("对比去年和今年的", "去年和今年的", "对比去年与今年的"):
      core_topic = core_topic.replace(prefix, "")
    for suffix in ("有哪些核心变化？", "有哪些核心变化?", "有哪些变化？", "什么区别？", "？", "?"):
      core_topic = core_topic.replace(suffix, "")
    core_topic = core_topic.strip() or standalone
    sub_queries = [
        f"{this_year - 1} 年 {core_topic} 技术规范",
        f"{this_year} 年 {core_topic} 技术规范",
    ]
  elif any(word in standalone for word in ("今年", "最新", "近期")):
    time_filter = {"after": f"{this_year}-01-01", "before": f"{this_year}-12-31"}
    sub_queries = [f"{this_year} {standalone}"]
  elif "去年" in standalone:
    time_filter = {"after": f"{this_year - 1}-01-01", "before": f"{this_year - 1}-12-31"}
    sub_queries = [f"{this_year - 1} {standalone}"]

  return json.dumps(
      {
          "need_retrieval": True,
          "standalone_query": standalone,
          "exact_terms": exact_terms,
          "sub_queries": sub_queries,
          "time_filter": time_filter,
      },
      ensure_ascii=False,
  )


def _strip_json_fence(raw_text: str) -> str:
  cleaned = raw_text.strip()
  if cleaned.startswith("```"):
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
  return cleaned.strip()


def build_query_plan(case: dict[str, Any]) -> dict[str, Any]:
  """调用规划提示词并做 JSON Schema 保真规整。"""
  raw_query = str(case.get("query", "")).strip()
  messages = [
      {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
      {"role": "user", "content": _format_planner_user_prompt(case)},
  ]
  raw_resp = chat_complete(
      messages,
      mock_fn=_deterministic_mock_planner,
      temperature=0.0,
      response_json=True,
  )
  parsed = json.loads(_strip_json_fence(raw_resp))

  need_retrieval = bool(parsed.get("need_retrieval", True))
  standalone = str(parsed.get("standalone_query") or raw_query).strip()

  if not need_retrieval:
    return {
        "need_retrieval": False,
        "standalone_query": standalone,
        "exact_terms": [],
        "sub_queries": [],
        "time_filter": None,
    }

  # 强制校核精确词未发生大小写或下划线篡改
  extracted_verbatim = extract_exact_terms(raw_query)
  raw_exact = [str(t) for t in parsed.get("exact_terms", []) if str(t) in raw_query]
  for item in extracted_verbatim:
    if item not in raw_exact:
      raw_exact.append(item)

  sub_queries = [str(q).strip() for q in parsed.get("sub_queries", []) if str(q).strip()]
  if not sub_queries:
    sub_queries = [standalone]

  tf = parsed.get("time_filter")
  norm_tf: dict[str, str] | None = None
  if isinstance(tf, dict) and tf.get("after") and tf.get("before"):
    norm_tf = {"after": str(tf["after"]), "before": str(tf["before"])}

  return {
      "need_retrieval": True,
      "standalone_query": standalone,
      "exact_terms": raw_exact,
      "sub_queries": sub_queries,
      "time_filter": norm_tf,
  }


def _split_identifier_subtokens(token: str) -> list[str]:
  """拆分下划线与驼峰技术标识符子词（如 UpstreamPool -> upstream, pool）。"""
  parts: list[str] = []
  for piece in token.split("_"):
    if not piece:
      continue
    camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|$)|\d+", piece)
    for cp in camel_parts:
      low = cp.lower()
      if len(low) >= 2:
        parts.append(low)
  return parts


def _tokenize_mixed(text: str) -> list[tuple[str, float]]:
  """混合词元化：高权重保留英文标识符/子词与四位年份，剥离口语疑问虚词后提取中文双字与单字特征。"""
  features: list[tuple[str, float]] = []
  for token in re.findall(r"[A-Za-z0-9_]+", text):
    low = token.lower()
    if re.fullmatch(r"20\d{2}", low):
      features.append((f"id:{low}", 4.0))
    elif re.search(r"[A-Za-z]", low):
      features.append((f"id:{low}", 5.0))
      subtokens = _split_identifier_subtokens(token)
      if len(subtokens) > 1:
        for sub in subtokens:
          features.append((f"sub:{sub}", 1.5))
    else:
      features.append((f"id:{low}", 2.0))

  cleaned_cjk = _CJK_STOP_RE.sub(" ", text)
  for raw_block in re.findall(r"[\u4e00-\u9fff]+", cleaned_cjk):
    seg_buf: list[str] = []
    segments: list[str] = []
    for ch in raw_block:
      if ch in _CJK_PARTICLES:
        if seg_buf:
          segments.append("".join(seg_buf))
          seg_buf = []
      else:
        seg_buf.append(ch)
    if seg_buf:
      segments.append("".join(seg_buf))

    for seg in segments:
      if len(seg) >= 2:
        for i in range(len(seg) - 1):
          features.append((f"bg:{seg[i : i + 2]}", 1.0))
      for ch in seg:
        features.append((f"ch:{ch}", 0.25))
  return features


def _rank_semantic_lexical(chunks: list[dict[str, Any]], query: str) -> list[str]:
  """基于 IDF 加权的语义/词面召回排序路。"""
  if not chunks:
    return []
  doc_feature_sets: list[set[str]] = []
  df_counts: dict[str, int] = {}
  for chunk in chunks:
    full_text = f"{chunk['title']} {' '.join(chunk.get('tags', []))} {chunk['content']}"
    feats = {name for name, _ in _tokenize_mixed(full_text)}
    doc_feature_sets.append(feats)
    for f in feats:
      df_counts[f] = df_counts.get(f, 0) + 1

  q_feats = _tokenize_mixed(query)
  n_docs = len(chunks)
  scored: list[tuple[float, str]] = []
  for chunk, d_feats in zip(chunks, doc_feature_sets):
    score = 0.0
    for f_name, weight in q_feats:
      if f_name in d_feats:
        idf = math.log((n_docs + 1) / (df_counts.get(f_name, 0) + 0.5)) + 1.0
        score += weight * idf
    scored.append((score, chunk["doc_id"]))

  scored.sort(key=lambda item: item[0], reverse=True)
  return [doc_id for score, doc_id in scored if score > 0]


def _rank_exact_terms_bm25(chunks: list[dict[str, Any]], exact_terms: list[str]) -> list[str]:
  """精确词检索路：严格区分大小写与下划线，模拟 FTS5 / BM25 精确匹配加权。"""
  if not chunks or not exact_terms:
    return []
  n_docs = len(chunks)
  df_map: dict[str, int] = {}
  corpus_texts: list[str] = []
  for chunk in chunks:
    blob = f"{chunk['title']} {' '.join(chunk.get('tags', []))} {chunk['content']}"
    corpus_texts.append(blob)
    for term in exact_terms:
      if term in blob:
        df_map[term] = df_map.get(term, 0) + 1

  scored: list[tuple[float, str]] = []
  for chunk, blob in zip(chunks, corpus_texts):
    score = 0.0
    for term in exact_terms:
      tf = blob.count(term)
      if tf > 0:
        idf = math.log(1.0 + (n_docs - df_map[term] + 0.5) / (df_map[term] + 0.5))
        score += idf * ((tf * 2.2) / (tf + 1.2))
    if score > 0:
      scored.append((score, chunk["doc_id"]))

  scored.sort(key=lambda item: item[0], reverse=True)
  return [doc_id for _, doc_id in scored]


def _rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
  """并行多路 Reciprocal Rank Fusion (RRF) 融合。"""
  fused_scores: dict[str, float] = {}
  for ranked in ranked_lists:
    for rank_idx, doc_id in enumerate(ranked, start=1):
      fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + 1.0 / (k + rank_idx)
  ordered = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)
  return [doc_id for doc_id, _ in ordered]


def execute_routed_search(
    case: dict[str, Any],
    kb_chunks: list[dict[str, Any]],
    top_k: int = 2,
) -> dict[str, Any]:
  """完整查询规划与多路路由检索闭环。"""
  plan = build_query_plan(case)

  # 1. 闲聊与非检索指令直接短路
  if not plan["need_retrieval"]:
    return {
        "plan": plan,
        "retrieval_triggered": False,
        "used_exact_route": False,
        "filtered_chunk_count": 0,
        "top_doc_ids": [],
    }

  # 2. 结构化元数据时间过滤
  candidate_chunks = list(kb_chunks)
  tf = plan.get("time_filter")
  if isinstance(tf, dict) and tf.get("after") and tf.get("before"):
    after_date = tf["after"]
    before_date = tf["before"]
    candidate_chunks = [
        c for c in candidate_chunks if after_date <= str(c.get("published_at", "")) <= before_date
    ]

  # 3. 并行构造多路检索结果：standalone_query + 各正交 sub_queries + 精确词通道
  ranked_lists: list[list[str]] = [
      _rank_semantic_lexical(candidate_chunks, plan["standalone_query"])
  ]
  for sub_q in plan["sub_queries"]:
    ranked_lists.append(_rank_semantic_lexical(candidate_chunks, sub_q))

  used_exact_route = False
  if plan["exact_terms"]:
    used_exact_route = True
    exact_ranked = _rank_exact_terms_bm25(candidate_chunks, plan["exact_terms"])
    if exact_ranked:
      # 精确故障码与函数名在排障场景具备高区分度，作为独立高置信通路参与 RRF
      ranked_lists.append(exact_ranked)
      ranked_lists.append(exact_ranked)

  # 4. RRF 融合排序
  fused_doc_ids = _rrf_fuse(ranked_lists, k=60)
  return {
      "plan": plan,
      "retrieval_triggered": True,
      "used_exact_route": used_exact_route,
      "filtered_chunk_count": len(candidate_chunks),
      "top_doc_ids": fused_doc_ids[: max(1, top_k)],
  }


if __name__ == "__main__":
  kb = json.loads((LAB_DIR / "fixtures" / "kb_chunks.json").read_text(encoding="utf-8"))
  cases = json.loads((LAB_DIR / "fixtures" / "dialog_cases.json").read_text(encoding="utf-8"))
  for item in cases:
    k = max(1, len(item["expected"]["expected_doc_ids"]))
    out = execute_routed_search(item, kb, top_k=k)
    print(
        f"[{item['case_id']}] need_retrieval={out['plan']['need_retrieval']} "
        f"| exact={out['plan']['exact_terms']} | time={out['plan']['time_filter']} "
        f"| top_docs={out['top_doc_ids']}"
    )
