# Presto Pay wire contract

The gateway protocol, written once for every Presto Pay SDK. It is language-neutral by construction: where an
SDK has to do something specific to its runtime to satisfy a rule here, that belongs in the SDK's own plan, not
in this document.

Normative sections are §1 to §10. Every rule is tagged:

| Tag | Meaning |
|-----|---------|
| **[C]** | Confirmed: in Presto's worked example, in a captured body that verifies, answered by Presto, or exercised against staging |
| **[U]** | Unconfirmed: believed to be gateway behaviour. Implement it, and expect staging to correct it |
| **[P]** | SDK policy. Not required by the gateway, but required of a conforming SDK so that all of them behave alike |

Changing a rule means changing the vectors in the same commit. An SDK pins this repository to a reviewed commit,
so a contract change is a visible update in each SDK rather than a silent drift.

## 1. Transport

- HTTPS `POST`, one JSON object per request and per response. Body bytes are UTF-8. **[C]**
- Base URLs: staging `https://presto-stg-ext.enovax.com`, production `https://pay-ext.prestouniverse.com`. **[C]**
- Header `Content-Type: application/json; charset=UTF-8` **[C]**; a `User-Agent` identifying the SDK and its
  version **[P]**; redirects are not followed **[P]**.

| Operation | Path | Safe to resend |
|-----------|------|----------------|
| init | `/v1/ext/payment/init` | No |
| query | `/v1/ext/payment/query` | Yes (read-only) |
| reverse | `/v1/ext/payment/reverse` | No |
| refund | `/v1/ext/payment/refund` | No |

Paths **[C]**. Resend safety: init is idempotent by `txnRefNum` — a resend returns the existing payment's
current status rather than an error (§9) **[C]** — and reverse/refund are treated conservatively (**[U]**) for
want of similar evidence.

## 2. Common request fields

| Field | Value |
|-------|-------|
| `mid` | Merchant ID, one per client configuration **[C]** |
| `prestoMrn` | Presto merchant reference. One `mid` can have several, so it is chosen per request **[C]** |
| `ts` | Request timestamp (§3), fresh for every attempt **[C]** |
| `signature` | Signature over all other fields (§4) **[C]** |

An optional field that is not set is **omitted**, never sent as `null` **[P]**. The gateway sends nulls and
canonicalizes them as the empty string (§4), so either form would verify; omitting keeps outgoing bodies to one
shape per request.

## 3. Timestamps

- Format `yyyyMMddHHmmss.SSS`, for example `20250423104500.000`, always at the fixed offset **UTC+08:00**
  regardless of where the host is or how it is configured. **[C]**
- Milliseconds are always three digits: 70 ms is `.070`. **[C]**
- The validity window for a request `ts` is **15 minutes**; outside it the gateway answers error `1005`. **[C]**
- Parsing is strict: exactly 18 characters, digits with a single `.` before the last three, and a real calendar
  date. A parser that rolls `20250230…` into 2 March is non-conforming. **[P]**
- `sessionValidity` on init uses the same format. **[U]**
- Date fields on responses other than `ts` use the same format **[C]**, but are passed to the caller as strings:
  only some are confirmed, and an unparseable date must not fail an otherwise valid response. **[P]**

Use a **fixed offset**, never a named zone. `Asia/Kuala_Lumpur` resolves to +08:00 today, and a signature is no
place to encode a political boundary.

Vectors: `vectors/timestamps.json`.

## 4. Signatures

### 4.1 Canonical string

From a flat JSON object:

1. Take every key except `signature`. **[C]**
2. Sort the keys by code point. **[C]** All known keys are ASCII, for which code point order, UTF-8 byte order
   and UTF-16 code unit order are identical — so a plain byte or code point sort is conforming in any language.
   A locale-aware or case-insensitive sort is not.
