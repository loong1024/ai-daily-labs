#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
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


def main() -> int:
    v = LabVerifier("S5-M04", "口头禁令总失灵？90分钟搭建两道硬护栏与绕过攻防")

    code_path = target_file(LAB_DIR, "starter.py", "solution.py")
    try:
        mod = _load_module(code_path, "s5_m04_target")
        hook_bundle = json.loads((LAB_DIR / "fixtures" / "hook_events.json").read_text(encoding="utf-8"))
        post_batch = json.loads((LAB_DIR / "fixtures" / "post_edit_batch.json").read_text(encoding="utf-8"))
        bypass_vectors = json.loads((LAB_DIR / "fixtures" / "bypass_vectors.json").read_text(encoding="utf-8"))
    except Exception as exc:
        v.check("1. 模块语法与测试素材加载", False, f"加载 {code_path.name} 失败：{exc}")
        return v.finish()

    workspace_root = hook_bundle["workspace_root"]
    events = hook_bundle["events"]

    # 1. 校验敏感文件保护（含 ../ 规范化、~/.ssh 拦截，以及 .env.example 白名单放行）
    try:
        secret_file_ids = {"EV-01", "EV-02", "EV-03", "EV-06", "EV-07", "EV-08", "EV-09"}
        file_guard_errors: list[str] = []
        for item in events:
            if item["id"] not in secret_file_ids:
                continue
            res = mod.evaluate_pre_tool_use(item["event"], workspace_root=workspace_root)
            exp = item["expected_decision"]
            if res.get("decision") != exp:
                file_guard_errors.append(f"{item['id']}({item['desc']}) 期望 {exp}，实际 {res.get('decision')}")
                continue
            if exp == "block":
                if res.get("exit_code") != 2:
                    file_guard_errors.append(f"{item['id']} 拦截时 exit_code 应为 2")
                if len(str(res.get("reason", "")).strip()) < 8 or len(str(res.get("remediation", "")).strip()) < 8:
                    file_guard_errors.append(f"{item['id']} 拦截时缺少清晰的 reason 或替代做法 remediation")

        v.check(
            "1. 敏感文件保护护栏（路径规范化防穿越、拦截 .env/私钥、精准放行 .env.example）",
            len(file_guard_errors) == 0,
            f"请改进 {code_path.name} 的敏感路径判断逻辑：{'；'.join(file_guard_errors[:3])}。",
        )
    except Exception as exc:
        v.check(
            "1. 敏感文件保护护栏（路径规范化防穿越、拦截 .env/私钥、精准放行 .env.example）",
            False,
            f"调用 evaluate_pre_tool_use 进行文件保护检查时抛出异常：{exc}",
        )

    # 2. 校验高危 Shell 命令拦截与良性构建目录清理放行
    try:
        shell_ids = {"EV-04", "EV-05", "EV-10", "EV-11", "EV-12", "EV-13"}
        shell_errors: list[str] = []
        for item in events:
            if item["id"] not in shell_ids:
                continue
            res = mod.evaluate_pre_tool_use(item["event"], workspace_root=workspace_root)
            exp = item["expected_decision"]
            if res.get("decision") != exp:
                shell_errors.append(f"{item['id']}({item['desc']}) 期望 {exp}，实际 {res.get('decision')}")
                continue
            if exp == "block" and (
                res.get("exit_code") != 2 or len(str(res.get("remediation", "")).strip()) < 8
            ):
                shell_errors.append(f"{item['id']} 拦截时需返回 exit_code=2 并附带安全替代建议 remediation")

        v.check(
            "2. 高危 Shell 指令拦截（阻断强推/硬重置/删家目录/管道脚本，放行项目内缓存清理）",
            len(shell_errors) == 0,
            f"请补齐 {code_path.name} 对高危 Shell 命令的检查：{'；'.join(shell_errors[:3])}。",
        )
    except Exception as exc:
        v.check(
            "2. 高危 Shell 指令拦截（阻断强推/硬重置/删家目录/管道脚本，放行项目内缓存清理）",
            False,
            f"执行高危命令拦截校验时抛出异常：{exc}",
        )

    # 3. 校验改后检查：仅扫描改动文件 + 硬编码测试密钥拦截 + ≤5 行摘要
    try:
        post_errors: list[str] = []
        noisy = post_batch["noisy_lint_only_on_changed"]
        res_noisy = mod.run_post_edit_guard(
            noisy["changed_files"],
            noisy["file_contents"],
            noisy["raw_linter_lines"],
            max_summary_lines=5,
        )
        if res_noisy.get("secret_findings"):
            post_errors.append("未改动文件 legacy/old_messy.py 中的测试串不应算入本次改动密钥告警")
        summary_lines = res_noisy.get("summary_lines", [])
        if not (1 <= len(summary_lines) <= 5):
            post_errors.append(f"失败摘要必须控制在 1..5 行以内，当前返回了 {len(summary_lines)} 行")
        if any("legacy/old_messy.py" in ln for ln in summary_lines):
            post_errors.append("摘要中混入了未改动文件 legacy/old_messy.py 的 Lint 告警")

        leaked = post_batch["secret_leaked_in_changed_file"]
        res_leaked = mod.run_post_edit_guard(
            leaked["changed_files"],
            leaked["file_contents"],
            leaked["raw_linter_lines"],
            max_summary_lines=5,
        )
        if res_leaked.get("passed") is not False or not res_leaked.get("secret_findings"):
            post_errors.append("未能在改动文件 src/client.py 中拦截明文测试密钥赋值")

        v.check(
            "3. 编辑后增量检查（仅扫改动文件、拦截明文测试密钥、反馈严格 ≤5 行）",
            len(post_errors) == 0,
            f"请改进 {code_path.name} 中的 run_post_edit_guard：{'；'.join(post_errors)}。",
        )
    except Exception as exc:
        v.check(
            "3. 编辑后增量检查（仅扫改动文件、拦截明文测试密钥、反馈严格 ≤5 行）",
            False,
            f"调用 run_post_edit_guard 抛出异常：{exc}",
        )

    # 4. 校验真实 stdin 命令行钩子退出码协议 + 绕过纵深防御矩阵
    try:
        cli_and_bypass_errors: list[str] = []

        allow_proc = subprocess.run(
            [sys.executable, str(code_path)],
            input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": ".env.example"}}),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        if allow_proc.returncode != 0:
            cli_and_bypass_errors.append(f"命令行喂入 .env.example 期望退出码 0，实际为 {allow_proc.returncode}")

        block_proc = subprocess.run(
            [sys.executable, str(code_path)],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main -f"}}),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        if block_proc.returncode != 2 or not block_proc.stderr.strip():
            cli_and_bypass_errors.append(
                f"命令行喂入 'git push -f' 期望退出码 2 且 stderr 输出拦截说明，实际退出码={block_proc.returncode}"
            )

        plan = mod.build_bypass_defense_plan(bypass_vectors)
        if not isinstance(plan, list) or len(plan) < 2:
            cli_and_bypass_errors.append("build_bypass_defense_plan 至少需记录 2 种以上绕过示例与补救措施")
        else:
            valid_records = [
                r
                for r in plan
                if isinstance(r, dict)
                and len(str(r.get("why_regex_fails", "")).strip()) >= 15
                and len(str(r.get("isolation_remediation", "")).strip()) >= 20
            ]
            if len(valid_records) < 3:
                cli_and_bypass_errors.append("绕过复盘记录少于 3 条有效分析（需写清正则盲区原因与系统隔离/低权限密钥补救）")
            joined_remediation = " ".join(str(r.get("isolation_remediation", "")) for r in valid_records)
            if not (
                any(k in joined_remediation for k in ("容器", "沙箱", "权限", "隔离", "挂载"))
                and any(k in joined_remediation for k in ("临时", "低额", "低权限", "测试专用", "分支保护"))
            ):
                cli_and_bypass_errors.append("补救措施需同时涵盖‘容器/目录权限隔离’与‘低权限测试密钥/服务端保护’")

        v.check(
            "4. 命令行 stdin 退出码 2 协议实测与纯文本绕过纵深防御矩阵",
            len(cli_and_bypass_errors) == 0,
            f"请完善 {code_path.name} 的 CLI 协议与 build_bypass_defense_plan：{'；'.join(cli_and_bypass_errors)}。",
        )
    except Exception as exc:
        v.check(
            "4. 命令行 stdin 退出码 2 协议实测与纯文本绕过纵深防御矩阵",
            False,
            f"执行 CLI 单测与绕过复盘校验时抛出异常：{exc}",
        )

    return v.finish()


if __name__ == "__main__":
    raise SystemExit(main())
