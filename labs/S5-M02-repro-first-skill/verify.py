#!/usr/bin/env python3
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

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: E402


def _load_module(path: pathlib.Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _parse_frontmatter(md_text: str) -> tuple[dict[str, str], str]:
    lines = md_text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, md_text
    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, md_text

    meta: dict[str, str] = {}
    cur_key: str | None = None
    for raw in lines[1:end_idx]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")) and cur_key is not None:
            meta[cur_key] = f"{meta[cur_key]} {raw.strip()}".strip()
        elif ":" in raw:
            k, val = raw.split(":", 1)
            cur_key = k.strip()
            meta[cur_key] = val.strip().lstrip("|>").strip().strip("\"'")
    body = "\n".join(lines[end_idx + 1 :])
    return meta, body


def main() -> int:
    v = LabVerifier("S5-M02", "AI修Bug总盲改？复现优先Skill与降噪脚本实战")

    skill_path = target_file(LAB_DIR, "starter.md", "solution.md")
    code_path = target_file(LAB_DIR, "starter.py", "solution.py")

    # 1. 校验 SKILL.md 结构、触发条件/禁区声明与二振回滚纪律
    try:
        md_text = skill_path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(md_text)
        desc = meta.get("description", "")
        missing_skill_parts: list[str] = []

        if meta.get("name") != "repro-first-debugging":
            missing_skill_parts.append("YAML name 必须为 repro-first-debugging")
        if not any(k in desc for k in ("报错", "测试失败", "异常", "bug", "Bug", "故障")):
            missing_skill_parts.append("YAML description 缺少报错/测试失败/行为异常等正向触发条件")
        if not any(k in desc for k in ("不用于", "非新功能", "不要用于", "不适用")):
            missing_skill_parts.append("YAML description 缺少负面边界声明（如‘不用于开发新功能’）")
        if not (
            any(k in body for k in ("缺少", "先向用户询问", "先询问", "不要猜"))
            and any(k in body for k in ("堆栈", "触发步骤", "期望"))
        ):
            missing_skill_parts.append("正文缺少‘开始前’四要素核对及缺项先询问规则")
        if not (
            "复现" in body
            and any(k in body for k in ("最小失败", "必败", "失败测试"))
            and any(k in body for k in ("不得修改", "不得删除", "禁止删除", "跳过既有测试", "不修改既有测试"))
        ):
            missing_skill_parts.append("正文缺少‘先写最小失败测试’或‘不得擅改/跳过既有测试’纪律")
        if not (
            any(k in body for k in ("2 次", "2次", "两次"))
            and any(k in body for k in ("回滚", "停止修改", "停下"))
            and any(k in body for k in ("公共接口", "数据库", "新增依赖"))
        ):
            missing_skill_parts.append("正文缺少‘连续 2 次修复无效回滚汇报’或‘改接口/库表/依赖先请示’停止条件")
        if not ("根因" in body and "回归测试" in body):
            missing_skill_parts.append("正文缺少标准汇报格式（根因及证据、回归测试名称等）")

        v.check(
            "1. repro-first-debugging SKILL.md 规范与止损条款完整性",
            len(missing_skill_parts) == 0,
            f"请完善 {skill_path.name}：{'；'.join(missing_skill_parts)}。",
        )
    except Exception as exc:
        v.check(
            "1. repro-first-debugging SKILL.md 规范与止损条款完整性",
            False,
            f"读取或解析 {skill_path.name} 出错：{exc}",
        )

    # 加载 Python 模块与测试素材
    try:
        mod = _load_module(code_path, "s5_m02_target")
        buggy_mod = _load_module(LAB_DIR / "fixtures" / "buggy_billing.py", "s5_m02_buggy")
        repro_bundle = json.loads((LAB_DIR / "fixtures" / "repro_cases.json").read_text(encoding="utf-8"))
        pytest_runs = repro_bundle["pytest_runs"]
        triage_cases = repro_bundle["triage_scenarios"]
    except Exception as exc:
        v.check("2. Python 模块加载与语法检查", False, f"加载 {code_path.name} 失败：{exc}")
        return v.finish()

    # 2. 校验精简测试输出包装器
    try:
        pass_summary = mod.summarize_test_run(pytest_runs["all_pass_verbose"], max_tail_lines=10)
        fail_summary = mod.summarize_test_run(pytest_runs["multi_fail_verbose"], max_tail_lines=10)

        pass_lines = [ln for ln in pass_summary.splitlines() if ln.strip()]
        fail_lines = [ln for ln in fail_summary.splitlines() if ln.strip()]

        wrapper_issues: list[str] = []
        if not (1 <= len(pass_lines) <= 3):
            wrapper_issues.append(f"全绿日志应压缩到 ≤3 行简短汇总，当前输出了 {len(pass_lines)} 行")
        if "DEBUG [" in pass_summary:
            wrapper_issues.append("全绿汇总未过滤 DEBUG 噪音日志")
        if "6 passed" not in pass_summary.lower() and "pass" not in pass_summary.lower():
            wrapper_issues.append("全绿汇总未保留通过统计信息")

        if "test_refund_with_promo_coupon" not in fail_summary or "test_refund_near_expiry_non_negative" not in fail_summary:
            wrapper_issues.append("失败摘要未完整提取失败用例名称")
        if "test_full_unused_refund PASSED" in fail_summary or "DEBUG [" in fail_summary:
            wrapper_issues.append("失败摘要仍混杂 PASSED 用例或 DEBUG 刷屏噪音")
        if len(fail_lines) > 15:
            wrapper_issues.append(f"失败摘要行数过多（当前 {len(fail_lines)} 行），应仅保留失败用例名与末尾关键报错行")

        v.check(
            "2. 测试包装脚本降噪能力（全绿极简汇总 / 失败仅留用例名与关键尾部报错）",
            len(wrapper_issues) == 0,
            f"请改进 {code_path.name} 中的 summarize_test_run：{'；'.join(wrapper_issues)}。",
        )
    except Exception as exc:
        v.check(
            "2. 测试包装脚本降噪能力（全绿极简汇总 / 失败仅留用例名与关键尾部报错）",
            False,
            f"调用 summarize_test_run 抛出异常：{exc}",
        )

    # 3. 校验历史 Bug “先红后绿”闭环与最小修复
    try:
        repro_issues: list[str] = []
        caught_on_buggy = False
        try:
            res = mod.test_promo_refund_repro(buggy_mod.calculate_prorated_refund)
            if res is False:
                caught_on_buggy = True
        except AssertionError:
            caught_on_buggy = True

        if not caught_on_buggy:
            repro_issues.append("test_promo_refund_repro 在故障基准代码上未触发 AssertionError（未做到修复前必败）")

        try:
            mod.test_promo_refund_repro(mod.calculate_prorated_refund)
        except AssertionError as assertion_err:
            repro_issues.append(f"test_promo_refund_repro 在当前修复代码上仍失败：{assertion_err}")

        baseline_checks = [
            (mod.calculate_prorated_refund(3000, 30, 0, 500) == 3000, "未用天数 0 应全退实付 3000"),
            (mod.calculate_prorated_refund(3000, 30, 30, 500) == 0, "已用满周期应退 0"),
            (mod.calculate_prorated_refund(3000, 30, 10, 0) == 2000, "无券订单 30 天用 10 天应退 2000"),
            (mod.calculate_prorated_refund(7000, 30, 15, 3000) == 3500, "有券订单实付 7000 用 15/30 天应退 3500"),
            (mod.calculate_prorated_refund(7000, 30, 25, 3000) == 1166, "有券订单实付 7000 用 25/30 天应退 1166"),
        ]
        for ok, msg in baseline_checks:
            if not ok:
                repro_issues.append(msg)

        root_cause = str(getattr(mod, "ROOT_CAUSE_SUMMARY", "")).strip()
        if len(root_cause) < 15 or "TODO" in root_cause.upper():
            repro_issues.append("ROOT_CAUSE_SUMMARY 尚未填写清晰的根因说明")

        v.check(
            "3. 历史故障‘先红后绿’复现测试、最小修复与既有测试零回归",
            len(repro_issues) == 0,
            f"请完善 {code_path.name} 的回归测试、退款修复与 ROOT_CAUSE_SUMMARY：{'；'.join(repro_issues)}。",
        )
    except Exception as exc:
        v.check(
            "3. 历史故障‘先红后绿’复现测试、最小修复与既有测试零回归",
            False,
            f"运行回归与修复校验时抛出异常：{exc}",
        )

    # 4. 校验缺信息追问与连续 2 次失败回滚止损守卫
    try:
        mismatches: list[str] = []
        for item in triage_cases:
            decision = mod.decide_debug_next_action(item["state"])
            actual_action = decision.get("action") if isinstance(decision, dict) else None
            reason = str(decision.get("reason", "")).strip() if isinstance(decision, dict) else ""
            if actual_action != item["expected_action"] or len(reason) < 6:
                mismatches.append(
                    f"{item['id']}({item['title']}) 期望 action={item['expected_action']}，实际={actual_action}"
                )

        v.check(
            "4. 缺信息先问、高危变更请示与连续 2 次失败回滚止损演练",
            len(mismatches) == 0,
            f"请修正 {code_path.name} 中的 decide_debug_next_action：{'；'.join(mismatches)}。",
        )
    except Exception as exc:
        v.check(
            "4. 缺信息先问、高危变更请示与连续 2 次失败回滚止损演练",
            False,
            f"调用 decide_debug_next_action 抛出异常：{exc}",
        )

    return v.finish()


if __name__ == "__main__":
    raise SystemExit(main())
