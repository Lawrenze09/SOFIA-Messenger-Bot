"""
services/rag_service.py

Pinecone vector search service (RAG pipeline).
Retrieves semantically relevant product context
for Gemini response generation.
"""

from config import settings
from services.llm_service import embed_text
from utils.logger import get_logger

logger = get_logger(__name__)


def retrieve_product_context(query: str, top_k: int = 3) -> str:
    """
    Retrieve the most semantically relevant product documents
    from Pinecone for a given customer query.

    Falls back to empty string if Pinecone is unconfigured or unavailable.

    Args:
        query: Customer message to use as the search query.
        top_k: Number of top results to retrieve.

    Returns:
        Concatenated product context string, or empty string on failure.
    """
    if not settings.pinecone_api_key or not settings.pinecone_index:
        logger.warning("Pinecone not configured — skipping RAG retrieval")
        return ""

    try:
        from pinecone import Pinecone

        pc     = Pinecone(api_key=settings.pinecone_api_key)
        index  = pc.Index(settings.pinecone_index)
        vector = embed_text(query)

        results = index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True,
        )

        docs = [
            match["metadata"].get("text", "")
            for match in results.get("matches", [])
            if match.get("metadata")
        ]

        return "\n".join(docs) if docs else ""

    except Exception as exc:
        logger.error(f"Pinecone retrieval error: {exc}")
        return ""
