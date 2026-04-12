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
    MSG_SIZE_CHART,
    SIZE_CHART_BOXER,
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
    is_first_message,
    is_spam,
    apply_message_gap,
    reset_session,
    get_redis,
)
from services.messenger_service import send_message, send_image
from services.email_service     import send_admin_alert
from utils.security import (
    verify_hmac,
    is_prompt_injection,
    is_silent_message,
    is_duplicate,
)
 
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
 
    Echo handling — app_id filtering:
    Meta echoes ALL outbound page messages back to the webhook with
    is_echo: true. This includes Sofia's own automated replies.
    We filter by app_id to distinguish echo sources:
 
    - Sofia's own replies carry settings.meta_app_id — skipped entirely
      so Sofia never pauses herself after sending a response.
    - Admin manual replies from Page Inbox carry null or a different
      app_id — processed by _handle_admin_echo → HUMAN_ACTIVE.
    - Third party tools connected to the page carry a different app_id
      — also processed by _handle_admin_echo → HUMAN_ACTIVE.
 
    Admin types 'sofia' or 'bot' to reactivate the bot for a customer.
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
 
    # ── Echo handling — synchronous before any background dispatch ──
    # Processes echoes from the page side to guarantee state is written
    # to Redis before any customer message thread is dispatched.
    # Sofia's own outbound replies are filtered out by app_id to prevent
    # the bot from pausing itself after every automated response.
    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            if event.get("message", {}).get("is_echo"):
                echo_app_id   = event.get("message", {}).get("app_id")
                text          = event["message"].get("text", "")
                customer_psid = (event.get("recipient") or {}).get("id")
 
                # ── Skip Sofia's own outbound messages ──
                # These are echoed back by Meta but must not trigger
                # HUMAN_ACTIVE — they originated from this app, not
                # from a human admin.
                if str(echo_app_id) == str(settings.meta_app_id):
                    logger.info(
                        f"Own echo skipped for {customer_psid} "
                        f"— app_id: {echo_app_id}"
                    )
                    continue
 
                if text and customer_psid:
                    _handle_admin_echo(customer_psid, text)
 
    executor.submit(_handle_payload, body)
    return jsonify({"status": "ok"}), 200
 
 
# ─────────────────────────────────────────────
# LOCAL DEVELOPMENT ENDPOINT
# ─────────────────────────────────────────────
 
@router.post("/simulate")
def simulate():
    """
    Simulate a customer message through the full processing pipeline.
    Bypasses Meta webhook transport — no Facebook credentials required.
    Disabled in production (returns 403 when RENDER is set).
 
    This endpoint exercises the complete core pipeline:
    intent classification, rule engine, RAG retrieval, guardrails,
    and fallback routing — without requiring ngrok or a Facebook Page.
 
    Request body:
        message (str): Customer message text to process. Required.
        psid    (str): Simulated Facebook PSID. Defaults to 'test_user'.
 
    Returns:
        JSON with intent, response text, and guardrail failure status.
 
    Example:
        POST /simulate
        {"message": "magkano yung hoodie?"}
    """
    if settings.is_production:
        return jsonify({"error": "Not available in production"}), 403
 
    data = request.get_json(force=True) or {}
    text = data.get("message", "").strip()
    psid = data.get("psid", "test_user")
 
    if not text:
        return jsonify({"error": "message field is required"}), 400
 
    # ── Run through the full classification and response pipeline ──
    intent            = classify(text)
    response, failure = agent.build_response(text, intent)
 
    return jsonify({
        "psid"    : psid,
        "message" : text,
        "intent"  : intent.value,
        "response": response,
        "failure" : failure.value,
    }), 200
 
 
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
    Skips echoes — already handled synchronously in webhook().
    """
    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            psid = (event.get("sender") or {}).get("id")
            if not psid:
                continue
 
            # ── Skip read receipts and delivery confirmations ──
            if "read" in event or "delivery" in event:
                continue
 
            # ── Skip echoes — handled synchronously above ──
            if event.get("message", {}).get("is_echo"):
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
    Process an echo event from the page side that did not originate
    from this app. Reactivation commands re-enable the bot.
    ALL other non-app echoes pause the bot — covers manual admin
    replies and any third party tools connected to the page.
 
    Sofia's own outbound replies are filtered out before this function
    is called — see app_id check in webhook().
 
    Args:
        customer_psid: PSID of the customer being messaged.
        text:          Text content of the echo.
    """
    if is_bot_reactivation(text):
        set_session_state(customer_psid, SessionState.BOT_ACTIVE)
        logger.info(f"Bot reactivated for customer {customer_psid}")
    else:
        set_session_state(customer_psid, SessionState.HUMAN_ACTIVE)
        logger.info(f"Bot paused — admin sent message to {customer_psid}")
 
 
# ─────────────────────────────────────────────
# WELCOME MESSAGE BUILDER
# ─────────────────────────────────────────────
 
