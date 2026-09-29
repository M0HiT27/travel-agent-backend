"""Regression test for stream_chat's handling of non-string chunk content.

Some providers (Gemini in particular) stream `chunk.content` as a list of
part dicts instead of a plain string once a tool call is involved in the
turn. `stream_chat` must not crash when that happens.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.repositories import conversation_repository, message_repository
from app.schemas.chat import ChatRequest
from app.services.chat_service import stream_chat


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, events):
        self._events = events

    async def astream_events(self, *args, **kwargs):
        for event in self._events:
            yield event


def _chat_request(message: str = "hello") -> ChatRequest:
    return ChatRequest(conversation_id=None, message=message)


@pytest.mark.asyncio
async def test_stream_chat_handles_list_content_chunks(db_session):
    conversation = conversation_repository.create(db_session, user_id=1)
    db_session.commit()

    events = [
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": _FakeChunk([{"type": "text", "text": "Hello "}])},
        },
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": _FakeChunk("world")},
        },
    ]

    with patch(
        "app.services.chat_service.build_agent", return_value=_FakeAgent(events)
    ):
        collected = [
            chunk
            async for chunk in stream_chat(
                settings=object(),
                db=db_session,
                conversation=conversation,
                request=_chat_request(),
            )
        ]

    assert any("event: done" in chunk for chunk in collected)
    assert not any("event: error" in chunk for chunk in collected)

    messages = message_repository.list_for_conversation(db_session, conversation.id)
    assistant_messages = [m for m in messages if m.role == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].content == "Hello world"
