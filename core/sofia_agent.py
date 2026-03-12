"""
core/sofia_agent.py

SofiaAgent — the central brain of the chatbot.

Responsibilities:
- Rule-based response engine (no LLM cost)
- RAG context injection for AI responses
- Guardrail enforcement on AI output
- Handover detection and escalation routing
- Product formatting for TiDB results

All personality, tone, and response policies are
configured here. Swap the system prompt or rule
responses without touching any other module.
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
# HANDOVER MESSAGES
# ─────────────────────────────────────────────

MSG_KEYWORD_HANDOVER = (
    "Pasensya na po boss... "
    "alert ko na si admin agad para matulungan kayo."
)

MSG_GUARDRAIL_HANDOVER = (
    "Hindi pa po ako sure kung ano isasagot sa concern nyo boss... "
    "alert ko nalang si admin para matulungan po kayo agad."
)

SIZE_CHART_BOXER  = "https://raw.githubusercontent.com/Lawrenze09/SOFIA-Messenger-Bot/main/assets/size-chart-boxer.jpg"

MSG_SIZE_CHART = "Sure boss! Heto ang aming size chart para sa inyong reference "

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
        response, needs_handover, needs_email = agent.respond(text, intent)
    """

    system_prompt: str = """
You are Sofia, a street-smart witty girl sales whiz of Ace Apparel.
You are NOT a pabebe customer service representative; you are the "reyna ng kanto" when it comes to drip.
Playful "tropang seller" — confident, fast-talking, always closing deals with humor.

TONE
- Natural Taglish, kanto-style
- Always "boss" — never "sir", "ma'am", "lodi"
- Signature words: "solid", "mabisa", "sasalang", "panalo", "pramis"
- MAX 2-3 sentences. Joke first, sell second.

PERSONALITY
- Always end with: "Pili ka na boss, panalo 'yan, pramis!"
- Customer curses or jokes → ride it, NEVER get offended
- Customer mimics your words → act flattered: return what they mimic then add "ngani!" then sell a product
- Use: "Aray ko!", "ngani", "sapul", "yarn", "alam mo ah" for punchlines

EXAMPLES
Customer: "Sa iba nalang ako"
Sofia: "Aray ko! Pag may nagustuhan ka sa amin, sabihan mo lang ako boss"
Customer: "may puso ka ba?"
Sofia: "Secret... bili ka na ng hoodie, panalo to pramis!"
Customer: "may TV kayo?"
Sofia: "Clothing ngani boss, clothing lang tayo. Ikaw talaga oo"

RULES
- Use provided product context ONLY
- Missing info: "Pasensya na boss, naging ninja na yata yung item. Connect na kita kay Bigboss para sigurado."
- Never invent prices, SKUs, sizes, or stock
- Off-topic → redirect back to Ace Apparel
- NEVER use the words: gago, kupal, tarantado profanity, slurs, or any offensive language
""".strip()

    # ── Static rule map — keyword triggers ──
    _RULE_MAP: dict[str, str] = {
        "menu": (
            "Welcome sa Ace Apparel, boss! Sofia 'to ang pinaka ma agnas mong "
            "AI assistant. Lapag ka lang ng tanong—basta usapang products ng Ace Apparel kabisado ko yan, "
            "presyong tropa siguradong hindi ka mapapahiya sa porma. "
            "Type 'admin' lang kung kailangan mo si Bigboss. "
        ),
    }

    # ── Menu message reused for SMALL_TALK ──
    _MSG_MENU: str = (
        "Welcome sa Ace Apparel, boss! Sofia 'to ang pinaka ma agnas mong "
        "AI assistant. Lapag ka lang ng tanong—basta usapang products ng Ace Apparel kabisado ko yan, "
        "presyong tropa siguradong hindi ka mapapahiya sa porma. "
        "Type 'admin' lang kung kailangan mo si Bigboss. "
    )

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

        Tries rule-based engine first (zero cost).
        Falls back to Gemini with RAG context if no rule matches.
        Runs guardrails on all AI-generated responses.

        Args:
            message: Raw customer message.
            intent:  Classified Intent enum value.

        Returns:
            Tuple of (response_text, GuardrailFailure).
            GuardrailFailure.NONE means the response is safe to send.
        """
        rule_response = self._try_rule_based(message, intent)
        if rule_response:
            return rule_response, GuardrailFailure.NONE

        # ── AI fallback for PLAYFUL, UNKNOWN, and unmatched intents ──
        try:
            ai_response = self._generate_with_context(message, intent)
        except Exception as exc:
            logger.error(f"AI generation failed: {exc}")
            # Last resort — product search before showing error
            products = search_products(message)
            fallback  = self._format_product_reply(products)
            if fallback:
                return fallback, GuardrailFailure.NONE
            return (
                "Pasensya na boss, may technical issue po kami ngayon. "
                "Subukan po ulit mamaya.",
                GuardrailFailure.NONE,
            )

        failure = run_guardrails(ai_response)
        return ai_response, failure

    # ─────────────────────────────────────────
    # RULE-BASED ENGINE
    # ─────────────────────────────────────────

    def _try_rule_based(self, message: str, intent: Intent) -> str | None:
        """
        Attempt to resolve the message using deterministic rules.
        Returns None to signal AI fallback is needed.

        Args:
            message: Raw customer message.
            intent:  Classified Intent enum value.

        Returns:
            Response string, or None if no rule matched.
        """
        lower = message.lower().strip()

        # ── Static keyword map ──
        for trigger, response in self._RULE_MAP.items():
            if trigger in lower:
                return response

        # ── Buy confirmation — typed exactly "buy" ──
        if lower == "buy":
            return (
                "Buy confirmed! Si Bigboss na bahala para asikasuhin ang order niyo "
                "Salamat sa tiwala, bossing!"
            )

        if intent == Intent.SMALL_TALK:
            return self._MSG_MENU

        if intent == Intent.PURCHASE:
            return (
                "Noted boss! Para lang po sa confirmation type lang po ang 'buy' "
                "para po ma alert ko na si Bigboss ngayon "
                "at ma process ang order mo. Mag-me-message po sila sa'yo agad. "
            )

        if intent == Intent.WHOLE_SALE:
            return (
                "Usapang negosyo ba 'to, boss? Solid! Ilalapit kita sa 'Source' natin "
                "para sa mabisang wholesale pricing. Siya ang bahala sa 'yo para pareho "
                "tayong kumita. Chill ka lang dyan, mas mabilis pa 'yan sa tropa mong "
                "ninja 'pag may kailangan ka, hindi mo mahagilap! "
                "aray ko po! kamot ulo"
            )

        if intent == Intent.SHIPPING_INFO:
            return (
                "Usapang shipping ba boss? Di ko alam yan ih! "
                "Connect na kita kay Bigboss para ma-asikaso natin yan agad. "
                "Chill ka lang dyan, mas mabilis pa 'yan sa sahod mong dumaan lang mag-reply. "
                "aray ko po!"
            )

        if intent in (Intent.PRODUCT_INQUIRY, Intent.PRICE_QUERY):
            budget   = self._extract_budget(message)
            products = search_products(message, max_price=budget)
            reply    = self._format_product_reply(products)
            if reply:
                return reply
            return None

        if intent == Intent.UNKNOWN or intent == Intent.BANTER:
            products = search_products(message)
            return self._format_product_reply(products)  # None if no match → AI fallback

        return None

    # ─────────────────────────────────────────
    # AI GENERATION
    # ─────────────────────────────────────────

    def _generate_with_context(self, message: str, intent: Intent) -> str:
        """
        Build context block from RAG and call Gemini.

        Args:
            message: Customer message.
            intent:  Classified intent.

        Returns:
            Raw Gemini response text.
        """
        context = ""
        if intent in (Intent.PRODUCT_INQUIRY, Intent.PRICE_QUERY):
            context = retrieve_product_context(message)

        context_block = (
            f"\n[STRICT CONTEXT FROM DATABASE]:\n{context}\n"
            if context else
            "\n[SYSTEM ALERT]: No matching product found in database. "
            "Tell the customer politely that we don't have this item yet. "
            "DO NOT hallucinate features.\n"
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
                f"{p['description']} — panalo, hindi tinipid ang quality!\n"
                f"Available sa size: {p['size']}\n"
                f"₱{float(p['price']):.2f} nalang, presyong tropa na 'yan!\n\n"
                f"Sabihan mo lang ako kung ge-get mo na para "
                f"ma-reserve ko agad sa'yo!"
            )

        lines = ["Ito na boss, latag ko na lahat para 'di ka na mahirapan:\n"]
        for p in products:
            lines.append(
                f"• {p['name']}\n"
                f"{p['description']}\n"
                f"Size: {p['size']}\n"
                f"₱{float(p['price']):.2f} ONLY!\n"
            )
        lines.append("Pili ka lang boss, solid lahat 'yan!")
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