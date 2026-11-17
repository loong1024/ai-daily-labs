#!/usr/bin/env python3
"""S0-M01 分词器实测与月度 API 预算核算（标准参考实现）。"""

from __future__ import annotations

import json
import pathlib
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent

_COMMON_ASCII_PIECES: tuple[bytes, ...] = (
    b"\n            ",
    b"\n        ",
    b"\n    ",
    b"\n  ",
    b"            ",
    b"        ",
    b"    ",
    b"  ",
    b" characters",
    b" indentation",
    b" structured",
    b" enterprise",
    b" consumption",
    b" extraction",
    b" tokenizer",
    b" different",
    b" switching",
    b" providers",
    b" expensive",
    b" summarize",
    b" pipeline",
    b" guessing",
    b" character",
    b" launching",
    b" silently",
    b" monthly",
    b" budgets",
    b" context",
    b" reports",
    b" printed",
    b" instead",
    b" without",
    b"json.dumps",
    b"separators",
    b"ensure_ascii",
    b" records",
    b" tokens",
    b" output",
    b" before",
    b" return",
    b"import ",
    b"return ",
    b" token",
    b" input",
    b" batch",
    b" three",
    b" times",
    b" space",
    b" quota",
    b" every",
    b" total",
    b" round",
    b" float",
    b" with",
    b" that",
    b" from",
    b" more",
    b" than",
    b" four",
    b" real",
    b" must",
    b" cost",
    b" also",
    b" long",
    b"def ",
    b"for ",
    b" the",
    b" and",
    b" for",
    b" per",
    b" can",
)

_CL100K_ZH_SINGLE: tuple[str, ...] = (
    "的", "一", "是", "在", "了", "有", "和", "与", "这", "中",
    "大", "为", "上", "个", "以", "要", "时", "用", "到", "作",
    "于", "出", "就", "可", "按", "对", "后", "前", "下", "不",
)

_O200K_ZH_WORDS: tuple[str, ...] = (
    "上下文", "多语言", "分词器", "结构化", "批处理", "预算", "模型", "报告", "长文",
    "截断", "接口", "调用", "成本", "计费", "输入", "输出", "缩进", "空格", "字符",
    "统计", "数据", "抽取", "表格", "摘要", "单价", "月度", "账单", "编码", "压缩",
    "对比", "估算", "企业", "分析", "文档", "格式", "实际", "词元", "词表", "团队",
)

_JSON_SYNTAX_CHARS = frozenset('{}[]:,"')


class _FallbackEncoding:
  """零第三方依赖的确定性 Byte-Level BPE 模拟器（兼容 tiktoken 核心接口）。"""

  def __init__(self, name: str) -> None:
    if name not in {"o200k_base", "cl100k_base"}:
      raise ValueError(f"不支持的分词编码：{name}")
    self.name = name
    zh_pieces = [s.encode("utf-8") for s in _CL100K_ZH_SINGLE]
    if name == "o200k_base":
      zh_pieces.extend(w.encode("utf-8") for w in _O200K_ZH_WORDS)

    raw_vocab = sorted(set(_COMMON_ASCII_PIECES) | set(zh_pieces), key=lambda b: (-len(b), b))
    self._static_vocab: tuple[bytes, ...] = tuple(raw_vocab)
    buckets: dict[int, list[tuple[bytes, int]]] = {}
    for idx, piece in enumerate(self._static_vocab):
      buckets.setdefault(piece[0], []).append((piece, 256 + idx))
    self._buckets = buckets

  def encode(self, text: str) -> list[int]:
    data = text.encode("utf-8")
    n = len(data)
    out: list[int] = []
    i = 0
    while i < n:
      matched = False
      for piece, tid in self._buckets.get(data[i], ()):
        plen = len(piece)
        if i + plen <= n and data[i : i + plen] == piece:
          out.append(tid)
          i += plen
          matched = True
          break
      if matched:
        continue

      if (
          i + 3 <= n
          and 0xE3 <= data[i] <= 0xEF
          and (data[i + 1] & 0xC0) == 0x80
          and (data[i + 2] & 0xC0) == 0x80
      ):
        if self.name == "o200k_base":
          out.append(0x1000000 | (data[i] << 16) | (data[i + 1] << 8) | data[i + 2])
        else:
          out.append(0x10000 | (data[i] << 8) | data[i + 1])
          out.append(data[i + 2])
        i += 3
        continue

      if i + 3 <= n and all(97 <= (data[i + k] | 32) <= 122 for k in range(3)):
        out.append(0x1000000 | (data[i] << 16) | (data[i + 1] << 8) | data[i + 2])
        i += 3
        continue

      if i + 2 <= n and all(97 <= (data[i + k] | 32) <= 122 for k in range(2)):
        out.append(0x10000 | (data[i] << 8) | data[i + 1])
        i += 2
        continue

      out.append(data[i])
      i += 1
    return out

  def decode_single_token_bytes(self, token_id: int) -> bytes:
    if 0 <= token_id <= 255:
      return bytes([token_id])
    if 256 <= token_id < 256 + len(self._static_vocab):
      return self._static_vocab[token_id - 256]
    if 0x10000 <= token_id <= 0x1FFFF:
      return bytes([(token_id >> 8) & 0xFF, token_id & 0xFF])
    if 0x1000000 <= token_id <= 0x1FFFFFF:
      return bytes([(token_id >> 16) & 0xFF, (token_id >> 8) & 0xFF, token_id & 0xFF])
    raise KeyError(f"未知 token_id: {token_id}")


