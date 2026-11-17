from __future__ import annotations
import json
import uuid

ALLOWED = {"BILLING", "BUG", "FEATURE", "ACCOUNT"}


def build_ticket_request(static_sop: str, schema_dict: dict, user_text: str) -> list[dict]:
  # 缺陷 1：混入随机 trace_id 且未固定 JSON 序列化键序，破坏前缀字节稳定性
  # 缺陷 2：未转义外部文本中的闭合标签 </user_ticket>，导致标签逃逸注入
  header = f"trace={uuid.uuid4()}\n{static_sop}\nSchema:{json.dumps(schema_dict)}"
  return [
      {"role": "system", "content": header},
      {"role": "user", "content": f"<user_ticket>{user_text}</user_ticket>"},
  ]


def safe_classify(raw_llm_json: str) -> dict:
  # 缺陷 3：未做枚举白名单强校验与异常字段剥离
  return json.loads(raw_llm_json)
