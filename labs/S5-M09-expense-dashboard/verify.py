#!/usr/bin/env python3
"""S5-M09 个人习惯打卡与日常开支交互看板 自动化验收脚本。"""

from __future__ import annotations

from html.parser import HTMLParser
import json
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


class _BoardHTMLInspector(HTMLParser):
  """解析单文件 HTML 的标签、外部依赖、按钮与脚本内容。"""

  def __init__(self) -> None:
    super().__init__()
    self.external_deps: list[str] = []
    self.input_types: set[str] = set()
    self.select_count: int = 0
    self.option_values: set[str] = set()
    self.buttons: list[str] = []
    self.styles: list[str] = []
    self.scripts: list[str] = []
    self._active_tag: str | None = None
    self._buf: list[str] = []

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    attr_map = {k.lower(): (v or "") for k, v in attrs}
    tag_lower = tag.lower()
    if tag_lower == "script" and attr_map.get("src"):
      src = attr_map["src"].strip()
      if src.startswith(("http://", "https://", "//")):
        self.external_deps.append(src)
    if tag_lower == "link" and attr_map.get("href"):
      href = attr_map["href"].strip()
      if href.startswith(("http://", "https://", "//")):
        self.external_deps.append(href)
    if tag_lower == "input":
      self.input_types.add(attr_map.get("type", "text").lower())
    if tag_lower == "select":
      self.select_count += 1
    if tag_lower == "option" and "value" in attr_map:
      self.option_values.add(attr_map["value"].strip())
    if tag_lower in {"option", "button", "style", "script"}:
      self._active_tag = tag_lower
      self._buf = []

  def handle_data(self, data: str) -> None:
    if self._active_tag is not None:
      self._buf.append(data)

  def handle_endtag(self, tag: str) -> None:
    tag_lower = tag.lower()
    if self._active_tag == tag_lower:
      content = "".join(self._buf)
      if tag_lower == "option":
        self.option_values.add(content.strip())
      elif tag_lower == "button":
        self.buttons.append(content.strip())
      elif tag_lower == "style":
        self.styles.append(content)
      elif tag_lower == "script":
        self.scripts.append(content)
      self._active_tag = None
      self._buf = []


def main() -> None:
  v = LabVerifier("S5-M09", "零代码造网页：个人习惯与开支交互看板")
  html_path = target_file(LAB_DIR, "starter.html", "solution.html")
  fixture_path = LAB_DIR / "fixtures" / "sample_records.json"

  try:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    html_text = html_path.read_text(encoding="utf-8")
    inspector = _BoardHTMLInspector()
    inspector.feed(html_text)
  except Exception as exc:
    v.check("实验文件与测试样本读取解析", False, f"读取或解析 HTML 失败：{exc}")
    v.finish()
    return

  style_blob = "\n".join(inspector.styles)
  script_blob = "\n".join(inspector.scripts)
  script_lower = script_blob.lower()

  required_types = set(fixture["supported_types"])
  required_categories = set(fixture["supported_categories"])
  has_doctype = "<!doctype html>" in html_text.lower()
  zero_cdn = len(inspector.external_deps) == 0
  has_date_input = "date" in inspector.input_types
  has_options = required_types.issubset(inspector.option_values) and required_categories.issubset(
      inspector.option_values
  )

  v.check(
      "单文件离线骨架与录入字段完备（零外部 CDN 依赖）",
      has_doctype and zero_cdn and has_date_input and has_options,
      "确保文件包含 <!DOCTYPE html>、无外部 http/https 脚本样式链接，且提供日期输入框与全部类型/分类选项。",
  )

  has_storage = "localStorage.getItem" in script_blob and "localStorage.setItem" in script_blob
  has_responsive = "@media" in style_blob and ("grid" in style_blob or "flex" in style_blob)
  has_guardrails = "confirm(" in script_blob and ".trim()" in script_blob
  has_dual_badge_styles = ("habit" in style_blob.lower() and "expense" in style_blob.lower()) or (
      style_blob.lower().count("badge") >= 2
  )

  v.check(
      "localStorage 持久化、响应式双栏双色样式与删除/空值防呆",
      has_storage and has_responsive and has_guardrails and has_dual_badge_styles,
      "在脚本中接入 localStorage.getItem/setItem；样式补充 @media 响应式双栏与习惯/开支双色标签；提交前用 .trim() 拦截空事项名，删除前调用 confirm() 二次确认。",
  )

  has_filter_controls = inspector.select_count >= 4 and "全部" in inspector.option_values
  has_filter_and_summary = (
      ".filter(" in script_blob
      and "习惯打卡" in script_blob
      and "日常开支" in script_blob
      and ("reduce(" in script_blob or "+=" in script_blob)
      and "toFixed(" in script_blob
  )

  v.check(
      "按类型与分类组合筛选联动及打卡次数/开支总额实时汇总",
      has_filter_controls and has_filter_and_summary,
      "新增包含“全部”选项的类型与分类筛选下拉框，使用 .filter() 过滤列表并分别统计“习惯打卡”次数与“日常开支”总额（保留两位小数）。",
  )

  has_demo_btn = any("示例" in b for b in inspector.buttons)
  has_csv_btn = any("导出" in b and "csv" in b.lower() for b in inspector.buttons)
  has_demo_dataset = script_blob.count("习惯打卡") >= 3 and script_blob.count("日常开支") >= 3
  has_bom = any(
      marker in script_lower
      for marker in (r"\ufeff", "\ufeff", "0xfeff", "0xef", "%ef%bb%bf")
  )
  has_csv_download_and_escape = (
      "text/csv" in script_lower
      and "download" in script_lower
      and ('""' in script_blob or '\\"\\"' in script_blob)
  )

  v.check(
      "一键填入 5+ 条示例数据与带 UTF-8 BOM 头防乱码 CSV 导出",
      has_demo_btn and has_csv_btn and has_demo_dataset and has_bom and has_csv_download_and_escape,
      "新增“填入示例数据”按钮（内置至少 5 条涵盖习惯打卡与日常开支的演示记录）与“导出 CSV”按钮，导出时拼接 \\uFEFF BOM 头并对含逗号/双引号字段做双引号转义。",
  )

  v.finish()


if __name__ == "__main__":
  main()
