"""
core/sofia_agent.py

SofiaAgent — the central brain of the chatbot.

Responsibilities:
- Rule-based response engine (guaranteed floor, no LLM cost)
- LLM as primary for conversation, rule-based as fallback
- RAG context injection for AI responses
- Guardrail enforcement on AI output
- Handover detection and escalation routing
- Product formatting for TiDB results

Architecture:
- PRODUCT_INQUIRY / PRICE_QUERY → TiDB SQL always (zero hallucination)
  └── Product found   → Rule-based format, no LLM
  └── Product missing → Gemini + RAG context
- SMALL_TALK / PLAYFUL / BANTER / UNKNOWN → Gemini primary
  └── Gemini fails    → Rule-based safe fallback
- "buy" exact         → Rule-based order confirmation
- Guardrail failure   → Rule-based safe fallback + product display
"""

from core.guardrails import GuardrailFailure, run_guardrails
from core.intent_classifier import Intent
from database.repository import search_products
from services.llm_service import generate_response
from services.rag_service import retrieve_product_context
from utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# HANDOVER KEYWORDS
# ─────────────────────────────────────────────

_HANDOVER_KEYWORDS: list[str] = [
    "admin", "refund", "complaint", "problem",
    "agent", "reklamo", "ibalik",
]


# ─────────────────────────────────────────────
# SYSTEM MESSAGES
# ─────────────────────────────────────────────

MSG_KEYWORD_HANDOVER = (
    "Pasensya na boss, ire-refer kita sa team namin — "
    "mag-me-message sila sa'yo agad."
)

MSG_GUARDRAIL_HANDOVER = (
    "Ay sorry boss, may nangyari sa system ko bigla — "
    "pero heto na ang products namin para hindi ka mahintay:\n\n"
    "{products}\n\n"
    "Kung may gusto kang i-order o kailangan mo ng tulong, "
    "type mo lang 'admin' para ma alert ko agad ang admin. "
    "Nandito lang ako kung may tanong ka sa products!"
)

MSG_GUARDRAIL_NO_PRODUCTS = (
    "Ay sorry boss, may nangyari sa system ko bigla. "
    "Type mo lang 'admin' para ma alert ko agad ang admin."
)

SIZE_CHART_BOXER = (
    "https://raw.githubusercontent.com/Lawrenze09/"
    "SOFIA-Messenger-Bot/main/assets/size-chart-boxer.jpg"
)

MSG_SIZE_CHART = (
    "Sa ngayon Boxer palang ang meron kaming "
    "Size Chart para sa inyong reference."
)

MSG_WHOLESALE = (
    "Usapang negosyo 'to boss — solid! "
    "Iko-connect kita sa team para sa wholesale pricing. "
    "Type mo lang 'admin' para makausap sila agad."
)

MSG_SHIPPING = (
    "Para sa shipping details boss, "
    "mas maganda kung makausap mo directly ang team. "
    "Type mo lang 'admin' at mag-re-reach out sila sa'yo."
)

MSG_LLM_FALLBACK = (
    "Ay sorry boss, may technical issue ako ngayon. "
    "Type mo lang 'admin' kung kailangan mo ng tulong, "
    "o subukan ulit mamaya."
)


# ─────────────────────────────────────────────
# SOFIA AGENT
# ─────────────────────────────────────────────

