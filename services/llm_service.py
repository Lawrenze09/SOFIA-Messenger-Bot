"""
services/llm_service.py

Google Gemini LLM client wrapper.
Handles all model interactions:
- Intent classification fallback
- Conversational response generation
"""

from google import genai

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Gemini client singleton ──
_client = genai.Client(api_key=settings.gemini_api_key)

_CLASSIFIER_MODEL  = "gemini-2.5-flash-lite"
_GENERATION_MODEL  = "gemini-2.5-flash-lite"
_MAX_OUTPUT_TOKENS = 300


def classify_intent(message: str, categories: list[str]) -> str:
    """
    Use Gemini to classify a message when keyword matching fails.
    Returns 'UNKNOWN' on any failure.

    Args:
        message:    Raw customer message.
        categories: List of valid intent label strings.

    Returns:
        Uppercase intent label string.
    """
    prompt = (
        f"Classify this customer message into exactly one category.\n"
        f"Categories: {', '.join(categories)}\n"
        f"Message: \"{message}\"\n"
        f"Return only the category label. No explanation."
    )
    try:
        result = _client.models.generate_content(
            model=_CLASSIFIER_MODEL,
            contents=prompt,
        )
        label = result.text.strip().upper()
        return label if label in categories else "UNKNOWN"

    except Exception as exc:
        logger.error(f"Gemini classification error: {exc}")
        return "UNKNOWN"


def generate_response(
    message: str,
    system_prompt: str,
    context_block: str,
) -> str:
    """
    Generate a conversational response from Gemini with RAG context injection.

    Args:
        message:       Raw customer message.
        system_prompt: Sofia's persona and rules.
        context_block: Product context from RAG or a no-match alert.

    Returns:
        Generated response text.

    Raises:
        Exception: Propagated to caller for error handling.
    """
    user_prompt = f"{context_block}\nCustomer Message: {message}\nSofia:"

    result = _client.models.generate_content(
        model=_GENERATION_MODEL,
        contents=user_prompt,
        config={
            "system_instruction": system_prompt,
            "max_output_tokens":  _MAX_OUTPUT_TOKENS,
        },
    )
    return result.text.strip()


def embed_text(text: str) -> list[float]:
    """
    Generate a text embedding vector using Gemini embedding model.
    Used by the RAG pipeline for semantic product search.

    Args:
        text: Query string to embed.

    Returns:
        List of floats representing the embedding vector.

    Raises:
        Exception: Propagated to caller for error handling.
    """
    response = _client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=text,
    )
    return response.embeddings[0].values
