"""
scripts/sync_products.py

Sync product catalog from TiDB to Pinecone vector index.
Run this script whenever products are added, updated, or removed.

Usage:
    python scripts/sync_products.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pinecone import Pinecone

from config import settings
from database.client import get_connection
from services.llm_service import embed_text
from utils.logger import get_logger

logger = get_logger("sync_products")


def fetch_all_products() -> list[dict]:
    """
    Fetch all active products from TiDB.

    Returns:
        List of product row dicts.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, size, price, description, category, stock_quantity
        FROM products
        WHERE stock_quantity > 0
        ORDER BY id
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    logger.info(f"Fetched {len(rows)} products from TiDB")
    return rows


def build_document_text(product: dict) -> str:
    """
    Build a descriptive text string for embedding.

    Args:
        product: Product row dict from TiDB.

    Returns:
        Formatted string for embedding.
    """
    return (
        f"Product: {product['name']}. "
        f"Category: {product['category']}. "
        f"Sizes: {product['size']}. "
        f"Price: PHP {float(product['price']):.2f}. "
        f"Description: {product['description']}."
    )


def sync() -> None:
    """
    Embed all products and upsert vectors into Pinecone.
    Logs progress for each product.
    """
    if not settings.pinecone_api_key or not settings.pinecone_index:
        logger.error("PINECONE_API_KEY or PINECONE_INDEX not set in environment.")
        sys.exit(1)

    products = fetch_all_products()
    if not products:
        logger.warning("No products found — nothing to sync.")
        return

    pc    = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index)

    vectors = []
    for product in products:
        text   = build_document_text(product)
        vector = embed_text(text)
        vectors.append({
            "id"      : str(product["id"]),
            "values"  : vector,
            "metadata": {"text": text, "name": product["name"]},
        })
        logger.info(f"Embedded: {product['name']} (id={product['id']})")

    index.upsert(vectors=vectors)
    logger.info(f"Sync complete — {len(vectors)} products upserted to Pinecone.")


if __name__ == "__main__":
    sync()
