#!/usr/bin/env python3
"""S0-M01 分词器实测与月度 API 预算核算（Starter 待补全基线）。"""

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
    # TODO(步骤1)：当前直接用字符长度充当 Token 数（典型拍脑袋错误）！
    # 请调用 enc = load_encoding(enc_name) 与 len(enc.encode(text)) 获取真实 Token 数，
    # 计算 tokens_per_char = round(tokens / chars, 2) 以及 naive_diff = tokens - chars。
    for label, text in samples.items():
      chars = len(text)
      naive_estimate = chars
      tokens = chars
      rows.append(
          {
              "encoding": enc_name,
              "label": label,
              "chars": chars,
              "naive_estimate": naive_estimate,
              "tokens": tokens,
              "tokens_per_char": 1.0,
              "naive_diff": 0,
          }
      )
  return rows


def inspect_token_bytes(text: str, encoding_name: str = "cl100k_base") -> dict[str, Any]:
  """调用 decode_single_token_bytes 分析 UTF-8 半字碎片、空白缩进与 JSON 结构符号开销。"""
  # TODO(步骤2)：请用 load_encoding(encoding_name) 对 text 编码，逐个调用 decode_single_token_bytes(tid)：
  # 1. 校验 b"".join(raw_slices) == text.encode("utf-8")；
  # 2. 统计无法独立 .decode("utf-8") 的半字字节碎片数 partial_utf8_count；
  # 3. 统计解码后非空且 decoded.strip() == "" 的纯空白缩进数 whitespace_token_count；
  # 4. 统计 decoded.strip() 非空且字符全属于 '{}[]:,"' 的结构符号数 syntax_token_count。
  return {
      "encoding": encoding_name,
      "total_tokens": 0,
      "reconstructed_matches_utf8": False,
      "partial_utf8_count": 0,
      "whitespace_token_count": 0,
      "syntax_token_count": 0,
      "preview_slices": [],
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
  # TODO(步骤3)：当前实现存在两处典型计费缺陷：
  # 1. 未将 output_pretty_json 压缩为 separators=(",", ":") 的紧凑 JSON；
  # 2. 错误地把输出 JSON 也按 input_price_per_1m 计价，漏算了高价输出费率！
  enc = load_encoding(encoding_name)
  input_tokens = len(enc.encode(input_text))
  pretty_output_tokens = len(enc.encode(output_pretty_json))
  compact_json = output_pretty_json
  compact_output_tokens = pretty_output_tokens

  monthly_calls = daily_calls * days
  wrong_monthly_usd = round(
      ((input_tokens + pretty_output_tokens) * input_price_per_1m / 1_000_000) * monthly_calls,
      4,
  )
  return {
      "encoding": encoding_name,
      "monthly_calls": monthly_calls,
      "input_tokens": input_tokens,
      "pretty_output_tokens": pretty_output_tokens,
      "compact_output_tokens": compact_output_tokens,
      "saved_output_tokens_per_call": 0,
      "output_token_reduction_pct": 0.0,
      "monthly_input_usd": 0.0,
      "monthly_pretty_output_usd": 0.0,
      "monthly_compact_output_usd": 0.0,
      "monthly_pretty_total_usd": wrong_monthly_usd,
      "monthly_compact_total_usd": wrong_monthly_usd,
      "monthly_savings_usd": 0.0,
      "compact_json": compact_json,
  }


def main() -> None:
  fixture = json.loads((LAB_DIR / "fixtures" / "samples.json").read_text(encoding="utf-8"))
  rows = benchmark_samples(fixture["samples"], tuple(fixture["encodings"]))
  print("=== 四类 500 字对照文本 Token 实测表 ===")
  for r in rows:
    print(
        f"[{r['encoding']}] {r['label']}: {r['chars']} 字符 -> {r['tokens']} tokens "
        f"(比值 {r['tokens_per_char']}, 较拍脑袋偏差 {r['naive_diff']:+d})"
    )


if __name__ == "__main__":
  main()
