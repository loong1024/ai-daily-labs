#!/usr/bin/env python3
"""P0-M05 零代码破冰 Vibe Coding：生成可交互个人专注番茄钟 - 自动化验收脚本。"""

from __future__ import annotations

from html.parser import HTMLParser
import json
import pathlib
import re
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


class SingleFileHTMLInspector(HTMLParser):
  """解析单文件 HTML 的标签属性、内联样式与内联脚本。"""

  def __init__(self) -> None:
    super().__init__()
    self.tags: list[tuple[str, dict[str, str]]] = []
    self.styles: list[str] = []
    self.scripts: list[str] = []
    self._in_style = False
    self._in_script = False

  def handle_starttag(
      self, tag: str, attrs: list[tuple[str, str | None]]
  ) -> None:
    attr_map = {k.lower(): (v or "") for k, v in attrs}
    self.tags.append((tag.lower(), attr_map))
    if tag.lower() == "style":
      self._in_style = True
    elif tag.lower() == "script" and not attr_map.get("src"):
      self._in_script = True

  def handle_endtag(self, tag: str) -> None:
    if tag.lower() == "style":
      self._in_style = False
    elif tag.lower() == "script":
      self._in_script = False

  def handle_data(self, data: str) -> None:
    if self._in_style:
      self.styles.append(data)
    elif self._in_script:
      self.scripts.append(data)


def run_optional_ai_coach(html_source: str) -> None:
  if "--ai-coach" not in sys.argv:
    return
  stage = "参考成品" if use_solution() else "当前页面"
  tip = chat_complete(
      [
          {
              "role": "system",
              "content": "你是友好的 Vibe Coding 前端产品教练，请用两句话给出番茄钟交互改进建议。",
          },
          {"role": "user", "content": html_source[:1200]},
      ],
      mock_fn=lambda _: (
          f"[离线教练模拟 - {stage}] 建议确保 10 秒极速演示、深色护眼模式切换与专注记录导出按钮均绑定在单文件内联脚本中。"
      ),
  )
  print(f"\n💡 Vibe Coding 教练建议：{tip}\n")


