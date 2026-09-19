"""MSG91 SMS gateway client (M31).

Contract for callers (the outbox worker):

* ``send()`` returns ``SmsSendResult(success=True, ...)`` ONLY when the provider
  acked the message. The body carries the raw provider acknowledgement.
* ``SmsGatewayNotConfigured`` — the provider credentials required to send are
  missing (a permanent, operator-level misconfiguration; retrying is useless).
* ``SmsGatewayError`` — any transport/app-layer failure (transient: retry with
  backoff).

MSG91 legacy transactional endpoint (``api/sendhttp.php``): GET/POST with
``authkey``, ``mobiles``, ``message``, ``sender`` (optional), ``route=4``
(transactional), ``country``. Success responses contain ``type:success``;
errors contain ``type:error,errorcode:...``.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("storeye.sms")


class SmsGatewayError(RuntimeError):
    """Transport or provider-level send failure (potentially transient)."""


class SmsGatewayNotConfigured(RuntimeError):
    """The provider credentials required to send are missing."""


class SmsSendResult:
    """A confirmed gateway acknowledgement (never fabricated)."""

    def __init__(self, response: str, success: bool = True, message_id: str | None = None):
        self.success = success
        self.response = response
        self.message_id = message_id


class Msg91Gateway:
    """Send a transactional SMS through MSG91's legacy ``sendhttp.php`` API."""

    ENDPOINT = "/api/sendhttp.php"

    def __init__(self, settings) -> None:
        self.auth_key = (settings.MSG91_AUTH_KEY or "").strip()
        self.sender_id = (settings.MSG91_SENDER_ID or "").strip()
        self.route = int(getattr(settings, "MSG91_ROUTE", 4) or 4)
        self.country = (settings.MSG91_COUNTRY_CODE or "91").strip()
        self.base_url = (settings.MSG91_BASE_URL or "https://control.msg91.com").rstrip("/")
        self.timeout = float(getattr(settings, "SMS_TIMEOUT_SECONDS", 10.0) or 10.0)

    def configured(self) -> bool:
        return bool(self.auth_key)

    def send(self, mobile: str, message: str) -> SmsSendResult:
        if not self.auth_key:
            raise SmsGatewayNotConfigured(
                "MSG91_AUTH_KEY is empty — configure SMS credentials (or leave SMS_ENABLED off)."
            )
        params = {
            "authkey": self.auth_key,
            "mobiles": mobile.strip(),
            "message": message,
            "route": self.route,
            "country": self.country,
        }
        if self.sender_id:
            params["sender"] = self.sender_id
        url = f"{self.base_url}{self.ENDPOINT}"
        try:
            response = httpx.post(url, params=params, timeout=self.timeout)
            text = response.text.strip()[:500]
        except httpx.HTTPError as exc:
            logger.warning("MSG91 transport error for %s: %s", mobile, exc)
            raise SmsGatewayError(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("MSG91 unexpected client error: %s", exc)
            raise SmsGatewayError(f"unexpected client error: {exc}") from exc

        if response.status_code != 200:
            raise SmsGatewayError(f"HTTP {response.status_code}: {text or '<empty>'}")
        lowered = text.lower()
        if "type:error" in lowered or "success" not in lowered:
            raise SmsGatewayError(text or "<empty provider response>")
        return SmsSendResult(response=text)


def get_gateway(settings=None) -> Msg91Gateway:
    """Build a gateway from Settings (the provider switch lives here)."""
    from ...core.config import get_settings

    settings = settings or get_settings()
    if (settings.SMS_PROVIDER or "").strip().lower() != "msg91":
        raise SmsGatewayError(f"Unsupported SMS_PROVIDER: {settings.SMS_PROVIDER!r}")
    return Msg91Gateway(settings)