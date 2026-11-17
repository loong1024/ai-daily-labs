#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import ModuleType
from typing import Any

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


def main() -> int:
    v = LabVerifier("S5-M03", "拒绝AI一把梭改乱千行：Spec先行与小步TDD实验")

    code_path = target_file(LAB_DIR, "starter.py", "solution.py")
    try:
        mod = _load_module(code_path, "s5_m03_target")
        vague_req = json.loads((LAB_DIR / "fixtures" / "vague_requirement.json").read_text(encoding="utf-8"))
        bad_spec = (LAB_DIR / "fixtures" / "bad_spec_stub.md").read_text(encoding="utf-8")
        io_cases = json.loads((LAB_DIR / "fixtures" / "clarified_io_cases.json").read_text(encoding="utf-8"))
    except Exception as exc:
        v.check("1. 模块语法与测试素材加载", False, f"加载 {code_path.name} 失败：{exc}")
        return v.finish()

    # 1. 校验 Spec 生成与 7 节规格书审计门禁
    try:
        spec_md = mod.draft_spec_markdown(vague_req)
        bad_audit = mod.audit_spec_markdown(bad_spec)
        good_audit = mod.audit_spec_markdown(spec_md)

        spec_issues: list[str] = []
        if bad_audit.get("valid") is not False or not bad_audit.get("missing"):
            spec_issues.append("audit_spec_markdown 未能拦截残缺规格 fixtures/bad_spec_stub.md")
        if good_audit.get("valid") is not True:
            spec_issues.append(f"draft_spec_markdown 产出的规格未通过自身审计：{good_audit.get('missing')}")

        if "非目标" not in spec_md and "Non-Goal" not in spec_md:
            spec_issues.append("生成的 spec.md 缺少‘非目标’章节")
        if sum(1 for ln in spec_md.splitlines() if ln.strip().startswith("|")) < 3:
            spec_issues.append("生成的 spec.md 缺少输入输出样例对照表格")
        if not ("给定" in spec_md and "当" in spec_md and "那么" in spec_md):
            spec_issues.append("生成的 spec.md 缺少‘给定…当…那么…’验收标准")
        if "须串行" not in spec_md and "可并行" not in spec_md:
            spec_issues.append("生成的 spec.md 未标注任务‘须串行/可并行’")
        if "待确认问题" not in spec_md or (spec_md.count("？") + spec_md.count("?")) < 3:
            spec_issues.append("生成的 spec.md 缺少至少 3 个待确认问题")

        v.check(
            "1. Spec 先行门禁（7 节完整 spec.md 生成与残缺规格拦截）",
            len(spec_issues) == 0,
            f"请完善 {code_path.name} 的 draft_spec_markdown 与 audit_spec_markdown：{'；'.join(spec_issues)}。",
        )
    except Exception as exc:
        v.check(
            "1. Spec 先行门禁（7 节完整 spec.md 生成与残缺规格拦截）",
            False,
            f"运行 Spec 生成/审计时抛出异常：{exc}",
        )

    # 2. 校验澄清后的输入输出样例表与异常边界
    try:
        case_failures: list[str] = []
        for item in io_cases["valid_cases"]:
            actual = mod.quote_team_subscription(dict(item["input"]))
            expected = item["expected"]
            for key, exp_val in expected.items():
                if actual.get(key) != exp_val:
                    case_failures.append(f"{item['name']} 字段 {key} 期望 {exp_val}，实际 {actual.get(key)}")
                    break

        for err_item in io_cases["error_cases"]:
            raised = False
            try:
                mod.quote_team_subscription(dict(err_item["input"]))
            except ValueError:
                raised = True
            if not raised:
                case_failures.append(f"{err_item['name']} 未抛出 ValueError")

        v.check(
            "2. 澄清规格输入输出样例表与边界错误处理全量验证（11 组用例）",
            len(case_failures) == 0,
            f"请按澄清规格修正 quote_team_subscription：{'；'.join(case_failures[:4])}。",
        )
    except Exception as exc:
        v.check(
            "2. 澄清规格输入输出样例表与边界错误处理全量验证（11 组用例）",
            False,
            f"执行输入输出样例验证时抛出异常：{exc}",
        )

    # 3. 校验小步 TDD 测试套件真能“先红后绿”
    try:
        tdd_issues: list[str] = []

        def _mutant_flat_tier(order: dict[str, Any]) -> dict[str, Any]:
            s = int(order["seats"])
            sub = s * (8000 if s > 10 else 10000)
            return {"seats": s, "subtotal_cents": sub, "discount_cents": 0, "payable_cents": sub, "currency": "CNY"}

        def _mutant_ignore_bad_coupon(order: dict[str, Any]) -> dict[str, Any]:
            return mod.quote_team_subscription({**order, "coupon_code": None})

        for label, mutant_fn in (
            ("全量跳档算错阶梯缺陷", _mutant_flat_tier),
            ("静默吞掉未知优惠码缺陷", _mutant_ignore_bad_coupon),
        ):
            caught = False
            try:
                mod.run_tdd_suite(mutant_fn)
            except AssertionError:
                caught = True
            if not caught:
                tdd_issues.append(f"run_tdd_suite 未能捕获‘{label}’（缺少红灯拦截力）")

        steps = mod.run_tdd_suite(mod.quote_team_subscription)
        if not isinstance(steps, list) or len(steps) < 3:
            tdd_issues.append("run_tdd_suite 拆分的小步验证少于 3 步")

        v.check(
            "3. 小步 TDD 测试套件‘先红后绿’有效性与分步覆盖度",
            len(tdd_issues) == 0,
            f"请增强 {code_path.name} 中的 run_tdd_suite：{'；'.join(tdd_issues)}。",
        )
    except Exception as exc:
        v.check(
            "3. 小步 TDD 测试套件‘先红后绿’有效性与分步覆盖度",
            False,
            f"执行 run_tdd_suite 时抛出异常：{exc}",
        )

    # 4. 校验非目标禁区（无越界字段、无擅改既有函数）
    try:
        scope_issues: list[str] = []
        sample_out = mod.quote_team_subscription({"seats": 12, "currency": "CNY"})
        expected_keys = {"seats", "subtotal_cents", "discount_cents", "payable_cents", "currency"}
        extra_keys = set(sample_out.keys()) - expected_keys
        if extra_keys:
            scope_issues.append(f"返回字典包含规格未约定的越界字段：{sorted(extra_keys)}")

        usd_blocked = False
        try:
            mod.quote_team_subscription({"seats": 5, "currency": "USD"})
        except ValueError:
            usd_blocked = True
        if not usd_blocked:
            scope_issues.append("未拦截非目标币种 USD（禁止擅自猜测汇率）")

        slug_actual = mod.normalize_account_slug("  Acme   Cloud  ")
        if slug_actual != "acme-cloud":
            scope_issues.append(
                f"既有函数 normalize_account_slug 被越界篡改（期望 'acme-cloud'，实际 '{slug_actual}'）"
            )

        v.check(
            "4. Diff 范围纯净度复核（严守 Non-Goals 禁区且不破坏既有模块）",
            len(scope_issues) == 0,
            f"请清理 {code_path.name} 中的越界加戏改动：{'；'.join(scope_issues)}。",
        )
    except Exception as exc:
        v.check(
            "4. Diff 范围纯净度复核（严守 Non-Goals 禁区且不破坏既有模块）",
            False,
            f"执行非目标范围复核时抛出异常：{exc}",
        )

    return v.finish()


if __name__ == "__main__":
    raise SystemExit(main())
