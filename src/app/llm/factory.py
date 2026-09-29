"""Chat model client, routed through a local LiteLLM proxy.

The rest of the app only ever depends on LangChain's own `BaseChatModel` interface.
Provider selection and fallback behaviour now live on the LiteLLM proxy's own side
(its config, not this app's) -- this app just points LangChain's OpenAI-compatible
client at the proxy, using whichever model alias the proxy has registered.
"""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.exceptions import AppError


def get_chat_model(settings: Settings) -> BaseChatModel:
    if settings.litellm_api_key is None or not settings.litellm_api_key.get_secret_value().strip():
        raise AppError("Chat is not configured (LITELLM_API_KEY is missing).", status_code=500)

    return ChatOpenAI(
        model=settings.litellm_reasoning_model_name,
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
    )
