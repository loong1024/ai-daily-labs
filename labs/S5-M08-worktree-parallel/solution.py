"""S5-M08 标准参考实现：git worktree 双会话物理隔离并行开发、审查合入与无痕清理编排器。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete

GIT_CMD_PREFIX = [
    "git",
    "-c",
    "user.name=AID Lab Bot",
    "-c",
    "user.email=aid-lab@example.local",
    "-c",
    "commit.gpgsign=false",
]

FORBIDDEN_ENV_MARKERS = ("PROD_", "PRODUCTION_", "LIVE_", "_LIVE_", "MASTER_SECRET")


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


def _run_git(cwd: pathlib.Path, *args: str) -> str:
  proc = subprocess.run(
      [*GIT_CMD_PREFIX, *args],
      cwd=cwd,
      env={
          **os.environ,
          "GIT_TERMINAL_PROMPT": "0",
          "GIT_EDITOR": "true",
      },
      capture_output=True,
      text=True,
      check=False,
  )
  if proc.returncode != 0:
    raise RuntimeError(f"git {' '.join(args)} 失败: {proc.stderr.strip() or proc.stdout.strip()}")
  return proc.stdout.strip()


def _run_unittest(project_dir: pathlib.Path) -> tuple[bool, str]:
  proc = subprocess.run(
      [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
      cwd=project_dir,
      env={
          **os.environ,
          "PYTHONPATH": str(project_dir),
          "PYTHONDONTWRITEBYTECODE": "1",
      },
      capture_output=True,
      text=True,
      check=False,
  )
  detail = (proc.stderr or proc.stdout).strip()
  return proc.returncode == 0, detail


def check_task_orthogonality(
    task_a: WorktreeTask,
    task_b: WorktreeTask,
    locked_contracts: list[str],
) -> OrthogonalityResult:
  """预检两个并行任务的文件集合是否正交，且未修改已锁死在 main 的共享契约。"""
  files_a = set(task_a.target_files)
  files_b = set(task_b.target_files)
  overlap = sorted(files_a & files_b)
  locked_hits = sorted((files_a | files_b) & set(locked_contracts))

  if overlap or locked_hits:
    reasons: list[str] = []
    if overlap:
      reasons.append(f"存在重叠修改文件 {overlap}")
    if locked_hits:
      reasons.append(f"触碰了已锁死的共享契约 {locked_hits}（须先在 main 单独提交锁死）")
    return OrthogonalityResult(
        is_orthogonal=False,
        overlapping_files=overlap,
        locked_contract_violations=locked_hits,
        reason="；".join(reasons),
    )

  return OrthogonalityResult(
      is_orthogonal=True,
      overlapping_files=[],
      locked_contract_violations=[],
      reason="双任务修改范围完全正交，且共享契约保持只读锁死。",
  )


def build_minimal_test_env(raw_env_text: str) -> str:
  """遵循最小权限原则生成 worktree 专用测试 .env，剔除所有生产敏感变量。"""
  kept: dict[str, str] = {}
  for raw_line in raw_env_text.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, val = line.split("=", 1)
    key = key.strip()
    val = val.strip()
    upper_key = key.upper()
    if any(marker in upper_key for marker in FORBIDDEN_ENV_MARKERS):
      continue
    kept[key] = val

  kept["APP_ENV"] = "test"
  kept["WORKTREE_ISOLATED"] = "1"
  return "\n".join(f"{k}={v}" for k, v in kept.items()) + "\n"


def _attach_test_runtime(target_dir: pathlib.Path, shared_deps_dir: pathlib.Path, clean_env_text: str) -> None:
  """为工作树挂载共享依赖缓存与最小化测试 .env。"""
  dep_link = target_dir / ".venv_shared"
  if not dep_link.exists() and not dep_link.is_symlink():
    try:
      os.symlink(shared_deps_dir, dep_link, target_is_directory=True)
    except OSError:
      shutil.copytree(shared_deps_dir, dep_link)
  (target_dir / ".env").write_text(clean_env_text, encoding="utf-8")


def _detach_test_runtime(target_dir: pathlib.Path) -> None:
  """移除挂载的未跟踪测试 .env、共享依赖软链接及字节码缓存，确保 git worktree remove 干净放行。"""
  env_file = target_dir / ".env"
  if env_file.exists() or env_file.is_symlink():
    env_file.unlink()
  dep_link = target_dir / ".venv_shared"
  if dep_link.is_symlink():
    dep_link.unlink()
  elif dep_link.is_dir():
    shutil.rmtree(dep_link)
  for cache_dir in (
      target_dir / "__pycache__",
      target_dir / "app" / "__pycache__",
      target_dir / "tests" / "__pycache__",
  ):
    if cache_dir.is_dir():
      shutil.rmtree(cache_dir)


def _review_scope_with_ai(task_a: WorktreeTask, task_b: WorktreeTask) -> dict[str, Any]:
  """调用三模自适应接口（默认回退确定性离线 Mock）复核双线并行拆分摘要。"""
  messages = [
      {
          "role": "system",
          "content": "你是并行开发架构顾问，请确认两个正交 worktree 任务的边界并输出 JSON：{\"approved\": true, \"note\": \"...\"}。",
      },
      {
          "role": "user",
          "content": f"Task A ({task_a.branch}): {task_a.target_files}\nTask B ({task_b.branch}): {task_b.target_files}",
      },
  ]
  resp = chat_complete(
      messages,
      mock_fn=lambda _m: json.dumps(
          {"approved": True, "note": "两个任务目录完全正交，可安全启用双 git worktree 并行会话。"},
          ensure_ascii=False,
      ),
      response_json=True,
  )
  cleaned = resp.strip()
  if cleaned.startswith("```"):
    lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
    cleaned = "\n".join(lines).strip()
  try:
    return json.loads(cleaned)
  except json.JSONDecodeError:
    return {"approved": True, "note": cleaned}


def run_parallel_worktree_workflow(
    repo_dir: pathlib.Path,
    workspace_root: pathlib.Path,
    shared_deps_dir: pathlib.Path,
    raw_env_text: str,
    task_a: WorktreeTask,
    task_b: WorktreeTask,
    locked_contracts: list[str],
) -> dict[str, Any]:
  """执行标准 git worktree 并行开发、独立单测、合入 main 全量回归与 100% 无痕清理。"""
  orth = check_task_orthogonality(task_a, task_b, locked_contracts)
  if not orth.is_orthogonal:
    raise ValueError(f"任务不满足并行正交条件：{orth.reason}")

  ai_scope_review = _review_scope_with_ai(task_a, task_b)
  clean_env = build_minimal_test_env(raw_env_text)
  initial_main_sha = _run_git(repo_dir, "rev-parse", "HEAD")

  wt_a = workspace_root / task_a.worktree_slug
  wt_b = workspace_root / task_b.worktree_slug

  # 1. 同时创建两个物理隔离但共享 Git 历史的兄弟工作树
  _run_git(repo_dir, "worktree", "add", "-b", task_a.branch, str(wt_a), "main")
  _run_git(repo_dir, "worktree", "add", "-b", task_b.branch, str(wt_b), "main")

  both_coexisted = wt_a.is_dir() and wt_b.is_dir()
  git_pointer_files_verified = (wt_a / ".git").is_file() and (wt_b / ".git").is_file()

  # 2. 为两个隔离工作树补齐共享依赖与脱敏最小化 .env，并同时写入各自任务代码
  _attach_test_runtime(wt_a, shared_deps_dir, clean_env)
  _attach_test_runtime(wt_b, shared_deps_dir, clean_env)

  for rel_path, content in task_a.file_updates.items():
    dst = wt_a / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")

  for rel_path, content in task_b.file_updates.items():
    dst = wt_b / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")

  # 验证双会话各自改码期间，主目录 main 工作区零污染、零切分支干扰
  main_status_mid = _run_git(repo_dir, "status", "--porcelain")
  main_sha_mid = _run_git(repo_dir, "rev-parse", "HEAD")
  main_untouched = (main_status_mid == "") and (main_sha_mid == initial_main_sha)

  # 3. 两个工作树各自独立跑通单测并提交到各自特性分支
  ok_a, err_a = _run_unittest(wt_a)
  ok_b, err_b = _run_unittest(wt_b)
  wt_tests = {
      task_a.name: ok_a,
      task_b.name: ok_b,
  }
  if not all(wt_tests.values()):
    raise RuntimeError(f"隔离工作树单测未通过：{wt_tests} | {err_a} | {err_b}")

  _run_git(wt_a, "add", *task_a.target_files)
  _run_git(wt_a, "commit", "-m", task_a.commit_message)

  _run_git(wt_b, "add", *task_b.target_files)
  _run_git(wt_b, "commit", "-m", task_b.commit_message)

  # 4. 回到主仓将两个特性分支干净合入 main，并运行全量回归测试
  _run_git(repo_dir, "merge", "--no-ff", task_a.branch, "-m", f"Merge {task_a.branch}")
  _run_git(repo_dir, "merge", "--no-ff", task_b.branch, "-m", f"Merge {task_b.branch}")

  _attach_test_runtime(repo_dir, shared_deps_dir, clean_env)
  try:
    main_merged_tests_passed, merged_err = _run_unittest(repo_dir)
    if not main_merged_tests_passed:
      raise RuntimeError(f"合入 main 后全量测试未通过：{merged_err}")
  finally:
    _detach_test_runtime(repo_dir)

  # 5. 无痕清理临时 worktree 目录与已合并的临时特性分支（git branch -d 强制校验已合入）
  for wt_dir, branch in ((wt_a, task_a.branch), (wt_b, task_b.branch)):
    _detach_test_runtime(wt_dir)
    if _run_git(wt_dir, "status", "--porcelain") != "":
      raise RuntimeError(f"{wt_dir} 仍存在未提交改动，拒绝强制清理")
    _run_git(repo_dir, "worktree", "remove", str(wt_dir))
    _run_git(repo_dir, "branch", "-d", branch)

  _run_git(repo_dir, "worktree", "prune")

  return {
      "ai_scope_review": ai_scope_review,
      "both_coexisted": both_coexisted,
      "git_pointer_files_verified": git_pointer_files_verified,
      "main_untouched_during_parallel_dev": main_untouched,
      "worktree_tests_passed": wt_tests,
      "main_merged_tests_passed": main_merged_tests_passed,
      "cleanup_completed": (not wt_a.exists()) and (not wt_b.exists()),
  }
