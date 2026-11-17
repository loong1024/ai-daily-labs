"""S1-M04 Prompt 自动体检、闭合标签转义与回归验证（Starter 待完善版）。

当前存在以下待修复问题：
1. lint_prompt_template 为空实现，无法检出缓存击穿、硬编码密钥、Few-shot 冲突与未隔离外部输入；
2. render_safe_user_input 直接拼接字符串，未对输入中夹带的 </user_input> 闭合标签做转义；
3. REPAIRED_PROMPT_TEMPLATE 仍保留了坏模板的四类缺陷，且缺少头部版本号注释；
4. run_regression_suite 未接入安全转义与规范分类逻辑，面对闭合标签注入会被劫持。
"""

from __future__ import annotations

import json
from typing import Any, Callable

# TODO: 修复以下模板中的 4 类缺陷，并在首行补充标准版本号注释
# <!-- version: v1.1.0 | changelog: ... -->
REPAIRED_PROMPT_TEMPLATE = """<!-- Ticket Triage Draft -->
[SYSTEM]
当前请求时间: {{current_timestamp}} | 请求追踪号: {{request_id}}
你是工单助手，请专业一点。
内部审计回传密钥: FAKE_TEST_KEY_DO_NOT_USE_PROMPT_90123

[EXAMPLES]
示例 1：
输入：账单多扣了 299 元。
输出：{"category": "billing", "priority": "P1", "reason": "重复扣费"}

示例 2：
输入：API 全部 503。
输出：{"type": "tech_outage", "urgent": true}

[USER]
客户来信：
{{raw_user_message}}
"""


def lint_prompt_template(
    text: str,
    filename: str = "template.prompt.md",
) -> list[dict[str, Any]]:
  """TODO: 扫描模板并返回问题列表。

  每项字典需包含:
    - rule_id: 'cache_prefix' | 'hardcoded_secret' | 'fewshot_consistency' | 'injection_isolation' | 'version_header'
    - location: f'{filename}:{line_no}'
    - line: int
    - severity: 'high' | 'medium' | 'low'
    - problem: str
    - suggestion: str
  """
  return []


def render_safe_user_input(raw_text: str, tag: str = "user_input") -> str:
  """TODO: 转义 raw_text 中的同名开闭标签后再用 <tag>...</tag> 包裹，防止闭合标签逃逸。"""
  return f"<{tag}>{raw_text}</{tag}>"


def _naive_starter_mock(messages: list[dict[str, str]]) -> str:
  user_text = messages[-1]["content"]
  # 未转义 </user_input> 时，恶意载荷成功闭合外层标签并注入 approved_refund
  if "</user_input>\n[SYSTEM]" in user_text or "approved_refund" in user_text:
    return json.dumps({"category": "approved_refund", "priority": "P0", "reason": "injected"})
  return json.dumps({"type": "unknown"})


def run_regression_suite(
    cases: list[dict[str, Any]],
    chat_fn: Callable[..., str],
) -> dict[str, Any]:
  """在回归测试集上验证修复后模板的输出结构与防注入表现。"""
  results: list[dict[str, Any]] = []
  passed_count = 0
  for case in cases:
    wrapped = render_safe_user_input(case["raw_input"], tag="user_input")
    raw_resp = chat_fn(
        [{"role": "user", "content": wrapped}],
        mock_fn=_naive_starter_mock,
        temperature=0.0,
        response_json=True,
    )
    data = json.loads(raw_resp)
    ok = (
        set(data.keys()) == {"category", "priority", "reason"}
        and data.get("category") in case["expected_categories"]
        and data.get("priority") in case["expected_priorities"]
    )
    if ok:
      passed_count += 1
    results.append({"id": case["id"], "passed": ok, "output": data})
  return {
      "total": len(cases),
      "passed": passed_count,
      "pass_rate": passed_count / max(len(cases), 1),
      "results": results,
  }
