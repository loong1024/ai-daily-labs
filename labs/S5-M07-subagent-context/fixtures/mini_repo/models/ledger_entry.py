"""Ledger persistence model and repository."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    order_id: str
    amount_cents: int
    idempotency_key: str
    status: str


class LedgerRepository:
    def __init__(self) -> None:
        self._by_key: dict[str, LedgerEntry] = {}

    def find_by_idempotency_key(self, key: str) -> LedgerEntry | None:
        return self._by_key.get(key)

    def record_reversal(self, order_id: str, amount_cents: int, idempotency_key: str) -> LedgerEntry:
        entry = LedgerEntry(
            entry_id=f"LED-{len(self._by_key) + 1:04d}",
            order_id=order_id,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
            status="REVERSED",
        )
        self._by_key[idempotency_key] = entry
        return entry


def run_ledger_smoke_check() -> bool:
    """Existing smoke check convention for ledger idempotency."""
    repo = LedgerRepository()
    entry = repo.record_reversal("ORD-100", 2500, "IDEM-1")
    return repo.find_by_idempotency_key("IDEM-1") == entry
