#!/usr/bin/env python3
"""S5-M06 量化验收脚本：检验本地扫密配置、五维 Diff 排雷准确率、独立会话交叉互审与零误报门禁。"""

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

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

try:
  import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
  tomllib = None  # type: ignore[assignment]


def _load_target_module() -> Any:
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  spec = importlib.util.spec_from_file_location("s5_m06_target", mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = module
  spec.loader.exec_module(module)
  return module


def main() -> None:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S5-M06", "AI代码合并前排雷实操（扫密拦截 + 核对表 + 独立交叉互审）")

  pr_items = json.loads((LAB_DIR / "fixtures" / "trapped_pr_diffs.json").read_text(encoding="utf-8"))
  registry = json.loads((LAB_DIR / "fixtures" / "package_registry_snapshot.json").read_text(encoding="utf-8"))
  checklist_path = LAB_DIR / "fixtures" / "pre_merge_checklist.md"
  pr_by_id = {item["pr_id"]: item for item in pr_items}

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("加载目标模块", False, f"导入 starter/solution 语法或运行时出错：{exc}")
    v.finish()
    return

  # Check 1: Gitleaks 扫密配置与假密钥阻断能力
  try:
    toml_text = mod.render_gitleaks_toml()
    toml_valid = "[[rules]]" in toml_text and "FAKE_" in toml_text and "[allowlist]" in toml_text
    if toml_valid and tomllib is not None:
      parsed_toml = tomllib.loads(toml_text)
      toml_valid = len(parsed_toml.get("rules", [])) >= 2
    secret_hits_104 = mod.scan_secrets_like_gitleaks(pr_by_id["PR-104"]["diff"])
    secret_hits_106 = mod.scan_secrets_like_gitleaks(pr_by_id["PR-106"]["diff"])
    ok_check1 = bool(toml_valid and len(secret_hits_104) >= 2 and len(secret_hits_106) == 0)
  except Exception:
    ok_check1 = False
  v.check(
      "本地 Gitleaks 扫密配置有效且准确阻断测试假密钥（零误伤环境变量读取）",
      ok_check1,
      "请完善 render_gitleaks_toml() 输出合法 [[rules]] 与 [allowlist]，并在 scan_secrets_like_gitleaks() 中拦截 PR-104 的 FAKE_..._DO_NOT_USE_... 假密钥且放行 PR-106 的 os.environ.get。",
  )

  # Run full audit across all 6 PR samples safely
  reports: dict[str, Any] = {}
  audit_error = ""
  try:
    for item in pr_items:
      reports[item["pr_id"]] = mod.audit_pr_diff(item, registry)
  except Exception as exc:
    audit_error = str(exc)

  # Check 2: 测试断言放水 + 静默吞异常/误删校验排雷
  if audit_error:
    ok_check2 = False
  else:
    r101 = reports.get("PR-101")
    r102 = reports.get("PR-102")
    r101_rules = {f.rule_id for f in getattr(r101, "findings", [])}
    r102_cats = set(getattr(r102, "categories_flagged", []))
    ok_check2 = bool(
        r101
        and r101.decision == "BLOCK"
        and "test_integrity" in r101.categories_flagged
        and len(r101_rules) >= 2
        and r102
        and r102.decision == "BLOCK"
        and "diff_hygiene" in r102_cats
        and len(r102.findings) >= 2
    )
  v.check(
      "精准揪出“测试断言放水/跳过”（PR-101）与“静默吞异常/误删签名校验”（PR-102）",
      ok_check2,
      f"请实现 audit_test_integrity()（同时识别 skip 标记与严格断言退化为 is not None）和 audit_diff_hygiene()（识别 except: pass 与误删 verify_hmac_signature）。{audit_error}",
  )

  # Check 3: 幻觉依赖包 + SQL 注入/管理接口缺鉴权拦截
  if audit_error:
    ok_check3 = False
  else:
    r103 = reports.get("PR-103")
    r105 = reports.get("PR-105")
    ok_check3 = bool(
        r103
        and r103.decision == "BLOCK"
        and "dependency" in r103.categories_flagged
        and r105
        and r105.decision == "BLOCK"
        and "security" in r105.categories_flagged
        and len(r105.findings) >= 2
    )
  v.check(
      "精准拦截“幻觉冗余依赖包”（PR-103）与“SQL 拼接注入 + 后台路由缺鉴权”（PR-105）",
      ok_check3,
      "请实现 audit_dependencies() 对照 package_registry_snapshot.json 拦截 fastjson-ultra-parse，并实现 audit_security_boundaries() 拦截 f-string SQL 拼接、/admin 漏挂 require_admin_auth 及暴露 traceback。",
  )

  # Check 4: 无历史包袱独立 AI 交叉互审
  if audit_error:
    ok_check4 = False
  else:
    cross_101 = getattr(reports.get("PR-101"), "cross_review", {})
    raw_msgs_101 = cross_101.get("prompt_messages", [])
    msgs_101_text = "\n".join(
        str(m.get("content", "")) if isinstance(m, dict) else str(m)
        for m in raw_msgs_101
    )
    msgs_101_serialized = json.dumps(raw_msgs_101, ensure_ascii=False)
    author_excuse = pr_by_id["PR-101"]["author_note"]
    cross_106 = getattr(reports.get("PR-106"), "cross_review", {})
    ok_check4 = bool(
        cross_101.get("reviewer_mode") == "isolated_clean_session"
        and author_excuse not in msgs_101_text
        and author_excuse not in msgs_101_serialized
        and pr_by_id["PR-101"]["diff"].splitlines()[3] in msgs_101_text
        and cross_101.get("verdict") == "BLOCK"
        and len(cross_101.get("blind_spots_caught", [])) >= 1
        and cross_106.get("verdict") == "APPROVE"
    )
  v.check(
      "独立干净会话 AI 交叉互审已剥离作者自信话术并产出准确复核结论",
      ok_check4,
      "请在 build_clean_reviewer_messages() 中剔除 author_note（只传原始 Diff 与检查标准），并在 cross_review_with_clean_agent() 中返回 isolated_clean_session 模式的 BLOCK/APPROVE 与隐患列表。",
  )

  # Check 5: 零误报对照门禁与可复用清单模板落盘
  checklist_text = checklist_path.read_text(encoding="utf-8") if checklist_path.is_file() else ""
  checklist_complete = all(
      dim in checklist_text for dim in ("【测试】", "【diff】", "【依赖】", "【安全】", "【理解】")
  )
  if audit_error:
    ok_check5 = False
  else:
    trapped_blocked = sum(
        1 for pid in ("PR-101", "PR-102", "PR-103", "PR-104", "PR-105")
        if reports.get(pid) and reports[pid].decision == "BLOCK"
    )
    r106 = reports.get("PR-106")
    clean_approved = bool(r106 and r106.decision == "APPROVE" and len(r106.findings) == 0)
    ok_check5 = bool(checklist_complete and trapped_blocked == 5 and clean_approved)
  v.check(
      "全量 5 份埋雷 PR 100% 阻断、合规对照 PR-106 零误报通过且核对清单齐全",
      ok_check5,
      "请确保 PR-101~PR-105 均返回 BLOCK，同时对使用标准库 decimal + 参数校验 + 环境变量的合规样本 PR-106 返回 APPROVE（零误报）。",
  )

  v.finish()


if __name__ == "__main__":
  main()
