#!/usr/bin/env python3
"""S2-M02 Solution：单提示基线 vs 四大确定性工作流模式 10 样本同题基准测完整实现。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import pathlib
import re
import sys
import threading
import time
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete  # noqa: E402

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


def _strip_fence(raw: str) -> str:
  s = raw.strip()
  if s.startswith("```"):
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
  return s.strip()


def _compose_compliant_reply(ticket_id: str, include_all: bool = True) -> str:
  """根据工单生成覆盖核心业务要点的合规回复文本。"""
  templates = {
      "T01": "您好，请前往控制台【账单中心】定位对应充值订单，在发票详情页更新【发票抬头】与税号后提交电子发票【重开】申请，系统将在 10 分钟内重新签发。",
      "T02": "您好，个人版中途升级企业协作版时，新增的 5 个成员【席位】费用会按当前计费周期剩余天数自动【按天折算】，结账页仅需支付对应【补差价】即可立即开通。",
      "T03": "您好，在控制台【开发者设置】执行 API Token【轮换】时，默认提供 24 小时平滑【宽限期】供 CI 脚本灰度更新；若存在泄露风险也可手动点击立即吊销旧令牌。",
      "T04": "您好，审计日志页面单次导出 CSV 上限为【10万行】记录；若需拉取更大时间跨度的数据，建议按月【分批导出】或调用后台【异步API】生成离线归档包。",
      "T05": (
          "您好，非常抱歉大促期间给您造成困扰：1）针对【Webhook延迟】与值班响应超时，我们已将【工单升级】至网关稳定性负责人；"
          "2）今日内将向您提交完整故障【根因报告】；3）服务补偿将严格依据企业【SLA协议】核定抵扣方案，坐席无法越权私自承诺现金退赔。"
      ),
      "T06": (
          "您好，已收到您的紧急反馈：1）针对知识库【同步任务】卡在 99%，可先在连接器页点击重置增量游标临时恢复；"
          "2）子账号目录可见性系【权限缓存】刷新延迟所致，研发已锁定今日热补丁【修复排期】；3）本月补偿将按合同为您核算【SLA抵扣券】。"
      ),
      "T07": (
          "您好，我们对您的多段反馈高度重视：1）海外节点双栏【PDF解析】乱码已转交文档引擎组定位；"
          "2）针对疑似重复扣款已启动财务【账单核查】并走异常流水【原路退回核实】流程；"
          "3）已督促客户成功主管在 1 小时内完成【经理回电】同步进展，具体赔付均以财务与合同核定为准。"
      ),
      "T08": "您好，为了准确帮您排查保存一直转圈的问题而不误改线上数据，请先补充【提供账号】或组织 ID、出问题的【具体页面】名称，并附上一张浏览器控制台【报错截图】。",
      "T09": "您好，后台配额变更需经安全留痕核验后执行，请您先补充【提供租户ID】、需要调整的【具体配额项】（如并发数或存储容量）以及期望调至的【目标数值】。",
      "T10": "您好，按钮置灰通常与工作空间菜单权限绑定有关，请补充该功能的【页面路径】、您与同事各自的【账号角色】名称，并上传一张页面【截图核实】以便快速定位。",
  }
  base = templates.get(ticket_id, "您好，请补充更多上下文信息以便核实处理。")
  if not include_all and ticket_id in ("T05", "T07"):
    # 模拟首轮初稿漏掉最后一项要素，留给评估循环第 2 轮补齐
    return base[:56] + "我们将尽快跟进处理，感谢理解。"
  return base


def _smart_mock_llm(messages: list[dict[str, str]]) -> str:
  sys_text = messages[0]["content"]
  user_text = messages[-1]["content"]

  tid_match = re.search(r"\b(T\d{2})\b", user_text)
  tid = tid_match.group(1) if tid_match else "T01"

  # 1. 路由分类器响应
  if "[MODE:ROUTER]" in sys_text:
    if tid in ("T01", "T02", "T03", "T04"):
      return json.dumps({"route": "simple_faq", "reason": "单一规则或操作路径咨询"}, ensure_ascii=False)
    if tid in ("T05", "T06", "T07"):
      return json.dumps({"route": "complex_complaint", "reason": "多段落复合故障客诉与赔偿交涉"}, ensure_ascii=False)
    return json.dumps({"route": "ambiguous_edge", "reason": "缺失账号/页面等关键上下文"}, ensure_ascii=False)

  # 2. 提示词链步骤 1：结构化诉求大纲提取
  if "[MODE:CHAIN_EXTRACT]" in sys_text:
    return json.dumps(
        {
            "ticket_id": tid,
            "intent": "customer_support",
            "key_issues": ["核心诉求梳理", "合规边界核查"],
            "need_clarification": tid in ("T08", "T09", "T10"),
        },
        ensure_ascii=False,
    )

  # 3. 并行分段提取器
  if "[MODE:PARALLEL_SEGMENT]" in sys_text:
    seg_preview = user_text.strip().splitlines()[-1][:28]
    return f"子诉求摘要：{seg_preview}"

  # 4. 并行三视角退款承诺投票器
  if "[MODE:VOTER_LEGAL]" in sys_text:
    # 法务严苛视角：既拦截直接退赔承诺，也对“抵扣券”字样做敏感提示
    flagged = any(w in user_text for w in ("现在为您办理退一赔三", "立即为您双倍退款", "SLA抵扣券"))
    return json.dumps({"flagged": flagged, "perspective": "legal_redline"}, ensure_ascii=False)
  if "[MODE:VOTER_FINANCE]" in sys_text:
    # 财务视角：仅拦截越权现金退赔承诺，认可合同内 SLA 抵扣券说明
    flagged = any(w in user_text for w in ("现在为您办理退一赔三", "立即为您双倍退款"))
    return json.dumps({"flagged": flagged, "perspective": "finance_sla"}, ensure_ascii=False)
  if "[MODE:VOTER_OPS]" in sys_text:
    flagged = any(w in user_text for w in ("现在为您办理退一赔三", "立即为您双倍退款", "已为您后台修改完毕"))
    return json.dumps({"flagged": flagged, "perspective": "ops_policy"}, ensure_ascii=False)

  # 5. 单提示基线（模拟过载提示词在长客诉与模糊件上的典型失误）
  if "[MODE:SINGLE_BASELINE]" in sys_text:
    if tid in ("T01", "T02", "T03", "T04", "T06"):
      return _compose_compliant_reply(tid, include_all=True)
    if tid in ("T08", "T09"):
      return "您好，收到您的紧急需求，我们已为您后台修改完毕并同步刷新了默认配额，请重新登录查看。"
    return "您好，非常抱歉给您带来不便，您反馈的问题我们已记录并安排值班工程师排查，感谢支持。"

  # 6. 评估循环首轮初稿 vs 反馈修订稿
  if "[MODE:EVAL_DRAFT]" in sys_text:
    return _compose_compliant_reply(tid, include_all=False)
  if "[MODE:EVAL_CRITIC]" in sys_text:
    return "请严格按缺失要点逐条补齐，并严守合规措辞边界。"

  return _compose_compliant_reply(tid, include_all=True)


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
      mock_fn=mock_fn or _smart_mock_llm,
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
  """单提示词基线：所有工单一律塞进大提示词并用高价 pro 模型直出。"""
  big_prompt = (
      f"工单ID: {ticket['id']} | 客户等级: {ticket['customer_tier']} | "
      f"需覆盖要点参考: {','.join(ticket['required_points'])}\n"
      "请在一个回合内同时完成意图判断、多诉求拆解、赔偿合规审查与最终客服回复撰写：\n"
      f"{ticket['text']}"
  )
  reply, _ = llm(big_prompt, tracker, tier="pro", system="[MODE:SINGLE_BASELINE] 你是全能客服助手。")
  ev = evaluate_reply_quality(ticket, reply)
  return {"ticket_id": ticket["id"], "reply": reply, "passed": ev["passed"], "eval": ev}


def run_prompt_chain(
    ticket: dict[str, Any],
    tracker: BenchmarkTracker,
    *,
    max_retries: int = 2,
    force_gate_fail: bool = False,
) -> dict[str, Any]:
  """模式 1（提示词链）：提取结构化大纲 -> 程序化关卡核验（最多重试 2 次）-> 生成最终回复。"""
  capped_retries = min(max(0, int(max_retries)), 2)
  attempts_used = 0
  gate_passed = False
  outline: dict[str, Any] = {}

  for _ in range(capped_retries + 1):
    attempts_used += 1
    raw_outline, _ = llm(
        f"提取工单 {ticket['id']} 的结构化诉求 JSON：\n{ticket['text']}",
        tracker,
        tier="mini",
        system="[MODE:CHAIN_EXTRACT] 仅输出含 ticket_id, intent, key_issues(非空数组), need_clarification 的 JSON。",
        response_json=True,
    )
    try:
      parsed = json.loads(_strip_fence(raw_outline))
      valid_schema = (
          isinstance(parsed, dict)
          and bool(parsed.get("intent"))
          and isinstance(parsed.get("key_issues"), list)
          and len(parsed["key_issues"]) > 0
          and not force_gate_fail
      )
    except Exception:  # noqa: BLE001
      valid_schema = False

    if valid_schema:
      outline = parsed
      gate_passed = True
      break

  if not gate_passed:
    outline = {
        "ticket_id": ticket["id"],
        "intent": "fallback_outline",
        "key_issues": ticket.get("required_points", []),
        "need_clarification": ticket["category"] == "ambiguous_edge",
    }

  writer_tier = "pro" if len(ticket["text"]) > 110 else "mini"
  write_prompt = (
      f"工单ID: {ticket['id']}\n已核验结构化大纲: {json.dumps(outline, ensure_ascii=False)}\n"
      f"必答要素: {'、'.join(ticket['required_points'])}\n"
      f"禁语红线: {'、'.join(ticket['forbidden_phrases'])}\n"
      f"原始工单: {ticket['text']}"
  )
  reply, _ = llm(
      write_prompt,
      tracker,
      tier=writer_tier,
      system="[MODE:CHAIN_WRITE] 请严格依据已验证大纲与必答要素撰写专业客服回复（40-260字）。",
  )
  ev = evaluate_reply_quality(ticket, reply)
  return {
      "ticket_id": ticket["id"],
      "reply": reply,
      "passed": ev["passed"],
      "attempts_used": attempts_used,
      "gate_passed": gate_passed,
      "eval": ev,
  }


def run_routing(ticket: dict[str, Any], tracker: BenchmarkTracker) -> dict[str, Any]:
  """模式 2（难度路由）：小模型分流简单咨询，长投诉升级旗舰模型，边界模糊件走澄清兜底分支。"""
  raw_route, _ = llm(
      f"工单ID: {ticket['id']}\n内容: {ticket['text']}",
      tracker,
      tier="mini",
      system=(
          "[MODE:ROUTER] 将工单分类为 simple_faq、complex_complaint、ambiguous_edge 或 other_fallback，"
          "输出 JSON: {\"route\": \"...\", \"reason\": \"...\"}"
      ),
      response_json=True,
  )
  try:
    route_obj = json.loads(_strip_fence(raw_route))
    route = str(route_obj.get("route", "other_fallback"))
  except Exception:  # noqa: BLE001
    route = "other_fallback"

  if route not in ("simple_faq", "complex_complaint", "ambiguous_edge", "other_fallback"):
    route = "other_fallback"

  if route == "simple_faq":
    reply, _ = llm(
        f"工单ID: {ticket['id']}\n要素: {'、'.join(ticket['required_points'])}\n问题: {ticket['text']}",
        tracker,
        tier="mini",
        system="[MODE:ROUTE_FAQ] 简洁准确解答产品规则与操作路径。",
    )
  elif route == "complex_complaint":
    reply, _ = llm(
        f"工单ID: {ticket['id']}\n必答要素: {'、'.join(ticket['required_points'])}\n"
        f"严禁越权承诺: {'、'.join(ticket['forbidden_phrases'])}\n长投诉全文:\n{ticket['text']}",
        tracker,
        tier="pro",
        system="[MODE:ROUTE_COMPLAINT] 逐段回应企业客户多诉求，安抚情绪并严守 SLA 合同边界。",
    )
  else:
    # ambiguous_edge 与 other_fallback 统一进入安全追问澄清模板分支，严禁盲目承诺已修改后台
    reply, _ = llm(
        f"工单ID: {ticket['id']}\n需引导补充信息: {'、'.join(ticket['required_points'])}\n原话: {ticket['text']}",
        tracker,
        tier="mini",
        system="[MODE:ROUTE_CLARIFY] 工单信息缺失，请礼貌列出需客户补充的定位要素，严禁臆测或声称已后台修改完毕。",
    )

  ev = evaluate_reply_quality(ticket, reply)
  return {
      "ticket_id": ticket["id"],
      "route": route,
      "reply": reply,
      "passed": ev["passed"],
      "eval": ev,
  }


def _run_three_voter_audit(draft: str, tracker: BenchmarkTracker, max_workers: int) -> dict[str, Any]:
  """三视角并行审校草稿是否含越权退款承诺，对比 majority_vote 与 any_hit 合并策略。"""
  voter_configs = [
      ("legal_redline", "[MODE:VOTER_LEGAL] 法务红线视角：检查回复草稿是否含任何退赔或抵扣承诺敏感词，输出 JSON {\"flagged\": bool}"),
      ("finance_sla", "[MODE:VOTER_FINANCE] 财务制度视角：检查回复草稿是否越权承诺现金退一赔三或双倍退款，输出 JSON {\"flagged\": bool}"),
      ("ops_policy", "[MODE:VOTER_OPS] 客服规范视角：检查回复草稿是否违规私自拍板退款或未核实改数据，输出 JSON {\"flagged\": bool}"),
  ]

  def _call_voter(cfg: tuple[str, str]) -> tuple[str, bool, float]:
    name, sys_prompt = cfg
    raw_vote, sim_ms = llm(
        f"待审客服草稿：\n{draft}",
        tracker,
        tier="mini",
        system=sys_prompt,
        response_json=True,
        count_latency=False,
    )
    try:
      flagged = bool(json.loads(_strip_fence(raw_vote)).get("flagged", False))
    except Exception:  # noqa: BLE001
      flagged = False
    return name, flagged, sim_ms

  with ThreadPoolExecutor(max_workers=min(max_workers, 3)) as pool:
    results = list(pool.map(_call_voter, voter_configs))

  tracker.add_parallel_batch_latency([r[2] for r in results], max_workers=min(max_workers, 3))
  votes = {name: flagged for name, flagged, _ in results}
  hit_count = sum(1 for v in votes.values() if v)
  return {
      "votes": votes,
      "majority_vote": hit_count >= 2,
      "any_hit": hit_count >= 1,
  }


def run_parallel_vote(
    ticket: dict[str, Any],
    tracker: BenchmarkTracker,
    *,
    max_workers: int = 5,
) -> dict[str, Any]:
  """模式 3（并行分段 + 投票审校）：5 并发上限分段提炼长投诉，并用三视角投票审校退款承诺。"""
  capped_workers = min(max(1, int(max_workers)), 5)
  segments = [p.strip() for p in ticket["text"].split("\n\n") if p.strip()] or [ticket["text"].strip()]

  def _extract_seg(idx_seg: tuple[int, str]) -> tuple[int, str, float]:
    idx, seg_text = idx_seg
    summary, sim_ms = llm(
        f"工单 {ticket['id']} 第 {idx} 段：\n{seg_text}",
        tracker,
        tier="mini",
        system="[MODE:PARALLEL_SEGMENT] 用一句话提取本段客户核心诉求与风险点。",
        count_latency=False,
    )
    return idx, summary, sim_ms

  if len(segments) > 1:
    with ThreadPoolExecutor(max_workers=capped_workers) as pool:
      seg_outputs = list(pool.map(_extract_seg, enumerate(segments, start=1)))
    tracker.add_parallel_batch_latency([item[2] for item in seg_outputs], max_workers=capped_workers)
    merged_notes = "\n".join(f"- {item[1]}" for item in sorted(seg_outputs, key=lambda x: x[0]))
  else:
    merged_notes = f"- 单段诉求：{segments[0]}"

  synth_tier = "pro" if len(segments) >= 3 else "mini"
  draft, _ = llm(
      f"工单ID: {ticket['id']}\n分段汇总:\n{merged_notes}\n"
      f"必答要素: {'、'.join(ticket['required_points'])}\n禁语: {'、'.join(ticket['forbidden_phrases'])}",
      tracker,
      tier=synth_tier,
      system="[MODE:PARALLEL_SYNTH] 汇总各分段诉求生成完整合规客服回复。",
  )

  audit = _run_three_voter_audit(draft, tracker, max_workers=capped_workers)
  final_reply = draft
  # 若多数投票判定存在真实越权退赔承诺，执行安全脱敏改写
  if audit["majority_vote"]:
    final_reply, _ = llm(
        f"工单ID: {ticket['id']}\n原草稿存在越权赔付风险，请保留必答要素（{'、'.join(ticket['required_points'])}）并移除违规承诺：\n{draft}",
        tracker,
        tier="mini",
        system="[MODE:PARALLEL_SAFE_REWRITE] 移除任何直接退赔承诺，改为按 SLA 与财务流程核定。",
    )

  ev = evaluate_reply_quality(ticket, final_reply)
  return {
      "ticket_id": ticket["id"],
      "reply": final_reply,
      "passed": ev["passed"],
      "max_workers_configured": capped_workers,
      "segments_processed": len(segments),
      "votes": audit["votes"],
      "majority_vote": audit["majority_vote"],
      "any_hit": audit["any_hit"],
      "eval": ev,
  }


def run_evaluator_loop(
    ticket: dict[str, Any],
    tracker: BenchmarkTracker,
    *,
    max_rounds: int = 3,
    strict_rubric: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """模式 4（评估-优化循环）：生成 -> 评估清单提修改意见 -> 定向修订，硬编码最多 3 轮上限！"""
  hard_capped_rounds = min(max(1, int(max_rounds)), 3)
  draft = ""
  ev: dict[str, Any] = {"passed": False, "feedback": ""}
  rounds_used = 0
  base_tier = "pro" if ticket["category"] == "complex_complaint" else "mini"

  for round_idx in range(1, hard_capped_rounds + 1):
    rounds_used = round_idx
    if round_idx == 1:
      draft, _ = llm(
          f"工单ID: {ticket['id']}\n工单原文:\n{ticket['text']}",
          tracker,
          tier=base_tier,
          system="[MODE:EVAL_DRAFT] 请撰写初版客服回复草稿。",
      )
    else:
      critic_note, _ = llm(
          f"工单ID: {ticket['id']}\n当前草稿: {draft}\n未过关原因: {ev['feedback']}",
          tracker,
          tier="mini",
          system="[MODE:EVAL_CRITIC] 根据规则校验结果给出精炼改写指令。",
      )
      draft, _ = llm(
          f"工单ID: {ticket['id']}\n上轮草稿: {draft}\n"
          f"评估修改要求: {ev['feedback']} ({critic_note})\n"
          f"必答要素清单: {'、'.join(ticket['required_points'])}",
          tracker,
          tier=base_tier,
          system="[MODE:EVAL_REFINE] 严格按修改要求补齐遗漏要素并控制字数。",
      )

    ev = evaluate_reply_quality(ticket, draft, strict_rubric=strict_rubric)
    if ev["passed"]:
      break

  return {
      "ticket_id": ticket["id"],
      "reply": draft,
      "passed": ev["passed"],
      "rounds_used": rounds_used,
      "halted_by_cap": (not ev["passed"]) and rounds_used == hard_capped_rounds,
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