3. Render each value:

   | JSON value | Rendering |
   |------------|-----------|
   | string | the decoded string as-is: no quoting, no escaping **[C]** |
   | integer | decimal, no leading zeros, `-` for negatives **[C]** |
   | `true` / `false` | `true` / `false`, lowercase **[C]** |
   | `null` | the empty string, indistinguishable from `""` **[C]** |
   | array, object, non-integer number | cannot occur; reject the body (§5) **[C]** |

4. Join with `:`. **[C]** Values are not escaped, so a `:` inside a value is ambiguous by design. A present key
   with an empty value keeps its separator (`x::y`); an absent key contributes nothing.

Two consequences of the null rule are worth stating outright, because both have cost someone a day:

- A body whose alphabetically first key is null or empty produces a canonical string that **starts with `:`**.
- `{"a": null}` and `{"a": ""}` produce the same canonical string and therefore the same signature. Nothing
  downstream can tell them apart.

### 4.2 Algorithm

- `RSASSA-PKCS1-v1_5` with SHA-256 over the **UTF-8 bytes** of the canonical string; standard Base64 with
  padding. **[C]**
- Requests are signed with the merchant's private key. Responses and webhooks are verified with Presto's public
  key. **[C]**
- Presto signs for **all** merchants with one key, so a valid signature does not prove an event is yours (§7).
  **[C]**
- A signature that is not valid Base64 is a failed verification, not a distinct error. **[P]**

### 4.3 What is signed must be what is sent

The canonical string uses decoded values, so any valid JSON escaping is fine as long as the gateway decodes the
same strings that were signed **[C]**. `\u00e9` and a raw `é` are interchangeable; HTML-escaping `<` changes
nothing. What is *not* fine is a string the serializer will alter:

- Reject outgoing strings that cannot round-trip through UTF-8 — unpaired surrogates, or bytes that are not
  valid UTF-8, depending on how the language represents text. Serializers variously substitute U+FFFD, escape,
  or throw, and all three make the body disagree with the signature. **[P]**
- Send integers only. A float formats differently than it canonicalizes. **[C]**

Vectors: `vectors/canonical.json`, `vectors/signatures.json`. Two cases in `canonical.json` are real staging
captures with real signatures; they are the ones that make this section a fact rather than a reading.

## 5. JSON rules

**Incoming bodies** **[P]** unless noted.

- Must be a single JSON object. A top-level array or scalar is a malformed body.
- Duplicate keys resolve last-wins, and the object used for verification must be the same one used for field
  mapping, so that what was verified is what the caller reads.
- Integers must round-trip exactly, and the conforming bound is **±(2^53 − 1)** — the tightest of the four SDK
  runtimes. Outside it, reject rather than verify a rounded value. A runtime whose parser rounds silently
  (anything that decodes JSON numbers as doubles) must inspect the raw token, not the parsed value.
- Non-integer numbers, `NaN` and `Infinity` are rejected. Several parsers accept the latter two by default.
- Decode bytes as UTF-8.

> **Unspecified on purpose.** A number written `1.0` or `1e3` is integer-*valued* but not integer-*shaped*, and
> runtimes disagree: some parsers hand back an integer, others a float. Presto never sends either (§11 round 1
> answer 1), so the vectors contain no such case and SDKs are not required to agree. Do not add one without
> settling the rule at the token level first.

**Stringified arrays.** Every list field is a **JSON string containing an array**, never a native array, in both
directions **[C]**. They canonicalize as ordinary strings — brackets, quotes and all — and are parsed a second
time after verification. A captured query response carrying `"refundDetails": "[]"` and `"paymentDetails": "[]"`
verifies only when each renders as the literal two characters `[]`, so this is confirmed rather than inferred
**[C]**. An empty list arrives as `"[]"`, not as `""` **[C]**; whether a field can also be absent entirely is
**[U]**, so treat a missing field as an empty list.

| Field | Direction | Elements |
|-------|-----------|----------|
| `allowedPaymentMethods` | init request | payment method codes |
| `itemList` | init request | line items (§8) |
| `refundDetails` | query response | refund details (§8) |
| `paymentDetails` | query response, webhook | payment details (§8) |

An SDK exposes these as real lists; the string is an encoding detail that never reaches the caller. **[P]**