def _send_welcome(psid: str) -> None:
    """
    Send a one-time welcome message to a first-time customer.
    Shows all current products from TiDB and explains how to
    reach a human assistant.
 
    Args:
        psid: Facebook PSID of the new customer.
    """
    from database.repository import search_products
    products      = search_products("")
    product_lines = []
 
    for p in products:
        product_lines.append(
            f"• {p['name']}\n"
            f"  {p['description']}\n"
            f"  Size: {p['size']}\n"
            f"  ₱{float(p['price']):.2f}"
        )
 
    product_text = "\n\n".join(product_lines) if product_lines else (
        "Pasensya boss, wala kaming products na available ngayon."
    )
 
    welcome = (
        f"Hello boss! Ako si Sofia, ang assistant ng Ace Apparel.\n\n"
        f"Heto ang mga products namin ngayon:\n\n"
        f"{product_text}\n\n"
        f"Kung kailangan mo ng human assistance "
        f"type lang 'admin'.\n"
        f"Para sa kahit anong tanong sa products namin, "
        f"nandito lang ako!"
    )
 
    send_message(psid, welcome)
    logger.info(f"Welcome message sent to new customer {psid}")
 
 
# ─────────────────────────────────────────────
# CORE MESSAGE PROCESSOR
# ─────────────────────────────────────────────
 
def _process_message(psid: str, text: str, mid: str) -> None:
    """
    Main message processing pipeline.
 
    Order of operations:
    1.  First message detection — send welcome + stop
    2.  Silent message drop
    3.  Spam detection — set HUMAN_ACTIVE, silent block
    4.  Message rate gap enforcement
    5.  Prompt injection check
    6.  Intent classification
    7.  Keyword handover check — escalate + pause + alert
    8.  Handover intents (PURCHASE / COMPLAINT / WHOLE_SALE /
        SHIPPING_INFO / REFUND_REQUEST) — rule reply + pause + alert
    9.  SIZE_CHART — send image reply, bot stays active
    10. PRODUCT_INQUIRY / PRICE_QUERY — TiDB first, LLM + RAG fallback
    11. Conversational intents (SMALL_TALK / PLAYFUL / BANTER / UNKNOWN)
        — Gemini primary, rule-based fallback if quota exhausted
    12. Guardrail failure — Sofia-voiced fallback + products + pause
    """
    start_time = time.time()
 
    # ── 1. First message — send welcome and stop ──
    # Customer's next message will go through the full pipeline.
    if is_first_message(psid):
        _send_welcome(psid)
        return
 
    # ── 2. Silent drop ──
    if is_silent_message(text):
        logger.info(f"Silent message dropped for {psid}")
        return
 
    # ── 3. Spam check ──
    if is_spam(psid):
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        logger.warning(f"Spam block — session paused for {psid}")
        return
 
    # ── 4. Rate gap ──
    apply_message_gap(psid)
 
    session_id = get_or_create_session_id(psid)
 
    # ── 5. Injection check ──
    if is_prompt_injection(text):
        send_message(psid,
            "Hm, di ko ma-gets yung sinabi mo boss — "
            "subukan mo ulit, baka may typo lang?"
        )
        return
 
    # ── 6. Intent classification ──
    intent = classify(text)
    log_intent(psid, session_id, intent.value, text)
 
    # ── 7. Keyword handover — raw text contains a trigger keyword ──
    # Checked before intent routing so explicit keywords like 'admin'
    # or 'refund' in a message always escalate regardless of intent.
    if agent.needs_keyword_handover(text):
        send_message(psid, MSG_KEYWORD_HANDOVER)
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        send_admin_alert(psid, text, intent.value, "Keyword Escalation")
        log_message(psid, session_id, text, MSG_KEYWORD_HANDOVER,
                    intent.value, time.time() - start_time)
        return
 
    # ── 8. Handover intents — one rule reply, then pause ──
    # PURCHASE / COMPLAINT / WHOLE_SALE / SHIPPING_INFO / REFUND_REQUEST
    # Bot does not remain active after this reply. Admin types
    # 'sofia' or 'bot' to reactivate for this customer.
    if agent.requires_handover(intent):
        response, _ = agent.build_response(text, intent)
        send_message(psid, response)
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        send_admin_alert(psid, text, intent.value,
                         f"Handover: {intent.value}")
        log_message(psid, session_id, text, response,
                    intent.value, time.time() - start_time)
        return
 
    # ── 9. SIZE_CHART — deterministic image reply, bot stays active ──
    if intent == Intent.SIZE_CHART:
        send_message(psid, MSG_SIZE_CHART)
        send_image(psid, SIZE_CHART_BOXER)
        log_message(psid, session_id, text, MSG_SIZE_CHART,
                    intent.value, time.time() - start_time)
        return
 
    # ── 10 & 11. All remaining intents — TiDB first, LLM fallback ──
    # Covers PRODUCT_INQUIRY, PRICE_QUERY, SMALL_TALK,
    # PLAYFUL, BANTER, UNKNOWN.
    # sofia_agent.build_response() handles routing internally:
    # - PRODUCT / PRICE → TiDB SQL → LLM + RAG on miss
    # - Conversational  → Gemini primary → rule-based on failure
    response, failure = agent.build_response(text, intent)
 
    # ── 12. Guardrail failure — fallback + pause + alert ──
    if failure != GuardrailFailure.NONE:
        fallback = agent.build_fallback_with_products()
        send_message(psid, fallback)
        set_session_state(psid, SessionState.HUMAN_ACTIVE)
        send_admin_alert(psid, text, intent.value,
                         f"Guardrail Failure: {failure.value}")
        log_message(psid, session_id, text, fallback,
                    intent.value, time.time() - start_time)
        return
 
    send_message(psid, response)
    log_message(psid, session_id, text, response,
                intent.value, time.time() - start_time)
    