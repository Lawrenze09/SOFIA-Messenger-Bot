"""
services/session_service.py

Redis-backed session management.
Handles session state, spam detection, message rate limiting,
and email rate limiting — all keyed by Facebook PSID.
"""

import time
import uuid
from enum import Enum

import redis

from config import settings
from database.repository import upsert_session
from utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# SESSION STATE ENUM
# ─────────────────────────────────────────────

class SessionState(str, Enum):
    BOT_ACTIVE   = "BOT_ACTIVE"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"


# ─────────────────────────────────────────────
# REDIS CLIENT (lazy singleton)
# ─────────────────────────────────────────────

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """
    Return a lazily-initialized Redis client.
    Reuses the same connection across requests.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis_client


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────

def get_session_state(psid: str) -> SessionState:
    """
    Retrieve current session state for a user.
    Defaults to BOT_ACTIVE if no state is stored.

    Args:
        psid: Facebook Page-Scoped ID of the customer.

    Returns:
        Current SessionState enum value.
    """
    state = get_redis().get(f"session:state:{psid}")
    return SessionState(state) if state else SessionState.BOT_ACTIVE


def set_session_state(psid: str, state: SessionState) -> None:
    """
    Persist session state to Redis with TTL.

    Args:
        psid:  Facebook PSID.
        state: New SessionState to store.
    """
    get_redis().setex(
        f"session:state:{psid}",
        settings.session_ttl,
        state.value,
    )


def get_or_create_session_id(psid: str) -> str:
    """
    Return existing session ID or create a new one.
    New sessions are persisted to the database.

    Args:
        psid: Facebook PSID.

    Returns:
        UUID string for the current session.
    """
    r   = get_redis()
    key = f"session:id:{psid}"
    sid = r.get(key)
    if not sid:
        sid = str(uuid.uuid4())
        r.setex(key, settings.session_ttl, sid)
        upsert_session(sid, psid)
    return sid


# ─────────────────────────────────────────────
# FIRST MESSAGE DETECTION
# ─────────────────────────────────────────────

def is_first_message(psid: str) -> bool:
    """
    Check if this is the customer's first ever message.
    Uses a permanent Redis key — once set, never expires.
    Returns True only once per PSID, then marks them as seen.

    Args:
        psid: Facebook PSID.

    Returns:
        True if this is the customer's first message, False otherwise.
    """
    r   = get_redis()
    key = f"seen:{psid}"

    if r.exists(key):
        return False

    # ── Mark as seen permanently — no TTL ──
    r.set(key, "1")
    return True


# ─────────────────────────────────────────────
# BOT REACTIVATION
# ─────────────────────────────────────────────

_BOT_REACTIVATION_COMMANDS: set[str] = {"sofia", "bot"}


def is_bot_reactivation(text: str) -> bool:
    """
    Check if admin typed a reactivation command.

    Args:
        text: Admin message text.

    Returns:
        True if text matches a reactivation command exactly.
    """
    return text.lower().strip() in _BOT_REACTIVATION_COMMANDS


# ─────────────────────────────────────────────
# SPAM DETECTION
# ─────────────────────────────────────────────

def is_spam(psid: str) -> bool:
    """
    Detect message flooding using a Redis counter with sliding window TTL.
    Returns True if user exceeds SPAM_MAX_MSGS in SPAM_WINDOW_SECS.
    On spam detection, counter is left to expire naturally.

    Args:
        psid: Facebook PSID.

    Returns:
        True if user is spamming and should be silently blocked.
    """
    r     = get_redis()
    key   = f"spam:{psid}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, settings.spam_window_secs)
    if count >= settings.spam_max_msgs:
        logger.warning(f"Spam detected for {psid} — count: {count}")
        return True
    return False


# ─────────────────────────────────────────────
# MESSAGE GAP ENFORCEMENT
# ─────────────────────────────────────────────

def apply_message_gap(psid: str) -> None:
    """
    Enforce a minimum gap between messages from the same user.
    If a message arrives too soon, sleeps the remaining time.
    Prevents AI credit burn from rapid sequential messages.

    Args:
        psid: Facebook PSID.
    """
    r    = get_redis()
    key  = f"lastmsg:{psid}"
    last = r.get(key)
    now  = time.time()

    if last:
        elapsed = now - float(last)
        if elapsed < settings.msg_gap_secs:
            wait = settings.msg_gap_secs - elapsed
            logger.info(f"Rate gap applied for {psid} — waiting {wait:.1f}s")
            time.sleep(wait)

    r.set(key, str(time.time()), ex=settings.session_ttl)


# ─────────────────────────────────────────────
# EMAIL RATE LIMITING
# ─────────────────────────────────────────────

def can_send_email(psid: str) -> bool:
    """
    Enforce per-user email rate limit to prevent SendGrid quota burn.
    Default: max 2 emails per 30 minutes per user.

    Args:
        psid: Facebook PSID.

    Returns:
        True if email is allowed, False if rate limit reached.
    """
    r     = get_redis()
    key   = f"email_count:{psid}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, settings.email_window_secs)
    if count > settings.email_max:
        logger.info(f"Email suppressed for {psid} — {count} in window")
        return False
    return True


# ─────────────────────────────────────────────
# FULL SESSION RESET
# ─────────────────────────────────────────────

def reset_session(psid: str) -> None:
    """
    Clear all Redis keys for a user.
    Used by the /reset/<psid> admin endpoint.
    Note: does not clear the seen:{psid} key —
    the welcome message should only fire once ever.

    Args:
        psid: Facebook PSID to reset.
    """
    r = get_redis()
    r.delete(
        f"session:state:{psid}",
        f"session:id:{psid}",
        f"spam:{psid}",
        f"lastmsg:{psid}",
        f"email_count:{psid}",
    )
    logger.info(f"Session fully reset for {psid}")
    