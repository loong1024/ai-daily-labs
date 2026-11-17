from __future__ import annotations
import time


def arrange_context_sandwich(docs: list[dict], min_score: float = 0.5) -> list[dict]:
  # TODO: 1) 过滤 score < min_score 的无关噪音段落；
  #       2) 将最高分/最新日期的核心证据排在首尾（Sandwich 首尾强化），避免埋在正中间。
  return list(docs)


def build_cached_messages(static_handbook: str, arranged_docs: list[dict], question: str) -> list[dict]:
  # 缺陷基线：把动态时间戳和变动问题放在最前面，导致每次请求前缀第 1 个字节就变化，缓存命中为 0！
  dynamic_ts = f"request_ts={time.time()}"
  ctx = "\n".join(f"[{d['id']} | {d['date']}] {d['text']}" for d in arranged_docs)
  return [
      {"role": "user", "content": f"{dynamic_ts}\n问题：{question}\n制度基座：{static_handbook}\n参考段落：\n{ctx}"}
  ]


def simulate_cache_tokens(msg_a: list[dict], msg_b: list[dict]) -> int:
  flat_a = "\n".join(m["content"] for m in msg_a)
  flat_b = "\n".join(m["content"] for m in msg_b)
  common = 0
  for ca, cb in zip(flat_a, flat_b):
    if ca != cb:
      break
    common += 1
  return common if common >= 1500 else 0
