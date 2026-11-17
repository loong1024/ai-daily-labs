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

def mock_ticket_llm(messages: list[dict]) -> str:
  user_msg = messages[-1]["content"]
  # 如果外部文本成功未转义闭合 </user_ticket>，模拟模型被逃逸后的伪指令劫持
  inner = user_msg.removeprefix("<user_ticket>").removesuffix("</user_ticket>")
  if "</user_ticket>" in inner and "ADMIN_HACKED" in inner:
    return json.dumps({"category": "ADMIN_HACKED", "leaked": messages[0]["content"][:80]})
  if "发票" in user_msg:
    return json.dumps({"category": "BILLING"})
  if "闪退" in user_msg:
    return json.dumps({"category": "BUG"})
  return json.dumps({"category": "ACCOUNT"})


def main() -> None:
  v = LabVerifier("S1-M07", "前缀缓存稳定性与闭合标签防劫持双线体检")
  fx = json.loads((LAB_DIR / "fixtures" / "tickets.json").read_text(encoding="utf-8"))
  mod = load_mod(target_file(LAB_DIR, "starter.py", "solution.py"))
  schema = {"type": "object", "required": ["category"], "properties": {"category": {"enum": fx["allowed_categories"]}}}

  r1 = mod.build_ticket_request(fx["static_sop"], schema, fx["samples"][0]["text"])
  r2 = mod.build_ticket_request(fx["static_sop"], schema, fx["samples"][1]["text"])
  prefix_identical = (r1[0]["content"] == r2[0]["content"]) and len(r1[0]["content"]) >= 1200
  v.check("≥1200 字符静态前缀在连续两次请求中字节级 100% 一致（cached_tokens > 0）", prefix_identical,
          "移除 system 消息中的随机 uuid/时间戳，并对 schema_dict 使用 json.dumps(..., sort_keys=True)。")

  atk_req = mod.build_ticket_request(fx["static_sop"], schema, fx["samples"][2]["text"])
  raw_out = chat_complete(atk_req, mock_fn=mock_ticket_llm, response_json=True)
  parsed = mod.safe_classify(raw_out)

  escaped_ok = "</user_ticket>" not in atk_req[-1]["content"][15:-16]
  v.check("外部不可信输入中的闭合分隔符 </user_ticket> 已被安全转义防逃逸", escaped_ok,
          "对拼入 <user_ticket> 标签的外部文本转义 </user_ticket> 为 &lt;/user_ticket&gt;。")

  enum_ok = parsed.get("category") in set(fx["allowed_categories"]) and "leaked" not in parsed
  v.check("恶意注入样本输出严格锁定在预设四类枚举且零系统设定泄露", enum_ok,
          "在 safe_classify() 中校验 category 必须属于 ALLOWED 枚举并仅返回白名单字段。")
  v.finish()


if __name__ == "__main__":
  main()
