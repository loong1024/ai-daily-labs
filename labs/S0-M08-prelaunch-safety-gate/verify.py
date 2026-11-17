#!/usr/bin/env python3
"""S0-M08 自动化验收脚本。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution  # noqa: E402


def _load_target_module() -> Any:
    mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
    spec = importlib.util.spec_from_file_location("s0_m08_target", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载目标模块: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s0_m08_target"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    v = LabVerifier("S0-M08", "上线前硬兜底安全排查")
    fixture_data = json.loads(
        (LAB_DIR / "fixtures" / "prelaunch_cases.json").read_text(encoding="utf-8")
    )
    policy = fixture_data["gateway_policy"]
    cases = {item["id"]: item for item in fixture_data["cases"]}

    try:
        mod = _load_target_module()
    except Exception as exc:
        v.check("模块加载与语法检查", False, f"加载目标文件失败：{exc}")
        return v.finish()

    # Check 1: 直接提示注入 vs 外部文档间接注入区分与数据边界隔离
    try:
        c_clean = mod.classify_injection_channel(
            cases["case_01_clean_summary"]["user_query"],
            cases["case_01_clean_summary"]["external_doc"],
        )
        c_direct = mod.classify_injection_channel(
            cases["case_02_direct_override"]["user_query"],
            cases["case_02_direct_override"]["external_doc"],
        )
        c_indirect = mod.classify_injection_channel(
            cases["case_03_indirect_doc_override"]["user_query"],
            cases["case_03_indirect_doc_override"]["external_doc"],
        )
        msgs_dump = json.dumps(c_indirect.get("isolated_messages", []), ensure_ascii=False)
        ok_channel = (
            c_clean.get("source_type") == "none"
            and c_direct.get("source_type") == "direct"
            and c_indirect.get("source_type") == "indirect"
            and "<untrusted_document>" in msgs_dump
            and "</untrusted_document>" in msgs_dump
        )
        v.check(
            "区分直接/间接提示注入并隔离不可信外部文档",
            ok_channel,
            "请在 classify_injection_channel 中准确识别 user_query(direct) 与 external_doc(indirect) 风险通道，并用 <untrusted_document> 包裹外部文本。",
        )
    except Exception as exc:
        v.check(
            "区分直接/间接提示注入并隔离不可信外部文档",
            False,
            f"classify_injection_channel 执行异常 ({exc})，请检查返回值字段。",
        )

    # Check 2: 模型不安全输出 HTML/script 转义
    try:
        raw_html = cases["case_04_unsafe_html_output"]["simulated_llm_output"]
        escaped = mod.sanitize_model_html(raw_html)
        ok_escape = (
            isinstance(escaped, str)
            and "<script>" not in escaped
            and "</script>" not in escaped
            and "&lt;script&gt;" in escaped
            and "&quot;" in escaped
        )
        v.check(
            "模型输出 HTML 与 <script> 严格转义为纯文本",
            ok_escape,
            "请在 sanitize_model_html 中使用 html.escape(raw_output, quote=True) 转义标签与属性引号。",
        )
    except Exception as exc:
        v.check(
            "模型输出 HTML 与 <script> 严格转义为纯文本",
            False,
            f"sanitize_model_html 执行异常 ({exc})。",
        )

    # Check 3: 服务端会话鉴权与参数化 SQL 查询
    try:
        cross = cases["case_05_cross_tenant_query"]
        denied_cross = mod.build_authorized_doc_query(
            cross["session_user_id"],
            cross["requested_owner_id"],
            cross["category"],
        )
        denied_anon = mod.build_authorized_doc_query("", "usr_alice", "notes")
        allowed_own = mod.build_authorized_doc_query(
            "usr_alice", "usr_alice", cross["category"]
        )
        sql_str = str(allowed_own.get("sql", ""))
        params_val = tuple(allowed_own.get("params", ()))
        ok_sql = (
            denied_cross.get("allowed") is False
            and denied_anon.get("allowed") is False
            and allowed_own.get("allowed") is True
            and "?" in sql_str
            and cross["category"] not in sql_str
            and params_val == ("usr_alice", cross["category"])
        )
        v.check(
            "服务端租户权限校验与 SQL 参数化占位查询",
            ok_sql,
            "请在 build_authorized_doc_query 中拒绝空会话及跨用户访问，并改用 WHERE owner_id = ? AND category = ? 与参数元组。",
        )
    except Exception as exc:
        v.check(
            "服务端租户权限校验与 SQL 参数化占位查询",
            False,
            f"build_authorized_doc_query 执行异常 ({exc})。",
        )

    # Check 4: 网关硬消费封顶、频控阻断与输出兜底闭环
    try:
        over_budget_case = cases["case_06_hard_budget_exceeded"]
        res_budget = mod.enforce_hard_quota_and_call(
            over_budget_case,
            policy,
            [{"role": "user", "content": over_budget_case["user_query"]}],
            simulated_output=over_budget_case["simulated_llm_output"],
        )

        over_rate_ctx = dict(cases["case_01_clean_summary"], user_requests_in_window=10)
        res_rate = mod.enforce_hard_quota_and_call(
            over_rate_ctx,
            policy,
            [{"role": "user", "content": "限流测试"}],
            simulated_output="不应执行",
        )

        html_case = cases["case_04_unsafe_html_output"]
        res_ok = mod.enforce_hard_quota_and_call(
            html_case,
            policy,
            [{"role": "user", "content": html_case["user_query"]}],
            simulated_output=html_case["simulated_llm_output"],
        )

        ok_quota = (
            res_budget.get("allowed") is False
            and res_budget.get("llm_called") is False
            and res_rate.get("allowed") is False
            and res_rate.get("llm_called") is False
            and res_ok.get("allowed") is True
            and res_ok.get("llm_called") is True
            and "<script>" not in str(res_ok.get("safe_html", ""))
            and "&lt;script&gt;" in str(res_ok.get("safe_html", ""))
        )
        v.check(
            "网关硬消费封顶、频控前置拦截与安全输出闭环",
            ok_quota,
            "请在 enforce_hard_quota_and_call 中前置拦截未认证、超频与超 hard_cap_usd 请求（llm_called=False），并对正常响应调用 sanitize_model_html。",
        )
    except Exception as exc:
        v.check(
            "网关硬消费封顶、频控前置拦截与安全输出闭环",
            False,
            f"enforce_hard_quota_and_call 执行异常 ({exc})。",
        )

    return v.finish()


if __name__ == "__main__":
    raise SystemExit(main())
