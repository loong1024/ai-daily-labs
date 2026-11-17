#!/usr/bin/env python3
"""S2-M02 Starter：10 样本工作流基准测骨架（已内置统一 llm() 计费耗时埋点与单提示基线）。

请结合 README.md 改造下方 4 个工作流函数，并运行 `python3 verify.py` 验收。
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete  # noqa: E402

# 统一计费与模拟延迟参数（确保无 API Key 离线评测也能真实反映大小模型成本/延迟差距）
MODEL_SPECS: dict[str, dict[str, float]] = {
    "mini": {"cost_per_1k": 0.15, "base_latency_ms": 95.0},
    "pro": {"cost_per_1k": 1.50, "base_latency_ms": 540.0},
}


class BenchmarkTracker:
  """线程安全的统一调用、Token、费用与耗时统计器。"""

  def __init__(self) -> None:
    self._lock = threading.Lock()
    self.calls: int = 0
    self.total_tokens: int = 0
    self.cost_usd: float = 0.0
    self.sim_latency_ms: float = 0.0
    self.wall_ms: float = 0.0

  def record(self, tier: str, tokens: int, wall_ms: float, *, count_latency: bool = True) -> float:
    spec = MODEL_SPECS.get(tier, MODEL_SPECS["pro"])
    call_sim_ms = spec["base_latency_ms"] + tokens * 0.18
    call_cost = (tokens / 1000.0) * spec["cost_per_1k"]
    with self._lock:
      self.calls += 1
      self.total_tokens += tokens
      self.cost_usd += call_cost
      self.wall_ms += wall_ms
      if count_latency:
        self.sim_latency_ms += call_sim_ms
    return call_sim_ms

  def add_parallel_batch_latency(self, batch_latencies: list[float], max_workers: int) -> None:
    if not batch_latencies:
      return
    ordered = list(batch_latencies)
    waves = [ordered[i : i + max_workers] for i in range(0, len(ordered), max_workers)]
    total_wave_ms = sum(max(w) for w in waves)
    with self._lock:
      self.sim_latency_ms += total_wave_ms


def _estimate_tokens(text: str) -> int:
  return max(12, int(len(text) * 0.85))


def _baseline_mock_llm(messages: list[dict[str, str]]) -> str:
  prompt = messages[-1]["content"]
  if "T01" in prompt or "发票" in prompt:
    return "您好，请进入控制台【账单中心】找到对应订单，修改【发票抬头】后点击申请【重开】电子发票即可，一般 10 分钟内生效。"
  if "T02" in prompt or "席位" in prompt:
    return "您好，中途升级版本时，新增【席位】将严格按照当前订阅周期剩余天数【按天折算】，您只需支付对应周期【补差价】即可立即生效。"
  if "T03" in prompt or "轮换" in prompt:
    return "您好，在控制台【开发者设置】执行密钥【轮换】时，可勾选保留 24 小时平滑【宽限期】，避免 CI 脚本瞬间中断；也可手动点立即吊销。"
  if "T04" in prompt or "CSV" in prompt:
    return "您好，审计日志页面单次最多支持导出【10万行】记录；若超出上限，请按时间段【分批导出】或调用后台【异步API】拉取全量归档。"
  if "T06" in prompt or "99%" in prompt:
    return "您好，针对【同步任务】卡在 99% 可先清理增量游标重试；【权限缓存】延迟问题研发已纳入本周紧急【修复排期】；同时我们将按合同核算本月【SLA抵扣券】。"
  # 单一大提示词在多诉求诱导客诉 (T05/T07) 易漏点，在模糊件 (T08/T09/T10) 易盲目承诺操作
  if "转圈" in prompt or "配额" in prompt or "灰色" in prompt:
    return "您好，收到您的反馈，我们已为您后台修改完毕并刷新了默认配置，请您重新登录页面再试一次。"
  return "您好，非常抱歉给您带来不好的体验，针对您反馈的故障我们已记录并推进排查，感谢您的理解与支持。"


def llm(
    prompt: str,
    tracker: BenchmarkTracker,
    *,
    tier: str = "pro",
    system: str = "你是企业 SaaS 客服助手。",
    mock_fn: Any = None,
    response_json: bool = False,
    count_latency: bool = True,
) -> tuple[str, float]:
  """统一的模型调用入口：自动统计调用次数、Token、费用与模拟/真实耗时。"""
  t0 = time.perf_counter()
  messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
  out = chat_complete(
      messages,
      mock_fn=mock_fn or _baseline_mock_llm,
      temperature=0.0,
      response_json=response_json,
  )
  wall_ms = (time.perf_counter() - t0) * 1000.0
  tokens = _estimate_tokens(system + prompt + out)
  sim_ms = tracker.record(tier, tokens, wall_ms, count_latency=count_latency)
  return out, sim_ms


def evaluate_reply_quality(
    ticket: dict[str, Any],
    reply: str,
    strict_rubric: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """程序化质量评估器：检查字数区间、必答要素覆盖率与违规承诺红线。"""
  min_len = int((strict_rubric or {}).get("min_len", 32))
  max_len = int((strict_rubric or {}).get("max_len", 420))
  impossible_token = (strict_rubric or {}).get("impossible_token")

  missing = [pt for pt in ticket.get("required_points", []) if pt not in reply]
  if impossible_token and impossible_token not in reply:
    missing.append(str(impossible_token))

  violations = [bad for bad in ticket.get("forbidden_phrases", []) if bad in reply]
  length_ok = min_len <= len(reply) <= max_len
  passed = length_ok and not missing and not violations

  feedback_parts: list[str] = []
  if not length_ok:
    feedback_parts.append(f"字数需在 {min_len}-{max_len} 字之间（当前 {len(reply)} 字）")
  if missing:
    feedback_parts.append("补充遗漏要点：" + "、".join(missing))
  if violations:
    feedback_parts.append("删除越权承诺表述：" + "、".join(violations))

  return {
      "passed": passed,
      "missing_points": missing,
      "violations": violations,
      "feedback": "；".join(feedback_parts) if feedback_parts else "合格",
  }


def run_single_prompt(ticket: dict[str, Any], tracker: BenchmarkTracker) -> dict[str, Any]:
  """基线模式：一条大提示词全走 pro 模型直出。"""
  big_prompt = (
      f"工单ID: {ticket['id']} | 客户等级: {ticket['customer_tier']}\n"
      "请一次性完成意图分类、多诉求提取、合规红线审查与最终客服回复撰写：\n"
      f"{ticket['text']}"
  )
  reply, _ = llm(big_prompt, tracker, tier="pro")
  ev = evaluate_reply_quality(ticket, reply)
  return {"ticket_id": ticket["id"], "reply": reply, "passed": ev["passed"], "eval": ev}


def run_prompt_chain(
    ticket: dict[str, Any],
    tracker: BenchmarkTracker,
    *,
    max_retries: int = 2,
    force_gate_fail: bool = False,
) -> dict[str, Any]:
  """TODO(Step 2a)：改造为“提取结构化大纲 -> 程序化关卡核验（最多重试 2 次）-> 生成正文”。"""
  res = run_single_prompt(ticket, tracker)
  res["attempts_used"] = 1
  res["gate_passed"] = not force_gate_fail
  return res


def run_routing(ticket: dict[str, Any], tracker: BenchmarkTracker) -> dict[str, Any]:
  """TODO(Step 2b)：改造为难度路由（mini 处理简单咨询，pro 处理长投诉，模糊件进兜底澄清分支）。"""
  res = run_single_prompt(ticket, tracker)
  res["route"] = "pro_all_in_one"
  return res


def run_parallel_vote(
    ticket: dict[str, Any],
    tracker: BenchmarkTracker,
    *,
    max_workers: int = 5,
) -> dict[str, Any]:
  """TODO(Step 3)：改造为 5 并发上限分段提取 + 3 视角退款承诺投票（对比 majority_vote 与 any_hit）。"""
  res = run_single_prompt(ticket, tracker)
  res["max_workers_configured"] = 1
  res["segments_processed"] = 1
  res["votes"] = {}
  res["majority_vote"] = False
  res["any_hit"] = False
  return res


def run_evaluator_loop(
    ticket: dict[str, Any],
    tracker: BenchmarkTracker,
    *,
    max_rounds: int = 3,
    strict_rubric: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """TODO(Step 4)：实现生成-评估-反馈迭代循环，并硬编码最多 3 轮上限（严禁超限空转）。"""
  # 基线缺陷演示：未将轮次钳制在 3 轮以内（此处仅设 6 轮防终端永久挂起，请修复为 <= 3 轮并结合 feedback 改写！）
  safety_guard = min(max(1, max_rounds), 6)
  reply = ""
  ev: dict[str, Any] = {"passed": False}
  rounds_used = 0
  for round_idx in range(1, safety_guard + 1):
    rounds_used = round_idx
    reply, _ = llm(f"工单 {ticket['id']}：\n{ticket['text']}", tracker, tier="pro")
    ev = evaluate_reply_quality(ticket, reply, strict_rubric=strict_rubric)
    if ev["passed"]:
      break
  return {
      "ticket_id": ticket["id"],
      "reply": reply,
      "passed": ev["passed"],
      "rounds_used": rounds_used,
      "eval": ev,
  }


def run_benchmark(tickets: list[dict[str, Any]]) -> dict[str, Any]:
  """在全部 10 条样本上同题运行单提示基线与四种工作流模式，汇总对比指标。"""
  runners = {
      "single_prompt": lambda t, tr: run_single_prompt(t, tr),
      "prompt_chain": lambda t, tr: run_prompt_chain(t, tr),
      "routing": lambda t, tr: run_routing(t, tr),
      "parallel_vote": lambda t, tr: run_parallel_vote(t, tr),
      "evaluator_loop": lambda t, tr: run_evaluator_loop(t, tr),
  }
  modes_summary: dict[str, Any] = {}
  for mode_name, fn in runners.items():
    tracker = BenchmarkTracker()
    details = [fn(ticket, tracker) for ticket in tickets]
    passed_cnt = sum(1 for d in details if d.get("passed"))
    modes_summary[mode_name] = {
        "sample_count": len(details),
        "llm_calls": tracker.calls,
        "total_tokens": tracker.total_tokens,
        "cost_usd": round(tracker.cost_usd, 5),
        "sim_latency_ms": round(tracker.sim_latency_ms, 1),
        "wall_ms": round(tracker.wall_ms, 2),
        "quality_pass_rate": round(passed_cnt / max(1, len(details)), 2),
        "details": details,
    }
  return {"ticket_count": len(tickets), "modes": modes_summary}


def format_benchmark_markdown(report: dict[str, Any]) -> str:
  lines = [
      "| 工作流模式 | 样本数 | LLM 调用次数 | 总 Tokens | 模拟耗时 (ms) | 估算费用 ($) | 质量合格率 |",
      "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
  ]
  for mode_name, stats in report["modes"].items():
    lines.append(
        f"| `{mode_name}` | {stats['sample_count']} | {stats['llm_calls']} | "
        f"{stats['total_tokens']} | {stats['sim_latency_ms']} | "
        f"{stats['cost_usd']:.4f} | {stats['quality_pass_rate']:.0%} |"
    )
  return "\n".join(lines)


if __name__ == "__main__":
  sample_tickets = json.loads((LAB_DIR / "fixtures" / "tickets_10.json").read_text(encoding="utf-8"))
  bench_report = run_benchmark(sample_tickets)
  print(format_benchmark_markdown(bench_report))
