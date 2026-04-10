"""
tests/test_agent.py
 
Unit tests for SofiaAgent rule-based engine.
Mocks database and LLM calls — no external services needed.
"""
 
import pytest
from unittest.mock import patch
 
from core.sofia_agent import (
    SofiaAgent,
    HANDOVER_INTENTS,
    _HANDOVER_REPLIES,
    MSG_FALLBACK_NO_PRODUCTS,
    MSG_SIZE_CHART,
)
from core.intent_classifier import Intent
from core.guardrails import GuardrailFailure
 
 
@pytest.fixture
def agent():
    return SofiaAgent()
 
 
# ─────────────────────────────────────────────
# KEYWORD HANDOVER
# ─────────────────────────────────────────────
 
class TestKeywordHandover:
    """needs_keyword_handover() detects raw trigger words in message text."""
 
    def test_admin_keyword(self, agent):
        assert agent.needs_keyword_handover("paki connect sa admin") is True
 
    def test_refund_keyword(self, agent):
        assert agent.needs_keyword_handover("gusto ko mag refund") is True
 
    def test_no_handover(self, agent):
        assert agent.needs_keyword_handover("magkano yung hoodie") is False
 
 
# ─────────────────────────────────────────────
# REQUIRES HANDOVER
# ─────────────────────────────────────────────
 
class TestRequiresHandover:
    """requires_handover() returns True for all five escalation intents."""
 
    def test_purchase_requires_handover(self, agent):
        assert agent.requires_handover(Intent.PURCHASE) is True
 
    def test_complaint_requires_handover(self, agent):
        assert agent.requires_handover(Intent.COMPLAINT) is True
 
    def test_wholesale_requires_handover(self, agent):
        assert agent.requires_handover(Intent.WHOLE_SALE) is True
 
    def test_shipping_requires_handover(self, agent):
        assert agent.requires_handover(Intent.SHIPPING_INFO) is True
 
    def test_refund_requires_handover(self, agent):
        assert agent.requires_handover(Intent.REFUND_REQUEST) is True
 
    def test_product_inquiry_does_not_require_handover(self, agent):
        assert agent.requires_handover(Intent.PRODUCT_INQUIRY) is False
 
    def test_small_talk_does_not_require_handover(self, agent):
        assert agent.requires_handover(Intent.SMALL_TALK) is False
 
    def test_size_chart_does_not_require_handover(self, agent):
        assert agent.requires_handover(Intent.SIZE_CHART) is False
 
 
# ─────────────────────────────────────────────
# HANDOVER INTENTS — RULE-BASED, NO LLM
# ─────────────────────────────────────────────
 
class TestHandoverIntentResponses:
    """
    All five handover intents must return a deterministic rule-based
    reply with no LLM involvement and no guardrail failure.
    """
 
    def test_purchase_rule_based(self, agent):
        response, failure = agent.build_response("pabili ng hoodie", Intent.PURCHASE)
        assert "team" in response.lower()
        assert failure == GuardrailFailure.NONE
 
    def test_complaint_rule_based(self, agent):
        response, failure = agent.build_response("sira yung natanggap ko", Intent.COMPLAINT)
        assert "team" in response.lower()
        assert failure == GuardrailFailure.NONE
 
    def test_wholesale_rule_based(self, agent):
        response, failure = agent.build_response("wholesale kayo?", Intent.WHOLE_SALE)
        assert "team" in response.lower()
        assert failure == GuardrailFailure.NONE
 
    def test_shipping_rule_based(self, agent):
        response, failure = agent.build_response("pano delivery?", Intent.SHIPPING_INFO)
        assert "team" in response.lower()
        assert failure == GuardrailFailure.NONE
 
    def test_refund_rule_based(self, agent):
        response, failure = agent.build_response("gusto ko mag refund", Intent.REFUND_REQUEST)
        assert "team" in response.lower()
        assert failure == GuardrailFailure.NONE
 
    def test_handover_intents_never_call_llm(self, agent):
        """LLM must never be called for any handover intent."""
        with patch("core.sofia_agent.generate_response") as mock_gen:
            for intent in HANDOVER_INTENTS:
                agent.build_response("test message", intent)
            mock_gen.assert_not_called()
 
    def test_handover_replies_map_is_complete(self, agent):
        """Every intent in HANDOVER_INTENTS must have a reply in _HANDOVER_REPLIES."""
        for intent in HANDOVER_INTENTS:
            assert intent in _HANDOVER_REPLIES, (
                f"{intent.value} is in HANDOVER_INTENTS but missing from _HANDOVER_REPLIES"
            )
 
 
