"""Domain service orchestrating idempotent order refunds."""
from __future__ import annotations

from dataclasses import dataclass
from models.ledger_entry import LedgerEntry, LedgerRepository


@dataclass(frozen=True)
class RefundRequest:
    order_id: str
    amount_cents: int
    idempotency_key: str


class RefundService:
    def __init__(self, repo: LedgerRepository) -> None:
        self._repo = repo

    def submit_refund(self, req: RefundRequest) -> LedgerEntry:
        if req.amount_cents <= 0:
            raise ValueError("refund amount_cents must be positive")
        existing = self._repo.find_by_idempotency_key(req.idempotency_key)
        if existing is not None:
            return existing
        return self._repo.record_reversal(
            order_id=req.order_id,
            amount_cents=req.amount_cents,
            idempotency_key=req.idempotency_key,
        )


class NightlySettlementJob:
    """Downstream consumer coupled to RefundService.submit_refund."""

    def replay_pending_refunds(self, service: RefundService, batch: list[RefundRequest]) -> int:
        completed = 0
        for item in batch:
            entry = service.submit_refund(item)
            if entry.status == "REVERSED":
                completed += 1
        return completed
