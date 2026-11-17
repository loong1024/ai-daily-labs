#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, target_file


def _load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("s2_m08_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    os.environ["AID_FORCE_MOCK"] = "1"
    v = LabVerifier("S2-M08", "异步批处理并发限速、断点续跑与死信隔离验收")
    mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
    fixture_path = LAB_DIR / "fixtures" / "batch_inputs.jsonl"

    try:
        mod = _load_module(mod_path)
        records = [
            json.loads(line)
            for line in fixture_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as exc:
        v.check("模块与样本加载", False, f"加载失败：{exc}")
        return v.finish()

    # 验收 1：SHA-256 幂等键包含 id + prompt_version + content
    try:
        k_v1 = mod.compute_item_key({"id": "rec-001", "content": "abc"}, "v1")
        k_v2 = mod.compute_item_key({"id": "rec-001", "content": "abc"}, "v2")
        k_diff = mod.compute_item_key({"id": "rec-001", "content": "xyz"}, "v1")
        key_ok = (
            isinstance(k_v1, str)
            and len(k_v1) == 64
            and all(c in "0123456789abcdef" for c in k_v1)
            and k_v1 != k_v2
            and k_v1 != k_diff
        )
    except Exception:
        key_ok = False
    v.check(
        "SHA-256 幂等指纹覆盖 ID、Prompt 版本与正文",
        key_ok,
        "请在 compute_item_key 中使用 hashlib.sha256(id + prompt_version + content) 返回 64 位十六进制摘要。",
    )

    # 验收 2 & 3：并发峰值 <= 5、429 指数退避自愈、28 正常 + 2 死信落盘
    concurrency_ok = False
    dlq_isolation_ok = False
    with tempfile.TemporaryDirectory() as tmp1:
        tmp_dir = pathlib.Path(tmp1)
        out_path = tmp_dir / "outputs.jsonl"
        dlq_path = tmp_dir / "dlq.jsonl"
        try:
            stub1 = mod.SimulatedModelStub(latency_sec=0.008, rate_limit_every=5)
            asyncio.run(
                mod.run_batch(
                    records,
                    out_path,
                    dlq_path,
                    worker_fn=stub1.process,
                    prompt_version="v1",
                    max_concurrency=5,
                    max_retries=3,
                    base_delay=0.005,
                )
            )
            retried_items = sum(1 for cnt in stub1.call_counts.values() if cnt >= 2)
            concurrency_ok = 1 <= stub1.max_observed_concurrency <= 5 and retried_items >= 5

            out_rows = (
                [json.loads(ln) for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if out_path.exists()
                else []
            )
            dlq_rows = (
                [json.loads(ln) for ln in dlq_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if dlq_path.exists()
                else []
            )
            dlq_ids = {r.get("id") for r in dlq_rows}
            dlq_isolation_ok = (
                len(out_rows) == 28
                and dlq_ids == {"rec-011", "rec-024"}
                and all(bool(r.get("error")) for r in dlq_rows)
            )
        except Exception:
            concurrency_ok = False
            dlq_isolation_ok = False

    v.check(
        "Semaphore(<=5) 并发限速与 429 错峰退避自愈",
        concurrency_ok,
        "请在 run_batch 中引入 asyncio.Semaphore(max_concurrency) 限制并发不超过 5，并对 RateLimitError 实现指数退避带抖动重试。",
    )
    v.check(
        "毒丸坏数据死信隔离（28 条正常落盘 + 2 条写入 dlq.jsonl）",
        dlq_isolation_ok,
        "请捕获毒丸坏数据与重试耗尽异常并写入 dlq.jsonl（含 error 原因），确保主流程不中断且产出 28 条正常结果。",
    )

    # 验收 4：耐半行残缺崩溃恢复与已完成 ID 零重复调用
    resume_ok = False
    with tempfile.TemporaryDirectory() as tmp2:
        tmp_dir2 = pathlib.Path(tmp2)
        out_path2 = tmp_dir2 / "outputs.jsonl"
        dlq_path2 = tmp_dir2 / "dlq.jsonl"
        try:
            pre_done = records[:10]
            seed_lines = [
                json.dumps(
                    {
                        "id": r["id"],
                        "item_key": mod.compute_item_key(r, "v1"),
                        "prompt_version": "v1",
                        "result": {"summary": "cached", "category": r["source"]},
                    },
                    ensure_ascii=False,
                )
                for r in pre_done
            ]
            # 模拟 Ctrl+C 强杀在文件末尾留下的未闭合半行残片（无结尾换行）
            corrupted_content = "\n".join(seed_lines) + '\n{"id": "rec-012", "item_key": "half_line_crash'
            out_path2.write_text(corrupted_content, encoding="utf-8")

            stub2 = mod.SimulatedModelStub(latency_sec=0.005, rate_limit_every=5)
            asyncio.run(
                mod.run_batch(
                    records,
                    out_path2,
                    dlq_path2,
                    worker_fn=stub2.process,
                    prompt_version="v1",
                    max_concurrency=5,
                    max_retries=3,
                    base_delay=0.005,
                )
            )
            zero_re_calls = all(stub2.call_counts.get(r["id"], 0) == 0 for r in pre_done)
            final_rows = [
                json.loads(ln)
                for ln in out_path2.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            resume_ok = zero_re_calls and len(final_rows) == 28
        except Exception:
            resume_ok = False

    v.check(
        "耐半行残缺崩溃恢复与断点续跑零重复调用",
        resume_ok,
        "请在 load_completed_keys 中用 try/except json.JSONDecodeError 跳过并清理残缺尾行，跳过已完成 item_key 避免重跑。",
    )

    return v.finish()


if __name__ == "__main__":
    main()
