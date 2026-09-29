"""Embeddings for RAG, routed through the same local LiteLLM proxy as chat.

Kept as its own small factory (rather than a bare call inline in the vector store)
so which embedding model backs this can change -- on the proxy side or here -- without
touching callers.
"""

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.document_chunk import EMBEDDING_DIM


def get_embeddings(settings: Settings) -> Embeddings:
    if settings.litellm_api_key is None or not settings.litellm_api_key.get_secret_value().strip():
        raise AppError("Embeddings are not configured (LITELLM_API_KEY is missing).", status_code=500)

    return OpenAIEmbeddings(
        model=settings.litellm_embedding_model_name,
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
        # document_chunks.embedding is a fixed-width pgvector column -- whatever
        # model litellm_embedding_model_name resolves to on the proxy side must
        # produce vectors of this size. Drop this if that model doesn't support a
        # configurable output dimension.
        dimensions=EMBEDDING_DIM,
    )
