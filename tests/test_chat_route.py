"""Tests for POST /chat/ask.

Gemini is never called: `ask` is replaced with a stub, so these run offline and cost
nothing. The agent's own behaviour is not tested here — only the route around it.
"""

import pytest

from app.ai.graph import _as_text


@pytest.fixture
def stub_ask(monkeypatch):
    """Replace the agent call with a stub that records how it was invoked."""
    calls = []

    async def fake_ask(agent, question: str, conversation_id: str) -> str:
        calls.append({"question": question, "conversation_id": conversation_id})
        return "You pay 20% of the ticket fare."

    monkeypatch.setattr("app.api.routes.chat.ask", fake_ask)
    return calls


def test_ask_returns_the_agent_answer(client, stub_ask):
    response = client.post("/chat/ask", json={"question": "What is the cancellation fee?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "You pay 20% of the ticket fare."
    assert stub_ask[0]["question"] == "What is the cancellation fee?"


def test_new_conversation_gets_an_id(client, stub_ask):
    """Omitting conversation_id starts a fresh conversation, and the id comes back."""
    response = client.post("/chat/ask", json={"question": "What is the fee?"})

    conversation_id = response.json()["conversation_id"]
    assert conversation_id
    # The same id the caller receives is the one the agent was run under.
    assert stub_ask[0]["conversation_id"] == conversation_id


def test_each_new_conversation_gets_a_different_id(client, stub_ask):
    first = client.post("/chat/ask", json={"question": "One?"}).json()["conversation_id"]
    second = client.post("/chat/ask", json={"question": "Two?"}).json()["conversation_id"]

    assert first != second, "separate conversations must not share history"


def test_supplied_conversation_id_is_reused(client, db_session, stub_ask):
    """Sending an id back continues that conversation rather than starting a new one."""
    from conftest import TEST_USER_ID

    from app.models.conversation import Conversation

    db_session.add(
        Conversation(id="existing-abc", user_id=TEST_USER_ID, title="Earlier chat")
    )
    db_session.commit()

    response = client.post(
        "/chat/ask",
        json={"question": "What about 20 hours?", "conversation_id": "existing-abc"},
    )

    assert response.json()["conversation_id"] == "existing-abc"
    assert stub_ask[0]["conversation_id"] == "existing-abc"


def test_empty_question_is_rejected(client, stub_ask):
    response = client.post("/chat/ask", json={"question": ""})

    assert response.status_code == 422
    assert stub_ask == [], "the agent must not be called for an invalid request"


def test_overlong_question_is_rejected(client, stub_ask):
    response = client.post("/chat/ask", json={"question": "x" * 2001})

    assert response.status_code == 422
    assert stub_ask == []


def test_agent_failure_becomes_502(client, monkeypatch):
    async def failing_ask(agent, question: str, conversation_id: str) -> str:
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr("app.api.routes.chat.ask", failing_ask)

    response = client.post("/chat/ask", json={"question": "What is the fee?"})

    assert response.status_code == 502
    # The internal error text must not reach the client.
    assert "gemini exploded" not in response.text


def test_rate_limit_becomes_429(client, monkeypatch):
    """A Gemini rate limit must be distinguishable from a real failure."""
    from langchain_google_genai.chat_models import GoogleRateLimitError

    async def rate_limited_ask(agent, question: str, conversation_id: str) -> str:
        raise GoogleRateLimitError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr("app.api.routes.chat.ask", rate_limited_ask)

    response = client.post("/chat/ask", json={"question": "What is the fee?"})

    assert response.status_code == 429
    assert "try again" in response.json()["detail"].lower()


def test_ask_requires_authentication(client, stub_ask):
    """Dropping only the auth override must make the endpoint reject the request."""
    from app.api.deps import get_current_user
    from app.main import app

    app.dependency_overrides.pop(get_current_user)

    response = client.post("/chat/ask", json={"question": "What is the fee?"})

    assert response.status_code == 401
    assert stub_ask == []


class TestFlattenContent:
    """LangChain v1 returns content as typed blocks, not a plain string."""

    def test_plain_string_passes_through(self):
        assert _as_text("hello") == "hello"

    def test_text_blocks_are_joined(self):
        content = [
            {"type": "text", "text": "First part."},
            {"type": "text", "text": "Second part."},
        ]
        assert _as_text(content) == "First part.\nSecond part."

    def test_non_text_blocks_are_dropped(self):
        content = [
            {"type": "reasoning", "reasoning": "internal thinking"},
            {"type": "text", "text": "The answer."},
        ]
        assert _as_text(content) == "The answer."

    def test_empty_block_list_gives_empty_string(self):
        assert _as_text([]) == ""