**Empty values on responses.** A successful response carries **every** documented field, using `""` or `null`
for the ones with no value **[C]**. The choice between the two is not stable: `userRefNum` arrives as `""` on
init and as `null` on query for the same payment, and one captured query response mixes nine nulls with five
empty strings across fields of the same kind — `reversalStatus` is `null` while `reversalDate` is `""` **[C]**.
Treat the two as one condition. So "optional" in §8 means *may be empty*, not *may be absent*:

- Those keys are in the signed body, so they are in the canonical string. Never strip them before verifying.
- Normalize `""` and `null` to the language's absent value when mapping optional fields, so nothing feeds `""`
  to a date parser or reads an empty `errorCode` as an error. A **required** field that arrives empty is a
  malformed body. **[P]**
- A business error is the opposite shape: `success`, `ts`, `errorCode`, `errorMessage` and `signature` only,
  with none of the payment fields. The two shapes are mapped separately rather than through one
  optional-everything type. **[P]**

## 6. Responses

In this order:

1. **Status not 200** — HTTP error. The body is unsigned and is not verified; details are in the
   `x-http-error-code` and `x-http-error` headers, matched case-insensitively, which are always set **[C]**.
   There is no rate limiting, so no 429 **[C]**.
2. **Parse** (§5). Failure is a malformed body.
3. **Signature** — missing or invalid is a signature error. This comes **before** `success`, because business
   errors are signed too. **[C]**
4. **`success`** — always present **[C]**. `false` is a business error carrying `errorCode` and `errorMessage`.
   Absent or non-boolean is a malformed body; nothing is defaulted.
5. **Map fields** (§8). A missing required field is a malformed body. A field documented as a string always
   arrives as a string **[C]**; an SDK may coerce a stray number or boolean to text rather than reject an
   authentic body after the operation took effect, but a strict mode must reject so staging reports it. **[P]**
6. **Echo check** — `prestoMrn`, and `txnRefNum` where present, must equal what was signed into the request. A
   mismatch is a response error. **[P]**

For `init`, `reverse` and `refund`, a status of 500 or above, or a failure at step 2, 3, 5 or 6 after a 200,
means **the operation may have taken effect**: reconcile with `query`. The same failures on `query` mean nothing
happened. An SDK decides this per operation where the error is raised, never by inspecting the error afterwards.
A `success: false` at step 4 means nothing happened. **[P]** (`1203` is a distinct case — see §9.)

### Error codes

Four-digit strings, open-ended; unknown codes pass through **[U]**. Load-bearing ones:

| Code | Meaning |
|------|---------|
| `1005` | Request `ts` outside the validity window — a clock problem, not a signing problem **[C]** |
| `1006`, `1007` | Signature invalid, or failed verification. The two do **not** distinguish a malformed signature from a well-formed one that did not verify **[C]** |
| `1201` | Invalid input **[C]** |
| `1203` | Meaning unconfirmed beyond "a payment record for this `txnRefNum` exists, in any state including a successful one." **Not** returned merely by resending `init` with an existing `txnRefNum` — that is idempotent instead (§9). **[U]** |
| `1212` | Payment not found **[U]** |

Full list **[U]**:

- **Request and auth:** 1001 invalid request path, 1002 invalid content type, 1003 missing master merchant
  reference, 1004 invalid timestamp format, 1005 exceeded validity period, 1006 invalid signature, 1007 signature
  verification failed, 1008 missing authorization header, 1009 invalid authorization header, 1010 invalid access
  token, 1011 access token validation error, 1012 invalid access token ownership, 1013 OAuth resource config
  error, 1014 missing OAuth scope, 1015 OAuth service unavailable.
- **Merchant:** 1100 general error, 1101 invalid input, 1102 invalid `mid`, 1103 master merchant info retrieval
  failed, 1104 master merchant info service unavailable, 1105 onboard processing failed, 1106 invalid merchant
  reference, 1107 document upload failed, 1108 missing document, 1109 record exists, 1110 profile not found,
  1111 invalid merchant txn type, 1112 file retry limit exceeded, 1113 merchant rejected.
