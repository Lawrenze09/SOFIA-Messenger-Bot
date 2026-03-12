"""
services/email_service.py

SendGrid email notification service.
Sends admin alerts for escalations, purchase intents,
and guardrail failures.
"""

from datetime import datetime, timezone

import requests

from config import settings
from services.session_service import can_send_email
from utils.logger import get_logger

logger = get_logger(__name__)

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_FROM_EMAIL   = "4ce.apparel@gmail.com"
_FROM_NAME    = "Sofia Bot"


def send_admin_alert(
    psid: str,
    message: str,
    intent: str,
    reason: str,
) -> bool:
    """
    Send an admin alert email via SendGrid.
    Respects per-user email rate limit (EMAIL_MAX per EMAIL_WINDOW_SECS).

    Args:
        psid:    Facebook PSID of the customer who triggered the alert.
        message: Raw customer message.
        intent:  Classified intent label.
        reason:  Human-readable reason for the alert.

    Returns:
        True if email was sent, False if suppressed or failed.
    """
    if not can_send_email(psid):
        logger.info(f"Email suppressed for {psid} — rate limit reached")
        return False

    payload = {
        "personalizations": [{"to": [{"email": settings.admin_email}]}],
        "from": {"email": _FROM_EMAIL, "name": _FROM_NAME},
        "subject": f"[Sofia Alert] {reason} — {intent}",
        "content": [{
            "type": "text/plain",
            "value": (
                f"Sofia Handover Alert\n"
                f"{'=' * 40}\n"
                f"Reason    : {reason}\n"
                f"User ID   : {psid}\n"
                f"Intent    : {intent}\n"
                f"Message   : {message}\n"
                f"Timestamp : {datetime.now(timezone.utc).isoformat()}\n"
            ),
        }],
    }

    try:
        response = requests.post(
            _SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=10,
        )
        if response.status_code in (200, 202):
            logger.info(f"Admin alert sent — reason: {reason} | user: {psid}")
            return True

        logger.error(
            f"SendGrid error {response.status_code}: {response.text[:200]}"
        )
        return False

    except requests.RequestException as exc:
        logger.error(f"Email send exception: {exc}")
        return False
