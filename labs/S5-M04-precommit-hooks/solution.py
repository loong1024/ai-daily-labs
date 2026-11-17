#!/usr/bin/env python3
"""S5-M04 Solution：双道安全硬护栏与绕过纵深防御参考实现（兼容 Agent PreToolUse stdin 协议）。"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
import sys
from typing import Any

SAFE_ENV_TEMPLATES = {
    ".env.example",
    ".env.sample",
    ".env.template",
}

SENSITIVE_BASENAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "credentials",
    "application_default_credentials.json",
}

SENSITIVE_EXTENSIONS = (".pem", ".key", ".p12", ".pfx")

HARDCODED_SECRET_RE = re.compile(
    r"""(?ix)
    \b(?:API_KEY|API_SECRET|SECRET_KEY|ACCESS_TOKEN|DB_PASSWORD|PRIVATE_TOKEN)\b
    \s*[:=]\s*
    ["']([^"'\n]{12,})["']
    """
)

PIPE_TO_SHELL_RE = re.compile(
    r"""\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b""",
    re.IGNORECASE,
)


def _normalize_candidate_path(raw_path: str, workspace_root: str) -> str:
    cleaned = raw_path.strip().strip("\"'")
    if not cleaned:
        return ""
    if cleaned == "~" or cleaned.startswith("~/"):
        cleaned = "/home/user" + cleaned[1:]
    elif cleaned.startswith("$HOME/") or cleaned.startswith("${HOME}/"):
        suffix = cleaned.split("/", 1)[1]
        cleaned = f"/home/user/{suffix}"
    if not cleaned.startswith("/"):
        cleaned = posixpath.join(workspace_root, cleaned)
    return posixpath.normpath(cleaned)


def _check_sensitive_path(raw_path: str, workspace_root: str) -> tuple[bool, str, str]:
    norm = _normalize_candidate_path(raw_path, workspace_root)
    if not norm:
        return False, "", ""

    base = posixpath.basename(norm)
    lower_base = base.lower()

    if lower_base in SAFE_ENV_TEMPLATES:
        return False, "", ""

    if lower_base == ".env" or lower_base.startswith(".env."):
        return (
            True,
            f"禁止读取或修改敏感环境配置文件 '{raw_path}'（规范化路径：{norm}）。",
            "请改为查看公开模板文件 .env.example 了解变量名，并让开发者自行在本地配置密钥。",
        )

    if (
        "/.ssh/" in norm
        or "/.aws/" in norm
        or "/.config/gcloud/" in norm
        or lower_base in SENSITIVE_BASENAMES
        or lower_base.endswith(SENSITIVE_EXTENSIONS)
    ):
        return (
            True,
            f"禁止访问私钥或云凭证文件 '{raw_path}'（规范化路径：{norm}）。",
            "请勿读取宿主机私钥或云凭证；如需联调请使用 mock 对象或向用户确认测试沙箱环境变量名。",
        )

    return False, "", ""


def _split_shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _is_dangerous_rm_target(target: str) -> bool:
    cleaned = target.strip().strip("\"'")
    if cleaned in {"/", "/*", "~", "~/", "$HOME", "${HOME}", "$HOME/", "${HOME}/", "..", "../"}:
        return True
    if cleaned.startswith(("~/", "$HOME/", "${HOME}/")):
        return True
    if cleaned.startswith("/"):
        norm = posixpath.normpath(cleaned)
        if norm in {"/", "/home", "/Users", "/root", "/etc", "/usr", "/var"}:
            return True
    return False


def _inspect_shell_command(command: str, workspace_root: str) -> tuple[bool, str, str]:
    if PIPE_TO_SHELL_RE.search(command):
        return (
            True,
            "检测到远程脚本直接通过管道交由 Shell 执行（curl/wget | sh），存在任意代码执行风险。",
            "请先将脚本下载到临时文件并审阅内容与校验和，征得用户确认后再执行。",
        )

    segments = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)
    for seg in segments:
        tokens = _split_shell_tokens(seg)
        if not tokens:
            continue

        if tokens[0] == "git" and len(tokens) >= 2:
            sub = tokens[1]
            rest = set(tokens[2:])
            if sub == "push" and (
                "--force" in rest
                or "-f" in rest
                or any(tok.startswith("--force=") for tok in rest)
                or any(tok.startswith("+") for tok in rest)
            ):
                return (
                    True,
                    "禁止执行 git push 强制推送（--force / -f / +refspec），防止覆盖远端协作历史。",
                    "请改推新功能分支提交 PR，或在确认无人协作的个人分支上由人工评估 --force-with-lease。",
                )
            if sub == "reset" and "--hard" in rest:
                return (
                    True,
                    "禁止执行 git reset --hard，该操作会不可逆地抹除工作区未提交修改。",
                    "如需暂存现场请改用 git stash push -u，或先创建备份分支再由开发者人工确认。",
                )

        if tokens[0] == "rm":
            flags = [t for t in tokens[1:] if t.startswith("-")]
            targets = [t for t in tokens[1:] if not t.startswith("-")]
            is_recursive = any(("r" in f.lower() or f == "--recursive") for f in flags)
            if is_recursive and any(_is_dangerous_rm_target(t) for t in targets):
                return (
                    True,
                    f"禁止对根目录或家目录执行递归删除命令：'{seg}'。",
                    "请将清理范围严格限定在当前工作区构建子目录（如 ./dist/build_cache），并先用 ls 核对路径。",
                )

        for tok in tokens[1:]:
            candidates = [tok.split("=", 1)[1]] if tok.startswith("-") and "=" in tok else ([] if tok.startswith("-") else [tok])
            for cand in candidates:
                blocked, reason, remediation = _check_sensitive_path(cand, workspace_root)
                if blocked:
                    return blocked, reason, remediation

    return False, "", ""


def evaluate_pre_tool_use(
    event: dict[str, Any],
    workspace_root: str = "/workspace/order-service",
) -> dict[str, Any]:
    """第一道护栏：工具调用前路径规范化防泄漏与高危 Shell 拦截。"""
    tool_name = str(event.get("tool_name", "")).strip()
    tool_input = event.get("tool_input") or {}

    if tool_name in {"Read", "Write", "Edit", "MultiEdit"}:
        for key in ("file_path", "path", "target_file"):
            if key in tool_input and tool_input[key]:
                blocked, reason, remediation = _check_sensitive_path(str(tool_input[key]), workspace_root)
                if blocked:
                    return {
                        "decision": "block",
                        "exit_code": 2,
                        "reason": reason,
                        "remediation": remediation,
                    }

    if tool_name in {"Bash", "run_command", "Shell"}:
        cmd = str(tool_input.get("command", ""))
        blocked, reason, remediation = _inspect_shell_command(cmd, workspace_root)
        if blocked:
            return {
                "decision": "block",
                "exit_code": 2,
                "reason": reason,
                "remediation": remediation,
            }

    return {
        "decision": "allow",
        "exit_code": 0,
        "reason": "ok",
        "remediation": "",
    }


def run_post_edit_guard(
    changed_files: list[str],
    file_contents: dict[str, str],
    raw_linter_lines: list[str],
    max_summary_lines: int = 5,
) -> dict[str, Any]:
    """第二道护栏：仅针对改动文件执行防硬编码密钥扫描与 ≤5 行 Lint 摘要压缩。"""
    changed_set = {posixpath.normpath(p) for p in changed_files}
    secret_findings: list[str] = []

    for rel_path in changed_files:
        norm_rel = posixpath.normpath(rel_path)
        content = file_contents.get(rel_path, file_contents.get(norm_rel, ""))
        for lineno, line in enumerate(content.splitlines(), 1):
            if HARDCODED_SECRET_RE.search(line):
                secret_findings.append(
                    f"{norm_rel}:{lineno}: 检测到疑似硬编码密钥赋值，请改用 os.environ 读取并在 .env.example 中声明变量名"
                )

    relevant_lint: list[str] = []
    for ln in raw_linter_lines:
        prefix = ln.split(":", 1)[0].strip()
        if posixpath.normpath(prefix) in changed_set:
            relevant_lint.append(ln.strip())

    all_issues = secret_findings + relevant_lint
    if not all_issues:
        return {
            "passed": True,
            "secret_findings": [],
            "summary_lines": [],
        }

    cap = max(1, max_summary_lines)
    if len(all_issues) <= cap:
        summary_lines = all_issues
    else:
        kept = all_issues[: cap - 1]
        remaining = len(all_issues) - len(kept)
        summary_lines = [*kept, f"... 另有 {remaining} 条改动文件检查项已折叠（请先修复上述问题后复测）"]

    return {
        "passed": False,
        "secret_findings": secret_findings,
        "summary_lines": summary_lines,
    }


def build_bypass_defense_plan(bypass_vectors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """绕过攻防复盘：剖析文本黑名单盲区并匹配系统级隔离与最小权限补救措施。"""
    playbook_by_category: dict[str, tuple[str, str]] = {
        "dynamic_string_or_interpreter_read": (
            "命令字面量被拆分为 '.e'+'nv' 动态拼接或编码，静态关键词/正则无法在不执行代码的前提下穷举所有等价表达式。",
            "使用 DevContainer / 容器沙箱隔离运行环境，绝不将真实生产 .env 挂载进 Agent 工作目录；本地联调仅注入低额度、可随时吊销的测试专用临时密钥。",
        ),
        "symlink_alias_indirection": (
            "工具入参字面路径看似普通文档名（不含 .env 或 id_rsa），仅靠路径字符串规范化（normpath）不解析文件系统真实 inode 目标会漏放软链接。",
            "在文件访问层使用 Path.resolve(strict=False) 校验真实物理路径必须位于工作区根目录内，并通过操作系统文件权限（chmod 600 / 独立低权限 UID）隔离宿主机敏感目录。",
        ),
        "indirect_test_runner_execution": (
            "执行的终端命令本身是完全合法的白名单指令（如 pytest），恶意或越界文件读取隐藏在被调用的 Python 测试源码内部，命令级 Hook 不可见。",
            "将测试运行器置于无敏感凭证、限制外网出口的沙箱容器中执行，并用测试替身（Mock/Fake）替代真实云凭证。",
        ),
        "git_plus_refspec_force_push": (
            "Git 支持通过前导加号 '+HEAD:refs/heads/main' 或配置 remote.*.push 触发非快进强推，字面上完全不出现 '--force' 或 '-f' 标志。",
            "除了在 Hook 中补充拦截 '+refspec' 外，必须在 GitHub/GitLab 服务端开启主干分支保护（Branch Protection：禁止 Force Push、强制 PR Review 与状态检查）。",
        ),
    }

    records: list[dict[str, str]] = []
    for vec in bypass_vectors:
        cat = str(vec.get("category", ""))
        why_fails, remediation = playbook_by_category.get(
            cat,
            (
                "纯文本黑名单只能匹配已知字面模式，无法覆盖等价语义变形、间接脚本调用或别名映射。",
                "下沉到容器/目录权限隔离（不挂载真实凭证）、最小权限临时测试密钥与服务端权限门禁。",
            ),
        )
        records.append(
            {
                "id": str(vec.get("id", "")),
                "category": cat,
                "why_regex_fails": why_fails,
                "isolation_remediation": remediation,
            }
        )
    return records


def main() -> int:
    """支持作为真实 PreToolUse Hook 脚本从 stdin 读取事件 JSON 并返回退出码 0 或 2。"""
    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    event = json.loads(raw)
    result = evaluate_pre_tool_use(event)
    if result["decision"] == "block":
        msg = f"[HOOK BLOCKED] {result['reason']}"
        if result.get("remediation"):
            msg += f" | 建议做法：{result['remediation']}"
        print(msg, file=sys.stderr)
        return int(result["exit_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
