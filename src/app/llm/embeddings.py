"""Embeddings for RAG.

Kept separate from `factory.py` because it is not actually provider-agnostic today:
Groq serves chat completions only, no embeddings endpoint. Gemini backs embeddings
regardless of `LLM_PROVIDER`. Structured as its own small factory anyway (rather than
a bare Gemini call inline in the vector store) so a second embeddings-capable
provider can be added later without touching callers.
"""

from langchain_core.embeddings import Embeddings

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.document_chunk import EMBEDDING_DIM


def get_embeddings(settings: Settings) -> Embeddings:
    if settings.google_api_key is None or not settings.google_api_key.get_secret_value().strip():
        raise AppError("Embeddings are not configured (GOOGLE_API_KEY is missing).", status_code=500)

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=settings.google_api_key,
        output_dimensionality=EMBEDDING_DIM,
    )
