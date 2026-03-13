"""
core/intent_classifier.py

Two-stage intent classification:
1. Keyword matching — instant, zero API cost
2. Gemini fallback — only when no keyword matches

Intent priority order in _INTENT_KEYWORDS matters:
PURCHASE must appear before PRODUCT_INQUIRY to prevent
"pabili" from matching the "bili" keyword in PRODUCT_INQUIRY.
"""

from enum import Enum

from services.llm_service import classify_intent as gemini_classify
from utils.logger import get_logger

logger = get_logger(__name__)


class Intent(str, Enum):
    PRODUCT_INQUIRY = "PRODUCT_INQUIRY"
    PRICE_QUERY     = "PRICE_QUERY"
    REFUND_REQUEST  = "REFUND_REQUEST"
    SMALL_TALK      = "SMALL_TALK"
    COMPLAINT       = "COMPLAINT"
    WHOLE_SALE      = "WHOLE_SALE"
    SHIPPING_INFO   = "SHIPPING_INFO"
    PURCHASE        = "PURCHASE"
    SIZE_CHART      = "SIZE_CHART"
    PLAYFUL         = "PLAYFUL"
    BANTER          = "BANTER"
    UNKNOWN         = "UNKNOWN"


# ── Order matters — more specific intents first ──
_INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.REFUND_REQUEST: [
        "refund", "ibalik", "return", "palitan", "pera ko", "bayad ko", "soli",
    ],
    Intent.COMPLAINT: [
        "complaint", "reklamo", "sira", "defective", "broken",
        "problem", "issue", "hindi okay",
    ],
    Intent.WHOLE_SALE: [
        "whole sale", "bultuhan", "maramihan", "reseller", "bulto",
        "pakyawan", "pakyawin", "bulk", "wholesale",
    ],
    Intent.SHIPPING_INFO: [
        "shipping", "deliver", "delivery", "pano delivery",
        "pano deliver", "dedeliver", "anong place", "anong location",
        "loc", "location",
    ],
    Intent.PURCHASE: [
        "bili na", "order na", "pabili", "kuha na", "gusto ko na",
        "pwede bang order", "pano mag order", "checkout",
        "how to order", "how to buy", "place order", "i'll take",
        "get ko na", "kukunin ko", "bibilhin ko", "bilhin ko na",
        "getlak", "g na yan", "g ko na", "bilhin", "buy",
    ],
    Intent.PRICE_QUERY: [
        "magkano", "how much", "price", "presyo", "halaga", "cost", "mag kano",
    ],
    Intent.SIZE_CHART: [
    "size chart", "size guide", "size reference", "boxer size chart",
    "size table", "sukat chart", "size ng boxer",
    "fitting chart", "size ko", "anong size ko", "size checker",
    ],
    Intent.PRODUCT_INQUIRY: [
        "available", "meron", "stock", "product", "item", "color",
        "kulay", "avail", "colorway", "pants", "hoodie", "jacket",
        "balaclava", "harrington", "baggy", "premium", "premiums",
        "order", "gusto", "paorder", "pa order", "gsm", "crop", "half zip",
        "pullover", "heavy cotton", "ribbings", "streetwear", "dickies",
        "leopard", "bandana", "300 - 400 gsm",
    ],
    Intent.BANTER: [
        "tarantado", "gago", "gagi", "ulul", "bulbol",
        "loko", "walang modo", "kupal",
    ],
    Intent.PLAYFUL: [
        "charot", "lol", "haha", "hahaha", "char", "jk", "landi",
        "crush", "mahal", "miss na miss", "boring", "ingay", "libre",
        "libre ba", "pabibo", "bored", "anong vibes", "feelings",
        "may puso ka ba", "robot ka ba", "tao ka ba", "sino ka talaga",
        "ganda mo", "maganda ka", "panget", "arte", "oa", "extra",
        "pautang", "wee", "kota", "aray ko",
    ],
    Intent.SMALL_TALK: [
        "hello", "hi", "kumusta", "good morning", "good afternoon",
        "kamusta", "hey", "musta", "sup",
        "good evening", "magandang umaga", "magandang hapon",
        "magandang gabi", "ace", "sofia",
    ],
}

_ALL_LABELS = [i.value for i in Intent]


def classify(message: str) -> Intent:
    """
    Classify a customer message into an Intent.

    Stage 1: Keyword scan — O(n) substring match, zero API cost.
    Stage 2: Gemini fallback — only if no keyword matched.

    Args:
        message: Raw customer message text.

    Returns:
        Intent enum value.
    """
    lower = message.lower()

    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            logger.info(f"Intent classified by keyword: {intent.value}")
            return intent

    logger.info("No keyword match — falling back to Gemini classifier")
    label = gemini_classify(message, _ALL_LABELS)
    try:
        intent = Intent(label)
        logger.info(f"Intent classified by Gemini: {intent.value}")
        return intent
    except ValueError:
        logger.warning(f"Gemini returned unknown label: '{label}' — defaulting to UNKNOWN")
        return Intent.UNKNOWN
    