# ─────────────────────────────────────────────
# SIZE CHART — DETERMINISTIC, BOT STAYS ACTIVE
# ─────────────────────────────────────────────
 
class TestSizeChart:
    """SIZE_CHART returns deterministic reply, LLM never called."""
 
    def test_size_chart_returns_message(self, agent):
        response, failure = agent.build_response("may size chart kayo?", Intent.SIZE_CHART)
        assert response == MSG_SIZE_CHART
        assert failure == GuardrailFailure.NONE
 
    def test_size_chart_never_calls_llm(self, agent):
        with patch("core.sofia_agent.generate_response") as mock_gen:
            agent.build_response("may size chart kayo?", Intent.SIZE_CHART)
            mock_gen.assert_not_called()
 
 
# ─────────────────────────────────────────────
# PRODUCT INTENTS — TiDB FIRST, LLM FALLBACK
# ─────────────────────────────────────────────
 
class TestProductIntents:
    """
    PRODUCT_INQUIRY and PRICE_QUERY use TiDB SQL as the primary source.
    LLM is only called when TiDB returns no match.
    """
 
    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_product_match_rule_based(self, mock_search, agent):
        response, failure = agent.build_response(
            "may hoodie ba kayo?", Intent.PRODUCT_INQUIRY
        )
        assert "Premium Hoodie" in response
        assert "899" in response
        assert failure == GuardrailFailure.NONE
 
    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_product_match_never_calls_llm(self, mock_search, agent):
        """LLM must never be called when TiDB returns a product match."""
        with patch("core.sofia_agent.generate_response") as mock_gen:
            agent.build_response("may hoodie ba kayo?", Intent.PRODUCT_INQUIRY)
            mock_gen.assert_not_called()
 
    @patch("core.sofia_agent.generate_response",
           return_value="Wala kaming ganyan boss, baka may iba kang trip?")
    @patch("core.sofia_agent.retrieve_product_context", return_value="")
    @patch("core.sofia_agent.search_products", return_value=[])
    def test_product_no_match_uses_llm(
        self, mock_search, mock_rag, mock_gen, agent
    ):
        """LLM is called when TiDB returns no product match."""
        response, failure = agent.build_response(
            "may tuxedo kayo?", Intent.PRODUCT_INQUIRY
        )
        mock_gen.assert_called_once()
        assert failure == GuardrailFailure.NONE
        assert len(response) > 0
 
    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_product_llm_failure_returns_fallback_with_products(
        self, mock_search, agent
    ):
        """When Gemini fails on product miss, fallback with products is returned."""
        with patch("core.sofia_agent.retrieve_product_context", return_value=""), \
             patch("core.sofia_agent.generate_response",
                   side_effect=Exception("Gemini unavailable")):
            # First search_products call returns [] for the product lookup
            # Second call returns the product list for build_fallback_with_products
            with patch("core.sofia_agent.search_products",
                       side_effect=[[], [{
                           "name": "Premium Hoodie",
                           "size": "S-XL",
                           "price": 899.00,
                           "description": "400 GSM heavy cotton",
                           "category": "hoodie",
                           "stock_quantity": 10,
                       }]]):
                response, failure = agent.build_response(
                    "may tuxedo kayo?", Intent.PRODUCT_INQUIRY
                )
                assert failure == GuardrailFailure.NONE
                assert "admin" in response.lower()
 
 
