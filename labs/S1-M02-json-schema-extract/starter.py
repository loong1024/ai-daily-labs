"""S1-M02 起点代码（待改进基线）：脆弱裸 json.loads + 结论前置 + 缺少业务校验重试。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


@dataclass
class Invoice:
  """TODO: 1) 将 evidence 原文依据字段置于最前；2) 补齐金额>0、合法币种、开票日期<=今天的强校验。"""

  amount: float
  currency: str
  issue_date: str
  vendor: str = "Unknown"

  @classmethod
  def model_validate(
      cls,
      data: dict[str, Any],
      *,
      reference_today: str | None = None,
  ) -> "Invoice":
    del reference_today
    return cls(
        amount=float(data["amount"]),
        currency=str(data["currency"]),
        issue_date=str(data["issue_date"]),
        vendor=str(data.get("vendor", "Unknown")),
    )

  def model_dump(self) -> dict[str, Any]:
    return asdict(self)


def _naive_mock(messages: list[dict[str, str]]) -> str:
  text = messages[-1]["content"]
  if "GitHub Team seat" in text:
    return (
        "好的，为您抽取的发票 JSON 如下：\n```json\n"
        '{"amount": 240.0, "currency": "USD", "issue_date": "2026-03-05", "vendor": "GitHub Inc."}\n```'
    )
  amt_m = re.search(r"(-?\d+\.\d+)", text)
  date_m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
  cur = "USD" if "USD" in text else "CNY"
  return json.dumps({
      "amount": float(amt_m.group(1)) if amt_m else 0.0,
      "currency": cur,
      "issue_date": date_m.group(1) if date_m else "2099-01-01",
      "vendor": "Unknown",
  })


def extract_invoice(
    email_text: str,
    *,
    max_retries: int = 2,
    evidence_first: bool = True,
    reference_today: str | None = None,
) -> tuple[Invoice, list[dict[str, Any]]]:
  """TODO: 改用 Schema 校验入口 + 错误回传 max_retries 自动纠错循环，消除裸 json.loads。"""
  del max_retries, evidence_first
  raw = chat_complete(
      [{"role": "user", "content": f"请从邮件中抽取发票 JSON：\n{email_text}"}],
      mock_fn=_naive_mock,
  )
  parsed = json.loads(raw)
  inv = Invoice.model_validate(parsed, reference_today=reference_today)
  return inv, [{"attempt": 1, "status": "ok", "error": None}]


def compare_evidence_order(samples: list[dict[str, Any]]) -> dict[str, Any]:
  """TODO: 对比 evidence_first=True 与 False 在 20 份样本上的准确率并复盘假阳性样本。"""
  del samples
  return {
      "evidence_first_accuracy": 0.0,
      "conclusion_first_accuracy": 0.0,
      "false_positive_cases": [],
  }
