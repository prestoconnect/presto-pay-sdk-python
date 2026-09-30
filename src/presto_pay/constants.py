from __future__ import annotations

from enum import StrEnum
from typing import Self


class _WireCode(StrEnum):
    @classmethod
    def try_parse(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        try:
            return cls(value)
        except ValueError:
            return None


class PaymentStatus(_WireCode):
    PENDING_AUTHORISE = "PendingAuthorise"
    CANCELLED = "Cancelled"
    AUTHORISED = "Authorised"
    FAILED = "Failed"
    PENDING_REVERSE = "PendingReverse"
    REVERSED = "Reversed"
    PENDING_REFUND = "PendingRefund"
    PARTIAL_REFUNDED = "PartialRefunded"
    REFUNDED = "Refunded"
    EXPIRED = "Expired"


class ReversalStatus(_WireCode):
    REVERSING = "Reversing"
    FAILED = "Failed"
    SUCCESS = "Success"


class RefundStatus(_WireCode):
    REFUNDING = "Refunding"
    FAILED = "Failed"
    SUCCESS = "Success"


class TxnType(_WireCode):
    QR_PAY = "QrPay"
    WEB_PAY = "WebPay"
    MINI_APP_PAY = "MiniAppPay"


class EventCode(_WireCode):
    AUTHORISED = "Authorised"
    CANCELLED = "Cancelled"
    REVERSED = "Reversed"
    REFUNDED = "Refunded"
    EXPIRED = "Expired"


class PaymentMethod(_WireCode):
    WALLET = "Wallet"
    CASH_BACK = "CashBack"
    CARD = "Card"
    BIG_LIFE = "BigLife"
    BONUS_LINK = "BonusLink"
    RISE = "RISE"
    PLUS_MILES = "PlusMiles"
    V_SING = "VSing"
    KLEAN = "KLEAN"
    GO_REWARDS = "GOrewards"
    SUBWALLET_NEAR_U = "Subwallet_NearU"
    SUBWALLET_CARROTS = "Subwallet_CARROTS"
    SUBWALLET_BUDDY = "Subwallet_BUDDY"
    TUNE_TALK = "TuneTalk"
    PM_PG_CARD = "PmPgCard"
    MAYBANK = "Maybank"
    AMBANK = "Ambank"
    RHB = "Rhb"
    HONG_LEONG = "HongLeong"
    CIMB = "Cimb"
    PUBLIC_BANK = "PublicBank"
    AFFIN_BANK = "AffinBank"
    BSN = "Bsn"
    ALLIANCE_BANK = "AllianceBank"
    AGRO_BANK = "AgroBank"
    BANK_ISLAM = "BankIslam"
    BANK_OF_CHINA = "BankOfChina"
    BANK_RAKYAT = "BankRakyat"
    BANK_MUAMALAT = "BankMuamalat"
    BOOST_BANK = "BoostBank"
    HSBC_BANK = "HsbcBank"
    KUWAIT_FINANCE_HOUSE = "KuwaitFinanceHouse"
    OCBC_BANK = "OcbcBank"
    AL_RAJHI_BANK = "AlRajhiBank"
    STANDARD_CHARTERED = "StandardChartered"
    UOB_BANK = "UobBank"
    MBSB_BANK = "MbsbBank"
    HONG_LEONG_PEX = "HongLeongPex"
    UNION_PAY = "UnionPay"
    UNION_PAY_QR = "UnionPayQR"
    BOOST = "Boost"
    GRAB_PAY = "GrabPay"
    GRAB_PAY_LATER = "GrabPayLater"
    WE_CHAT_PAY_CHINA = "WeChatPayChina"
    TOUCH_N_GO = "TouchNGo"
    TOUCH_N_GO_E_WALLET = "TouchNGoEWallet"
    ALI_PAY_CHINA = "AliPayChina"
    LATITUDE_PAY = "LatitudePay"
    APPLE_PAY = "ApplePay"
    GOOGLE_PAY = "GooglePay"
    DUIT_NOW_QR = "DuitNowQR"


class ErrorCode(_WireCode):
    INVALID_REQUEST_PATH = "1001"
    INVALID_CONTENT_TYPE = "1002"
    MISSING_MASTER_MERCHANT_REF = "1003"
    INVALID_TIMESTAMP_FORMAT = "1004"
    CLOCK_SKEW = "1005"
    INVALID_SIGNATURE = "1006"
    SIGNATURE_VERIFICATION_FAILED = "1007"
    MISSING_AUTHORIZATION_HEADER = "1008"
    INVALID_AUTHORIZATION_HEADER = "1009"
    INVALID_ACCESS_TOKEN = "1010"
    ACCESS_TOKEN_VALIDATION_ERROR = "1011"
    INVALID_ACCESS_TOKEN_OWNERSHIP = "1012"
    OAUTH_RESOURCE_CONFIG_ERROR = "1013"
    MISSING_OAUTH_SCOPE = "1014"
    OAUTH_SERVICE_UNAVAILABLE = "1015"

    MERCHANT_GENERAL_ERROR = "1100"
    MERCHANT_INVALID_INPUT = "1101"
    INVALID_MID = "1102"
    MASTER_MERCHANT_INFO_RETRIEVAL_FAILED = "1103"
    MASTER_MERCHANT_INFO_SERVICE_UNAVAILABLE = "1104"
    ONBOARD_PROCESSING_FAILED = "1105"
    INVALID_MERCHANT_REFERENCE = "1106"
    DOCUMENT_UPLOAD_FAILED = "1107"
    MISSING_DOCUMENT = "1108"
    RECORD_EXISTS = "1109"
    PROFILE_NOT_FOUND = "1110"
    INVALID_MERCHANT_TXN_TYPE = "1111"
    FILE_RETRY_LIMIT_EXCEEDED = "1112"
    MERCHANT_REJECTED = "1113"

    PAYMENT_GENERAL_ERROR = "1200"
    INVALID_INPUT = "1201"
    INIT_FAILED = "1202"
    DUPLICATE_TXN_REF_NUM = "1203"
    QR_VALUE_NOT_RECOGNISED = "1204"
    QR_VALUE_NOT_BOUND = "1205"
    QR_TOTP_EXPIRED = "1206"
    QR_VALIDATION_FAILED = "1207"
    QR_INVALID_TOTP_SECRET = "1208"
    QR_INVALID_TOTP = "1209"
    QR_INVALID_PREFIX = "1210"
    QR_PAYMENT_SUSPENDED = "1211"
    PAYMENT_NOT_FOUND = "1212"
    INVALID_STATUS_FOR_AUTHORISATION = "1213"
    AUTHORISATION_GENERAL_ERROR = "1214"
    QR_VALUE_ALREADY_USED = "1215"
    INVALID_USER = "1216"
    QUERY_ACCESS_DENIED = "1217"
    QUERY_FAILED = "1218"
    INVALID_STATUS_FOR_REVERSAL = "1219"
    REVERSAL_NOT_ALLOWED_SETTLED = "1220"
    REVERSAL_GRACE_PERIOD_ENDED = "1221"
    REFUND_TO_ACCOUNT_FAILED = "1222"
    REVERSAL_FAILED = "1223"
    REVERSAL_ALREADY_IN_PROGRESS = "1224"
    INVALID_PAYMENT_METHOD = "1225"
    REFUND_ALREADY_IN_PROGRESS = "1226"
    INVALID_STATUS_FOR_REFUND = "1227"
    REFUND_GRACE_PERIOD_ENDED = "1228"
    INSUFFICIENT_UNSETTLED_AMOUNT = "1229"
    REFUND_FAILED = "1230"
    PAYMENT_LIMIT_EXCEEDED = "1231"
    INVALID_SESSION_VALIDITY_PERIOD = "1232"
    INVALID_SESSION_VALIDITY_FORMAT = "1233"
    PAYMENT_METHOD_MISMATCH = "1234"
    REFUND_AMOUNT_EXCEEDS_TRANSACTION = "1235"
    REFUNDABLE_AMOUNT_EXCEEDED = "1236"
    GUEST_ACCOUNT_REFUND_NOT_SUPPORTED = "1242"

    USER_GENERAL_ERROR = "1400"
    INVALID_USER_TOKEN_FORMAT = "1401"
    USER_TOKEN_NOT_FOUND = "1402"
    USER_REFERENCE_RETRIEVAL_FAILED = "1403"
    USER_PROFILE_RETRIEVAL_FAILED = "1404"
    USER_INFO_RETRIEVAL_FAILED = "1405"