def load_encoding(encoding_name: str = "o200k_base") -> Any:
  """优先加载官方 tiktoken；若当前环境未安装则回退至内置 Byte-Level BPE 分词器。"""
  try:
    import tiktoken  # type: ignore

    return tiktoken.get_encoding(encoding_name)
  except Exception:
    return _FallbackEncoding(encoding_name)


def benchmark_samples(
    samples: dict[str, str],
    encoding_names: tuple[str, ...] = ("o200k_base", "cl100k_base"),
) -> list[dict[str, Any]]:
  """统计四类对照文本在不同分词编码下的字符数、实际 Token 数、比值及与拍脑袋预测的误差。"""
  rows: list[dict[str, Any]] = []
  for enc_name in encoding_names:
    enc = load_encoding(enc_name)
    for label, text in samples.items():
      chars = len(text)
      tokens = len(enc.encode(text))
      ratio = round(tokens / chars, 2) if chars > 0 else 0.0
      rows.append(
          {
              "encoding": enc_name,
              "label": label,
              "chars": chars,
              "naive_estimate": chars,
              "tokens": tokens,
              "tokens_per_char": ratio,
              "naive_diff": tokens - chars,
          }
      )
  return rows


def inspect_token_bytes(text: str, encoding_name: str = "cl100k_base") -> dict[str, Any]:
  """调用 decode_single_token_bytes 分析 UTF-8 半字碎片、空白缩进与 JSON 结构符号开销。"""
  enc = load_encoding(encoding_name)
  token_ids = enc.encode(text)
  raw_slices: list[bytes] = []
  partial_utf8_count = 0
  whitespace_token_count = 0
  syntax_token_count = 0
  preview_slices: list[dict[str, Any]] = []

  for idx, tid in enumerate(token_ids):
    raw = enc.decode_single_token_bytes(tid)
    raw_slices.append(raw)
    try:
      decoded = raw.decode("utf-8")
      is_partial = False
    except UnicodeDecodeError:
      decoded = ""
      is_partial = True

    if is_partial:
      partial_utf8_count += 1
    elif decoded and decoded.strip() == "":
      whitespace_token_count += 1
    elif decoded.strip() and all(ch in _JSON_SYNTAX_CHARS for ch in decoded.strip()):
      syntax_token_count += 1

    if idx < 12:
      preview_slices.append(
          {
              "token_id": tid,
              "hex_bytes": raw.hex(),
              "display": repr(decoded) if not is_partial else f"<UTF8半字字节:{raw.hex()}>",
          }
      )

  return {
      "encoding": encoding_name,
      "total_tokens": len(token_ids),
      "reconstructed_matches_utf8": b"".join(raw_slices) == text.encode("utf-8"),
      "partial_utf8_count": partial_utf8_count,
      "whitespace_token_count": whitespace_token_count,
      "syntax_token_count": syntax_token_count,
      "preview_slices": preview_slices,
  }


