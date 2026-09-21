"""Model-agnostic chat model selection.

The rest of the app (graphs, services) only ever depends on LangChain's own
`BaseChatModel` interface -- never on `ChatGoogleGenerativeAI` or `ChatGroq` directly.
Swapping providers is an `LLM_PROVIDER` env var change; adding a new one is one more
branch here plus one package, nothing else in the app changes.
"""

from langchain_core.language_models import BaseChatModel

from app.core.config import Settings
from app.core.exceptions import AppError


def get_chat_model(settings: Settings) -> BaseChatModel:
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        return _build_gemini_chat_model(settings)
    if provider == "groq":
        return _build_groq_chat_model(settings)

    raise AppError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}", status_code=500)


def _build_gemini_chat_model(settings: Settings) -> BaseChatModel:
    if settings.google_api_key is None or not settings.google_api_key.get_secret_value().strip():
        raise AppError("Chat is not configured (GOOGLE_API_KEY is missing).", status_code=500)

    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.google_api_key,
    )


def _build_groq_chat_model(settings: Settings) -> BaseChatModel:
    if settings.groq_api_key is None or not settings.groq_api_key.get_secret_value().strip():
        raise AppError("Chat is not configured (GROQ_API_KEY is missing).", status_code=500)

    from langchain_groq import ChatGroq

    return ChatGroq(
        model_name=settings.groq_chat_model,
        groq_api_key=settings.groq_api_key,
    )