- **Payment:** 1200 general error, 1201 invalid input, 1202 init failed, 1203 duplicate `txnRefNum`, 1204 QR
  value not recognised, 1205 QR value not bound, 1206 QR TOTP expired, 1207 QR validation failed, 1208 QR invalid
  TOTP secret, 1209 QR invalid TOTP, 1210 QR invalid prefix, 1211 QR payment suspended, 1212 payment not found,
  1213 invalid status for authorisation, 1214 authorisation general error, 1215 QR value already used, 1216
  invalid user, 1217 query access denied, 1218 query failed, 1219 invalid status for reversal, 1220 reversal not
  allowed (settled), 1221 reversal grace period ended, 1222 refund to account failed, 1223 reversal failed, 1224
  reversal already in progress, 1225 invalid payment method, 1226 refund already in progress, 1227 invalid status
  for refund, 1228 refund grace period ended, 1229 insufficient unsettled amount, 1230 refund failed, 1231
  payment limit exceeded, 1232 invalid session validity period, 1233 invalid session validity format, 1234
  payment method mismatch, 1235 refund amount exceeds transaction, 1236 refundable amount exceeded.
- **User:** 1400 general error, 1401 invalid user token format, 1402 user token not found, 1403 user reference
  retrieval failed, 1404 user profile retrieval failed, 1405 user info retrieval failed.

## 7. Webhooks (notify)

**Delivery.** Presto POSTs a signed JSON body to the `notifyUrl` given on init, reverse or refund; the URL must
be publicly reachable **[C]**. The merchant replies HTTP 200 with `{"resend":false}` (accepted) or
`{"resend":true}` (resend it) **[C]**. Presto retries on its own backoff of **2, 4, 8, 16, 32, 64, 128, 256, 512 and
1024 minutes** between attempts — up to 11 deliveries over roughly 34 hours **[C]**.

Three rules follow from the retries:

- **Never answer a permanent failure with `{"resend":true}`.** A bad signature, a foreign `mid` or a stale `ts`
  fails identically on every redelivery, so a resend request builds a loop that ends only when Presto gives up.
  `resend:true` is for the merchant's own transient failures. **[P]**
- **Answer a webhook that fails signature verification with HTTP 401** — a bad signature, a foreign `mid` or a
  stale `ts` (§7 verification steps 2, 4 and 5) — and a malformed body with HTTP 200 and `{"resend":false}`.
  Every SDK's documentation and samples do this; the SDKs' ack helpers still map both to `{"resend":false}`, so
  a handler checks for the signature error first. **[P]** How Presto treats a 401, and whether it redelivers
  after one, is **[U]**.
- **The freshness window is 15 minutes**, matching §3, because a redelivery carries a **fresh `ts`** **[C]**. A
  redelivery therefore never looks like a replay.
- **`eventRefNum` is stable across redeliveries of the same event** **[C]**. A handler that fulfils on each
  delivery double-fulfils up to 11 times, so the documented guard is on the merchant's order record: apply
  the queried status with a conditional update that finalises the order only once. **[P]**

**Verification**, in order:

1. Parse the **raw request body** — never a framework's parsed object re-serialized.
2. Signature present and valid, else a signature error.
3. Map fields (§8). `success` is always present **[C]**.
4. `mid` must be one of the configured merchant IDs, else a signature error. **Mandatory**, not defensive: one
   Presto key signs for every merchant, so the signature alone says nothing about who the event is for. A
   verifier takes a set of IDs and reports which matched, because one endpoint serving several `mid`s is normal.
   **[P]**
5. Freshness: reject if `|now − ts|` exceeds the window in either direction, as a signature error; a malformed
   `ts` is a malformed body. Widening or disabling the check is acceptable only where the order update is
   guarded that way. **[P]**

Event codes, open-ended **[U]**: `Authorised`, `Cancelled`, `Reversed`, `Refunded`, `Expired`.

