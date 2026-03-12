"""
app/routes.py

Flask webhook routes.
Handles Facebook Messenger webhook verification and event processing.
Delegates all business logic to services and core modules.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, request, jsonify

from config import settings
from core import (
    Intent,
    SofiaAgent,
    MSG_KEYWORD_HANDOVER,
    MSG_GUARDRAIL_HANDOVER,
    GuardrailFailure,
    classify,
)
from database import log_intent, log_message, get_monthly_report
from services.session_service import (
    SessionState,
    get_session_state,
    set_session_state,
    get_or_create_session_id,
    is_bot_reactivation,
    is_spam,
    apply_message_gap,
    reset_session,
    get_redis,
)
from services.messenger_service import send_message
from services.email_service     import send_admin_alert
from utils.security import verify_hmac, is_prompt_injection, is_silent_message, is_duplicate

from utils.logger import get_logger

logger   = get_logger(__name__)
router   = Blueprint("webhook", __name__)
executor = ThreadPoolExecutor(max_workers=4)
agent    = SofiaAgent()


# ─────────────────────────────────────────────
# WEBHOOK VERIFICATION
# ─────────────────────────────────────────────

@router.get("/webhook")
def webhook_verify():
    """Facebook webhook challenge verification."""
    if (request.args.get("hub.mode")         == "subscribe" and
        request.args.get("hub.verify_token")  == settings.verify_token):
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403


# ─────────────────────────────────────────────
# WEBHOOK EVENT RECEIVER
# ─────────────────────────────────────────────

@router.post("/webhook")
def webhook():
    """
    Receive Facebook Messenger events.
    Verifies HMAC signature then dispatches to background thread.
    Always returns 200 immediately to prevent Meta retries.
    """
    payload   = request.get_data()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_hmac(payload, signature, settings.meta_app_secret):
        logger.warning("HMAC verification failed — rejected webhook event")
        return "Unauthorized", 401

    try:
        body = request.get_json(force=True)
    except Exception:
        return "Bad Request", 400

    executor.submit(_handle_payload, body)
    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────
# ADMIN ENDPOINTS
# ─────────────────────────────────────────────

@router.post("/reset/<psid>")
def reset_user_session(psid: str):
    """
    Emergency session reset for a specific user.
    Use when a customer gets stuck in HUMAN_ACTIVE state.
    """
    try:
        reset_session(psid)
        return jsonify({"status": "ok", "psid": psid, "state": "BOT_ACTIVE"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@router.get("/health")
def health():
    """Service health check — verifies Redis and MySQL connectivity."""
    from database.client import get_connection
    checks: dict = {}

    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    try:
        conn = get_connection()
        conn.close()
        checks["mysql"] = "ok"
    except Exception as exc:
        checks["mysql"] = f"error: {exc}"

    checks["status"] = (
        "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    )
    return jsonify(checks), 200


@router.get("/analytics/monthly")
def monthly_analytics():
    """Return intent distribution report for the requested month."""
    from datetime import datetime, timezone
    now   = datetime.now(timezone.utc)
    year  = request.args.get("year",  default=now.year,  type=int)
    month = request.args.get("month", default=now.month, type=int)
    return jsonify(get_monthly_report(year, month)), 200


# ─────────────────────────────────────────────
# PAYLOAD HANDLER
# ─────────────────────────────────────────────

def _handle_payload(body: dict) -> None:
    """
    Process incoming Messenger webhook payload.
    Handles echo events (admin replies) and customer messages.
    """
    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            psid = (event.get("sender") or {}).get("id")
            if not psid:
                continue

            # ── Skip read receipts and delivery confirmations ──
            if "read" in event or "delivery" in event:
                continue

            # ── Echo events — admin typing in Page Inbox ──
            if event.get("message", {}).get("is_echo"):
                text          = event["message"].get("text", "")
                customer_psid = (event.get("recipient") or {}).get("id")
                if text and customer_psid:
                    if is_bot_reactivation(text):
                        _handle_admin_echo(customer_psid, text)
                    elif not event["message"].get("app_id"):
                        _handle_admin_echo(customer_psid, text)
                continue

            # ── Customer message ──
            msg  = event.get("message", {})
            text = msg.get("text", "").strip()
            mid  = msg.get("mid", "")

            if not text or not mid:
                continue

            if is_duplicate(mid, get_redis(), settings.dedup_ttl):
                logger.info(f"Duplicate message dropped: {mid}")
                continue

            if get_session_state(psid) == SessionState.HUMAN_ACTIVE:
                logger.info(f"HUMAN_ACTIVE — message ignored for {psid}")
                continue

            executor.submit(_process_message, psid, text, mid)


def _handle_admin_echo(customer_psid: str, text: str) -> None:
    """
    Process an echo event from the admin typing in Page Inbox.
    Reactivation commands re-enable the bot; all other text pauses it.
    """
    if is_bot_reactivation(text):
        set_session_state(customer_psid, SessionState.BOT_ACTIVE)
        logger.info(f"Bot reactivated for customer {customer_psid}")
    else:
        set_session_state(customer_psid, SessionState.HUMAN_ACTIVE)
        logger.info(f"Bot paused — admin responding to {customer_psid}")


# ─────────────────────────────────────────────
# CORE MESSAGE PROCESSOR
# ─────────────────────────────────────────────

def _process_message(psid: str, text: str, mid: str) -> None:
    """
    Main message processing pipeline.

    Order of operations:
    1. Silent message drop
    2. Spam detection
    3. Message rate gap enforcement
    4. Prompt injection check
    5. Intent classification
    6. Escalation routing (refund, complaint, wholesale, shipping)
    7. Purchase handling
    8. Rule-based engine
    9. AI fallback with guardrails
    """
    start_time = time.time()

    # ── 1. Silent drop ──
    if is_silent_message(text):
        logger.info(f"Silent message dropped for {psid}")
        return

    # ── 2. Spam check ──
    if is_spam(psid):
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        logger.warning(f"Spam block — session paused for {psid}")
        return

    # ── 3. Rate gap ──
    apply_message_gap(psid)

    session_id = get_or_create_session_id(psid)

    # ── 4. Injection check ──
    if is_prompt_injection(text):
        send_message(psid,
            "Hindi po ako makapag-process ng mensaheng iyan. "
            "Subukan po ulit na mag-type ng inyong tanong."
        )
        return

    # ── 5. Intent classification ──
    intent = classify(text)
    log_intent(psid, session_id, intent.value, text)

    # ── 6a. Keyword handover or REFUND / COMPLAINT ──
    if agent.needs_keyword_handover(text) or intent in (
        Intent.REFUND_REQUEST,
        Intent.COMPLAINT,
    ):
        send_message(psid, MSG_KEYWORD_HANDOVER)
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        send_admin_alert(psid, text, intent.value, "Keyword Escalation")
        log_message(psid, session_id, text, MSG_KEYWORD_HANDOVER,
                    intent.value, time.time() - start_time)
        return

    # ── 6b. WHOLESALE / SHIPPING — reply then pause ──
    if intent in (Intent.WHOLE_SALE, Intent.SHIPPING_INFO):
        response, _ = agent.build_response(text, intent)
        send_message(psid, response)
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        send_admin_alert(psid, text, intent.value, f"Admin Inquiry: {intent.value}")
        log_message(psid, session_id, text, response,
                    intent.value, time.time() - start_time)
        return

    # ── 7. PURCHASE — confirm + alert admin, bot stays active ──
    if intent == Intent.PURCHASE:
        response, _ = agent.build_response(text, intent)
        send_message(psid, response)
        send_admin_alert(psid, text, intent.value, "Purchase Intent")
        log_message(psid, session_id, text, response,
                    intent.value, time.time() - start_time)
        return

    # ── 8 & 9. Rule-based engine → AI fallback + guardrails ──
    response, failure = agent.build_response(text, intent)

    if failure != GuardrailFailure.NONE:
        send_message(psid, MSG_GUARDRAIL_HANDOVER)
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        send_admin_alert(psid, text, intent.value,
                         f"Guardrail Failure: {failure.value}")
        log_message(psid, session_id, text, MSG_GUARDRAIL_HANDOVER,
                    intent.value, time.time() - start_time)
        return

    send_message(psid, response)
    log_message(psid, session_id, text, response,
                intent.value, time.time() - start_time)