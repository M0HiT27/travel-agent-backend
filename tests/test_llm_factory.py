"""Tests for the LiteLLM-routed chat model factory.

No network calls: constructing a LangChain chat model client does not itself contact
the proxy, only using it (which these tests never do) would.
"""

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import AppError
from app.llm.factory import get_chat_model


def _settings(**overrides) -> Settings:
    base = dict(
        jwt_secret_key="x",
        parsebot_hotel_scraper_id="h",
        parsebot_redbus_scraper_id="r",
    )
    base.update(overrides)
    return Settings(**base)


def test_without_key_raises():
    settings = _settings(litellm_api_key=None)

    with pytest.raises(AppError, match="LITELLM_API_KEY"):
        get_chat_model(settings)


def test_with_key_builds_a_chat_openai_client_pointed_at_the_proxy():
    from langchain_openai import ChatOpenAI

    settings = _settings(
        litellm_api_key=SecretStr("fake-key"),
        litellm_base_url="http://localhost:4000",
        litellm_reasoning_model_name="reasoning-model",
    )

    model = get_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == settings.litellm_reasoning_model_name
    assert str(model.openai_api_base) == settings.litellm_base_url
