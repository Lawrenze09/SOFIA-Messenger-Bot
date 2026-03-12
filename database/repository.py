"""
database/repository.py

All database read/write operations in one place.
No SQL should exist outside this module.
"""

from datetime import datetime, timezone

from database.client import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────

def upsert_session(session_id: str, user_id: str) -> None:
    """
    Insert a new session or update last_seen if it already exists.

    Args:
        session_id: UUID for this session.
        user_id:    Facebook PSID of the customer.
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        now    = datetime.now(timezone.utc)
        cursor.execute(
            """
            INSERT INTO sessions (session_id, user_id, started_at, last_seen, state)
            VALUES (%s, %s, %s, %s, 'BOT_ACTIVE')
            ON DUPLICATE KEY UPDATE last_seen = %s
            """,
            (session_id, user_id, now, now, now),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        logger.error(f"upsert_session error: {exc}")


# ─────────────────────────────────────────────
# MESSAGES
# ─────────────────────────────────────────────

def log_message(
    session_id: str,
    user_id: str,
    message: str,
    response: str,
    intent: str,
    response_time: float,
) -> None:
    """
    Persist a customer message and bot response to the messages table.

    Args:
        session_id:    Active session UUID.
        user_id:       Facebook PSID.
        message:       Raw customer message text.
        response:      Bot response text.
        intent:        Classified intent label.
        response_time: Processing time in seconds.
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages
                (session_id, user_id, message, response, intent, timestamp, response_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (session_id, user_id, message, response, intent,
             datetime.now(timezone.utc), response_time),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        logger.error(f"log_message error: {exc}")


# ─────────────────────────────────────────────
# INTENT LOG
# ─────────────────────────────────────────────

def log_intent(
    user_id: str,
    session_id: str,
    intent: str,
    message: str,
) -> None:
    """
    Log the classified intent for analytics and monthly reporting.

    Args:
        user_id:    Facebook PSID.
        session_id: Active session UUID.
        intent:     Classified intent label.
        message:    Raw customer message.
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO intent_log (user_id, session_id, intent, message, timestamp)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, session_id, intent, message, datetime.now(timezone.utc)),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        logger.error(f"log_intent error: {exc}")


# ─────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────

def search_products(text: str, max_price: float | None = None) -> list[dict]:
    """
    Search products by name, category, or description using LIKE matching.
    Tries full phrase first, then falls back to individual word matching.
    Optionally filters by price ceiling (max_price).

    Args:
        text:      Customer message to search against product data.
        max_price: Optional price ceiling — returns only products <= this price.

    Returns:
        List of matching product dicts (up to 3 results).
    """
    try:
        lower  = text.lower()
        conn   = get_connection()
        cursor = conn.cursor()

        # ── Build price filter ──
        price_filter = " AND price <= %s" if max_price is not None else ""

        # ── Full phrase match ──
        params = [f"%{lower}%", f"%{lower}%", f"%{lower}%"]
        if max_price is not None:
            params.append(max_price)

        cursor.execute(
            f"""
            SELECT name, size, price, description, category, stock_quantity
            FROM products
            WHERE stock_quantity > 0
            AND (
                LOWER(name)        LIKE %s OR
                LOWER(category)    LIKE %s OR
                LOWER(description) LIKE %s
            )
            {price_filter}
            LIMIT 3
            """,
            params,
        )
        rows = cursor.fetchall()

        # ── Word-by-word fallback ──
        if not rows:
            stop_words = {
                "po", "ba", "ko", "mo", "na", "ng", "sa", "ang", "mga",
                "ay", "at", "pa", "lang", "yung", "ung", "boss", "the",
                "a", "is", "are", "for", "of", "may", "wala", "ano",
            }
            words = [
                w for w in lower.split()
                if len(w) > 2 and w not in stop_words
            ]
            for word in words:
                word_params = [f"%{word}%", f"%{word}%", f"%{word}%"]
                if max_price is not None:
                    word_params.append(max_price)

                cursor.execute(
                    f"""
                    SELECT name, size, price, description, category, stock_quantity
                    FROM products
                    WHERE stock_quantity > 0
                    AND (
                        LOWER(name)        LIKE %s OR
                        LOWER(category)    LIKE %s OR
                        LOWER(description) LIKE %s
                    )
                    {price_filter}
                    LIMIT 3
                    """,
                    word_params,
                )
                rows = cursor.fetchall()
                if rows:
                    break

        cursor.close()
        conn.close()
        return rows or []

    except Exception as exc:
        logger.error(f"search_products error: {exc}")
        return []


# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────

def get_monthly_report(year: int, month: int) -> dict:
    """
    Generate intent distribution report for a given month.

    Args:
        year:  4-digit year.
        month: Month number (1-12).

    Returns:
        Dict with year, month, and distribution list.
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                intent,
                COUNT(*) AS count,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage
            FROM intent_log
            WHERE YEAR(timestamp) = %s AND MONTH(timestamp) = %s
            GROUP BY intent
            ORDER BY count DESC
            """,
            (year, month),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {"year": year, "month": month, "distribution": rows}
    except Exception as exc:
        logger.error(f"get_monthly_report error: {exc}")
        return {}
