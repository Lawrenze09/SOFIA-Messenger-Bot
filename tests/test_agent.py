"""
tests/test_agent.py

Unit tests for SofiaAgent rule-based engine.
Mocks database and LLM calls — no external services needed.
"""

import pytest
from unittest.mock import patch, MagicMock

from core.sofia_agent import SofiaAgent
from core.intent_classifier import Intent
from core.guardrails import GuardrailFailure


@pytest.fixture
def agent():
    return SofiaAgent()


class TestKeywordHandover:
    def test_admin_keyword(self, agent):
        assert agent.needs_keyword_handover("paki connect sa admin") is True

    def test_refund_keyword(self, agent):
        assert agent.needs_keyword_handover("gusto ko mag refund") is True

    def test_no_handover(self, agent):
        assert agent.needs_keyword_handover("magkano yung hoodie") is False


class TestRuleBasedResponses:
    """Rule-based engine — guaranteed deterministic exits."""

    def test_purchase_intent_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Noted boss! Anong size mo?") as mock_gen:
            response, failure = agent.build_response(
                "pabili ng hoodie", Intent.PURCHASE
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE
            assert len(response) > 0

    def test_small_talk_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Kamusta boss! Anong hanap mo?") as mock_gen:
            response, failure = agent.build_response(
                "hello", Intent.SMALL_TALK
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE

    def test_wholesale_rule_based(self, agent):
        response, failure = agent.build_response("wholesale kayo?", Intent.WHOLE_SALE)
        assert "admin" in response.lower()
        assert failure == GuardrailFailure.NONE

    def test_shipping_rule_based(self, agent):
        response, failure = agent.build_response("pano delivery?", Intent.SHIPPING_INFO)
        assert "admin" in response.lower()
        assert failure == GuardrailFailure.NONE

    def test_banter_uses_llm(self, agent):
        with patch("core.sofia_agent.generate_response",
                   return_value="Haha chill boss!") as mock_gen:
            response, failure = agent.build_response(
                "gago ka", Intent.BANTER
            )
            mock_gen.assert_called_once()
            assert failure == GuardrailFailure.NONE
            assert len(response) > 0

    @patch("core.sofia_agent.generate_response",
           return_value="Magkano ng ano boss? Anong item?")
    @patch("core.sofia_agent.retrieve_product_context", return_value="")
    @patch("core.sofia_agent.search_products", return_value=[])
    def test_product_no_match_uses_llm(
        self, mock_search, mock_rag, mock_gen, agent
    ):
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


class TestAIFallback:
    """LLM is primary for PLAYFUL, SMALL_TALK, BANTER, UNKNOWN."""

    @patch("core.sofia_agent.search_products", return_value=[])
    @patch("core.sofia_agent.generate_response",
           return_value="Secret boss, anong trip mo?")
    @patch("core.sofia_agent.retrieve_product_context", return_value="")
    def test_playful_uses_llm(self, mock_rag, mock_gen, mock_search, agent):
        response, failure = agent.build_response(
            "may puso ka ba?", Intent.PLAYFUL
        )
        mock_gen.assert_called_once()
        assert failure == GuardrailFailure.NONE

    @patch("core.sofia_agent.generate_response",
           side_effect=Exception("Gemini unavailable"))
    @patch("core.sofia_agent.search_products", return_value=[])
    def test_llm_failure_returns_fallback(self, mock_search, mock_gen, agent):
        """When Gemini fails, Sofia returns the safe fallback message."""
        response, failure = agent.build_response(
            "kumusta?", Intent.SMALL_TALK
        )
        assert failure == GuardrailFailure.NONE
        assert "admin" in response.lower() or "technical" in response.lower()


class TestGuardrailFallback:
    """build_guardrail_fallback injects live products into fallback message."""

    @patch("core.sofia_agent.search_products", return_value=[{
        "name": "Premium Hoodie",
        "size": "S-XL",
        "price": 899.00,
        "description": "400 GSM heavy cotton",
        "category": "hoodie",
        "stock_quantity": 10,
    }])
    def test_guardrail_fallback_includes_products(self, mock_search, agent):
        result = agent.build_guardrail_fallback()
        assert "Premium Hoodie" in result
        assert "admin" in result.lower()

    @patch("core.sofia_agent.search_products", return_value=[])
    def test_guardrail_fallback_no_products(self, mock_search, agent):
        result = agent.build_guardrail_fallback()
        assert "admin" in result.lower()
        