def main() -> int:
  v = LabVerifier("P0-M05", "零代码破冰 Vibe Coding：生成可交互个人专注番茄钟")
  html_path = target_file(LAB_DIR, "starter.html", "solution.html")
  preset_path = LAB_DIR / "fixtures" / "focus_presets.json"

  try:
    raw_html = html_path.read_text(encoding="utf-8")
    presets = json.loads(preset_path.read_text(encoding="utf-8"))
    inspector = SingleFileHTMLInspector()
    inspector.feed(raw_html)
  except Exception as exc:
    v.check(
        "单文件网页与预设素材可正常读取解析",
        False,
        f"读取或解析 {html_path.name} / fixtures/focus_presets.json 失败：{exc}",
    )
    return v.finish()

  css_text = "\n".join(inspector.styles)
  js_text = "\n".join(inspector.scripts)

  # 指标 1：单文件自包含 HTML5 基础结构，零外部 CDN 依赖
  external_urls: list[str] = []
  for tag_name, attrs in inspector.tags:
    if tag_name == "script" and attrs.get("src", "").startswith(
        ("http://", "https://", "//")
    ):
      external_urls.append(attrs["src"])
    if tag_name == "link" and attrs.get("href", "").startswith(
        ("http://", "https://", "//")
    ):
      external_urls.append(attrs["href"])
  if re.search(r"@import\s+url\(['\"]?(?:https?:)?//", css_text, re.I):
    external_urls.append("CSS @import 外部样式")

  check1_ok = (
      "<!doctype html>" in raw_html.lower()
      and len(css_text.strip()) >= 80
      and len(js_text.strip()) >= 40
      and not external_urls
  )
  v.check(
      "单文件自包含 HTML5 结构完备且零外部网络资源依赖",
      check1_ok,
      f"请确保使用单个 HTML5 文件内联全部 `<style>` 与 `<script>`，移除外部 CDN 引用：{external_urls}。",
  )

  # 指标 2：温暖浅米色护眼卡片布局 + 今日单点目标输入框
  expected_placeholder_core = "写下此刻最想推进的一件小事"
  has_goal_input = any(
      tag_name == "input"
      and expected_placeholder_core in attrs.get("placeholder", "")
      for tag_name, attrs in inspector.tags
  )
  has_warm_card_style = bool(
      re.search(r"#f[0-9a-f]{5}\b", css_text, re.I)
      and "max-width" in css_text.lower()
      and "border-radius" in css_text.lower()
  )
  check2_ok = has_goal_input and has_warm_card_style
  v.check(
      "界面与视觉：温暖浅米色居中卡片设计 + 今日单点目标输入框",
      check2_ok,
      f"请在卡片顶部添加 `<input>` 单点目标输入框（placeholder 需包含「{presets.get('goal_input_placeholder', expected_placeholder_core)}」），并采用浅米色圆角居中卡片样式。",
  )

  # 指标 3：四档计时模式（25/5/15 分钟 + 10 秒极速演示）及开始/暂停/重置交互
  has_focus_25 = bool(re.search(r"专注\s*25\s*分钟", raw_html))
  has_short_5 = bool(re.search(r"短休\s*5\s*分钟", raw_html))
  has_long_15 = bool(re.search(r"长休\s*15\s*分钟", raw_html))
  has_demo_10s = bool(re.search(r"10\s*秒.*演示|极速演示.*10\s*秒", raw_html))
  has_start_pause = ("开始" in raw_html) and ("暂停" in raw_html)
  has_reset = "重置" in raw_html
  has_timer_engine = ("setInterval" in js_text) and ("clearInterval" in js_text)
  has_durations = (
      ("1500" in raw_html or "25 * 60" in js_text or "25*60" in js_text)
      and ("300" in raw_html or "5 * 60" in js_text or "5*60" in js_text)
      and ("900" in raw_html or "15 * 60" in js_text or "15*60" in js_text)
      and bool(re.search(r"\b10\b", raw_html))
  )
  check3_ok = (
      has_focus_25
      and has_short_5
      and has_long_15
      and has_demo_10s
      and has_start_pause
      and has_reset
      and has_timer_engine
      and has_durations
  )
  v.check(
      "核心交互：支持 25/5/15 分钟与 10 秒极速演示四档切换及开始/暂停/重置倒计时",
      check3_ok,
      "请补齐「专注 25 分钟」「短休 5 分钟」「长休 15 分钟」「10 秒极速演示」四个模式按钮，以及绑定 `setInterval`/`clearInterval` 的「开始 / 暂停」和「重置当前计时」按钮。",
  )

  # 指标 4：状态反馈闭环（已完成专注轮数徽章、清零计数按钮、归零轮数+1 与休息提醒横幅）
  has_round_badge = ("专注轮数" in raw_html) and ("清零" in raw_html)
  has_rest_banner = "休息" in raw_html and any(
      kw in raw_html.lower() for kw in ["banner", "reminder", "alert", "toast"]
  )
  has_zero_increment = bool(
      re.search(r"<=\s*0|===\s*0|==\s*0", js_text)
      and re.search(r"\+\+|(?:\+=\s*1)|(?:\+\s*1\b)", js_text)
  )
  check4_ok = has_round_badge and has_rest_banner and has_zero_increment
  v.check(
      "状态反馈：倒计时归零自动累加专注轮数、弹出休息提醒横幅并支持清零计数",
      check4_ok,
      "请在底部展示「今日已完成专注轮数」与「清零计数」按钮，并在 JS 倒计时归零时自动将轮数 +1、弹出顶部温和休息提醒横幅。",
  )

  # 指标 5：追问迭代进阶（深色护眼模式切换开关 + 专注记录导出特性）
  has_dark_toggle = any(kw in raw_html for kw in ["深色", "夜间"]) and bool(
      re.search(r"dark|data-theme", css_text + "\n" + js_text, re.I)
  )
  has_export_feature = ("导出" in raw_html) and (
      "Blob" in js_text or "createObjectURL" in js_text or "data:text/" in js_text
  )
  check5_ok = has_dark_toggle and has_export_feature
  v.check(
      "追问迭代进阶：支持深色护眼模式一键切换与本地专注记录导出",
      check5_ok,
      "请通过自然语言追问为页面增加「深色护眼模式」切换开关（含深色 CSS 配色）与「导出专注记录」下载按钮（使用 Blob / createObjectURL 导出本地文件）。",
  )

  run_optional_ai_coach(raw_html)
  return v.finish()


if __name__ == "__main__":
  main()
