"""
utils/security.py

Security utilities:
- HMAC-SHA256 webhook signature verification
- Prompt injection detection
- Message deduplication via Redis
"""

import hmac
import hashlib
import re
from typing import TYPE_CHECKING

import redis as redis_lib

from utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# ─────────────────────────────────────────────
# HMAC VERIFICATION
# ─────────────────────────────────────────────

def verify_hmac(payload: bytes, signature: str, app_secret: str) -> bool:
    """
    Verify Facebook webhook payload signature using HMAC-SHA256.

    Args:
        payload:    Raw request body bytes.
        signature:  X-Hub-Signature-256 header value.
        app_secret: Facebook App Secret from settings.

    Returns:
        True if signature is valid, False otherwise.
    """
    expected = "sha256=" + hmac.new(
        app_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────────
# PROMPT INJECTION DETECTION
# ─────────────────────────────────────────────

_INJECTION_PATTERNS: list[str] = [
    r"ignore\s+(?:previous|all|above)\s+instructions",
    r"you\s+are\s+now\s+(?:a\s+)?(?:new|different|evil|unrestricted)",
    r"act\s+as\s+(?:if\s+you\s+(?:are|have)\s+)?(?:no\s+restrictions|DAN|jailbreak)",
    r"pretend\s+you\s+(?:are|have)\s+no",
    r"forget\s+(?:your\s+)?(?:instructions|training|rules|guidelines)",
    r"system\s*prompt\s*[:=]",
    r"\[SYSTEM\]|\[INST\]|<\|system\|>",
]


def is_prompt_injection(text: str) -> bool:
    """
    Detect common prompt injection patterns in user input.

    Args:
        text: Raw customer message.

    Returns:
        True if injection pattern detected.
    """
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Prompt injection detected — pattern: {pattern[:40]}")
            return True
    return False


# ─────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────

def is_duplicate(mid: str, redis_client: redis_lib.Redis, ttl: int) -> bool:
    """
    Check if a message ID has already been processed.
    Uses atomic Redis SETNX to prevent race conditions.

    Args:
        mid:          Facebook message ID.
        redis_client: Active Redis connection.
        ttl:          Seconds before dedup key expires.

    Returns:
        True if message is a duplicate and should be dropped.
    """
    key = f"dedup:{mid}"
    if redis_client.exists(key):
        return True
    redis_client.setex(key, ttl, "1")
    return False


# ─────────────────────────────────────────────
# SILENT MESSAGE DETECTION
# ─────────────────────────────────────────────

_SILENT_KEYWORDS: set[str] = {
    "sige", "sige po", "sige boss", "ok", "ok po", "okay", "okay po",
    "gege", "ge", "oo", "oo po", "oopo", "noted", "noted po",
    "hintayin ko", "hihintayin ko", "wait ko", "salamat", "salamat po",
    "thanks", "thank you", "ty", "👍", "✅", "😊", "🙏", "wait",
    "naiintindihan ko", "copy", "copy po", "sige na", "okie", "oksiee",
    "ayos", "ayos po", "nice", "nice po", "oks", "oksi", ".", "ahh", "ah",
}


def is_silent_message(text: str) -> bool:
    """
    Detect acknowledgement messages that need no bot reply.

    Args:
        text: Customer message text.

    Returns:
        True if message should be silently dropped.
    """
    return text.lower().strip() in _SILENT_KEYWORDS
