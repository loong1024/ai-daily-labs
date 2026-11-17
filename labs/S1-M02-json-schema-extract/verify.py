#!/usr/bin/env python3
"""S1-M02 验收脚本：验证强类型 Invoice Schema、业务校验自动重试纠错链路与依据前置对照实验。"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_target_module(path: pathlib.Path) -> Any:
  spec = importlib.util.spec_from_file_location("s1_m02_target_mod", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法为 {path} 创建模块加载器")
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod
  spec.loader.exec_module(mod)
  return mod


def _has_bare_json_loads_in_business_funcs(source_code: str) -> bool:
  tree = ast.parse(source_code)
  for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "extract_invoice":
      for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == "json"
            and sub.func.attr == "loads"
        ):
          return True
  return False


def main() -> None:
  v = LabVerifier("S1-M02", "Instructor 强类型发票抽取与校验重试闭环")
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  samples: list[dict[str, Any]] = json.loads(
      (LAB_DIR / "fixtures" / "invoices.json").read_text(encoding="utf-8")
  )

  try:
    source_code = mod_path.read_text(encoding="utf-8")
    mod = _load_target_module(mod_path)
  except Exception as exc:
    v.check("目标模块可正常导入", False, f"加载 {mod_path.name} 出错：{exc}")
    v.finish()
    return

  extracted_ok_count = 0
  first_err_msg = ""
  retry_logs_by_id: dict[str, list[dict[str, Any]]] = {}

  for item in samples:
    try:
      res = mod.extract_invoice(
          item["email_text"],
          max_retries=2,
          evidence_first=True,
          reference_today="2026-05-20",
      )
      inv, rlog = res if isinstance(res, tuple) else (res, [])
      retry_logs_by_id[item["id"]] = rlog
      ev_val = getattr(inv, "evidence", "")
      valid_obj = (
          isinstance(inv, mod.Invoice)
          and isinstance(ev_val, str)
          and len(ev_val.strip()) >= 6
          and abs(float(inv.amount) - float(item["expected_amount"])) < 1e-6
          and inv.currency == item["expected_currency"]
          and inv.issue_date == item["expected_date"]
      )
      if valid_obj:
        extracted_ok_count += 1
      elif not first_err_msg:
        first_err_msg = (
            f"{item['id']} 字段不匹配或缺少非空 evidence（期望 {item['expected_currency']} "
            f"{item['expected_amount']} @ {item['expected_date']}，实际 {inv!r}）"
        )
    except Exception as exc:
      if not first_err_msg:
        first_err_msg = f"{item['id']} 抛出异常：{exc}"

  v.check(
      f"20 份含噪/含雷样本强类型抽取全通过（当前通过 {extracted_ok_count}/{len(samples)} 份）",
      extracted_ok_count == len(samples) and len(samples) >= 20,
      f"请完善 Invoice 模型与 extract_invoice 抽取重试逻辑（首条失败详情：{first_err_msg}）。",
  )

  validator_blocks_bad = False
  try:
    blocked_cases = 0
    for bad_payload in (
        {
            "evidence": "测试负数金额拦截原句",
            "amount": -50.0,
            "currency": "CNY",
            "issue_date": "2026-03-10",
            "vendor": "A",
        },
        {
            "evidence": "测试未来日期拦截原句",
            "amount": 100.0,
            "currency": "CNY",
            "issue_date": "2099-12-31",
            "vendor": "A",
        },
        {
            "evidence": "测试非法币种拦截原句",
            "amount": 100.0,
            "currency": "EUR",
            "issue_date": "2026-03-10",
            "vendor": "A",
        },
    ):
      try:
        mod.Invoice.model_validate(bad_payload, reference_today="2026-05-20")
      except ValueError:
        blocked_cases += 1
    validator_blocks_bad = blocked_cases == 3
  except Exception:
    validator_blocks_bad = False

  log_future = retry_logs_by_id.get("INV-17", [])
  log_neg = retry_logs_by_id.get("INV-18", [])
  future_retried = (
      len(log_future) >= 2
      and log_future[0].get("status") == "validation_error"
      and log_future[-1].get("status") == "ok"
  )
  neg_retried = (
      len(log_neg) >= 2
      and log_neg[0].get("status") == "validation_error"
      and log_neg[-1].get("status") == "ok"
  )
  v.check(
      "业务规则校验与 max_retries=2 自动纠错闭环（拦截未来日期/非正数金额并捕获重试自愈日志）",
      validator_blocks_bad and future_retried and neg_retried,
      "请在 Invoice.model_validate 中拦截 amount<=0、非法币种与晚于今天的 issue_date，并在 extract_invoice 中把校验报错回传给模型重试（确保 INV-17 与 INV-18 记录 validation_error -> ok 自愈链路）。",
  )

  field_names: list[str] = []
  if dataclasses.is_dataclass(mod.Invoice):
    field_names = [f.name for f in dataclasses.fields(mod.Invoice)]
  elif hasattr(mod.Invoice, "model_fields"):
    field_names = list(mod.Invoice.model_fields.keys())

  evidence_is_first = bool(field_names) and field_names[0] == "evidence"
  try:
    cmp_report = mod.compare_evidence_order(samples)
  except Exception:
    cmp_report = {}

  ev_acc = float(cmp_report.get("evidence_first_accuracy", 0.0))
  conc_acc = float(cmp_report.get("conclusion_first_accuracy", 0.0))
  fp_cases = cmp_report.get("false_positive_cases", [])
  v.check(
      f"“依据前置 vs 结论前置”实测对照与假阳性复盘（前置准确率 {ev_acc:.0%} vs 后置 {conc_acc:.0%}）",
      evidence_is_first and ev_acc >= 0.95 and ev_acc > conc_acc and len(fp_cases) >= 2,
      "请确保 Invoice 第一个字段为 evidence，并实现 compare_evidence_order(samples) 输出字段准确率对比及至少 2 条假阳性样本成因分析。",
  )

  no_bare_loads = not _has_bare_json_loads_in_business_funcs(source_code)
  v.check(
      "淘汰 extract_invoice 中的脆弱裸 json.loads，统一由 Schema 校验器接管反序列化",
      no_bare_loads and hasattr(mod.Invoice, "model_validate_json"),
      "请移除 extract_invoice 内的裸 json.loads(...) 调用，封装 Invoice.model_validate_json 统一处理解析与强类型校验。",
  )

  v.finish()


if __name__ == "__main__":
  main()
