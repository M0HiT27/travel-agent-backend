"""Gemini embeddings + the pgvector store they are saved in.

Both the ingest script and the question-answering tool need the same embedding model
and the same store, so they are built here once and imported by both. If these two ever
disagreed, questions would be compared against documents in a different "number space"
and every answer would be nonsense.
"""

from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector

from app.core.config import Settings


def build_embeddings(settings: Settings) -> GoogleGenerativeAIEmbeddings:
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value().strip():
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=settings.gemini_api_key,
        output_dimensionality=settings.gemini_embedding_dimensions,
    )


def build_vector_store(settings: Settings) -> PGVector:
    """Connect to (and if needed create) the pgvector collection.

    PGVector runs `CREATE EXTENSION vector` and creates its own tables on first use,
    so there is no Alembic migration for this — the store manages its own schema.
    """
    return PGVector(
        embeddings=build_embeddings(settings),
        connection=settings.database_url,
        collection_name=settings.vector_collection_name,
        embedding_length=settings.gemini_embedding_dimensions,
        use_jsonb=True,
    )


@lru_cache
def get_vector_store() -> PGVector:
    """Cached store for the running app. The ingest script builds its own instead."""
    from app.core.config import get_settings

    return build_vector_store(get_settings())
