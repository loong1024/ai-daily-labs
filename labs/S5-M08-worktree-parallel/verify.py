#!/usr/bin/env python3
"""S5-M08 量化验收脚本：在真实临时 Git 仓库中验证正交预检、最小化 .env、双 worktree 并行测试、合入与无痕清理。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

GIT_PREFIX = [
    "git",
    "-c",
    "user.name=AID Verifier",
    "-c",
    "user.email=verifier@example.local",
    "-c",
    "commit.gpgsign=false",
]


def _load_target_module() -> Any:
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  spec = importlib.util.spec_from_file_location("s5_m08_target", mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = module
  spec.loader.exec_module(module)
  return module


def _git(cwd: pathlib.Path, *args: str) -> str:
  proc = subprocess.run([*GIT_PREFIX, *args], cwd=cwd, capture_output=True, text=True, check=True)
  return proc.stdout.strip()


def _seed_git_repo(repo_dir: pathlib.Path, seed_files: dict[str, str]) -> None:
  repo_dir.mkdir(parents=True, exist_ok=True)
  _git(repo_dir, "init")
  _git(repo_dir, "checkout", "-B", "main")
  for rel_path, content in seed_files.items():
    file_path = repo_dir / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
  _git(repo_dir, "add", ".")
  _git(repo_dir, "commit", "-m", "chore: lock OrderRecord contract and seed baseline on main")


def main() -> None:
  _ = (chat_complete, use_solution)
  v = LabVerifier("S5-M08", "git worktree 物理隔离双会话并行实验（依赖复用 + 最小 .env + 无痕清理）")

  spec_data = json.loads((LAB_DIR / "fixtures" / "parallel_tasks_spec.json").read_text(encoding="utf-8"))
  dirty_env = (LAB_DIR / "fixtures" / "dirty_env_sample.env").read_text(encoding="utf-8")
  locked_contracts: list[str] = spec_data["locked_contracts"]

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("加载目标模块", False, f"导入 starter/solution 失败：{exc}")
    v.finish()
    return

  def _make_task(raw: dict[str, Any]) -> Any:
    return mod.WorktreeTask(
        name=raw["name"],
        branch=raw["branch"],
        worktree_slug=raw["worktree_slug"],
        commit_message=raw["commit_message"],
        target_files=list(raw["target_files"]),
        file_updates=dict(raw.get("file_updates", {})),
    )

  task_a = _make_task(spec_data["orthogonal_pair"]["task_a"])
  task_b = _make_task(spec_data["orthogonal_pair"]["task_b"])
  task_c = _make_task(spec_data["conflicting_pair"]["task_c"])
  task_d = _make_task(spec_data["conflicting_pair"]["task_d"])

  # Check 1: 并行前正交性与共享契约锁死预检
  try:
    orth_good = mod.check_task_orthogonality(task_a, task_b, locked_contracts)
    orth_bad = mod.check_task_orthogonality(task_c, task_d, locked_contracts)
    ok_check1 = bool(
        orth_good.is_orthogonal
        and not orth_bad.is_orthogonal
        and "app/exporter.py" in orth_bad.overlapping_files
        and "app/contracts.py" in orth_bad.locked_contract_violations
    )
  except Exception:
    ok_check1 = False
  v.check(
      "并行前正交预检通过正交任务对，且准确拦截重叠文件与未锁死契约修改",
      ok_check1,
      "请在 check_task_orthogonality() 中计算 target_files 交集（overlapping_files）并检查是否触碰 locked_contracts（如 app/contracts.py）。",
  )

  # Check 2~4 在真实临时 Git 仓库中端到端执行
  with tempfile.TemporaryDirectory(prefix="aid_s5_m08_") as tmp_str:
    tmp_root = pathlib.Path(tmp_str)
    repo_dir = tmp_root / "main-repo"
    shared_deps_dir = tmp_root / "shared_venv_cache"
    shared_deps_dir.mkdir(parents=True, exist_ok=True)
    (shared_deps_dir / "site_packages_marker.json").write_text(
        json.dumps({"ready": True, "source": "shared_venv_cache"}), encoding="utf-8"
    )
    _seed_git_repo(repo_dir, spec_data["seed_files"])

    # Check 2: 最小化测试 .env 脱敏 + 双 worktree 隔离单测通过
    workflow_report: dict[str, Any] = {}
    workflow_err = ""
    try:
      clean_env = mod.build_minimal_test_env(dirty_env)
      env_sanitized = (
          "APP_ENV=test" in clean_env
          and "TEST_SANDBOX_TOKEN=FAKE_TEST_KEY_DO_NOT_USE_12345" in clean_env
          and "PAGE_MAX_SIZE=100" in clean_env
          and "PROD_DB_PASSWORD" not in clean_env
          and "STRIPE_LIVE_SECRET" not in clean_env
          and "PRODUCTION_WEBHOOK_KEY" not in clean_env
      )
      workflow_report = mod.run_parallel_worktree_workflow(
          repo_dir=repo_dir,
          workspace_root=tmp_root,
          shared_deps_dir=shared_deps_dir,
          raw_env_text=dirty_env,
          task_a=task_a,
          task_b=task_b,
          locked_contracts=locked_contracts,
      )
    except Exception as exc:
      env_sanitized = False
      workflow_err = f"（执行异常：{exc}）"

    wt_tests = workflow_report.get("worktree_tests_passed", {})
    ok_check2 = bool(
        env_sanitized
        and workflow_report.get("both_coexisted") is True
        and workflow_report.get("git_pointer_files_verified") is True
        and workflow_report.get("main_untouched_during_parallel_dev") is True
        and wt_tests.get("export_csv") is True
        and wt_tests.get("fix_pagination") is True
    )
    v.check(
        "两个兄弟 git worktree 均剥离生产敏感变量、复用共享依赖并各自独立跑通测试且零污染 main",
        ok_check2,
        f"请完善 build_minimal_test_env() 剔除 PROD_*/LIVE_* 变量并设置 APP_ENV=test，且在 run_parallel_worktree_workflow() 中使用 git worktree add 创建双目录、挂载 .venv_shared 与 .env 并跑通各自 unittest。{workflow_err}",
    )

    # Check 3: 两个特性分支已干净合入 main 且合入后全量测试通过
    merged_exporter = (repo_dir / "tests" / "test_exporter.py").is_file()
    merged_paginator = (repo_dir / "tests" / "test_paginator.py").is_file()
    log_out = _git(repo_dir, "log", "--oneline", "-n", "6")
    ok_check3 = bool(
        merged_exporter
        and merged_paginator
        and workflow_report.get("main_merged_tests_passed") is True
        and "feat(export)" in log_out
        and "fix(pagination)" in log_out
    )
    v.check(
        "两个特性分支（feat/export 与 fix/pagination）已无冲突合入 main 且全量回归测试通过",
        ok_check3,
        "请在各自 worktree 提交后回到 main 执行 git merge --no-ff 合入两个特性分支，并在 main 上运行一次全量 unittest 校验。",
    )

    # Check 4: git worktree list 与 git branch 验证 100% 无痕清理
    wt_list_out = _git(repo_dir, "worktree", "list", "--porcelain")
    worktree_entries = [ln for ln in wt_list_out.splitlines() if ln.startswith("worktree ")]
    branches_out = _git(repo_dir, "branch", "--format=%(refname:short)")
    branches = [b.strip() for b in branches_out.splitlines() if b.strip()]
    wt_dirs_gone = not (tmp_root / task_a.worktree_slug).exists() and not (tmp_root / task_b.worktree_slug).exists()
    repo_clean = _git(repo_dir, "status", "--porcelain") == ""

    ok_check4 = bool(
        ok_check3
        and len(worktree_entries) == 1
        and branches == ["main"]
        and wt_dirs_gone
        and repo_clean
    )
    v.check(
        "执行 git worktree list 与 git branch 检查确认临时目录与临时分支已 100% 清理干净",
        ok_check4,
        f"请在合并验证后移除临时 .env/.venv_shared 软链，并调用 git worktree remove 与 git branch -d 清理两个临时工作树和分支（当前分支列表：{branches}，工作树数：{len(worktree_entries)}）。",
    )

  v.finish()


if __name__ == "__main__":
  main()
