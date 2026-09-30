from __future__ import annotations

import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime

MAX_WEBHOOK_HISTORY = 50
MAX_REMEMBERED_EVENTS = 1000


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
class WebhookRecord:
    event_ref_num: str
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
        self._seen_events: OrderedDict[str, None] = OrderedDict()

    def save_checkout(self, record: CheckoutRecord) -> None:
        with self._lock:
            self._checkouts[record.txn_ref_num] = record

    def find_checkout(self, txn_ref_num: str) -> CheckoutRecord | None:
        with self._lock:
            return self._checkouts.get(txn_ref_num)

    def record_webhook(self, record: WebhookRecord) -> bool:
        with self._lock:
            if record.event_ref_num in self._seen_events:
                return False
            self._seen_events[record.event_ref_num] = None
            if len(self._seen_events) > MAX_REMEMBERED_EVENTS:
                self._seen_events.popitem(last=False)
            self._webhooks.appendleft(record)
            return True

    def recent_webhooks(self) -> list[WebhookRecord]:
        with self._lock:
            return list(self._webhooks)
