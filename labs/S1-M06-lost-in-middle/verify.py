#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def load_mod(path: pathlib.Path):
  spec = importlib.util.spec_from_file_location("lab_target", path)
  mod = importlib.util.module_from_spec(spec)
  assert spec and spec.loader
  spec.loader.exec_module(mod)
  return mod

def mock_position_sensitive_llm(messages: list[dict]) -> str:
  # 模拟真实长窗口注意力U型曲线：重点关注首段与末段证据，若中间混入大量噪音或旧规排在前面则易答偏
  full = "\n".join(m["content"] for m in messages)
  lines = [ln.strip() for ln in full.splitlines() if ln.strip().startswith("[")]
  if not lines:
    return "未知"
  attending = [lines[0], lines[-1]] if len(lines) >= 2 else lines
  joined = " ".join(attending)
  if "80万元" in joined:
    return "80万元"
  if "65%" in joined:
    return "65%"
  if "30万元" in full:
    return "30万元"
  return "40%"


def main() -> None:
  v = LabVerifier("S1-M06", "大篇幅“中间遗忘”与前缀缓存实测")
  data = json.loads((LAB_DIR / "fixtures" / "probe_docs.json").read_text(encoding="utf-8"))
  mod = load_mod(target_file(LAB_DIR, "starter.py", "solution.py"))

  q1, q2 = data["queries"][0], data["queries"][1]
  arr1 = mod.arrange_context_sandwich(q1["docs"], min_score=0.5)
  arr2 = mod.arrange_context_sandwich(q2["docs"], min_score=0.5)

  no_noise = all(d["score"] >= 0.5 for d in arr1) and len(arr1) < len(q1["docs"])
  v.check("低相关性噪音过滤（剔除 score < 0.5 的无关行政琐事段落）", no_noise,
          "在 arrange_context_sandwich() 中过滤 score < min_score 的噪音段落。")

  edge_placed = bool(arr1) and (arr1[0]["id"] == "D_KEY" or arr1[-1]["id"] == "D_KEY")
  v.check("核心最新证据置于首尾高注意力区（避开中间遗忘谷底）", edge_placed,
          "按日期与相关性排序，将最关键的现行生效条款放在列表首位或末位。")

  msg1 = mod.build_cached_messages(data["static_handbook"], arr1, q1["question"])
  msg2 = mod.build_cached_messages(data["static_handbook"], arr2, q2["question"])
  ans1 = chat_complete(msg1, mock_fn=mock_position_sensitive_llm)
  ans2 = chat_complete(msg2, mock_fn=mock_position_sensitive_llm)
  acc_ok = (q1["expected_answer"] in ans1) and (q2["expected_answer"] in ans2)
  v.check("冲突探针问答准确率达 100%（不被旧废止条款与中间噪音误导）", acc_ok,
          "确保去噪后最新条款排在首尾，并在系统指令中声明新旧冲突以最新日期为准。")

  cached_chars = mod.simulate_cache_tokens(msg1, msg2)
  v.check(f"连续请求静态前缀稳定命中缓存（公共静态前缀长度={cached_chars}，需 ≥1500）", cached_chars >= 1500,
          "移除前置动态时间戳，把固定规则与 static_handbook 固定在 messages[0] 静态前缀，变动问题放末尾。")
  v.finish()


if __name__ == "__main__":
  main()
