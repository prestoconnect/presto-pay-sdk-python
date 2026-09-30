# Payments and errors

`presto.payments` has four operations: `init`, `query`, `reverse` and `refund`. Each one takes keyword arguments
named after the gateway's wire fields in snake_case, so `txnRefNum` becomes `txn_ref_num`. Amounts are `int`
minor currency units. A `float` or `Decimal` is rejected, because `1200.0` would sign as a different string
than `1200`. Unset optional fields are left out of the request, never sent as `null`.

```python
from presto_pay import LineItem, PaymentMethod, TxnType

payment = presto.payments.init(
    presto_mrn=presto_mrn,
    txn_type=TxnType.WEB_PAY,
    txn_ref_num="order-123",
    display_desc="Order 123",
    amount=10_000,
    currency_code="MYR",
    redirect_url="https://shop.example/return/order-123",
    notify_url="https://shop.example/presto/notify",
    allowed_payment_methods=[PaymentMethod.WALLET, PaymentMethod.CARD],
    item_list=[LineItem(item_desc="Tea", quantity=2, unit_amount=500, total_amount=1_000)],
    session_validity=datetime.now(UTC) + timedelta(minutes=15),
)

current = presto.payments.query(presto_mrn=presto_mrn, txn_ref_num="order-123")

presto.payments.reverse(
    presto_mrn=presto_mrn,
    payment_ref_num=current.payment_ref_num,
    reversal_ref_num="order-123-reversal",
    remark="Customer cancelled",
)

presto.payments.refund(
    presto_mrn=presto_mrn,
    payment_ref_num=current.payment_ref_num,
    refund_ref_num="order-123-refund-1",
    remark="Customer request",
    amount=2_500,  # omit for a full refund
)
```

`init` validates its input before sending anything:

- `qr_value` and `payer_ref_num` are mutually exclusive.
- `currency_code` is required when `amount` is set.
- `redirect_url` is required for `TxnType.WEB_PAY`.

`query` needs `payment_ref_num` or `txn_ref_num`, and so does `reverse`. A validation failure raises
`PrestoPayConfigError`, whose `field` names the argument.

Documented field lengths, such as 50 characters for `txn_ref_num`, are not enforced by default because the
gateway doesn't enforce them either. `strict=True` enforces them.

## Results

Each operation returns a frozen dataclass: `InitResult`, `QueryResult`, `ReverseResult` or `RefundResult`.

- **Empty values.** An optional field that the gateway sends empty, as either `""` or `null`, is `None`. The
  gateway uses the two interchangeably.
- **List fields.** `payment_details` and `refund_details` are tuples of `PaymentDetail` / `RefundDetail`. On the
  wire they are JSON strings.
- **Dates.** Date fields stay strings. `parse_gateway_timestamp()` turns them into aware `datetime`s.
- **Raw body.** `result.raw` holds the full wire body, including fields the SDK doesn't model yet.

Status and method fields are plain `str`. Compare them against the constants:

```python
if current.payment_status == PaymentStatus.AUTHORISED:
    ...
PaymentMethod.try_parse(detail.method)  # None for a method this SDK version doesn't know
```

`reverse` on a payment that is still `PendingAuthorise` cancels it: the resulting status is `Cancelled`.
`refund` in that state fails with `1227`. A refund can be requested for any payment method, and the gateway
decides the outcome. Some methods are settled manually or offline, so an accepted refund request doesn't mean
the refund is complete. Query the payment before treating it as final.

## When the outcome is unknown

For `init`, `reverse` and `refund`, the following failures leave the outcome unknown:

- a transport failure after the request may have been sent;
- an HTTP 5xx;
- a response that fails parsing, signature verification, field mapping or the echo check.

These errors have `may_have_taken_effect=True` and a `reconcile_by` key you can pass straight to `query`:

```python
from presto_pay import PrestoPayError

try:
    result = presto.payments.refund(...)
except PrestoPayError as exc:
    if not exc.may_have_taken_effect or exc.reconcile_by is None:
        raise
    current = presto.payments.query(**exc.reconcile_by)
```

`reconcile_by` is always set for an ambiguous `init`, `reverse` or `refund`. It is `None` for
`presto.raw.post`, which can't know the lookup key for an endpoint the SDK doesn't model.

The same failures on `query` mean nothing happened, and the SDK retries them automatically. A business error
(`success: false`) means nothing happened, with one exception: `1203` on `init` proves a record exists but not
its state, so it is flagged for reconciliation. `may_have_succeeded(exc)` is a helper for handlers that catch
`Exception`.

## Business errors

`PrestoPayApiError` with `kind="business"` carries `error_code` and `error_message`. The `ErrorCode` constants
cover the documented codes. Unknown codes pass through as strings. Three codes add extra context:

- **`1005`**: the request `ts` is outside the gateway's 15-minute window. `clock_offset` holds the difference
  in seconds between the gateway clock and yours. Fix the host clock (NTP). All timestamps use a fixed UTC+08:00
  offset, whatever the host's time zone.
- **`1006` / `1007`**: the gateway couldn't verify the request signature. `canonical` holds the string the SDK
  signed. Check that the private key matches the certificate registered with Presto.
- **`1203`**: see above.