**A webhook carries no payment status.** It reports that something happened to a payment: `eventCode` says what,
and `success` says whether it succeeded. A `Refunded` or `Reversed` event with `success: false` is a refund or
reversal that failed, and the payment keeps its previous status, which the event does not carry **[C]**
(confirmed API behaviour, 2026-09-30). So the resulting status cannot be read off the event:

- An SDK must **not** derive a payment status from `eventCode` and `success`. It exposes both exactly as sent.
  **[P]**
- A handler that needs the payment's status calls `query`, which is authoritative whatever order webhooks and the
  payer's redirect arrive in. If that `query` fails, the handler answers `{"resend":true}` — the failure is the
  merchant's, not the webhook's — so the redelivery can try again. **[P]**

## 8. Operation fields

All **[U]** unless noted. Amounts are integers in minor currency units **[C]**.

**Lengths below are documented maxima, not gateway limits.** Presto enforces no length limit today **[C]**, so
rejecting at `≤50` would fail requests the gateway would accept — and the characters-or-bytes question is moot.
Carry them as documentation and as strict-mode checks only. **[P]**

### Requests

- **init.** Required: `txnType`, `txnRefNum` (≤50), `displayDesc` (≤255). Optional: `qrValue`, `payerRefNum`,
  `deviceRefNum` (≤50), `deviceIp` (≤50), `itemList`, `transactionalData`, `amount` (>0), `currencyCode`,
  `notifyUrl` (≤255), `redirectUrl` (≤255), `sessionValidity`, `additionalData` (≤255), `mode` (≤50), `modeData`
  (≤1000), `allowedPaymentMethods`, `bindData`, `themeRefNum`, `receiptEmail` (≤320), `receiptName` (≤200).
  Rules: `qrValue` and `payerRefNum` are mutually exclusive; `currencyCode` is required with `amount`;
  `redirectUrl` is required when `txnType` is `WebPay`.
- **Line item** (in `itemList`). Required: `itemDesc`, `quantity` (>0), `unitAmount`, `totalAmount`. Optional:
  `imageUrl`, `itemUrl`, `category`, `categoryDesc`, `supplier`, `supplierDesc`, `supplierUrl`.
- **query.** `paymentRefNum` or `txnRefNum`, at least one.
- **reverse.** Required: `reversalRefNum` (≤50) and one of `paymentRefNum` / `txnRefNum`. Optional: `remark`
  (≤200), `notifyUrl` (≤255).
- **refund.** Required: `paymentRefNum`, `refundRefNum` (≤50), `remark` (≤200). Optional: `notifyUrl` (≤255),
  `amount` (>0; omit for a full refund).

### Responses

Every response also carries `prestoMrn`, `success`, `ts`, `errorCode`, `errorMessage` and `signature`. On a
successful call `errorCode` and `errorMessage` are present and **empty** **[C]**, so their presence never
signals an error — only `success: false` does. `*` marks fields that must be non-empty.

| Operation | Fields |
|-----------|--------|
| init | `paymentRefNum`*, `paymentStatus`*, `txnRefNum`, `paymentUrl`, `userRefNum`, `amount`, `currencyCode`, `paymentRequestDate`, `paymentFinalisedDate`, `additionalData` |
| query | `paymentRefNum`*, `txnRefNum`, `userRefNum`, `paymentStatus`, `amount`, `currencyCode`, `paymentRequestDate`, `paymentFinalisedDate`, `reversalRefNum`, `prestoReversalRefNum`, `reversalStatus`, `reversalDate`, `refundRefNum`, `prestoRefundRefNum`, `refundStatus`, `refundRequestDate`, `refundFinalisedDate`, `additionalData`, `refundDetails`, `paymentDetails` |
| reverse | `paymentRefNum`*, `prestoReversalRefNum`, `amount`, `currencyCode`, `paymentStatus` |
| refund | `paymentRefNum`*, `prestoRefundRefNum`, `amount` (original payment), `refundAmount`, `currencyCode`, `paymentStatus`, `refundedDate` |

