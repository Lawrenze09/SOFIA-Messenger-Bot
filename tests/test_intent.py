"""
tests/test_intent.py

Unit tests for the intent classification engine.
Tests keyword matching priority and edge cases.
"""

import pytest
from unittest.mock import patch

from core.intent_classifier import Intent, classify


class TestKeywordClassification:
    """Keyword-based classification — zero API cost."""

    def test_purchase_pabili(self):
        assert classify("pabili nga ako ng hoodie") == Intent.PURCHASE

    def test_purchase_buy_exact(self):
        assert classify("buy") == Intent.PURCHASE

    def test_purchase_before_product_inquiry(self):
        # "bili" exists in PRODUCT_INQUIRY but "pabili" must match PURCHASE first
        assert classify("pabili") == Intent.PURCHASE

    def test_product_inquiry_hoodie(self):
        assert classify("meron ba kayong hoodie?") == Intent.PRODUCT_INQUIRY

    def test_price_query_magkano(self):
        assert classify("magkano yung pants?") == Intent.PRICE_QUERY

    def test_small_talk_hello(self):
        assert classify("hello") == Intent.SMALL_TALK

    def test_small_talk_hi(self):
        assert classify("hi") == Intent.SMALL_TALK

    def test_complaint_sira(self):
        assert classify("sira yung natanggap ko") == Intent.COMPLAINT

    def test_refund_request(self):
        assert classify("gusto ko mag refund") == Intent.REFUND_REQUEST

    def test_wholesale(self):
        assert classify("wholesale kayo?") == Intent.WHOLE_SALE

    def test_shipping(self):
        assert classify("pano ang delivery?") == Intent.SHIPPING_INFO

    def test_banter(self):
        assert classify("gagi ka talaga") == Intent.BANTER

    def test_playful_haha(self):
        assert classify("haha panalo") == Intent.PLAYFUL


class TestGeminiFallback:
    """Gemini fallback — only triggers when no keyword matches."""

    @patch("core.intent_classifier.gemini_classify", return_value="UNKNOWN")
    def test_fallback_returns_unknown(self, mock_gemini):
        result = classify("some completely random text xyz")
        assert result == Intent.UNKNOWN
        mock_gemini.assert_called_once()

    @patch("core.intent_classifier.gemini_classify", return_value="PRODUCT_INQUIRY")
    def test_fallback_returns_valid_intent(self, mock_gemini):
        result = classify("anong mga tinda ninyo")
        # "tinda" has no keyword, should fall back to Gemini
        assert result == Intent.PRODUCT_INQUIRY
