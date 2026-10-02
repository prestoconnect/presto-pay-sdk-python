# Payment methods

This page lists the payment method codes the SDK knows. It assumes you've set up a client as in the
[quick start](../README.md#quick-start).

Payment method codes appear in two places: in `allowed_payment_methods`, which you can pass to `init`, and in
`method` on each `PaymentDetail` that a `query` result or a webhook event returns in `payment_details`. You
only need `allowed_payment_methods` if you build your own payment selection page; otherwise the shopper
chooses on Presto's page.

**Which methods you can use depends on your account.** Presto enables payment methods for each merchant during
onboarding. A code being listed here doesn't make it available to you; ask Presto which methods are enabled
for your account, or to enable more.

- [Codes are plain strings](#codes-are-plain-strings)
- [Methods that need a Presto account](#methods-that-need-a-presto-account)
- [Legacy methods](#legacy-methods)
- [All payment methods](#all-payment-methods)

## Codes are plain strings

The constants are a convenience: each one's value is exactly the code Presto sends and receives, and every
field that holds a payment method is a plain string. So when Presto adds a payment method, you don't need a
new SDK release to use it. Pass its code as a string:

```python
payment = presto.payments.init(
    # ...
    allowed_payment_methods=[PaymentMethod.TOUCH_N_GO_E_WALLET, "NewMethodCode"],
)
```

Like any other code, it works only once Presto has enabled it for your account.

The same applies to what you read back. `method` is a `str`. Compare it with the constants, or use
`PaymentMethod.try_parse(detail.method)`, which returns `None` for a code the SDK doesn't list. Handle that
case without failing: store and show the code as it is.

## Methods that need a Presto account

To pay with one of these, the shopper logs in to their Presto account on Presto's payment page. If you limit
`allowed_payment_methods` to these methods only, shoppers without a Presto account can't pay.

| Code | Constant | What it is |
|------|----------|------------|
| `Wallet` | `PaymentMethod.WALLET` | PrestoPay eWallet |
| `CashBack` | `PaymentMethod.CASH_BACK` | PrestoPay Credits |
| `Card` | `PaymentMethod.CARD` | Tokenised card saved to the shopper's Presto account |

Loyalty programmes, where the shopper pays with points:

| Code | Constant | Programme |
|------|----------|-----------|
| `Subwallet_NearU` | `PaymentMethod.SUBWALLET_NEAR_U` | NearU Points |
| `Subwallet_CARROTS` | `PaymentMethod.SUBWALLET_CARROTS` | Carrots |
| `Subwallet_BUDDY` | `PaymentMethod.SUBWALLET_BUDDY` | Buddy+ |
| `BigLife` | `PaymentMethod.BIG_LIFE` | AirAsia rewards (legacy) |
| `BonusLink` | `PaymentMethod.BONUS_LINK` | BonusLink |
| `GOrewards` | `PaymentMethod.GO_REWARDS` | GOrewards |
| `RISE` | `PaymentMethod.RISE` | RISE |
| `PlusMiles` | `PaymentMethod.PLUS_MILES` | PlusMiles |
| `VSing` | `PaymentMethod.V_SING` | VSing |
| `KLEAN` | `PaymentMethod.KLEAN` | KLEAN |

`Card` and `PmPgCard` are both card payments. `Card` uses a card the shopper saved to their Presto account;
with `PmPgCard`, the shopper enters card details on Presto's payment page and doesn't need to log in.

## Legacy methods

Don't use these in new integrations:

- `TouchNGo`: use `TouchNGoEWallet` instead.
- `BigLife` (AirAsia rewards).

## All payment methods

Which of these you can use depends on what Presto enabled for your account during onboarding.

| Code | Constant | Notes |
|------|----------|-------|
| `Wallet` | `PaymentMethod.WALLET` | PrestoPay eWallet. Needs a Presto account |
| `CashBack` | `PaymentMethod.CASH_BACK` | PrestoPay Credits. Needs a Presto account |
| `Card` | `PaymentMethod.CARD` | Tokenised card. Needs a Presto account |
| `BigLife` | `PaymentMethod.BIG_LIFE` | Loyalty: AirAsia rewards (legacy). Needs a Presto account |
| `BonusLink` | `PaymentMethod.BONUS_LINK` | Loyalty points. Needs a Presto account |
| `RISE` | `PaymentMethod.RISE` | Loyalty points. Needs a Presto account |
| `PlusMiles` | `PaymentMethod.PLUS_MILES` | Loyalty points. Needs a Presto account |
| `VSing` | `PaymentMethod.V_SING` | Loyalty points. Needs a Presto account |
| `KLEAN` | `PaymentMethod.KLEAN` | Loyalty points. Needs a Presto account |
| `GOrewards` | `PaymentMethod.GO_REWARDS` | Loyalty points. Needs a Presto account |
| `Subwallet_NearU` | `PaymentMethod.SUBWALLET_NEAR_U` | Loyalty: NearU Points. Needs a Presto account |
| `Subwallet_CARROTS` | `PaymentMethod.SUBWALLET_CARROTS` | Loyalty: Carrots. Needs a Presto account |
| `Subwallet_BUDDY` | `PaymentMethod.SUBWALLET_BUDDY` | Loyalty: Buddy+. Needs a Presto account |
| `TuneTalk` | `PaymentMethod.TUNE_TALK` | |
| `PmPgCard` | `PaymentMethod.PM_PG_CARD` | Card entered on Presto's payment page |
| `Maybank` | `PaymentMethod.MAYBANK` | |
| `Ambank` | `PaymentMethod.AMBANK` | |
| `Rhb` | `PaymentMethod.RHB` | |
| `HongLeong` | `PaymentMethod.HONG_LEONG` | |
| `Cimb` | `PaymentMethod.CIMB` | |
| `PublicBank` | `PaymentMethod.PUBLIC_BANK` | |
| `AffinBank` | `PaymentMethod.AFFIN_BANK` | |
| `Bsn` | `PaymentMethod.BSN` | |
| `AllianceBank` | `PaymentMethod.ALLIANCE_BANK` | |
| `AgroBank` | `PaymentMethod.AGRO_BANK` | |
| `BankIslam` | `PaymentMethod.BANK_ISLAM` | |
| `BankOfChina` | `PaymentMethod.BANK_OF_CHINA` | |
| `BankRakyat` | `PaymentMethod.BANK_RAKYAT` | |
| `BankMuamalat` | `PaymentMethod.BANK_MUAMALAT` | |
| `BoostBank` | `PaymentMethod.BOOST_BANK` | |
| `HsbcBank` | `PaymentMethod.HSBC_BANK` | |
| `KuwaitFinanceHouse` | `PaymentMethod.KUWAIT_FINANCE_HOUSE` | |
| `OcbcBank` | `PaymentMethod.OCBC_BANK` | |
| `AlRajhiBank` | `PaymentMethod.AL_RAJHI_BANK` | |
| `StandardChartered` | `PaymentMethod.STANDARD_CHARTERED` | |
| `UobBank` | `PaymentMethod.UOB_BANK` | |
| `MbsbBank` | `PaymentMethod.MBSB_BANK` | |
| `HongLeongPex` | `PaymentMethod.HONG_LEONG_PEX` | |
| `UnionPay` | `PaymentMethod.UNION_PAY` | |
| `UnionPayQR` | `PaymentMethod.UNION_PAY_QR` | |
| `Boost` | `PaymentMethod.BOOST` | |
| `GrabPay` | `PaymentMethod.GRAB_PAY` | |
| `GrabPayLater` | `PaymentMethod.GRAB_PAY_LATER` | |
| `WeChatPayChina` | `PaymentMethod.WE_CHAT_PAY_CHINA` | |
| `TouchNGo` | `PaymentMethod.TOUCH_N_GO` | Legacy; use `TouchNGoEWallet` |
| `TouchNGoEWallet` | `PaymentMethod.TOUCH_N_GO_E_WALLET` | Touch 'n Go eWallet |
| `AliPayChina` | `PaymentMethod.ALI_PAY_CHINA` | |
| `LatitudePay` | `PaymentMethod.LATITUDE_PAY` | |
| `ApplePay` | `PaymentMethod.APPLE_PAY` | |
| `GooglePay` | `PaymentMethod.GOOGLE_PAY` | |
| `DuitNowQR` | `PaymentMethod.DUIT_NOW_QR` | |