- **Refund detail:** `refundRefNum`*, `prestoRefundRefNum`*, `refundStatus`*, `refundRequestDate`*,
  `refundFinalisedDate`.
- **Payment detail:** `amount`* (integer), `method`, `cardBin`, `cardSummary`, `cardType`, `refNum`.
- **Webhook:** required `eventCode`, `mid`, `prestoMrn`, `paymentRefNum`, `txnRefNum`, `eventRefNum`, `eventTs`,
  `amount`, `currencyCode`, `ts`, `success`; optional `userRefNum`, `additionalData`, `paymentDetails`.

`paymentUrl` is served from a **different host** than the API — `hpp-staging.prestouniverse.com`, not the
staging base URL **[C]** — so nothing may assume it shares an origin with the gateway.

### Code lists

Open-ended; unknown values pass through as strings **[U]**. An SDK exposes these as constants whose value is the
wire string exactly, and types response fields as plain strings so a value Presto added last week cannot throw.

- **Payment status:** `PendingAuthorise`, `Cancelled`, `Authorised`, `Failed`, `PendingReverse`, `Reversed`,
  `PendingRefund`, `PartialRefunded`, `Refunded`, `Expired`.
- **Reversal status:** `Reversing`, `Failed`, `Success`. **Refund status:** `Refunding`, `Failed`, `Success`.
- **Transaction type:** `QrPay`, `WebPay`, `MiniAppPay`.
- **Payment method** (`Wallet` **[C]**): `Wallet`, `CashBack`, `Card`, `BigLife`, `BonusLink`, `RISE`,
  `PlusMiles`, `VSing`, `KLEAN`, `GOrewards`, `Subwallet_NearU`, `Subwallet_CARROTS`, `Subwallet_BUDDY`,
  `TuneTalk`, `PmPgCard`, `Maybank`, `Ambank`, `Rhb`, `HongLeong`, `Cimb`, `PublicBank`, `AffinBank`, `Bsn`,
  `AllianceBank`, `AgroBank`, `BankIslam`, `BankOfChina`, `BankRakyat`, `BankMuamalat`, `BoostBank`, `HsbcBank`,
  `KuwaitFinanceHouse`, `OcbcBank`, `AlRajhiBank`, `StandardChartered`, `UobBank`, `MbsbBank`, `HongLeongPex`,
  `UnionPay`, `UnionPayQR`, `Boost`, `GrabPay`, `GrabPayLater`, `WeChatPayChina`, `TouchNGo`, `TouchNGoEWallet`,
  `AliPayChina`, `LatitudePay`, `ApplePay`, `GooglePay`, `DuitNowQR`.

## 9. Idempotency and retries

- `init`, `reverse` and `refund` must not be resent by the SDK once any byte may have reached the gateway, since
  a transport failure alone doesn't tell the SDK whether the gateway received it. `init` itself is idempotent by
  `txnRefNum`, though: resending it (same body) returns the existing payment's current status rather than
  creating a second record or failing. **[C]** — confirmed against real staging traffic, which corrects an
  earlier draft of this document that treated a resend as colliding with error `1203`. What (if anything) does
  produce `1203` is **[U]**.
- They may be retried **only** when the request certainly never left the process: DNS failure, connection
  refused, or a TLS failure before the body was written. When in doubt, do not retry. **[P]**
- `query` may be retried on transport errors and on statuses of 500 and above. **[P]**
- Every attempt gets a fresh `ts` and a fresh signature **[C]**; a stale `ts` fails with `1005`.
- After an ambiguous failure, reconcile with `query`: by `txnRefNum` after init, by `paymentRefNum` after
  reverse or refund. **[P]**
- If the gateway does return `1203`, that proves a record exists but says nothing about its state — treat it as
  a prompt to `query`, never as confirmation that the payment succeeded. **[P]**
- `reverse` on a payment that is still `PendingAuthorise` (never paid) **succeeds** and cancels it
  (`paymentStatus` becomes `Cancelled`) rather than failing — there is nothing to reverse financially if nothing
  was ever paid. **[C]** — confirmed against real staging traffic. `refund` in the same state has no such
  carve-out: it is rejected with error `1227` (invalid payment status). **[C]**
