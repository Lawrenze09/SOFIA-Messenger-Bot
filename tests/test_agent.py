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
    """Rule-based engine returns without touching Gemini."""

    def test_menu_trigger(self, agent):
        response, failure = agent.build_response("menu", Intent.SMALL_TALK)
        assert "Sofia" in response
        assert failure == GuardrailFailure.NONE

    def test_small_talk_returns_menu(self, agent):
        response, failure = agent.build_response("hello", Intent.SMALL_TALK)
        assert "Ace Apparel" in response
        assert failure == GuardrailFailure.NONE

    def test_buy_exact_confirmation(self, agent):
        response, failure = agent.build_response("buy", Intent.PURCHASE)
        assert "Bigboss" in response
        assert failure == GuardrailFailure.NONE

    def test_purchase_intent_prompt(self, agent):
        response, failure = agent.build_response("pabili ng hoodie", Intent.PURCHASE)
        assert "buy" in response.lower()
        assert failure == GuardrailFailure.NONE

    def test_banter_response(self, agent):
        response, failure = agent.build_response("gago ka", Intent.BANTER)
        assert failure == GuardrailFailure.NONE
        assert len(response) > 0

    @patch("core.sofia_agent.generate_response", return_value="Magkano ng ano boss? Anong item?")
    @patch("core.sofia_agent.retrieve_product_context", return_value="")
    @patch("core.sofia_agent.search_products", return_value=[])
    def test_product_no_match(self, mock_search, mock_rag, mock_gen, agent):
        response, failure = agent.build_response("may tuxedo kayo?", Intent.PRODUCT_INQUIRY)
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
    def test_product_match_formats_reply(self, mock_search, agent):
        response, failure = agent.build_response("may hoodie ba kayo?", Intent.PRODUCT_INQUIRY)
        assert "Premium Hoodie" in response
        assert "899" in response
        assert failure == GuardrailFailure.NONE


class TestAIFallback:
    """AI fallback is only used for PLAYFUL and UNKNOWN with no product match."""

    @patch("core.sofia_agent.search_products", return_value=[])
    @patch("core.sofia_agent.generate_response", return_value="Secret boss, buy na!")
    @patch("core.sofia_agent.retrieve_product_context", return_value="")
    def test_playful_uses_ai(self, mock_rag, mock_gen, mock_search, agent):
        response, failure = agent.build_response("may puso ka ba?", Intent.PLAYFUL)
        mock_gen.assert_called_once()
        assert failure == GuardrailFailure.NONE
