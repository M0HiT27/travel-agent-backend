"""Tests for provider selection in the model-agnostic chat factory.

No network calls: constructing a LangChain chat model client does not itself contact
the provider, only using it (which these tests never do) would.
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


def test_unsupported_provider_raises():
    settings = _settings(llm_provider="openai")

    with pytest.raises(AppError, match="Unsupported LLM_PROVIDER"):
        get_chat_model(settings)


def test_gemini_without_key_raises():
    settings = _settings(llm_provider="gemini", google_api_key=None)

    with pytest.raises(AppError, match="GOOGLE_API_KEY"):
        get_chat_model(settings)


def test_groq_without_key_raises():
    settings = _settings(llm_provider="groq", groq_api_key=None)

    with pytest.raises(AppError, match="GROQ_API_KEY"):
        get_chat_model(settings)


def test_gemini_with_key_builds_a_gemini_model():
    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = _settings(llm_provider="gemini", google_api_key=SecretStr("fake-key"))

    model = get_chat_model(settings)

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == settings.gemini_chat_model


def test_groq_with_key_builds_a_groq_model():
    from langchain_groq import ChatGroq

    settings = _settings(llm_provider="groq", groq_api_key=SecretStr("fake-key"))

    model = get_chat_model(settings)

    assert isinstance(model, ChatGroq)
    assert model.model_name == settings.groq_chat_model


def test_provider_is_case_insensitive():
    settings = _settings(llm_provider="GEMINI", google_api_key=SecretStr("fake-key"))

    from langchain_google_genai import ChatGoogleGenerativeAI

    assert isinstance(get_chat_model(settings), ChatGoogleGenerativeAI)
