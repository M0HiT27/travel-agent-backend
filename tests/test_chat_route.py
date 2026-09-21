"""Tests for POST /chat/.

`stream_chat` (the actual LangGraph agent run) is stubbed: these tests exercise the
route's own logic (conversation resolution, auth, the SSE response), not the agent or
any LLM. `resolve_conversation` runs for real against the in-memory `db_session`.
"""

import pytest

from app.models.conversation import Conversation
from app.services import chat_service


@pytest.fixture
def stub_stream_chat(monkeypatch):
    calls = []

    async def fake_stream_chat(settings, db, conversation, request):
        calls.append((conversation.id, request.message))
        yield "event: token\ndata: {\"content\": \"hi\"}\n\n"
        yield "event: done\ndata: {}\n\n"

    monkeypatch.setattr(chat_service, "stream_chat", fake_stream_chat)
    return calls


def test_chat_starts_a_new_conversation(chat_client, stub_stream_chat, db_session):
    response = chat_client.post("/chat/", json={"message": "hello"})

    assert response.status_code == 200
    assert "event: token" in response.text
    assert "event: done" in response.text
    assert len(stub_stream_chat) == 1

    # A real conversation row was created for the current user.
    conversation_id = stub_stream_chat[0][0]
    conversation = db_session.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.user_id == 1


def test_chat_continues_an_existing_conversation(chat_client, stub_stream_chat, db_session):
    from app.repositories import conversation_repository

    existing = conversation_repository.create(db_session, user_id=1)
    db_session.commit()

    response = chat_client.post(
        "/chat/", json={"conversation_id": existing.id, "message": "follow up"}
    )

    assert response.status_code == 200
    assert stub_stream_chat == [(existing.id, "follow up")]


def test_chat_with_unknown_conversation_id_is_404(chat_client, stub_stream_chat):
    response = chat_client.post("/chat/", json={"conversation_id": 999, "message": "hi"})

    assert response.status_code == 404
    assert stub_stream_chat == []


def test_chat_cannot_continue_another_users_conversation(chat_client, stub_stream_chat, db_session):
    from app.repositories import conversation_repository

    other_users_conversation = conversation_repository.create(db_session, user_id=2)
    db_session.commit()

    response = chat_client.post(
        "/chat/", json={"conversation_id": other_users_conversation.id, "message": "hi"}
    )

    assert response.status_code == 404
    assert stub_stream_chat == []


def test_blank_message_is_rejected(chat_client, stub_stream_chat):
    response = chat_client.post("/chat/", json={"message": ""})

    assert response.status_code == 422
    assert stub_stream_chat == []


def test_chat_requires_authentication(stub_stream_chat):
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides.clear()
    with TestClient(app) as anonymous_client:
        response = anonymous_client.post("/chat/", json={"message": "hi"})

    assert response.status_code == 401
    assert stub_stream_chat == []
