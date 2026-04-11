"""
utils/security.py
 
Security utilities:
- HMAC-SHA256 webhook signature verification
- Prompt injection detection
- Message deduplication via Redis
- Silent message detection (acknowledgements and emoji-only messages)
 
Gibberish detection is intentionally omitted.
A single gibberish message routes to UNKNOWN intent — one API call,
acceptable cost. Repeated gibberish is caught by is_spam() in
session_service.py after 5 messages in 15 seconds, setting the
session to HUMAN_ACTIVE and blocking further processing.
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
 
# Explicit acknowledgement phrases that need no bot reply.
# Checked as exact full-message matches after stripping whitespace.
# Deliberately minimal — ambiguous words like "ok", "sige", "oo"
# are excluded because they can signal purchase confirmation intent
# (e.g. "ok pabili na") and must reach the intent classifier.
_SILENT_KEYWORDS: set[str] = {
    "noted", "noted po",
    "naiintindihan ko", "copy", "copy po",
    "👍", "✅", "😊", "🙏",
    ".", "ahh", "ah",
}
 
# Unicode ranges covering all standard emoji blocks.
# Used to detect messages composed entirely of emoji characters
# regardless of which specific emojis are used.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002500-\U00002BEF"  # chinese/japanese/korean characters
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed characters
    "\U0001F926-\U0001F937"  # supplemental symbols
    "\U00010000-\U0010FFFF"  # supplementary multilingual plane
    "\u2640-\u2642"          # gender signs
    "\u2600-\u2B55"          # misc symbols
    "\u200d"                 # zero width joiner
    "\u23cf"                 # eject symbol
    "\u23e9"                 # fast forward
    "\u231a"                 # watch
    "\ufe0f"                 # variation selector
    "\u3030"                 # wavy dash
    "]+",
    re.UNICODE,
)
 
 
def _is_emoji_only(text: str) -> bool:
    """
    Check if a message is composed entirely of emoji characters.
    Strips whitespace before checking so spaced emoji are also caught.
 
    Args:
        text: Customer message text.
 
    Returns:
        True if the message contains only emoji and no meaningful text.
    """
    stripped = text.replace(" ", "")
    if not stripped:
        return False
    return bool(_EMOJI_PATTERN.fullmatch(stripped))
 
 
def is_silent_message(text: str) -> bool:
    """
    Detect messages that need no bot reply.
 
    Catches two categories:
    1. Explicit acknowledgement phrases — exact match against
       _SILENT_KEYWORDS (e.g. "noted", "copy po").
    2. Emoji-only messages — any message composed entirely of
       emoji characters regardless of which specific emojis are used.
 
    Gibberish detection (random character sequences) is handled
    upstream by is_spam() in session_service.py — repeated gibberish
    triggers HUMAN_ACTIVE after 5 messages in 15 seconds. A single
    gibberish message routes to UNKNOWN intent at negligible API cost.
 
    Args:
        text: Customer message text.
 
    Returns:
        True if message should be silently dropped.
    """
    normalized = text.lower().strip()
 
    if normalized in _SILENT_KEYWORDS:
        return True
 
    if _is_emoji_only(normalized):
        logger.info(f"Emoji-only message silently dropped: {text!r}")
        return True
 
    return False
