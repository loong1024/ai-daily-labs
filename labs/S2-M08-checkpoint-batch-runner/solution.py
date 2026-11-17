"""S2-M08 Solution：支持并发限速、指数退避抖动、耐半行崩溃断点续跑与死信隔离的批处理标准实现。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import random
import sys
from typing import Any, Awaitable, Callable

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import chat_complete


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
            raw = chat_complete(
                [{"role": "user", "content": content.strip()}],
                mock_fn=lambda msgs: json.dumps(
                    {
                        "summary": msgs[-1]["content"][:24],
                        "category": str(record.get("source") or "general"),
                    },
                    ensure_ascii=False,
                ),
                response_json=True,
            )
            return json.loads(raw)
        finally:
            self.in_flight -= 1


def compute_item_key(record: dict[str, Any], prompt_version: str = "v1") -> str:
    rec_id = str(record.get("id") or "")
    content = "" if record.get("content") is None else str(record.get("content"))
    payload = f"{rec_id}\x1f{prompt_version}\x1f{content}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_completed_keys(output_path: pathlib.Path) -> set[str]:
    if not output_path.exists():
        return set()

    raw_text = output_path.read_text(encoding="utf-8", errors="replace")
    valid_lines: list[str] = []
    completed: set[str] = set()
    needs_rewrite = bool(raw_text and not raw_text.endswith("\n"))

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            needs_rewrite = True
            continue
        if isinstance(obj, dict) and isinstance(obj.get("item_key"), str):
            completed.add(obj["item_key"])
            valid_lines.append(stripped)
        else:
            needs_rewrite = True

    if needs_rewrite:
        cleaned = ("\n".join(valid_lines) + "\n") if valid_lines else ""
        output_path.write_text(cleaned, encoding="utf-8")

    return completed


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitError, TimeoutError, ConnectionError)):
        return True
    return getattr(exc, "status_code", None) in {429, 500, 502, 503, 504}


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dlq_path.parent.mkdir(parents=True, exist_ok=True)

    stub = SimulatedModelStub()
    fn = worker_fn or stub.process
    completed = load_completed_keys(output_path)
    pending = [r for r in records if compute_item_key(r, prompt_version) not in completed]

    sem = asyncio.Semaphore(max_concurrency)
    write_lock = asyncio.Lock()
    stats = {"written": 0, "skipped": len(records) - len(pending), "dlq": 0}

    with output_path.open("a", encoding="utf-8") as out_f, dlq_path.open("a", encoding="utf-8") as dlq_f:

        async def _handle_item(rec: dict[str, Any]) -> None:
            item_key = compute_item_key(rec, prompt_version)
            async with sem:
                attempts = 0
                while True:
                    attempts += 1
                    try:
                        res = await fn(rec)
                        row = {
                            "id": rec.get("id"),
                            "item_key": item_key,
                            "prompt_version": prompt_version,
                            "result": res,
                        }
                        async with write_lock:
                            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                            out_f.flush()
                        stats["written"] += 1
                        return
                    except Exception as exc:
                        if _is_retryable(exc) and attempts <= max_retries:
                            backoff = base_delay * (2 ** (attempts - 1)) + random.uniform(0.0, base_delay)
                            await asyncio.sleep(backoff)
                            continue
                        dlq_row = {
                            "id": rec.get("id"),
                            "item_key": item_key,
                            "prompt_version": prompt_version,
                            "attempts": attempts,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        async with write_lock:
                            dlq_f.write(json.dumps(dlq_row, ensure_ascii=False) + "\n")
                            dlq_f.flush()
                        stats["dlq"] += 1
                        return

        await asyncio.gather(*(_handle_item(r) for r in pending))

    return stats
