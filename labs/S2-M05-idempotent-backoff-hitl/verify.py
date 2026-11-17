#!/usr/bin/env python3
"""S2-M05 四合一破坏性演练验收脚本：幂等去重与死信补发、指数退避与错误分级、一次性审批与30秒超时中止、预算熔断。"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

_ = chat_complete


class FakeClock:
  """可控虚拟时钟：无需真实等待即可演练 30 秒审批超时。"""

  def __init__(self, initial: float = 1_780_000_000.0) -> None:
    self.now = initial

  def __call__(self) -> float:
    return self.now

  def advance(self, seconds: float) -> None:
    self.now += seconds


def _load_target_module(mod_path: pathlib.Path) -> Any:
  mod_name = f"s2_m05_{'solution' if use_solution() else 'starter'}"
  spec = importlib.util.spec_from_file_location(mod_name, mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块: {mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> None:
  if os.environ.get("AID_USE_LIVE_LLM") != "1":
    os.environ.setdefault("AID_FORCE_MOCK", "1")

  v = LabVerifier("S2-M05", "幂等退避、死信补发、一次性审批与单期预算熔断演练")
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")

  try:
    mod = _load_target_module(mod_path)
  except Exception as exc:  # noqa: BLE001
    v.check("加载周报流水线模块", False, f"导入 {mod_path.name} 失败：{exc}")
    v.finish()
    return

  # 演练 1 & 2：同一期号连续重跑两次 + 持续 503/429 指数退避落死信 + 400 不重试 + 仅补发死信
  try:
    clock1 = FakeClock()
    sleeps1: list[float] = []
    pipe1 = mod.NewsletterPipeline(clock_fn=clock1, sleep_fn=sleeps1.append)
    prep1 = pipe1.prepare_issue("2026-W20", max_budget_usd=0.05, approval_timeout_seconds=1800.0)
    token1 = prep1.get("approval_token") or ""
    pipe1.approve_issue("2026-W20", token1)

    run1 = pipe1.dispatch_issue("2026-W20", max_retries=4)
    attempts_after_run1 = dict(pipe1.gateway.call_attempts)

    # 同一期号重跑第 2 次：已成功的 5 位订户必须零重复收信、零额外调用
    run2 = pipe1.dispatch_issue("2026-W20", max_retries=4)
    succeeded_subs = ("sub_01", "sub_02", "sub_03", "sub_06", "sub_08")
    zero_duplicate_send = all(
        pipe1.gateway.delivered_count.get(sid) == 1
        and pipe1.gateway.call_attempts.get(sid) == attempts_after_run1.get(sid)
        for sid in succeeded_subs
    )

    # 故障恢复后执行“仅补发死信”入口：只补发 sub_04 与 sub_07，不触碰已成功订户与 400 无效地址
    pipe1.gateway.transient_recovered = True
    attempts_before_replay = dict(pipe1.gateway.call_attempts)
    replay_res = pipe1.replay_dead_letters("2026-W20")
    only_dlq_replayed = (
        replay_res.get("replayed_sent_count") == 2
        and replay_res.get("remaining_dead_letters") == 0
        and all(
            pipe1.gateway.call_attempts.get(sid) == attempts_before_replay.get(sid)
            for sid in (*succeeded_subs, "sub_05")
        )
        and pipe1.gateway.delivered_count.get("sub_04") == 1
        and pipe1.gateway.delivered_count.get("sub_07") == 1
    )
    drill1_ok = (
        run1.get("sent_count") == 5
        and run2.get("sent_count") == 0
        and zero_duplicate_send
        and only_dlq_replayed
    )
    drill1_err = ""
  except Exception as exc:  # noqa: BLE001
    drill1_ok = False
    drill1_err = f"演练 1 执行异常：{exc}"
    run1 = {}
    sleeps1 = []
    attempts_after_run1 = {}
    pipe1 = None

  v.check(
      "演练① 幂等防重与死信精准补发：同号重跑零重发，死信补发仅投递失败订户",
      drill1_ok,
      drill1_err
      or "请在 SQLite send_logs 表对 (issue_id, subscriber_id) 设唯一约束并跳过已 sent 订户，"
      "将重试耗尽者写入 dead_letters 表，并在 replay_dead_letters 中仅重投死信记录。",
  )

  # 检查演练 2 的退避曲线、错误分级与死信告警
  try:
    non_retryable_attempts = attempts_after_run1.get("sub_05", 99)
    exhausted_503_attempts = attempts_after_run1.get("sub_04", 0)
    # 带抖动指数退避：至少包含 2s+, 4s+, 8s+, 16s+ 四档递增延迟，且非固定整秒（含随机抖动）
    has_exp_tiers = (
        any(2.0 <= d < 3.5 for d in sleeps1)
        and any(4.0 <= d < 5.5 for d in sleeps1)
        and any(8.0 <= d < 9.5 for d in sleeps1)
        and any(16.0 <= d < 17.5 for d in sleeps1)
        and any(abs(d - round(d)) > 1e-4 for d in sleeps1)
    )
    has_dlq_alert = pipe1 is not None and len(getattr(pipe1, "alerts", [])) > 0
    drill2_ok = (
        non_retryable_attempts == 1
        and exhausted_503_attempts == 5
        and run1.get("dead_letter_count") == 2
        and has_exp_tiers
        and has_dlq_alert
    )
  except Exception as exc:  # noqa: BLE001
    drill2_ok = False
    drill1_err = f"演练 2 检查异常：{exc}"

  v.check(
      "演练② 带抖动指数退避与错误分级：503/超时按 2^n+抖动退避入死信并告警，400 零重试",
      drill2_ok,
      "请区分可重试错误（429/5xx/TIMEOUT 按 2^n 秒加随机抖动最多重试 4 次，耗尽入死信并追加告警）"
      "与不可重试错误（400/401 仅尝试 1 次立即跳过，严禁盲目重试）。",
  )

  # 演练 3：一次性审批令牌防重放 + 30 秒超时未确认自动作废中止
  try:
    clock3 = FakeClock()
    pipe3 = mod.NewsletterPipeline(clock_fn=clock3, sleep_fn=lambda _: None)
    prep_timeout = pipe3.prepare_issue(
        "2026-W21-TIMEOUT", max_budget_usd=0.05, approval_timeout_seconds=30.0
    )
    # 推进虚拟时钟 31 秒，未点击审批
    clock3.advance(31.0)
    expired_approve_ok = pipe3.approve_issue(
        "2026-W21-TIMEOUT", prep_timeout.get("approval_token") or ""
    )
    expired_dispatch = pipe3.dispatch_issue("2026-W21-TIMEOUT")
    total_delivered_on_timeout = sum(pipe3.gateway.delivered_count.values())

    # 验证令牌只能生效一次且拒绝错误令牌
    prep_once = pipe3.prepare_issue(
        "2026-W22-ONCE", max_budget_usd=0.05, approval_timeout_seconds=30.0
    )
    tok = prep_once.get("approval_token") or ""
    wrong_tok_rejected = pipe3.approve_issue("2026-W22-ONCE", "appr_wrong_token") is False
    first_use_ok = pipe3.approve_issue("2026-W22-ONCE", tok) is True
    second_use_rejected = pipe3.approve_issue("2026-W22-ONCE", tok) is False

    drill3_ok = (
        expired_approve_ok is False
        and total_delivered_on_timeout == 0
        and expired_dispatch.get("sent_count", 99) == 0
        and wrong_tok_rejected
        and first_use_ok
        and second_use_rejected
    )
    drill3_err = ""
  except Exception as exc:  # noqa: BLE001
    drill3_ok = False
    drill3_err = f"演练 3 执行异常：{exc}"

  v.check(
      "演练③ 一次性鉴权审批与 30 秒超时止损：令牌点过即失效，30 秒超时未确认零邮件发出",
      drill3_ok,
      drill3_err
      or "请在 approve_issue 中核验令牌未过期且 used==0（通过后立即置 used=1 防止二次消费），"
      "并在 dispatch_issue 中确保未审批或超时后默认中止发送（严禁超时自动发出）。",
  )

  # 演练 4：草稿质量关卡重写（清除 {{...}} 占位符）与单期预算硬熔断
  try:
    clock4 = FakeClock()
    pipe4 = mod.NewsletterPipeline(clock_fn=clock4, sleep_fn=lambda _: None)
    # 调低单期预算至 0.002 USD（低于单次 LLM 调用估算成本 0.004 USD），应秒级熔断并告警
    low_budget_res = pipe4.prepare_issue("2026-W23-BUDGET", max_budget_usd=0.002)
    budget_tripped = (
        low_budget_res.get("status") == "aborted_budget"
        and low_budget_res.get("approval_token") is None
        and any("BUDGET" in a or "预算" in a or "上限" in a for a in getattr(pipe4, "alerts", []))
    )

    # 正常预算下验证首轮遗留 {{UNFILLED_METRIC}} 被关卡拦截重写清除，且费用被准确记账
    draft_text = str((prep1 if "prep1" in locals() else {}).get("draft") or "")
    spent_usd = float((prep1 if "prep1" in locals() else {}).get("spent_usd") or 0.0)
    draft_clean_and_metered = (
        len(draft_text) >= 80
        and "{{UNFILLED_METRIC}}" not in draft_text
        and spent_usd > 0.0
    )
    drill4_ok = budget_tripped and draft_clean_and_metered
    drill4_err = ""
  except Exception as exc:  # noqa: BLE001
    drill4_ok = False
    drill4_err = f"演练 4 执行异常：{exc}"

  v.check(
      "演练④ 草稿关卡校验与单期预算硬熔断：自动重写清除残留占位符，超预算立即熔断告警",
      drill4_ok,
      drill4_err
      or "请在 prepare_issue 中记录每次 LLM 调用费用（超 max_budget_usd 立即中止返回 status='aborted_budget' 并写入 alerts），"
      "并校验草稿字数、链接与无未替换 {{...}} 占位符（不通过最多带原因重写 2 次）。",
  )

  v.finish()


if __name__ == "__main__":
  main()
