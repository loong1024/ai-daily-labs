"""HTTP entry routes for order refund operations."""
from __future__ import annotations

from services.refund_service import RefundRequest, RefundService


def parse_refund_payload(body: dict) -> RefundRequest:
    order_id = str(body.get("order_id", "")).strip()
    amount_cents = int(body.get("amount_cents", 0))
    idempotency_key = str(body.get("idempotency_key", "")).strip()
    if not order_id or not idempotency_key:
        raise ValueError("order_id and idempotency_key are required")
    return RefundRequest(
        order_id=order_id,
        amount_cents=amount_cents,
        idempotency_key=idempotency_key,
    )


def post_order_refund(body: dict, service: RefundService) -> dict:
    """Entry route handler for POST /v2/orders/refund."""
    req = parse_refund_payload(body)
    entry = service.submit_refund(req)
    return {"refund_id": entry.entry_id, "status": entry.status}
