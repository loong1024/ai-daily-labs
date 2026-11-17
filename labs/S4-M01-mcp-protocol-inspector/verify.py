#!/usr/bin/env python3
"""S4-M01 自动化验收脚本：验证 MCP 三类原语拆解、沙箱越权拦截与 Schema 防呆改造。"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from types import ModuleType
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_module(path: pathlib.Path) -> ModuleType:
  spec = importlib.util.spec_from_file_location("s4_m01_target", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{path}")
  mod = importlib.util.module_from_spec(spec)
  sys.modules["s4_m01_target"] = mod
  spec.loader.exec_module(mod)
  return mod


def _has_enum_and_bound(schema: dict[str, Any]) -> tuple[bool, bool]:
  props = schema.get("properties", {}) if isinstance(schema, dict) else {}
  has_enum = any(isinstance(v, dict) and len(v.get("enum", [])) >= 2 for v in props.values())
  has_max = any(isinstance(v, dict) and isinstance(v.get("maximum"), (int, float)) for v in props.values())
  return has_enum, has_max


def main() -> int:
  v = LabVerifier("S4-M01", "MCP 三类原语拆解、目录白名单沙箱与 Schema 防呆体检")
  impl_path = target_file(LAB_DIR, "starter.py", "solution.py")

  try:
    mod = _load_module(impl_path)
  except Exception as exc:
    v.check("加载目标实现模块", False, f"导入 {impl_path.name} 失败（{type(exc).__name__}: {exc}），请先修复语法错误。")
    return v.finish()

  traces_payload = json.loads((LAB_DIR / "fixtures" / "inspector_traces.json").read_text(encoding="utf-8"))
  sandbox_payload = json.loads((LAB_DIR / "fixtures" / "sandbox_cases.json").read_text(encoding="utf-8"))
  schemas_payload = json.loads((LAB_DIR / "fixtures" / "messy_tool_schemas.json").read_text(encoding="utf-8"))

  # 验收项 1：MCP 三类原语对照记录表（控制主体 + URI/名称 + -32602 报错与反模式识别）
  primitive_report: dict[str, Any] = {}
  try:
    primitive_report = mod.build_primitive_comparison_table(traces_payload["traces"])
    rows = primitive_report.get("rows", [])
    by_method = {r.get("jsonrpc_method"): r for r in rows if isinstance(r, dict)}
    controllers_ok = (
        by_method.get("tools/call", {}).get("controller") == "model"
        and by_method.get("resources/read", {}).get("controller") == "application"
        and by_method.get("prompts/get", {}).get("controller") == "user"
    )
    primitives_named = {r.get("primitive") for r in rows} >= {"Tools", "Resources", "Prompts"}
    uri_extracted = "file:///tmp/mcp-demo/sprint_notes.md" in str(
        by_method.get("resources/read", {}).get("identifier", "")
    )
    errors_recorded = any(
        e.get("code") == -32602 for e in primitive_report.get("error_observations", []) if isinstance(e, dict)
    )
    anti_pattern_recorded = any(
        ap.get("recommended_primitive") == "Resources"
        for ap in primitive_report.get("anti_patterns", [])
        if isinstance(ap, dict)
    )
    v.check(
        "MCP 三类原语控制方（model/application/user）与错误/反模式拆解",
        bool(controllers_ok and primitives_named and uri_extracted and errors_recorded and anti_pattern_recorded),
        "请在 build_primitive_comparison_table 中准确映射 Tools(model)、Resources(application, 提取 uri)、Prompts(user)，并记录 -32602 参数错误与静态文档误塞入 Tool 的反模式。",
    )
  except Exception as exc:
    v.check(
        "MCP 三类原语控制方（model/application/user）与错误/反模式拆解",
        False,
        f"调用 build_primitive_comparison_table 抛出异常（{type(exc).__name__}: {exc}）。",
    )

  # 验收项 2：Filesystem 目录白名单放行与四类越权攻击拦截实测
  sandbox_records: list[dict[str, Any]] = []
  try:
    with tempfile.TemporaryDirectory(prefix="aid_s4m01_") as tmp_str:
      base = pathlib.Path(tmp_str)
      sandbox_root = base / sandbox_payload["sandbox_root_name"]
      (sandbox_root / "docs").mkdir(parents=True, exist_ok=True)
      (sandbox_root / "hello.txt").write_text("MCP Sandbox Demo\n", encoding="utf-8")
      (sandbox_root / "docs" / "architecture.md").write_text("# MCP Gateway\n", encoding="utf-8")

      sibling_secret_dir = base / "mcp-demo-secrets"
      sibling_secret_dir.mkdir(parents=True, exist_ok=True)
      (sibling_secret_dir / "credentials.env").write_text(
          sandbox_payload["outside_fixture_secret"] + "\n", encoding="utf-8"
      )
      outside_conf = base.parent / f"outside_{base.name}.conf"
      outside_conf.write_text("SECRET=FAKE_TEST_KEY_DO_NOT_USE_12345\n", encoding="utf-8")

      try:
        # 构造指向沙箱外敏感文件的符号链接，验证软链逃逸拦截
        os.symlink(outside_conf, sandbox_root / "escape_symlink.conf")
        all_matched = True
        for case in sandbox_payload["cases"]:
          if case["case_id"] == "SB03":
            target_path = sandbox_root / ".." / outside_conf.name
          else:
            target_path = base / case["rel_from_base"]
          res = mod.evaluate_filesystem_access(
              target_path,
              [sandbox_root],
              operation=case["operation"],
              read_only=case["read_only"],
          )
          res_with_id = {"case_id": case["case_id"], **res}
          sandbox_records.append(res_with_id)
          if bool(res.get("allowed")) != bool(case["expected_allowed"]):
            all_matched = False
          if not case["expected_allowed"] and res.get("reason_code") != case["expected_reason"]:
            all_matched = False
      finally:
        outside_conf.unlink(missing_ok=True)

    v.check(
        "Filesystem 目录白名单放行与 ../ 穿越、前缀欺骗、软链逃逸、只读写入拦截",
        all_matched and len(sandbox_records) == len(sandbox_payload["cases"]),
        "请改用 Path.resolve() + is_relative_to() 替代字符串 startswith，并区分 SYMLINK_ESCAPE、OUTSIDE_ALLOWLIST 与 READ_ONLY_VIOLATION。",
    )
  except Exception as exc:
    v.check(
        "Filesystem 目录白名单放行与 ../ 穿越、前缀欺骗、软链逃逸、只读写入拦截",
        False,
        f"沙箱访问校验执行异常（{type(exc).__name__}: {exc}）。",
    )

  # 验收项 3：3 个坏设计工具的防呆 Schema 体检与重构对比清单
  schema_upgrades: list[dict[str, Any]] = []
  try:
    schema_upgrades = mod.build_schema_upgrade_plan(schemas_payload["tools"])
    count_ok = isinstance(schema_upgrades, list) and len(schema_upgrades) >= 3
    names_upgraded = count_ok and all(
        isinstance(item, dict)
        and item.get("before_name") != item.get("after_name")
        and bool(item.get("after_name"))
        and len(str(item.get("boundary_note", "")).strip()) >= 15
        and len(item.get("issues", [])) >= 2
        for item in schema_upgrades[:3]
    )
    after_names = [item.get("after_name") for item in schema_upgrades[:3] if isinstance(item, dict)]
    unique_names = len(set(after_names)) == len(after_names)

    constraints_ok = count_ok
    for item in schema_upgrades[:3] if count_ok else []:
      schema = item.get("upgraded_schema", {})
      example = item.get("foolproof_example", {})
      has_enum, has_max = _has_enum_and_bound(schema)
      req_fields = schema.get("required", []) if isinstance(schema, dict) else []
      req_satisfied = bool(req_fields) and isinstance(example, dict) and all(k in example for k in req_fields)
      if not (has_enum and has_max and req_satisfied and schema.get("additionalProperties") is False):
        constraints_ok = False

    v.check(
        "3 个工具的防呆 Schema 升级（具体名称不重叠、enum 下拉化、分页 maximum 上限与示例）",
        bool(names_upgraded and unique_names and constraints_ok),
        "请为 do_data、manage_files、query_tickets 重构具体不重叠的新名称，补充用途与禁用边界（boundary_note）、enum 枚举约束、maximum 分页上限、additionalProperties=False 及合法的 foolproof_example。",
    )
  except Exception as exc:
    v.check(
        "3 个工具的防呆 Schema 升级（具体名称不重叠、enum 下拉化、分页 maximum 上限与示例）",
        False,
        f"调用 build_schema_upgrade_plan 抛出异常（{type(exc).__name__}: {exc}）。",
    )

  # 验收项 4：汇总生成完整 Markdown 体检对照报告
  try:
    report_md = mod.render_inspector_report(primitive_report, sandbox_records, schema_upgrades)
    has_sections = (
        isinstance(report_md, str)
        and "Tools" in report_md
        and "Resources" in report_md
        and "Prompts" in report_md
        and "OUTSIDE_ALLOWLIST" in report_md
        and "SYMLINK_ESCAPE" in report_md
        and all(str(item.get("after_name", "")) in report_md for item in schema_upgrades[:3] if item.get("after_name"))
    )
    v.check(
        "结构化《MCP 三类原语对照记录表》与安全体检报告渲染完整性",
        bool(has_sections and len(report_md) >= 500),
        "请在 render_inspector_report 中输出包含三类原语对照表、沙箱放行/拒绝记录表及 3 个工具改进前后 Schema 对比的完整 Markdown 报告。",
    )
  except Exception as exc:
    v.check(
        "结构化《MCP 三类原语对照记录表》与安全体检报告渲染完整性",
        False,
        f"调用 render_inspector_report 抛出异常（{type(exc).__name__}: {exc}）。",
    )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
