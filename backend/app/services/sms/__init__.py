"""SMS gateway package (M31 — bill receipts by SMS).

The gateway is a THIN, honest HTTP client: given a mobile number + message it
calls the provider's API and returns the provider's raw acknowledgement. It
never fabricates success; the outbox service stores the raw provider text so
the UI can show exactly why a delivery failed.
"""

from .gateway import Msg91Gateway, SmsGatewayError, SmsGatewayNotConfigured, SmsSendResult, get_gateway
from .receipt import build_bill_receipt
from .outbox import SmsOutboxService
from .manager import (
    configure_sms_worker,
    get_sms_worker,
    reset_sms_worker,
    start_sms_worker,
    stop_sms_worker,
)

__all__ = [
    "Msg91Gateway",
    "SmsGatewayError",
    "SmsGatewayNotConfigured",
    "SmsSendResult",
    "get_gateway",
    "build_bill_receipt",
    "SmsOutboxService",
    "configure_sms_worker",
    "get_sms_worker",
    "reset_sms_worker",
    "start_sms_worker",
    "stop_sms_worker",
]