# ─────────────────────────────────────────────
# CONVERSATIONAL INTENTS — GEMINI PRIMARY
# ─────────────────────────────────────────────
 
class TestConversationalIntents:
    """
    SMALL_TALK, PLAYFUL, BANTER, UNKNOWN use Gemini as primary.
    build_fallback_with_products() is returned when Gemini fails.
    """
 
    def test_small_talk_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Kamusta boss! Anong hanap mo?") as mock_gen:
            response, failure = agent.build_response(
                "hello", Intent.SMALL_TALK
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE
 
    def test_playful_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Secret boss, anong trip mo?") as mock_gen:
            response, failure = agent.build_response(
                "may puso ka ba?", Intent.PLAYFUL
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE
 
    def test_banter_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Haha chill boss!") as mock_gen:
            response, failure = agent.build_response(
                "gago ka", Intent.BANTER
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE
 
    def test_unknown_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Di ko gets boss, ulitin mo?") as mock_gen:
            response, failure = agent.build_response(
                "random xyz text", Intent.UNKNOWN
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE

    def test_llm_response_with_guardrail_failure_propagates_enum(self, agent):
        """build_response() must return the guardrail failure enum to the caller."""
        with patch("core.sofia_agent.generate_response",
                   return_value="I am 100% sure this is available PHP 599"):
            response, failure = agent.build_response(
                "kumusta?", Intent.SMALL_TALK
            )
            assert failure != GuardrailFailure.NONE
            assert response == "I am 100% sure this is available PHP 599"
 
    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_llm_failure_returns_fallback_with_products(
        self, mock_search, agent
    ):
        """When Gemini fails, build_fallback_with_products() is returned."""
        with patch("core.sofia_agent.generate_response",
                   side_effect=Exception("Gemini unavailable")):
            response, failure = agent.build_response(
                "kumusta?", Intent.SMALL_TALK
            )
            assert failure == GuardrailFailure.NONE
            assert "admin" in response.lower()
            assert "Premium Hoodie" in response
 
    @patch("core.sofia_agent.search_products", return_value=[])
    def test_llm_failure_no_products_returns_fallback(
        self, mock_search, agent
    ):
        """When Gemini fails and TiDB is empty, MSG_FALLBACK_NO_PRODUCTS returned."""
        with patch("core.sofia_agent.generate_response",
                   side_effect=Exception("Gemini unavailable")):
            response, failure = agent.build_response(
                "kumusta?", Intent.SMALL_TALK
            )
            assert failure == GuardrailFailure.NONE
            assert response == MSG_FALLBACK_NO_PRODUCTS
 
 
# ─────────────────────────────────────────────
# UNIFIED FALLBACK BUILDER
# ─────────────────────────────────────────────
 
class TestBuildFallbackWithProducts:
    """
    build_fallback_with_products() is the single fallback for all
    failure paths — guardrail failure, LLM exception, product miss.
    """
 
    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_fallback_includes_products(self, mock_search, agent):
        result = agent.build_fallback_with_products()
        assert "Premium Hoodie" in result
        assert "admin" in result.lower()
 
    @patch("core.sofia_agent.search_products", return_value=[])
    def test_fallback_no_products_returns_no_products_message(
        self, mock_search, agent
    ):
        result = agent.build_fallback_with_products()
        assert result == MSG_FALLBACK_NO_PRODUCTS
 
    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_fallback_uses_msg_fallback_with_products_template(
        self, mock_search, agent
    ):
        """Fallback message must use MSG_FALLBACK_WITH_PRODUCTS template."""
        result = agent.build_fallback_with_products()
        # Template text should appear in the output
        assert "di ko alam" in result.lower()
        assert "products namin" in result.lower()
 