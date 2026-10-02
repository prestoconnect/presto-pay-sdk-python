from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from presto_pay import PaymentStatus

MAX_WEBHOOK_HISTORY = 50

PAID_AND_STILL_OPEN = frozenset(
    {
        PaymentStatus.AUTHORISED,
        PaymentStatus.PENDING_REVERSE,
        PaymentStatus.PENDING_REFUND,
        PaymentStatus.PARTIAL_REFUNDED,
    }
)
AFTER_PAYMENT = PAID_AND_STILL_OPEN | {PaymentStatus.REVERSED, PaymentStatus.REFUNDED}


def can_change_status(current: str | None, new: str) -> bool:
    if current == new:
        return False
    if current in (None, PaymentStatus.PENDING_AUTHORISE):
        return True
    if current in PAID_AND_STILL_OPEN:
        return new in AFTER_PAYMENT
    return False


@dataclass(frozen=True, slots=True)
class CheckoutRecord:
    txn_ref_num: str
    display_desc: str
    page_title: str | None
    amount_minor_units: int
    currency_code: str
    selected_payment_method: str | None
    receipt_name: str | None
    receipt_email: str | None
    payment_ref_num: str | None
    payment_status: str | None
    initiated_at: datetime


@dataclass(frozen=True, slots=True)
class StatusChange:
    changed: bool
    fulfil: bool


@dataclass(frozen=True, slots=True)
class WebhookRecord:
    txn_ref_num: str
    event_code: str
    payment_status: str | None
    success: bool
    amount_minor_units: int
    currency_code: str
    received_at: datetime


class ActivityStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._checkouts: dict[str, CheckoutRecord] = {}
        self._webhooks: deque[WebhookRecord] = deque(maxlen=MAX_WEBHOOK_HISTORY)
        self._order_statuses: dict[str, str] = {}

    def save_checkout(self, record: CheckoutRecord) -> None:
        with self._lock:
            self._checkouts[record.txn_ref_num] = record
            if record.payment_status:
                self._order_statuses.setdefault(record.txn_ref_num, record.payment_status)

    def find_checkout(self, txn_ref_num: str) -> CheckoutRecord | None:
        with self._lock:
            return self._checkouts.get(txn_ref_num)

    def apply_payment_status(self, txn_ref_num: str, status: str) -> StatusChange:
        # A real store makes this one conditional UPDATE on the orders table, so that only one of the
        # return page and the webhook finalises the order.
        with self._lock:
            current = self._order_statuses.get(txn_ref_num)
            if not can_change_status(current, status):
                return StatusChange(changed=False, fulfil=False)
            self._order_statuses[txn_ref_num] = status
            paid_now = status == PaymentStatus.AUTHORISED and current in (None, PaymentStatus.PENDING_AUTHORISE)
            return StatusChange(changed=True, fulfil=paid_now)

    def order_status(self, txn_ref_num: str) -> str | None:
        with self._lock:
            return self._order_statuses.get(txn_ref_num)

    def record_webhook(self, record: WebhookRecord) -> None:
        with self._lock:
            self._webhooks.appendleft(record)

    def recent_webhooks(self) -> list[WebhookRecord]:
        with self._lock:
            return list(self._webhooks)
