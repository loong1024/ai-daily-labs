"""S5-M08 起点骨架：git worktree 双会话物理隔离并行编排器（待完善版）。

当前存在典型反模式缺陷：
1. check_task_orthogonality() 未拦截重叠文件与擅改 main 锁死契约文件的风险；
2. build_minimal_test_env() 把包含 PROD_* / *_LIVE_* 的敏感 .env 原样复制了出去；
3. run_parallel_worktree_workflow() 未使用 git worktree 创建共享历史的兄弟工作目录并链接 .venv_shared；
4. 收尾未执行无冲突合入与 git worktree remove + git branch -d 无痕清理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


@dataclass
class WorktreeTask:
  name: str
  branch: str
  worktree_slug: str
  commit_message: str
  target_files: list[str]
  file_updates: dict[str, str] = field(default_factory=dict)


@dataclass
class OrthogonalityResult:
  is_orthogonal: bool
  overlapping_files: list[str] = field(default_factory=list)
  locked_contract_violations: list[str] = field(default_factory=list)
  reason: str = ""


def check_task_orthogonality(
    task_a: WorktreeTask,
    task_b: WorktreeTask,
    locked_contracts: list[str],
) -> OrthogonalityResult:
  """TODO(Step 2): 检查两个并行任务是否正交（无重叠修改文件，且未触碰已锁死的共享契约）。"""
  _ = (task_a, task_b, locked_contracts)
  return OrthogonalityResult(is_orthogonal=True, reason="TODO: 尚未检查文件交集与共享契约锁死状态")


def build_minimal_test_env(raw_env_text: str) -> str:
  """TODO(Step 3.1): 生成仅含最小化测试变量的 .env 文本。

  要求：
  - 剔除所有 PROD_*、PRODUCTION_*、*_LIVE_* 等生产敏感变量；
  - 保留安全测试项（如 PAGE_MAX_SIZE、EXPORT_DELIMITER、TEST_SANDBOX_TOKEN）；
  - 强制设置 APP_ENV=test 并标记 WORKTREE_ISOLATED=1。
  """
  return raw_env_text


def run_parallel_worktree_workflow(
    repo_dir: pathlib.Path,
    workspace_root: pathlib.Path,
    shared_deps_dir: pathlib.Path,
    raw_env_text: str,
    task_a: WorktreeTask,
    task_b: WorktreeTask,
    locked_contracts: list[str],
) -> dict[str, Any]:
  """TODO(Step 3 & Step 4): 使用 git worktree 完成双任务隔离开发、各自单测、合入 main 与无痕清理。"""
  _ = (repo_dir, workspace_root, shared_deps_dir, raw_env_text, task_a, task_b, locked_contracts, chat_complete)
  return {
      "both_coexisted": False,
      "git_pointer_files_verified": False,
      "main_untouched_during_parallel_dev": False,
      "worktree_tests_passed": {task_a.name: False, task_b.name: False},
      "main_merged_tests_passed": False,
      "cleanup_completed": False,
  }
