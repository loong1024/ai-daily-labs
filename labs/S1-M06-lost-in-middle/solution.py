from __future__ import annotations

SYSTEM_RULES = (
    "你是严谨的企业制度核查助手。请严格依据提供的参考段落作答；"
    "若存在新旧条款冲突，必须以最新日期（date 最大）的现行生效条款为准，忽略废止条款。"
)


def arrange_context_sandwich(docs: list[dict], min_score: float = 0.5) -> list[dict]:
  filtered = [d for d in docs if float(d.get("score", 0.0)) >= min_score]
  ranked = sorted(filtered, key=lambda d: (d.get("date", ""), float(d.get("score", 0.0))), reverse=True)
  if len(ranked) <= 2:
    return ranked
  # 首尾排布（Sandwich）：第 1 强证据放开头，第 2 强证据放末尾，次要证据放中间
  head = [ranked[0]]
  tail = [ranked[1]]
  middle = ranked[2:]
  return head + middle + tail


def build_cached_messages(static_handbook: str, arranged_docs: list[dict], question: str) -> list[dict]:
  static_prefix = f"{SYSTEM_RULES}\n\n{static_handbook}"
  ctx = "\n".join(f"[{d['id']} | {d['date']}] {d['text']}" for d in arranged_docs)
  return [
      {"role": "system", "content": static_prefix},
      {"role": "user", "content": f"<context>\n{ctx}\n</context>\n请回答：{question}"},
  ]


def simulate_cache_tokens(msg_a: list[dict], msg_b: list[dict]) -> int:
  flat_a = "\n".join(f"{m['role']}:{m['content']}" for m in msg_a)
  flat_b = "\n".join(f"{m['role']}:{m['content']}" for m in msg_b)
  common = 0
  for ca, cb in zip(flat_a, flat_b):
    if ca != cb:
      break
    common += 1
  return common if common >= 1500 else 0
