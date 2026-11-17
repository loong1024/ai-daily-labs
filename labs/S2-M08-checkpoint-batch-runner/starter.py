"""S2-M08 Starter：异步批处理基线骨架（含并发、退避、半行续跑与死信隔离待修复项）。"""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any, Awaitable, Callable


class RateLimitError(RuntimeError):
    """本地测试桩模拟的 HTTP 429 限流异常。"""

    def __init__(self, message: str = "429 Too Many Requests") -> None:
        super().__init__(message)
        self.status_code = 429


class SimulatedModelStub:
    """内置本地测试桩：统计并发峰值与调用次数，模拟 20% 概率 429 限流及毒丸校验报错。"""

    def __init__(self, latency_sec: float = 0.01, rate_limit_every: int = 5) -> None:
        self.latency_sec = latency_sec
        self.rate_limit_every = rate_limit_every
        self.in_flight = 0
        self.max_observed_concurrency = 0
        self.call_counts: dict[str, int] = {}
        self._first_attempt_seq = 0

    async def process(self, record: dict[str, Any]) -> dict[str, Any]:
        rec_id = str(record.get("id") or "unknown")
        self.call_counts[rec_id] = self.call_counts.get(rec_id, 0) + 1
        attempt = self.call_counts[rec_id]

        self.in_flight += 1
        if self.in_flight > self.max_observed_concurrency:
            self.max_observed_concurrency = self.in_flight
        try:
            await asyncio.sleep(self.latency_sec)
            content = record.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Invalid or empty content in {rec_id}")
            if attempt == 1:
                self._first_attempt_seq += 1
                if self.rate_limit_every > 0 and self._first_attempt_seq % self.rate_limit_every == 0:
                    raise RateLimitError(f"Simulated 429 rate limit on {rec_id}")
            return {
                "summary": content.strip()[:24],
                "category": str(record.get("source") or "general"),
            }
        finally:
            self.in_flight -= 1


def compute_item_key(record: dict[str, Any], prompt_version: str = "v1") -> str:
    # TODO 1: 使用 sha256(id + prompt_version + content) 生成 64 位十六进制幂等键
    return str(record.get("id") or "")


def load_completed_keys(output_path: pathlib.Path) -> set[str]:
    # TODO 2: 对每行加 try/except 容错跳过残缺半行，并清理损坏尾行防止后续追加粘连
    if not output_path.exists():
        return set()
    completed: set[str] = set()
    for line in output_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            completed.add(obj["item_key"])
    return completed


async def run_batch(
    records: list[dict[str, Any]],
    output_path: pathlib.Path,
    dlq_path: pathlib.Path,
    *,
    worker_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    prompt_version: str = "v1",
    max_concurrency: int = 5,
    max_retries: int = 3,
    base_delay: float = 0.01,
) -> dict[str, int]:
    # TODO 3: 补全 Semaphore(max_concurrency)、429 指数退避加抖动重试、逐条 flush() 与 dlq.jsonl 死信隔离
    stub = SimulatedModelStub()
    fn = worker_fn or stub.process
    completed = load_completed_keys(output_path)
    pending = [r for r in records if compute_item_key(r, prompt_version) not in completed]

    results = await asyncio.gather(*(fn(r) for r in pending))
    with output_path.open("a", encoding="utf-8") as out_f:
        for rec, res in zip(pending, results):
            row = {
                "id": rec.get("id"),
                "item_key": compute_item_key(rec, prompt_version),
                "prompt_version": prompt_version,
                "result": res,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"written": len(results), "skipped": len(records) - len(pending), "dlq": 0}
