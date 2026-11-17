#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def main() -> int:
    v = LabVerifier("S2-M07", "CI 工作流权限与输入隔离概念结构验收")
    wf_path = target_file(LAB_DIR, "starter_workflow.yml", "solution_workflow.yml")
    fixture_path = LAB_DIR / "fixtures" / "issue_events.json"

    try:
        events_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        wf_text = wf_path.read_text(encoding="utf-8")
    except Exception as exc:
        v.check("配置文件与素材读取", False, f"读取失败：{exc}")
        return v.finish()

    samples = events_data.get("samples", []) if isinstance(events_data, dict) else []
    v.check(
        "占位事件素材结构完整",
        len(samples) >= 4,
        "请保持 fixtures/issue_events.json 中至少 4 条占位样本。",
    )

    has_permissions = "\npermissions:" in f"\n{wf_text}"
    v.check(
        "顶层显式声明最小权限配置块",
        has_permissions,
        "请在工作流 YAML 顶层显式声明 permissions 配置块以收敛默认令牌范围。",
    )

    has_env_boundary = "env:" in wf_text and "Baseline draft - hardening required" not in wf_text
    v.check(
        "外部输入经由 env 环境变量边界隔离",
        has_env_boundary,
        "请通过 env 字段绑定外部事件数据并移除未加固基线占位。",
    )

    return v.finish()


if __name__ == "__main__":
    main()
