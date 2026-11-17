#!/usr/bin/env python3
from __future__ import annotations
import pathlib, sys
LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

import csv
import importlib.util
import os
import tempfile
from types import ModuleType


def _load_target_module() -> ModuleType:
  path = target_file(LAB_DIR, "starter.py", "solution.py")
  mod_name = f"s0_m05_{path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标文件：{path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> int:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S0-M05", "手工复制粘贴太慢？60 分钟写个批量抽表小脚本")
  target_path = target_file(LAB_DIR, "starter.py", "solution.py")
  input_csv = LAB_DIR / "fixtures" / "customer_feedback_15.csv"

  try:
    mod = _load_target_module()
    source_text = target_path.read_text(encoding="utf-8")
  except Exception as exc:
    v.check("加载目标模块", False, f"模块导入异常（{exc}），请先修复语法错误。")
    return v.finish()

  # 验收项 1：无硬编码密钥 & 缺失环境变量/401 错误立即提示退出（零无效重试）
  try:
    no_hardcoded_secret = (
        "HARDCODED_PLACEHOLDER_KEY" not in source_text
        and "FAKE_TEST_KEY_DO_NOT_USE_12345" not in source_text
        and "os.environ" in source_text
    )

    saved_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
      missing_env_blocked = False
      try:
        mod.load_config_from_env(allow_mock_fallback=False)
      except mod.AuthConfigError as err:
        missing_env_blocked = "401" in str(err) or "OPENAI_API_KEY" in str(err)
    finally:
      if saved_key is not None:
        os.environ["OPENAI_API_KEY"] = saved_key

    sleep_401: list[float] = []
    bad_cfg = mod.BatchConfig(api_key="FAKE_INVALID_KEY_401_DO_NOT_USE")
    transport_401 = mod.create_mock_transport()
    fast_401_blocked = False
    try:
      mod.call_with_retry(
          {"feedback_id": "FB-001", "content": "测试鉴权"},
          bad_cfg,
          transport_401,
          sleep_fn=sleep_401.append,
      )
    except mod.AuthConfigError as err:
      fast_401_blocked = ("401" in str(err)) and (len(sleep_401) == 0)

    v.check(
        "环境变量安全鉴权（无硬编码 Key）与 401 错误零重试立即阻断",
        bool(no_hardcoded_secret and missing_env_blocked and fast_401_blocked),
        "请移除 starter.py 中的 HARDCODED_PLACEHOLDER_KEY 硬编码常量，在 load_config_from_env 中严格读取 OPENAI_API_KEY，"
        "并在 call_with_retry 中遇到 status_code == 401 时立即抛出包含 '401' 提示的 AuthConfigError（不要重试）。",
    )
  except Exception as exc:
    v.check(
        "环境变量安全鉴权（无硬编码 Key）与 401 错误零重试立即阻断",
        False,
        f"401 鉴权分支未按预期转换为 AuthConfigError（捕获到 {type(exc).__name__}: {exc}），请在 call_with_retry 中区分 401 与 429。",
    )

  # 验收项 2：模拟前 2 次返回 429 异常时指数退避等待并在第 3 次重试成功 + Retry-After 遵循
  try:
    sleep_delays: list[float] = []
    cfg_retry = mod.BatchConfig(
        api_key="FAKE_TEST_KEY_DO_NOT_USE_12345",
        max_retries=3,
        base_backoff_sec=0.5,
    )
    transport_429 = mod.create_mock_transport(fail_429_plan={"FB-003": 2})
    resp_ok = mod.call_with_retry(
        {"feedback_id": "FB-003", "content": "希望能支持每日工单自动推送"},
        cfg_retry,
        transport_429,
        sleep_fn=sleep_delays.append,
    )

    sleep_ra: list[float] = []
    transport_ra = mod.create_mock_transport(fail_429_plan={"FB-005": 1}, retry_after_sec=1.75)
    mod.call_with_retry(
        {"feedback_id": "FB-005", "content": "主管理员两步验证重置"},
        cfg_retry,
        transport_ra,
        sleep_fn=sleep_ra.append,
    )

    backoff_ok = (
        isinstance(resp_ok, dict)
        and "content" in resp_ok
        and len(sleep_delays) == 2
        and sleep_delays[0] >= 0.5
        and sleep_delays[1] > sleep_delays[0]
        and sleep_ra == [1.75]
    )
    v.check(
        "429 限流指数退避重试（前 2 次 429 后第 3 次成功）及 Retry-After 响应头遵循",
        bool(backoff_ok),
        "请完善 call_with_retry：捕获 status_code 为 429/5xx 的 ApiHttpError，优先按 retry_after 等待，"
        "无 retry_after 时按 base_backoff_sec * (2 ** attempt) 指数退避调用 sleep_fn 并重试。",
    )
  except Exception as exc:
    v.check(
        "429 限流指数退避重试（前 2 次 429 后第 3 次成功）及 Retry-After 遵循",
        False,
        f"触发 429 时未完成自动退避重试（捕获到 {type(exc).__name__}: {exc}），请在 call_with_retry 中加入重试循环。",
    )

  # 验收项 3 & 4：15 条全量容错批处理、UTF-8-SIG Excel CSV 导出与 Token 实付账单精确对账
  with tempfile.TemporaryDirectory() as tmp_dir:
    out_csv = pathlib.Path(tmp_dir) / "batch_result.csv"
    cfg_batch = mod.BatchConfig(
        api_key="FAKE_TEST_KEY_DO_NOT_USE_12345",
        input_price_per_1m=0.15,
        output_price_per_1m=0.60,
        max_retries=3,
        base_backoff_sec=0.25,
    )
    batch_transport = mod.create_mock_transport(
        fail_429_plan={"FB-003": 2},
        malformed_ids={"FB-012"},
        code_fence_ids={"FB-009"},
    )

    summary = None
    batch_err: Exception | None = None
    try:
      summary = mod.run_batch_pipeline(
          input_csv,
          out_csv,
          cfg_batch,
          request_fn=batch_transport,
          sleep_fn=lambda _s: None,
      )
    except Exception as exc:
      batch_err = exc

    if batch_err is not None or not isinstance(summary, dict) or not out_csv.is_file():
      v.check(
          "15 条样本全量抽取、代码块剥离/脏 JSON 容错兜底与 UTF-8-SIG Excel 无乱码导出",
          False,
          f"批处理管线中途崩溃或未生成 CSV（{batch_err}）。请完善 parse_extraction_json（剥离 ```json 围栏并捕获 JSONDecodeError 返回错误原因）"
          "及 run_batch_pipeline（使用 encoding='utf-8-sig' 导出全部 15 行）。",
      )
      v.check(
          "前 5 条试跑预算预估与全批 15 条输入/输出 Token 实付账单精确对账",
          False,
          "因批处理尚未跑通全量 15 条，无法核对 Token 账单，请先修复批处理容错逻辑。",
      )
    else:
      raw_bytes = out_csv.read_bytes()
      has_utf8_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
      with out_csv.open("r", encoding="utf-8-sig", newline="") as rf:
        exported_rows = list(csv.DictReader(rf))

      by_id = {r["feedback_id"]: r for r in exported_rows}
      fenced_parsed_ok = by_id.get("FB-009", {}).get("status") == "ok" and bool(
          by_id.get("FB-009", {}).get("category")
      )
      malformed_skipped_ok = by_id.get("FB-012", {}).get("status") == "parse_error" and bool(
          by_id.get("FB-012", {}).get("error")
      )
      comma_escaped_ok = by_id.get("FB-007", {}).get("status") == "ok"

      csv_ok = (
          has_utf8_bom
          and len(exported_rows) == 15
          and summary.get("processed_count") == 15
          and summary.get("success_count") == 14
          and summary.get("failed_count") == 1
          and fenced_parsed_ok
          and malformed_skipped_ok
          and comma_escaped_ok
      )
      v.check(
          "15 条样本全量抽取、代码块剥离/脏 JSON 容错兜底与 UTF-8-SIG Excel 无乱码导出",
          bool(csv_ok),
          "请检查：1) 输出 CSV 必须使用 encoding='utf-8-sig'（含 UTF-8 BOM 头供 Excel 识别）；"
          "2) parse_extraction_json 需剥离 FB-009 的 ```json 围栏并对 FB-012 非法 JSON 返回错误原因而不中断全批（14 成功 + 1 parse_error）。",
      )

      # 独立重算 15 条真实响应的 ground-truth Token 与账单对账
      with input_csv.open("r", encoding="utf-8-sig", newline="") as inf:
        raw_inputs = list(csv.DictReader(inf))
      ref_transport = mod.create_mock_transport(
          malformed_ids={"FB-012"}, code_fence_ids={"FB-009"}
      )
      ref_usages = [ref_transport(r, cfg_batch)["usage"] for r in raw_inputs]
      expected_in = sum(u["prompt_tokens"] for u in ref_usages)
      expected_out = sum(u["completion_tokens"] for u in ref_usages)
      expected_cost = round(
          (expected_in / 1_000_000.0) * cfg_batch.input_price_per_1m
          + (expected_out / 1_000_000.0) * cfg_batch.output_price_per_1m,
          8,
      )
      pilot = summary.get("pilot_estimate") or {}
      expected_pilot_avg_in = round(sum(u["prompt_tokens"] for u in ref_usages[:5]) / 5, 2)

      billing_ok = (
          summary.get("total_prompt_tokens") == expected_in
          and summary.get("total_completion_tokens") == expected_out
          and summary.get("total_tokens") == expected_in + expected_out
          and abs(float(summary.get("total_cost_usd", -1.0)) - expected_cost) < 1e-9
          and pilot.get("pilot_size") == 5
          and abs(float(pilot.get("avg_prompt_tokens", -1.0)) - expected_pilot_avg_in) < 1e-6
          and float(pilot.get("estimated_total_cost_usd", 0.0)) > 0.0
      )
      v.check(
          "前 5 条试跑预算预估与全批 15 条输入/输出 Token 实付账单精确对账",
          bool(billing_ok),
          f"Token 账单对账未通过：期望累计输入 {expected_in}、输出 {expected_out}、实付 ${expected_cost:.8f}，"
          "且 pilot_estimate 需基于前 5 条样本估算均耗与总预算，请完善 estimate_pilot_budget 与 run_batch_pipeline 中的用量累加。",
      )

  return v.finish()


if __name__ == "__main__":
  main()
