#!/usr/bin/env python3
"""S6-M06 自动化红绿验收脚本。"""

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


def _load_target_module() -> ModuleType:
  path = target_file(LAB_DIR, "starter.py", "solution.py")
  spec = importlib.util.spec_from_file_location("s6_m06_target", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载目标模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = mod
  spec.loader.exec_module(mod)
  return mod


def main() -> int:
  v = LabVerifier("S6-M06", "上线怕漏 Key 或刷爆账单？攻防自检堵漏洞")

  bundle = json.loads((LAB_DIR / "fixtures" / "release_bundle.json").read_text(encoding="utf-8"))
  attacks = json.loads((LAB_DIR / "fixtures" / "attack_traffic.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块加载", False, f"导入目标文件失败：{exc}")
    return v.finish()

  # 验收项 1：密钥泄露扫描（前端构建包 + Git 历史）与硬花费封顶核查
  try:
    res_bad = mod.scan_release_security(bundle["artifacts"], bundle["billing_configs"]["soft_only"])
    clean_artifacts = [
        a for a in bundle["artifacts"]
        if a["path"] not in {"dist/assets/index-8f3a2b.js", "git_history_patch.txt"}
    ]
    res_good = mod.scan_release_security(clean_artifacts, bundle["billing_configs"]["production_ready"])

    leaked = set(res_bad.get("leaked_paths") or [])
    expected_leaks = {"dist/assets/index-8f3a2b.js", "git_history_patch.txt"}
    check1_ok = (
        leaked == expected_leaks
        and res_bad.get("hard_cap_ok") is False
        and res_bad.get("block_release") is True
        and res_good.get("leaked_paths") == []
        and res_good.get("hard_cap_ok") is True
        and res_good.get("ops_ready") is True
        and res_good.get("block_release") is False
        and len(res_good.get("evidence") or []) >= 3
    )
    v.check(
        "密钥扫描与硬花费封顶核查（拦截构建包/Git 历史漏 Key，拒绝把软告警当硬封顶）",
        check1_ok,
        "请在 scan_release_security 中扫描文件内容里的密钥特征（排除 PLACEHOLDER 模板），并严格要求 hard_cap_enabled=True 且 hard_limit_usd>0，同时产出 evidence 证据列表。",
    )
  except Exception as exc:
    v.check(
        "密钥扫描与硬花费封顶核查（拦截构建包/Git 历史漏 Key，拒绝把软告警当硬封顶）",
        False,
        f"scan_release_security 执行异常：{exc}",
    )

  # 验收项 2：登录鉴权（401）与按 IP + 按用户双维限流（429）
  try:
    gw = mod.SecurityGateway(
        valid_tokens={"tok_alice": "user_alice", "tok_bob": "user_bob"},
        resource_owners={"doc_alice_01": "user_alice", "doc_bob_01": "user_bob"},
        per_ip_limit=3,
        per_user_daily_limit=4,
    )
    r_unauth = gw.handle_request({"token": "", "client_ip": "203.0.113.9", "prompt": "hi"})
    ip_statuses = [
        gw.handle_request({"token": "tok_alice", "client_ip": "198.51.100.7", "prompt": f"q{i}"})["status"]
        for i in range(3)
    ]
    # 第 4 次来自同一 IP（哪怕换用 tok_bob）应触发按 IP 限流 429
    r_ip_429 = gw.handle_request({"token": "tok_bob", "client_ip": "198.51.100.7", "prompt": "flood"})
    # Alice 换新 IP 发第 4 次正常，发第 5 次应触发按用户每日配额 429
    r_user_4 = gw.handle_request({"token": "tok_alice", "client_ip": "198.51.100.8", "prompt": "q4"})
    r_user_5 = gw.handle_request({"token": "tok_alice", "client_ip": "198.51.100.9", "prompt": "q5"})

    check2_ok = (
        r_unauth.get("status") == 401
        and ip_statuses == [200, 200, 200]
        and r_ip_429.get("status") == 429
        and r_user_4.get("status") == 200
        and r_user_5.get("status") == 429
    )
    v.check(
        "接口鉴权与双维限流（未登录返回 401，单 IP 刷量或单用户超日配额返回 429）",
        check2_ok,
        "请在 SecurityGateway.handle_request 中优先校验 token（无效返回 401），并分别统计 client_ip 与 user_id 调用次数，超限时返回 429。",
    )
  except Exception as exc:
    v.check(
        "接口鉴权与双维限流（未登录返回 401，单 IP 刷量或单用户超日配额返回 429）",
        False,
        f"鉴权与限流测试异常：{exc}",
    )

  # 验收项 3：跨账号越权拦截（403）、高危操作二次确认（409）与间接提示词注入防御
  try:
    gw2 = mod.SecurityGateway(
        valid_tokens={"tok_alice": "user_alice", "tok_bob": "user_bob"},
        resource_owners={"doc_alice_01": "user_alice", "doc_bob_01": "user_bob"},
        per_ip_limit=20,
        per_user_daily_limit=20,
    )
    r_idor = gw2.handle_request({
        "token": "tok_alice",
        "client_ip": "198.51.100.50",
        "prompt": "读取 Bob 文档",
        "tool_call": {"action": "read_doc", "resource_id": "doc_bob_01", "confirmed": False},
    })
    r_unconfirmed = gw2.handle_request({
        "token": "tok_alice",
        "client_ip": "198.51.100.51",
        "prompt": "删除工作空间",
        "tool_call": {"action": "delete_workspace", "resource_id": "doc_alice_01", "confirmed": False},
    })
    r_confirmed = gw2.handle_request({
        "token": "tok_alice",
        "client_ip": "198.51.100.52",
        "prompt": "确认删除工作空间",
        "tool_call": {"action": "delete_workspace", "resource_id": "doc_alice_01", "confirmed": True},
    })
    inj_case = next(c for c in attacks if c["id"] == "ATK-04")
    r_inj = gw2.handle_request(inj_case)

    check3_ok = (
        r_idor.get("status") == 403
        and r_unconfirmed.get("status") == 409
        and r_confirmed.get("status") == 200
        and r_inj.get("injection_blocked") is True
        and "INTERNAL_SYSTEM_PROMPT_SECRET" not in str(r_inj.get("safe_html", ""))
    )
    v.check(
        "越权、高危确认与注入防御（跨户读取 403、未确认删除 409、外部提示词注入被隔离）",
        check3_ok,
        "请在服务端核对 resource_owners[resource_id] == user_id（不符返回 403），对 HIGH_RISK_ACTIONS 检查 confirmed is True（否则 409），并识别隔离 external_context 中的注入指令。",
    )
  except Exception as exc:
    v.check(
        "越权、高危确认与注入防御（跨户读取 403、未确认删除 409、外部提示词注入被隔离）",
        False,
        f"越权与注入测试异常：{exc}",
    )

  # 验收项 4：输出 XSS 转义、日志隐私脱敏与恶意回归评测集沉淀
  try:
    gw3 = mod.SecurityGateway(
        valid_tokens={"tok_alice": "user_alice", "tok_bob": "user_bob"},
        resource_owners={"doc_alice_01": "user_alice", "doc_bob_01": "user_bob"},
        per_ip_limit=20,
        per_user_daily_limit=20,
    )
    xss_case = next(c for c in attacks if c["id"] == "ATK-05")
    pii_case = next(c for c in attacks if c["id"] == "ATK-06")
    r_xss = gw3.handle_request(xss_case)
    r_pii = gw3.handle_request(pii_case)
    safe_html = str(r_xss.get("safe_html") or "")
    audit_log = str(r_pii.get("audit_log") or "")

    suite = mod.export_regression_suite(attacks)
    categories = {item.get("category") for item in suite}
    required_cats = {
        "unauthenticated",
        "idor_cross_tenant",
        "high_risk_unconfirmed",
        "prompt_injection",
        "xss_escape",
    }

    check4_ok = (
        "<script>" not in safe_html
        and "&lt;script&gt;" in safe_html
        and 'onerror="' not in safe_html
        and "javascript:" not in safe_html.lower()
        and "13800138000" not in audit_log
        and "ops_team@example.org" not in audit_log
        and "FAKE_TEST_KEY_DO_NOT_USE_" not in audit_log
        and len(suite) >= 5
        and required_cats.issubset(categories)
        and all(item.get("passed") is True and bool(item.get("evidence")) for item in suite)
    )
    v.check(
        "输出 XSS 转义、日志隐私脱敏与回归评测集导出（恶意用例 100% 留证入库）",
        check4_ok,
        "请用 html.escape 转义模型输出并阻断 javascript: 链接，脱敏日志中的手机号/邮箱/测试密钥，并在 export_regression_suite 中导出全部恶意样本的实测证据。",
    )
  except Exception as exc:
    v.check(
        "输出 XSS 转义、日志隐私脱敏与回归评测集导出（恶意用例 100% 留证入库）",
        False,
        f"XSS 转义与回归集导出测试异常：{exc}",
    )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
