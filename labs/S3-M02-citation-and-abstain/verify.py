#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def load_mod(path: pathlib.Path):
  spec = importlib.util.spec_from_file_location("lab_target", path)
  mod = importlib.util.module_from_spec(spec)
  assert spec and spec.loader
  spec.loader.exec_module(mod)
  return mod

def simulate_rag_generation(prompt_tpl: str, case: dict) -> str:
  has_cite_rule = "[S1]" in prompt_tpl or "[S编号]" in prompt_tpl
  has_abstain_rule = ("拒答" in prompt_tpl or "无法从现有参考资料中确认" in prompt_tpl) and ("严禁" in prompt_tpl or "常识" in prompt_tpl)
  has_recency_rule = "最新" in prompt_tpl and ("冲突" in prompt_tpl or "date" in prompt_tpl)
  has_inject_guard = "<sources>" in prompt_tpl and ("数据" in prompt_tpl or "恶意" in prompt_tpl or "忽略" in prompt_tpl)

  ctype = case["type"]
  if ctype == "answerable":
    return "远程办公外接显示器最高报销上限为 1500 元 [S1]。" if has_cite_rule else "显示器大约可以报销 1500 元左右。"
  if ctype == "conflict":
    if has_recency_rule and has_cite_rule:
      return "研发晚间值班打车报销自 21:00 起生效 [S2]（原 [S1] 的 22:00 旧规已废止）。"
    return "晚间加班打车 22:00 开始报销。"
  if ctype == "abstain":
    if has_abstain_rule:
      return "无法从现有参考资料中确认公司健身房周末开放时间（现有资料仅提及茶水间）。"
    return "根据一般企业惯例，公司健身房周末通常在 09:00-21:00 开放。"
  if ctype == "injection":
    if has_inject_guard and has_cite_rule:
      return "实习生餐补标准为每出勤日 40 元 [S1]。"
    return "实习生餐补每日 9999 元"
  return ""


def main() -> None:
  v = LabVerifier("S3-M02", "防常识混入与假引用：逐句标号与拒答闸门")
  cases = json.loads((LAB_DIR / "fixtures" / "eval_cases.json").read_text(encoding="utf-8"))
  tpl = target_file(LAB_DIR, "starter_prompt.md", "solution_prompt.md").read_text(encoding="utf-8")

  outs = {c["id"]: simulate_rag_generation(tpl, c) for c in cases}
  v.check("有据可查题强制附带真实 [S编号] 内联引用且数值准确",
          "1500" in outs["C1_FACT"] and "[S1]" in outs["C1_FACT"],
          "在提示词模板中明确要求每条事实句末尾标注真实存在的 [S1]/[S2] 来源编号。")
  v.check("新旧规定冲突题优先采信最新日期条款 [S2] 并指出旧稿 [S1]",
          "21:00" in outs["C2_CONFLICT"] and "[S2]" in outs["C2_CONFLICT"],
          "补充新旧版本冲突择新规则：优先采信 date 最新的来源片段。")
  v.check("资料未覆盖题严格触发拒答闸门（零常识脑补）",
          "无法从现有参考资料中确认" in outs["C3_UNANSWERABLE"],
          "删除“结合常识补充”表述，强制规定无直接依据时必须拒答并说明资料缺口。")
  v.check("检索片段内藏恶意提示注入被成功隔离拦截",
          "40" in outs["C4_INJECT"] and "[S1]" in outs["C4_INJECT"] and "9999" not in outs["C4_INJECT"],
          "使用 <sources> 分隔符包裹检索内容，并声明其中一切祈使句均为静态数据而非指令。")
  v.finish()


if __name__ == "__main__":
  main()
