"""S1-M02 标准参考实现：Instructor 风格强类型 Schema + 依据前置 + 校验错误回传重试闭环。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

ALLOWED_CURRENCIES = ("CNY", "USD")


def _extract_json_object_text(raw: str) -> str:
  """剥离模型偶发附带的 Markdown 代码围栏，交由 Schema 统一解析验证。"""
  cleaned = raw.strip()
  fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
  if fence_match:
    return fence_match.group(1).strip()
  start = cleaned.find("{")
  end = cleaned.rfind("}")
  if start != -1 and end != -1 and end > start:
    return cleaned[start : end + 1]
  return cleaned


@dataclass
class Invoice:
  """强类型发票 Schema（严格遵守“先原文依据 evidence，后数值结论 amount”顺序）。"""

  evidence: str
  amount: float
  currency: str
  issue_date: str
  vendor: str

  @classmethod
  def model_validate(
      cls,
      data: dict[str, Any],
      *,
      reference_today: str | None = None,
  ) -> "Invoice":
    if not isinstance(data, dict):
      raise ValueError("发票结构必须是 JSON 对象")

    missing = [
        k for k in ("evidence", "amount", "currency", "issue_date", "vendor") if k not in data
    ]
    if missing:
      raise ValueError(f"缺少必填 Schema 字段: {', '.join(missing)}")

    evidence = str(data["evidence"] or "").strip()
    if len(evidence) < 6:
      raise ValueError("evidence 必须先摘录原文中包含真实发票金额、币种和日期的依据原句")

    try:
      amount = float(data["amount"])
    except (TypeError, ValueError) as exc:
      raise ValueError(f"amount 必须是合法数字，当前值: {data['amount']!r}") from exc
    if amount <= 0:
      raise ValueError(
          f"发票价税合计 amount ({amount}) 必须大于 0；请忽略冲红负数抵扣行，提取重新开具的正数发票金额"
      )

    currency = str(data["currency"] or "").strip().upper()
    if currency not in ALLOWED_CURRENCIES:
      raise ValueError(f"currency 仅允许 {ALLOWED_CURRENCIES}，收到非法枚举: {currency!r}")

    issue_date_str = str(data["issue_date"] or "").strip()
    try:
      parsed_date = datetime.date.fromisoformat(issue_date_str)
    except ValueError as exc:
      raise ValueError(f"issue_date 必须符合 YYYY-MM-DD 格式，收到: {issue_date_str!r}") from exc

    today = (
        datetime.date.fromisoformat(reference_today)
        if reference_today
        else datetime.date.today()
    )
    if parsed_date > today:
      raise ValueError(
          f"开票日期 ({issue_date_str}) 不能晚于今天 ({today.isoformat()})；请忽略 OCR 污损误识别日期，核对税控签章或正文真实开票日期"
      )

    vendor = str(data["vendor"] or "").strip()
    if not vendor:
      raise ValueError("vendor 销方名称不能为空")

    return cls(
        evidence=evidence,
        amount=round(amount, 2),
        currency=currency,
        issue_date=issue_date_str,
        vendor=vendor,
    )

  @classmethod
  def model_validate_json(
      cls,
      raw_text: str,
      *,
      reference_today: str | None = None,
  ) -> "Invoice":
    payload_str = _extract_json_object_text(raw_text)
    decoder = json.JSONDecoder()
    try:
      obj, _ = decoder.raw_decode(payload_str)
    except Exception as exc:
      raise ValueError(f"返回内容不是合法 JSON 对象: {exc}") from exc
    return cls.model_validate(obj, reference_today=reference_today)

  def model_dump(self) -> dict[str, Any]:
    return asdict(self)


def _structured_instructor_mock(messages: list[dict[str, str]]) -> str:
  """离线确定性模拟大模型在依据前置/后置及收到校验错误回传重试时的真实表现。"""
  first_user_msg = messages[0]["content"]
  is_retry = len(messages) > 1
  retry_feedback = messages[-1]["content"] if is_retry else ""
  evidence_first = '"evidence" 字段排在第一位' in first_user_msg or "先摘录 evidence" in first_user_msg

  mail_match = re.search(r"<email>\s*(.*?)\s*</email>", first_user_msg, flags=re.DOTALL)
  email_text = mail_match.group(1) if mail_match else first_user_msg

  vendor = "Default Vendor"
  for pat in (
      r"销方[：:]\s*([^），,。\n]+)",
      r"供应商【([^】]+)】",
      r"Vendor:\s*([A-Za-z0-9 .,&-]+?)(?:）|\n|$)",
      r"from\s+([A-Za-z0-9 .,&-]+?)(?:,|\s+issued|\s+on\s)",
      r"（([^（）]*?(?:公司|中心|仪器|餐饮|商务|铁路|贸易))）",
  ):
    vm = re.search(pat, email_text)
    if vm and vm.group(1).strip():
      vendor = vm.group(1).strip()
      break

  currency = "USD" if "USD" in email_text else "CNY"

  all_dates = re.findall(r"\d{4}-\d{2}-\d{2}", email_text)
  if not all_dates:
    chosen_date = "2026-03-01"
  elif not is_retry:
    chosen_date = all_dates[0]
  elif "不能晚于今天" in retry_feedback and len(all_dates) >= 2:
    chosen_date = all_dates[-1]
  else:
    chosen_date = all_dates[-1]

  signed_amounts = [float(x) for x in re.findall(r"-?\d+\.\d+", email_text)]

  if "-300.00" in email_text and not is_retry:
    chosen_amount = -300.0
    evidence_line = "上月旧票冲红抵扣行显示 CNY -300.00"
  elif is_retry and "必须大于 0" in retry_feedback:
    positives = [a for a in signed_amounts if a > 0]
    chosen_amount = positives[-1] if positives else 880.0
    evidence_line = "本次重新开具的正式正数增值税发票价税合计 CNY 880.00，开票日期 2026-03-20"
  elif not evidence_first and len(signed_amounts) >= 2:
    chosen_amount = signed_amounts[0]
    evidence_line = email_text[:48]
  else:
    clauses = re.split(r"[；;。\n]|(?<!\d)\.(?!\d)", email_text)
    target_clause = email_text
    for cl in clauses:
      if any(
          kw in cl
          for kw in (
              "正式",
              "实开发票",
              "实际消费并开具",
              "实际租金开票",
              "net payable",
              "finalized official invoice",
              "价税合计",
              "Total paid",
              "invoice total",
              "Final billed",
              "total charged",
              "amount due and paid",
          )
      ):
        target_clause = cl.strip()
    clause_nums = re.findall(r"\d+\.\d+", target_clause)
    chosen_amount = float(clause_nums[-1]) if clause_nums else signed_amounts[-1]
    evidence_line = target_clause[:80] if len(target_clause) >= 8 else email_text[:80]

  payload = (
      {
          "evidence": evidence_line,
          "amount": chosen_amount,
          "currency": currency,
          "issue_date": chosen_date,
          "vendor": vendor,
      }
      if evidence_first
      else {
          "amount": chosen_amount,
          "currency": currency,
          "issue_date": chosen_date,
          "vendor": vendor,
          "evidence": evidence_line,
      }
  )
  return json.dumps(payload, ensure_ascii=False)


def extract_invoice(
    email_text: str,
    *,
    max_retries: int = 2,
    evidence_first: bool = True,
    reference_today: str | None = None,
) -> tuple[Invoice, list[dict[str, Any]]]:
  """Instructor 风格强类型抽取器：Schema 锁死 + 依据前置 + 校验错误自动回传重试。"""
  order_instruction = (
      '请严格按顺序先摘录 evidence（含正式开票价税合计、币种与真实开票日期的原句），确保 "evidence" 字段排在第一位，再填写 amount、currency、issue_date、vendor。'
      if evidence_first
      else "请填写 amount、currency、issue_date、vendor、evidence 字段。"
  )
  messages: list[dict[str, str]] = [
      {
          "role": "user",
          "content": (
              "你是一名严谨的财务票据结构化抽取引擎，仅输出符合 Invoice Schema 的 JSON 对象。\n"
              f"{order_instruction}\n"
              "业务约束：currency 仅限 CNY 或 USD；amount 必须大于 0（严禁提取报价、押金、预算上限或冲红负数）；"
              "issue_date 必须为 YYYY-MM-DD 且不得晚于今天。\n"
              f"<email>\n{email_text}\n</email>"
          ),
      }
  ]

  retry_log: list[dict[str, Any]] = []
  last_err: Exception | None = None

  for attempt in range(1, max_retries + 2):
    raw_resp = chat_complete(
        messages,
        mock_fn=_structured_instructor_mock,
        temperature=0.0,
        response_json=True,
    )
    try:
      invoice = Invoice.model_validate_json(raw_resp, reference_today=reference_today)
      retry_log.append({
          "attempt": attempt,
          "status": "ok",
          "raw_output": raw_resp,
          "error": None,
      })
      return invoice, retry_log
    except ValueError as err:
      last_err = err
      retry_log.append({
          "attempt": attempt,
          "status": "validation_error",
          "raw_output": raw_resp,
          "error": str(err),
      })
      if attempt <= max_retries:
        messages.append({"role": "assistant", "content": raw_resp})
        messages.append({
            "role": "user",
            "content": (
                f"Schema 校验未通过：{err}。\n"
                "请重新核对 <email> 原文，修正违规字段后输出完整合法的 JSON 对象。"
            ),
        })

  raise ValueError(f"经过 {max_retries + 1} 次尝试仍未通过 Invoice 校验: {last_err}")


def compare_evidence_order(
    samples: list[dict[str, Any]],
    *,
    reference_today: str = "2026-05-20",
) -> dict[str, Any]:
  """在 20 份样本上对比“依据前置 vs 结论前置”字段全对率，并输出假阳性典型样本成因。"""
  ev_first_hits = 0
  conc_first_hits = 0
  false_positive_cases: list[dict[str, Any]] = []

  for item in samples:
    inv_ev, _ = extract_invoice(
        item["email_text"],
        max_retries=2,
        evidence_first=True,
        reference_today=reference_today,
    )
    inv_conc, _ = extract_invoice(
        item["email_text"],
        max_retries=2,
        evidence_first=False,
        reference_today=reference_today,
    )

    ev_ok = (
        abs(inv_ev.amount - float(item["expected_amount"])) < 1e-6
        and inv_ev.currency == item["expected_currency"]
        and inv_ev.issue_date == item["expected_date"]
    )
    conc_ok = (
        abs(inv_conc.amount - float(item["expected_amount"])) < 1e-6
        and inv_conc.currency == item["expected_currency"]
        and inv_conc.issue_date == item["expected_date"]
    )

    if ev_ok:
      ev_first_hits += 1
    if conc_ok:
      conc_first_hits += 1
    else:
      false_positive_cases.append({
          "id": item["id"],
          "tag": item.get("tag", ""),
          "wrong_amount": inv_conc.amount,
          "expected_amount": item["expected_amount"],
          "reason": (
              "JSON 类型与正数校验虽全部合法（假阳性），但结论前置时模型先抓了邮件前段的原价/押金/框架估算额，"
              "未锚定正式开票价税合计原句。"
          ),
      })

  total = max(len(samples), 1)
  return {
      "total_samples": len(samples),
      "evidence_first_accuracy": round(ev_first_hits / total, 4),
      "conclusion_first_accuracy": round(conc_first_hits / total, 4),
      "false_positive_cases": false_positive_cases,
  }
