"""Tests for POST /chat/stream and the streaming helpers.

Gemini is never called: `ask_streaming` is replaced with a stub that yields a fixed
sequence of events, so these run offline and cost nothing.
"""

import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.ai.graph import _chunk_text, _tool_events
from app.ai.tools import DEFAULT_TOOL_LABEL, label_for_tool
from app.models.conversation import Conversation
from conftest import OTHER_USER_ID, TEST_USER_ID


def parse_sse(body: str) -> list[dict]:
    """Pull the JSON payload out of each `data:` line of a text/event-stream body."""
    return [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
def stub_stream(monkeypatch):
    """Replace the agent with a stub that yields a realistic event sequence."""
    calls = []

    async def fake_ask_streaming(agent, question, conversation_id):
        calls.append({"question": question, "conversation_id": conversation_id})
        yield {"event": "tool_start", "tool": "search_travel_policies", "label": "Searching policy documents"}
        yield {"event": "tool_end", "tool": "search_travel_policies"}
        yield {"event": "token", "delta": "You pay "}
        yield {"event": "token", "delta": "20%."}
        yield {"event": "done", "conversation_id": conversation_id, "answer": "You pay 20%."}

    monkeypatch.setattr("app.api.routes.chat.ask_streaming", fake_ask_streaming)
    return calls


class TestStreamingEndpoint:
    def test_streams_events_in_order(self, client, stub_stream):
        response = client.post("/chat/stream", json={"question": "What is the fee?"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert [e["event"] for e in parse_sse(response.text)] == [
            "tool_start",
            "tool_end",
            "token",
            "token",
            "done",
        ]

    def test_each_event_is_a_well_formed_sse_block(self, client, stub_stream):
        """`event:` then `data:` then a blank line — what an SSE reader expects."""
        response = client.post("/chat/stream", json={"question": "What is the fee?"})

        assert response.text.startswith("event: tool_start\ndata: ")
        assert response.text.endswith("\n\n")

    def test_tool_progress_carries_a_readable_label(self, client, stub_stream):
        events = parse_sse(client.post("/chat/stream", json={"question": "x"}).text)

        assert events[0]["label"] == "Searching policy documents"

    def test_proxy_buffering_is_disabled(self, client, stub_stream):
        """A buffering proxy would collect the whole answer and defeat streaming."""
        response = client.post("/chat/stream", json={"question": "x"})

        assert response.headers["x-accel-buffering"] == "no"

    def test_a_new_conversation_is_recorded_against_the_user(
        self, client, db_session, stub_stream
    ):
        events = parse_sse(client.post("/chat/stream", json={"question": "Fees?"}).text)

        conversation_id = events[-1]["conversation_id"]
        stored = db_session.get(Conversation, conversation_id)
        assert stored is not None
        assert stored.user_id == TEST_USER_ID
        assert stored.title == "Fees?"

    def test_own_conversation_can_be_continued(self, client, db_session, stub_stream):
        db_session.add(Conversation(id="mine", user_id=TEST_USER_ID, title="Earlier"))
        db_session.commit()

        response = client.post(
            "/chat/stream", json={"question": "And 20 hours?", "conversation_id": "mine"}
        )

        assert response.status_code == 200
        assert stub_stream[0]["conversation_id"] == "mine"


class TestStreamingOwnership:
    """Identical rules to /chat/ask. Duplicating a route is how a hole gets introduced."""

    def test_someone_elses_conversation_is_refused(self, client, db_session, stub_stream):
        db_session.add(Conversation(id="theirs", user_id=OTHER_USER_ID, title="Private"))
        db_session.commit()

        response = client.post(
            "/chat/stream", json={"question": "x", "conversation_id": "theirs"}
        )

        # A plain 404 before any streaming starts — not a 200 with an error event.
        assert response.status_code == 404
        assert stub_stream == [], "the agent must not run on someone else's conversation"

    def test_unknown_conversation_is_refused(self, client, stub_stream):
        response = client.post(
            "/chat/stream", json={"question": "x", "conversation_id": "no-such-id"}
        )

        assert response.status_code == 404

    def test_requires_authentication(self, client, stub_stream):
        from app.api.deps import get_current_user
        from app.main import app

        app.dependency_overrides.pop(get_current_user)

        response = client.post("/chat/stream", json={"question": "x"})

        assert response.status_code == 401
        assert stub_stream == []

    def test_empty_question_is_rejected(self, client, stub_stream):
        assert client.post("/chat/stream", json={"question": ""}).status_code == 422
        assert stub_stream == []


class TestStreamingFailures:
    """Once streaming starts the status is already 200, so failures travel as events."""

    def test_rate_limit_becomes_an_error_event(self, client, monkeypatch):
        from langchain_google_genai.chat_models import GoogleRateLimitError

        async def rate_limited(agent, question, conversation_id):
            raise GoogleRateLimitError("429 RESOURCE_EXHAUSTED")
            yield  # pragma: no cover  (makes this an async generator)

        monkeypatch.setattr("app.api.routes.chat.ask_streaming", rate_limited)

        events = parse_sse(client.post("/chat/stream", json={"question": "x"}).text)

        assert events == [
            {
                "event": "error",
                "status": 429,
                "detail": "The assistant is busy (AI rate limit reached). "
                "Please try again in a minute.",
            }
        ]

    def test_unexpected_failure_becomes_a_502_event(self, client, monkeypatch):
        async def exploding(agent, question, conversation_id):
            raise RuntimeError("gemini exploded")
            yield  # pragma: no cover

        monkeypatch.setattr("app.api.routes.chat.ask_streaming", exploding)

        response = client.post("/chat/stream", json={"question": "x"})
        events = parse_sse(response.text)

        assert events[0]["event"] == "error"
        assert events[0]["status"] == 502
        assert "gemini exploded" not in response.text, "internals must not leak"

    def test_failure_after_some_tokens_still_ends_with_an_error(self, client, monkeypatch):
        """A reply cut off mid-sentence must be flagged, not left looking complete."""

        async def fails_midway(agent, question, conversation_id):
            yield {"event": "token", "delta": "You pay "}
            raise RuntimeError("connection dropped")

        monkeypatch.setattr("app.api.routes.chat.ask_streaming", fails_midway)

        events = parse_sse(client.post("/chat/stream", json={"question": "x"}).text)

        assert [e["event"] for e in events] == ["token", "error"]


class TestChunkText:
    """Only the assistant's own words may reach the user as tokens."""

    def test_assistant_text_is_streamed(self):
        assert _chunk_text(AIMessageChunk(content="Hello")) == "Hello"

    def test_tool_output_is_never_streamed(self):
        """The bug this guards: retrieved policy chunks appearing in the chat."""
        leaked = ToolMessage(content="FLIGHT CANCELLATION POLICY ...", tool_call_id="c1")

        assert _chunk_text(leaked) == ""

    def test_a_tool_request_contributes_nothing(self):
        request = AIMessage(
            content="",
            tool_calls=[{"name": "search_travel_policies", "args": {}, "id": "c1"}],
        )

        assert _chunk_text(request) == ""

    def test_content_blocks_are_flattened(self):
        chunk = AIMessageChunk(content=[{"type": "text", "text": "20% of the fare"}])

        assert _chunk_text(chunk) == "20% of the fare"

    def test_whitespace_at_chunk_edges_is_kept(self):
        """The bug this guards: stripping each chunk fused words into "returnedto"."""
        assert _chunk_text(AIMessageChunk(content="returned ")) == "returned "
        assert _chunk_text(AIMessageChunk(content=" to the")) == " to the"

        block_chunk = AIMessageChunk(content=[{"type": "text", "text": "no-shows and "}])
        assert _chunk_text(block_chunk) == "no-shows and "

    def test_chunks_reassemble_into_the_original_sentence(self):
        pieces = ["Approved refunds are normally returned ", "to the original ", "payment method."]

        streamed = "".join(_chunk_text(AIMessageChunk(content=p)) for p in pieces)

        assert streamed == "Approved refunds are normally returned to the original payment method."


class TestToolEvents:
    def test_a_tool_request_becomes_tool_start_with_its_label(self):
        update = {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "search_flight_offers", "args": {}, "id": "c1"}
                        ],
                    )
                ]
            }
        }

        assert _tool_events(update) == [
            {
                "event": "tool_start",
                "tool": "search_flight_offers",
                "label": "Checking flight details",
            }
        ]

    def test_a_tool_result_becomes_tool_end(self):
        update = {
            "tools": {
                "messages": [
                    ToolMessage(content="...", tool_call_id="c1", name="search_travel_policies")
                ]
            }
        }

        assert _tool_events(update) == [
            {"event": "tool_end", "tool": "search_travel_policies"}
        ]

    def test_plain_answers_produce_no_tool_events(self):
        update = {"agent": {"messages": [AIMessage(content="20% of the fare.")]}}

        assert _tool_events(update) == []

    def test_updates_without_messages_are_ignored(self):
        assert _tool_events({"pre_model_hook": None}) == []
        assert _tool_events({"agent": {}}) == []


class TestToolLabels:
    def test_known_tools_have_category_labels(self):
        assert label_for_tool("search_travel_policies") == "Searching policy documents"
        assert label_for_tool("search_flight_offers") == "Checking flight details"

    def test_an_unregistered_tool_falls_back_rather_than_leaking_its_name(self):
        """Adding a tool must never show a raw function name to a user."""
        assert label_for_tool("search_hotel_offers") == DEFAULT_TOOL_LABEL