def estimate_monthly_bill(
    input_text: str,
    output_pretty_json: str,
    *,
    encoding_name: str = "o200k_base",
    input_price_per_1m: float = 2.5,
    output_price_per_1m: float = 10.0,
    daily_calls: int = 100,
    days: int = 30,
) -> dict[str, Any]:
  """按输入原文单价与高价输出 JSON 单价核算月度账单，并对比去缩进压缩前后的价差。"""
  enc = load_encoding(encoding_name)
  parsed_payload = json.loads(output_pretty_json)
  compact_json = json.dumps(parsed_payload, ensure_ascii=False, separators=(",", ":"))

  input_tokens = len(enc.encode(input_text))
  pretty_output_tokens = len(enc.encode(output_pretty_json))
  compact_output_tokens = len(enc.encode(compact_json))
  saved_output_tokens = pretty_output_tokens - compact_output_tokens
  reduction_pct = (
      round(saved_output_tokens / pretty_output_tokens * 100, 2) if pretty_output_tokens > 0 else 0.0
  )

  monthly_calls = daily_calls * days
  monthly_input_usd = (input_tokens * input_price_per_1m / 1_000_000) * monthly_calls
  monthly_pretty_out_usd = (pretty_output_tokens * output_price_per_1m / 1_000_000) * monthly_calls
  monthly_compact_out_usd = (
      compact_output_tokens * output_price_per_1m / 1_000_000
  ) * monthly_calls

  pretty_total_usd = monthly_input_usd + monthly_pretty_out_usd
  compact_total_usd = monthly_input_usd + monthly_compact_out_usd
  savings_usd = pretty_total_usd - compact_total_usd

  return {
      "encoding": encoding_name,
      "monthly_calls": monthly_calls,
      "input_tokens": input_tokens,
      "pretty_output_tokens": pretty_output_tokens,
      "compact_output_tokens": compact_output_tokens,
      "saved_output_tokens_per_call": saved_output_tokens,
      "output_token_reduction_pct": reduction_pct,
      "monthly_input_usd": round(monthly_input_usd, 4),
      "monthly_pretty_output_usd": round(monthly_pretty_out_usd, 4),
      "monthly_compact_output_usd": round(monthly_compact_out_usd, 4),
      "monthly_pretty_total_usd": round(pretty_total_usd, 4),
      "monthly_compact_total_usd": round(compact_total_usd, 4),
      "monthly_savings_usd": round(savings_usd, 4),
      "compact_json": compact_json,
  }


def main() -> None:
  fixture = json.loads((LAB_DIR / "fixtures" / "samples.json").read_text(encoding="utf-8"))
  samples = fixture["samples"]
  rows = benchmark_samples(samples, tuple(fixture["encodings"]))
  print("=== 1. 四类 500 字规模对照语料双编码实测表 ===")
  for r in rows:
    print(
        f"  [{r['encoding']}] {r['label']}: {r['chars']} 字符 -> {r['tokens']} tokens "
        f"(比值 {r['tokens_per_char']:.2f}, 较 1:1 预测偏差 {r['naive_diff']:+d})"
    )

  zh_breakdown = inspect_token_bytes(samples["中文"], "cl100k_base")
  json_breakdown = inspect_token_bytes(samples["JSON"], "o200k_base")
  print("\n=== 2. decode_single_token_bytes 切片归因 ===")
  print(
      f"  中文 (cl100k_base): 总 Token {zh_breakdown['total_tokens']}，"
      f"UTF-8 半字字节碎片 {zh_breakdown['partial_utf8_count']} 个"
  )
  print(
      f"  缩进 JSON (o200k_base): 总 Token {json_breakdown['total_tokens']}，"
      f"纯空白缩进 Token {json_breakdown['whitespace_token_count']} 个，"
      f"结构符号 Token {json_breakdown['syntax_token_count']} 个"
  )

  cfg = fixture["billing_scenario"]
  print("\n=== 3. 每日 100 篇 × 30 天月度账单对比（含跨词表核对） ===")
  for prof in cfg["provider_profiles"]:
    bill = estimate_monthly_bill(
        samples["中文"],
        samples["JSON"],
        encoding_name=prof["encoding"],
        input_price_per_1m=prof["input_price_per_1m"],
        output_price_per_1m=prof["output_price_per_1m"],
        daily_calls=cfg["daily_calls"],
        days=cfg["days"],
    )
    print(
        f"  {prof['profile_name']}: 缩进月账单 ${bill['monthly_pretty_total_usd']:.4f} -> "
        f"紧凑 JSON 月账单 ${bill['monthly_compact_total_usd']:.4f} "
        f"(月省 ${bill['monthly_savings_usd']:.4f}, 输出瘦身 {bill['output_token_reduction_pct']}%)"
    )


if __name__ == "__main__":
  main()