- A `PendingAuthorise` payment expires (`paymentStatus` becomes `Expired`) 15 minutes after `init` if not
  finalised (authorised) by then. **[C]** — confirmed business rule; consistent with real staging traffic
  (still `PendingAuthorise` at ~13 minutes, already `Expired` by ~107 minutes). Once `Expired`, `reverse` fails
  with `1219` (invalid payment status) **[C]** rather than cancelling it — this
  corrects an earlier draft of this document that guessed `1221` (reversal grace period ended) for this case.
  `1221`'s actual trigger is still **[U]**; it may apply to reversing an already-authorised (paid) payment past
  its own separate window, a scenario not yet exercised against staging.
- A refund request may be submitted for any payment method. The gateway decides whether it succeeds; some
  methods require manual or offline processing. An SDK must not reject a refund request based on the payment
  method or treat request acceptance as proof that the refund is complete. **[C]** for the request policy;
  method-specific outcomes remain **[U]**. One guest-checkout `AffinBank` reversal returned business error
  `1242`, `"Unable to refund to a guest account, please contact support."` That observation does not establish
  a general restriction on refund requests. Reversal eligibility across methods remains **[U]**.

## 10. Keys

- Merchant key pair: RSA, **generated by the merchant**, who keeps the private key and registers the public key
  with Presto. Presto does not issue the merchant private key. **[C]** (Presto Connect, 2026-10-01; this
  corrects an earlier draft that said the private key is delivered at onboarding.) Each SDK's documentation shows
  how to generate the pair with tools its developers already have.
- Public keys are exchanged **only as DER**, in both directions **[C]**: the merchant sends its public key as a
  DER-encoded X.509 certificate, and Presto's certificate arrives as DER. An SDK accepts Presto's certificate as
  DER, and may also accept PEM; where a DER file can't be passed directly (an environment variable holds text,
  say), its documentation shows the conversion to PEM.
- A merchant may keep its private key in a PKCS#12 keystore. Some keystores, including the staging ones Presto
  has handed out, encrypt the certificate bag with RC2-40-CBC, which OpenSSL 3 refuses without the legacy
  provider; the private key bag is readable without it. An SDK that cannot read PKCS#12 must document the
  conversion, and must not pipe `openssl pkcs12` into another command, because the RC2 failure sets a non-zero
  exit status *after* the key has been written correctly.
- **One Presto key signs responses and webhooks for every merchant**, and rotations are announced out of band
  **[C]**. There is no `kid` on the wire, so an SDK must accept a list of Presto keys and try each, or a
  rotation is an outage.

## 11. What Presto was asked

Every question is answered; this is the provenance behind the **[C]** tags.

**Round 1.** Numbers are always integers within 2^31, and `"amount": 100` is the shape. A string field never
arrives as a number or boolean. List fields are always strings. The gateway does send `null`. `success` is
always present. The request `ts` window is 15 minutes. The `x-http-error-*` headers are always set and there is
no rate limiting. Presto retries webhooks on its own backoff. There is no length limit today. One key signs for
all merchants, and partners are told about rotations.

**Round 2.** `null` renders as the empty string. A webhook's `ts` is refreshed on each delivery attempt.
`eventRefNum` is stable across redeliveries. The retry backoff is 2, 4, 8, 16, 32, 64, 128, 256, 512 and 1024
minutes between attempts. `1203` means the record was created and may even be successful. `1006` and `1007` do not
distinguish malformed from failed-to-verify.

What remains **[U]** is pass-through behaviour — unknown error codes, the status and payment-method lists,
`sessionValidity` formatting, resend safety for reverse and refund — where a wrong guess surfaces as an
unrecognized string rather than a failed verification or a lost payment. Staging is what resolves those.

## Conformance

An SDK conforms when it passes every vector in `vectors/`. See `README.md` for the file formats and for how to
check the vectors against themselves without an SDK.
