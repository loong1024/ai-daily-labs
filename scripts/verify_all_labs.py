#!/usr/bin/env python3
"""并行批量验收全部 66 个实验目录。

用法：
  python3 scripts/verify_all_labs.py --solution     # 验证全部 66 个实验的 solution 均 100% PASS (exit 0)
  python3 scripts/verify_all_labs.py --audit-both   # 同时审计：starter 默认处于待完成状态(exit 1) 且 solution 100% 通过(exit 0)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LABS_DIR = ROOT / "labs"


def run_one(lab_dir: pathlib.Path, audit_both: bool) -> tuple[str, bool, str]:
  verify_py = lab_dir / "verify.py"
  readme_md = lab_dir / "README.md"
  fixtures_dir = lab_dir / "fixtures"
  if not verify_py.is_file():
    return lab_dir.name, False, "缺少 verify.py"
  if not readme_md.is_file():
    return lab_dir.name, False, "缺少 README.md"
  if not fixtures_dir.is_dir() or not any(fixtures_dir.iterdir()):
    return lab_dir.name, False, "缺少非空 fixtures/ 测试样本目录"

  env = dict(os.environ, AID_FORCE_MOCK="1", PYTHONPATH=str(ROOT))
  sol = subprocess.run(
      [sys.executable, str(verify_py), "--solution"],
      cwd=str(lab_dir),
      env=env,
      capture_output=True,
      text=True,
      timeout=20,
  )
  if sol.returncode != 0:
    msg = (sol.stdout + "\n" + sol.stderr).strip()[-400:]
    return lab_dir.name, False, f"--solution 未通过 (code={sol.returncode}): {msg}"

  if audit_both:
    st = subprocess.run(
        [sys.executable, str(verify_py)],
        cwd=str(lab_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if st.returncode == 0:
      return lab_dir.name, False, "starter 在未修改前直接通过了验收（失去红绿闯关意义）"
    if "Traceback (most recent call last)" in st.stderr:
      return lab_dir.name, False, f"starter 验收抛出了未捕获异常:\n{st.stderr[-350:]}"

  return lab_dir.name, True, "OK"


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--solution", action="store_true", help="验证全部 solution 通过")
  ap.add_argument("--audit-both", action="store_true", help="验证 starter 为红灯提示且 solution 为绿灯通过")
  args = ap.parse_args()

  dirs = sorted(d for d in LABS_DIR.iterdir() if d.is_dir())
  if not dirs:
    print("ERROR: labs/ 下没有任何实验目录")
    return 1

  passed = 0
  failures: list[tuple[str, str]] = []
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
    futs = [ex.submit(run_one, d, args.audit_both) for d in dirs]
    for fut in concurrent.futures.as_completed(futs):
      name, ok, detail = fut.result()
      if ok:
        passed += 1
      else:
        failures.append((name, detail))

  failures.sort()
  print(f"== AI 日课实验仓批量验收：通过 {passed}/{len(dirs)} 个实验 ==")
  for name, detail in failures:
    print(f"❌ {name}: {detail}")
  return 0 if not failures else 1


if __name__ == "__main__":
  sys.exit(main())