class SofiaAgent:
    """
    Encapsulates all of Sofia's response logic.

    Attributes:
        system_prompt: Persona and rules injected into every Gemini call.

    Usage:
        agent = SofiaAgent()
        response, failure = agent.build_response(text, intent)
    """

    system_prompt: str = """
ROLE
You are Sofia, the in-house assistant of Ace Apparel —
a Filipino streetwear brand. You're not a formal bot.
You're more like that one friend who actually knows the fits
and will give you a straight answer.

TONE
- Taglish, natural. Not forced, not trying too hard.
- Warm but not overexcited. Chill but not cold.
- Address customers as "boss" — always.
  Never "sir", "ma'am", or "lodi".
- Keep it short. 2 to 3 sentences max per reply.
- If you have nothing useful to add, don't add it.

WHAT YOU NEVER DO
- Never invent prices, sizes, or stock availability.
- Never use words like "absolutely", "certainly",
  "of course" — that's bot language.
- Never use profanity even if the customer does.
- Never force slang just to sound cool.
  If it doesn't fit naturally, skip it.
- Never use "guaranteed" or claim to be 100% sure of anything.

WHAT YOU ALWAYS DO
- Use only the product data provided to you in the context block.
- If a product isn't in the context, say you don't
  have it — don't guess.
- If a customer has a complaint or wants a refund,
  tell them to type 'admin' to reach the team.
- End product replies with a soft, natural nudge —
  not a scripted sales line.

EXAMPLE TONE (use this as reference, not a script)
Customer: "may hoodie ba kayo?"
Sofia: "Meron boss — heavy cotton, solid ang quality.
        Anong size mo para makita ko kung available?"

Customer: "magkano?"
Sofia: "Depende sa item boss, anong trip mo?
        Ilabas ko na details."

Customer: "pangit naman ng design"
Sofia: "Haha tama ka boss,
        di talaga pang-lahat ang every piece.
        May iba pa kaming options — gusto mo tingnan?"

RAG RULES
- Use ONLY the product data inside [STRICT CONTEXT FROM DATABASE].
- If no context is provided, tell the customer honestly
  that you don't have that item right now.
- Never mix context data with anything you assume from training.
""".strip()

    # ─────────────────────────────────────────
    # PUBLIC INTERFACE
    # ─────────────────────────────────────────

    def needs_keyword_handover(self, text: str) -> bool:
        """
        Check if raw message text contains a handover trigger keyword.

        Args:
            text: Raw customer message.

        Returns:
            True if handover should be triggered.
        """
        lower = text.lower()
        return any(kw in lower for kw in _HANDOVER_KEYWORDS)

    def build_response(
        self,
        message: str,
        intent: Intent,
    ) -> tuple[str, GuardrailFailure]:
        """
        Generate a response for a given message and intent.

        Product intents → TiDB SQL always (no LLM).
        Everything else → Gemini primary, rule-based fallback.
        Guardrails run on all AI-generated responses.

        Args:
            message: Raw customer message.
            intent:  Classified Intent enum value.

        Returns:
            Tuple of (response_text, GuardrailFailure).
            GuardrailFailure.NONE means the response is safe to send.
        """
        # ── Product intents are always rule-based, no LLM ──
        if intent in (Intent.PRODUCT_INQUIRY, Intent.PRICE_QUERY):
            return self._handle_product_intent(message)

        # ── Static rule-based exits ──
        rule_response = self._try_rule_based(message, intent)
        if rule_response:
            return rule_response, GuardrailFailure.NONE

        # ── LLM primary for everything else ──
        try:
            ai_response = self._generate_with_context(message, intent)
            failure = run_guardrails(ai_response)
            return ai_response, failure

        except Exception as exc:
            logger.error(f"AI generation failed: {exc}")
            return MSG_LLM_FALLBACK, GuardrailFailure.NONE

    def build_guardrail_fallback(self) -> str:
        """
        Build the guardrail fallback message with current products.
        Called by routes.py when a guardrail failure is detected.

        Returns:
            Formatted fallback message string with product list injected.
        """
        products = search_products("")
        product_text = self._format_product_reply(products)

        if product_text:
            return MSG_GUARDRAIL_HANDOVER.format(products=product_text)
        return MSG_GUARDRAIL_NO_PRODUCTS

    # ─────────────────────────────────────────
    # PRODUCT HANDLER — 100% RULE-BASED
    # ─────────────────────────────────────────

    def _handle_product_intent(
        self, message: str
    ) -> tuple[str, GuardrailFailure]:
        """
        Handle PRODUCT_INQUIRY and PRICE_QUERY intents.
        TiDB SQL is always the source — LLM never touches product facts.
        Falls back to Gemini + RAG only when TiDB returns no match.

        Args:
            message: Raw customer message.

        Returns:
            Tuple of (response_text, GuardrailFailure).
        """
        budget   = self._extract_budget(message)
        products = search_products(message, max_price=budget)
        reply    = self._format_product_reply(products)

        if reply:
            # ── Product found in TiDB — pure rule-based, no LLM ──
            return reply, GuardrailFailure.NONE

        # ── Product not in TiDB — Gemini + RAG context ──
        try:
            context = retrieve_product_context(message)
            context_block = (
                f"\n[STRICT CONTEXT FROM DATABASE]:\n{context}\n"
                if context else
                "\n[SYSTEM ALERT]: No matching product found in database. "
                "Tell the customer honestly that we don't carry that item. "
                "DO NOT hallucinate features, prices, or availability.\n"
            )
            ai_response = generate_response(
                message, self.system_prompt, context_block
            )
            failure = run_guardrails(ai_response)
            return ai_response, failure

        except Exception as exc:
            logger.error(f"AI product fallback failed: {exc}")
            return MSG_LLM_FALLBACK, GuardrailFailure.NONE

    # ─────────────────────────────────────────
    # RULE-BASED ENGINE
    # ─────────────────────────────────────────

    def _try_rule_based(self, message: str, intent: Intent) -> str | None:
        """
        Handle intents with guaranteed deterministic responses.
        Returns None to signal LLM should handle this message.

        Args:
            message: Raw customer message.
            intent:  Classified Intent enum value.

        Returns:
            Response string, or None if LLM should handle it.
        """
        lower = message.lower().strip()

        # ── Wholesale — escalate ──
        if intent == Intent.WHOLE_SALE:
            return MSG_WHOLESALE

        # ── Shipping — escalate ──
        if intent == Intent.SHIPPING_INFO:
            return MSG_SHIPPING

        # ── Everything else — LLM handles it ──
        return None

    # ─────────────────────────────────────────
    # AI GENERATION
    # ─────────────────────────────────────────

    def _generate_with_context(self, message: str, intent: Intent) -> str:
        """
        Call Gemini for non-product intents.
        No RAG needed here — context is conversational only.

        Args:
            message: Customer message.
            intent:  Classified intent.

        Returns:
            Raw Gemini response text.
        """
        context_block = (
            "\n[CONTEXT]: This is a casual conversation. "
            "Respond naturally as Sofia. "
            "Do not invent product details unless they are "
            "provided in a context block.\n"
        )
        return generate_response(message, self.system_prompt, context_block)

    # ─────────────────────────────────────────
    # PRODUCT FORMATTING
    # ─────────────────────────────────────────

    def _format_product_reply(self, products: list[dict]) -> str | None:
        """
        Format TiDB product rows into a natural Taglish reply.

        Args:
            products: List of product dicts from repository.search_products().

        Returns:
            Formatted reply string, or None if products list is empty.
        """
        if not products:
            return None

        if len(products) == 1:
            p = products[0]
            return (
                f"Meron kaming {p['name']} boss!\n"
                f"{p['description']}\n"
                f"Available sa size na {p['size']}\n"
                f"₱{float(p['price']):.2f} nalang"
                f"sabihan mo lang ako kung kukunin mo na."
            )

        lines = ["Heto boss, lahat ng options namin:\n"]
        for p in products:
            lines.append(
                f"• {p['name']}\n"
                f"  {p['description']}\n"
                f"  Size: {p['size']}\n"
                f"  ₱{float(p['price']):.2f}\n"
            )
        lines.append("Sabihan mo lang ako kung ano trip mo")
        return "\n".join(lines)

    # ─────────────────────────────────────────
    # BUDGET EXTRACTION
    # ─────────────────────────────────────────

    def _extract_budget(self, message: str) -> float | None:
        """
        Extract a budget ceiling from a customer message.
        e.g. 'may hoodie below 500?' → 500.0

        Returns:
            Float price ceiling, or None if no budget found.
        """
        import re
        match = re.search(
            r'(?:below|under|less than|hindi hihigit|hindi lalampas|'
            r'wala pang|max|budget(?:\s*ko)?)\s*₱?\s*(\d+)',
            message.lower()
        )
        if match:
            return float(match.group(1))
        return None
    