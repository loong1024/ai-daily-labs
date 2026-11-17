#!/usr/bin/env python3
"""S5-M09 门店/个人经营收支与目标追踪可视化看板 自动化验收脚本。"""

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
    self.element_ids: set[str] = set()
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
    if attr_map.get("id"):
      self.element_ids.add(attr_map["id"].strip())
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


def _verify_fixture_consistency(fixture: dict) -> bool:
  records = fixture.get("records", [])
  views = fixture.get("expected_views", {})
  target = float(fixture.get("default_monthly_target", 5000.0))
  inc = sum(float(r["amount"]) for r in records if r["type"] == "经营收入")
  exp = sum(float(r["amount"]) for r in records if r["type"] == "经营支出")
  all_view = views.get("all", {})
  return (
      len(records) == all_view.get("visible_count")
      and abs(inc - float(all_view.get("income_total", -1))) < 1e-6
      and abs(exp - float(all_view.get("expense_total", -1))) < 1e-6
      and abs((inc - exp) - float(all_view.get("net_balance", -1))) < 1e-6
      and abs((inc / target * 100.0) - float(all_view.get("target_progress_pct", -1))) < 0.2
  )


def main() -> None:
  v = LabVerifier("S5-M09", "零代码15分钟造交互网页：门店/个人经营收支与目标追踪可视化看板")
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
  has_date_and_num = "date" in inspector.input_types and "number" in inspector.input_types
  has_options = required_types.issubset(inspector.option_values) and required_categories.issubset(
      inspector.option_values
  )

  v.check(
      "1. 单文件离线骨架与经营收支分类字段完备（零外部 CDN 依赖）",
      has_doctype and zero_cdn and has_date_and_num and has_options and _verify_fixture_consistency(fixture),
      "确保文件包含 <!DOCTYPE html>、无外部 http/https 脚本样式链接，且提供日期、金额输入框及全部经营收支类型与分类选项。",
  )

  has_goal_progress = (
      ("目标" in html_text)
      and ("progress" in html_text.lower())
      and (".style.width" in script_blob or "width:" in script_blob)
      and ("* 100" in script_blob or "*100" in script_blob)
  )
  v.check(
      "2. 月度营收目标设定与可视化达成率进度条实时联动",
      has_goal_progress,
      "新增月度营收目标输入框（如默认 5000 元）与可视化进度条容器，根据累计经营收入动态计算达成百分比并更新进度条 width。",
  )

  has_storage = "localStorage.getItem" in script_blob and "localStorage.setItem" in script_blob
  has_responsive = "@media" in style_blob and ("grid" in style_blob or "flex" in style_blob)
  has_guardrails = "confirm(" in script_blob and ".trim()" in script_blob
  has_dual_badge_styles = ("income" in style_blob.lower() and "expense" in style_blob.lower()) or (
      style_blob.lower().count("badge") >= 2
  )

  v.check(
      "3. localStorage 持久化、响应式双栏收支双色卡片与删除/空值防呆",
      has_storage and has_responsive and has_guardrails and has_dual_badge_styles,
      "接入 localStorage.getItem/setItem 保存流水与月目标；补充 @media 响应式双栏与收入/支出双色标签；提交前用 .trim() 拦截空摘要，删除前调用 confirm() 二次确认。",
  )

  has_filter_controls = inspector.select_count >= 4 and "全部" in inspector.option_values
  has_filter_and_summary = (
      ".filter(" in script_blob
      and "经营收入" in script_blob
      and "经营支出" in script_blob
      and ("reduce(" in script_blob or "+=" in script_blob)
      and "-" in script_blob
      and "toFixed(" in script_blob
  )

  v.check(
      "4. 按收支类型与经营分类组合筛选联动及总收入/总支出/净结余汇总",
      has_filter_controls and has_filter_and_summary,
      "新增包含“全部”选项的收支类型与经营分类筛选下拉框，使用 .filter() 过滤列表并实时计算经营总收入、经营总支出与净结余（保留两位小数）。",
  )

  has_demo_btn = any("示例" in b for b in inspector.buttons)
  has_csv_btn = any("导出" in b and "csv" in b.lower() for b in inspector.buttons)
  has_demo_dataset = (
      script_blob.count("经营收入") >= 3
      and script_blob.count("经营支出") >= 3
      and "," in script_blob
      and ('\"' in script_blob or '""' in script_blob)
  )
  has_bom = any(
      marker in script_lower
      for marker in (r"\ufeff", "\ufeff", "0xfeff", "0xef", "%ef%bb%bf")
  )
  has_csv_download_and_escape = (
      "text/csv" in script_lower
      and "download" in script_lower
      and ('""' in script_blob or '\"\"' in script_blob)
  )

  v.check(
      "5. 一键填入 6 条基准经营样本与带 UTF-8 BOM 头防乱码 CSV 对账导出",
      has_demo_btn and has_csv_btn and has_demo_dataset and has_bom and has_csv_download_and_escape,
      "新增“填入示例数据”按钮（内置涵盖经营收入与经营支出的基准演示记录）与“导出 CSV”按钮，导出时拼接 \\uFEFF BOM 头并对含逗号/双引号字段做双引号转义。",
  )

  v.finish()


if __name__ == "__main__":
  main()
