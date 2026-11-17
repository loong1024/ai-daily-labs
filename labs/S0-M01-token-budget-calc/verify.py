#!/usr/bin/env python3
"""S0-M01 tiktoken 实测中英与代码账单 自动化验收脚本。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import ModuleType

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_target_module(py_path: pathlib.Path) -> ModuleType:
  spec = importlib.util.spec_from_file_location("aid_s0_m01_target", py_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{py_path}")
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def main() -> None:
  v = LabVerifier("S0-M01", "长文总被截断或超支？tiktoken 实测中英与代码账单")
  py_path = target_file(LAB_DIR, "starter.py", "solution.py")
  fixture_path = LAB_DIR / "fixtures" / "samples.json"

  try:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    samples: dict[str, str] = fixture["samples"]
    mod = _load_target_module(py_path)
    enc_o200k = mod.load_encoding("o200k_base")
    enc_cl100k = mod.load_encoding("cl100k_base")
    roundtrip_ok = all(
        b"".join(enc.decode_single_token_bytes(t) for t in enc.encode(txt)) == txt.encode("utf-8")
        for enc in (enc_o200k, enc_cl100k)
        for txt in samples.values()
    )
  except Exception as exc:
    v.check("模块加载与分词器字节无损往返验证", False, f"加载模块或调用 load_encoding 报错：{exc}")
    v.finish()
    return

  v.check(
      "四类 500 字对照语料就绪且双编码器支持字节级无损还原",
      set(samples.keys()) == {"中文", "英文", "代码", "JSON"} and roundtrip_ok,
      "确保 load_encoding('o200k_base') 与 load_encoding('cl100k_base') 的 encode / decode_single_token_bytes 能无损还原 UTF-8 字节。",
  )

  try:
    rows = mod.benchmark_samples(samples, ("o200k_base", "cl100k_base"))
    row_map = {(r["encoding"], r["label"]): r for r in rows}
    expected_ok = len(row_map) == 8
    for enc_name, enc_obj in (("o200k_base", enc_o200k), ("cl100k_base", enc_cl100k)):
      for label, txt in samples.items():
        r = row_map.get((enc_name, label), {})
        real_tokens = len(enc_obj.encode(txt))
        real_chars = len(txt)
        if (
            r.get("tokens") != real_tokens
            or r.get("chars") != real_chars
            or r.get("naive_diff") != real_tokens - real_chars
            or abs(float(r.get("tokens_per_char", -1.0)) - round(real_tokens / real_chars, 2))
            > 0.01
        ):
          expected_ok = False
    zh_cl100k = row_map.get(("cl100k_base", "中文"), {}).get("tokens", 0)
    zh_o200k = row_map.get(("o200k_base", "中文"), {}).get("tokens", 0)
    en_ratio = float(row_map.get(("o200k_base", "英文"), {}).get("tokens_per_char", 1.0))
    domain_ok = zh_cl100k > len(samples["中文"]) and zh_o200k < zh_cl100k and en_ratio < 0.45
    bench_ok = expected_ok and domain_ok
  except Exception as exc:
    bench_ok = False

  v.check(
      "双编码（o200k_base vs cl100k_base）四类样本实测比值与拍脑袋误差核算",
      bench_ok,
      "补全 benchmark_samples()：对每种编码调用 enc.encode(text) 统计真实 tokens、tokens_per_char（保留两位小数）与 naive_diff = tokens - chars，切勿直接用 len(text) 冒充 Token 数。",
  )

  try:
    zh_info = mod.inspect_token_bytes(samples["中文"], "cl100k_base")
    json_info = mod.inspect_token_bytes(samples["JSON"], "o200k_base")
    inspect_ok = (
        bool(zh_info.get("reconstructed_matches_utf8"))
        and bool(json_info.get("reconstructed_matches_utf8"))
        and int(zh_info.get("partial_utf8_count", 0)) >= 50
        and int(json_info.get("whitespace_token_count", 0)) >= 10
        and int(json_info.get("syntax_token_count", 0)) >= 10
    )
  except Exception:
    inspect_ok = False

  v.check(
      "decode_single_token_bytes 切片归因（检出中文 UTF-8 半字碎片与 JSON 空白/结构开销）",
      inspect_ok,
      "补全 inspect_token_bytes()：遍历 enc.encode(text) 并调用 decode_single_token_bytes()，准确统计无法单独解码 UTF-8 的半字字节数 partial_utf8_count、纯空白缩进数 whitespace_token_count 与 JSON 结构符号数 syntax_token_count。",
  )

  try:
    cfg = fixture["billing_scenario"]
    bill = mod.estimate_monthly_bill(
        samples["中文"],
        samples["JSON"],
        encoding_name=cfg["default_encoding"],
        input_price_per_1m=cfg["input_price_per_1m"],
        output_price_per_1m=cfg["output_price_per_1m"],
        daily_calls=cfg["daily_calls"],
        days=cfg["days"],
    )
    compact_text = str(bill.get("compact_json", ""))
    semantic_same = json.loads(compact_text) == json.loads(samples["JSON"])
    in_tok = len(enc_o200k.encode(samples["中文"]))
    pretty_tok = len(enc_o200k.encode(samples["JSON"]))
    compact_tok = len(enc_o200k.encode(compact_text))
    calls = cfg["daily_calls"] * cfg["days"]
    exp_in_usd = (in_tok * cfg["input_price_per_1m"] / 1_000_000) * calls
    exp_pretty_out_usd = (pretty_tok * cfg["output_price_per_1m"] / 1_000_000) * calls
    exp_compact_out_usd = (compact_tok * cfg["output_price_per_1m"] / 1_000_000) * calls
    exp_pretty_total = exp_in_usd + exp_pretty_out_usd
    exp_compact_total = exp_in_usd + exp_compact_out_usd
    exp_savings = exp_pretty_total - exp_compact_total

    bill_ok = (
        semantic_same
        and compact_tok < pretty_tok
        and bill.get("saved_output_tokens_per_call") == pretty_tok - compact_tok
        and abs(float(bill.get("monthly_input_usd", -1.0)) - exp_in_usd) < 1e-3
        and abs(float(bill.get("monthly_pretty_output_usd", -1.0)) - exp_pretty_out_usd) < 1e-3
        and abs(float(bill.get("monthly_compact_output_usd", -1.0)) - exp_compact_out_usd) < 1e-3
        and abs(float(bill.get("monthly_pretty_total_usd", -1.0)) - exp_pretty_total) < 1e-3
        and abs(float(bill.get("monthly_compact_total_usd", -1.0)) - exp_compact_total) < 1e-3
        and abs(float(bill.get("monthly_savings_usd", -1.0)) - exp_savings) < 1e-3
        and float(bill.get("monthly_savings_usd", 0.0)) > 0
    )
  except Exception:
    bill_ok = False

  v.check(
      "输入/输出差异化费率月度账单与 JSON 去缩进压缩省钱复核",
      bill_ok,
      "补全 estimate_monthly_bill()：用 json.dumps(..., ensure_ascii=False, separators=(',', ':')) 压缩输出 JSON，严格区分 input_price_per_1m 与更高单价的 output_price_per_1m 核算 30 天月度总账单及压缩后净省金额。",
  )

  v.finish()


if __name__ == "__main__":
  main()
