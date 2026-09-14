"""Tests for conversation ownership and the sidebar endpoints.

The rule under test: a conversation belongs to exactly one user, and nobody else can
read it, continue it, or delete it — even knowing its id.
"""

from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.models.conversation import Conversation
from conftest import OTHER_USER_ID, TEST_USER_ID


@pytest.fixture
def stub_ask(monkeypatch):
    """Replace the agent call so no model or database memory is touched."""
    calls = []

    async def fake_ask(agent, question: str, conversation_id: str) -> str:
        calls.append({"question": question, "conversation_id": conversation_id})
        return "You pay 20% of the ticket fare."

    monkeypatch.setattr("app.api.routes.chat.ask", fake_ask)
    return calls


def make_conversation(db_session, conversation_id: str, user_id: int, **kwargs):
    conversation = Conversation(
        id=conversation_id,
        user_id=user_id,
        title=kwargs.get("title", "A conversation"),
        last_message_at=kwargs.get("last_message_at", datetime.now(timezone.utc)),
    )
    db_session.add(conversation)
    db_session.commit()
    return conversation


class TestStartingAConversation:
    def test_a_new_conversation_is_recorded_against_the_user(
        self, client, db_session, stub_ask
    ):
        response = client.post("/chat/ask", json={"question": "What is the fee?"})

        conversation_id = response.json()["conversation_id"]
        stored = db_session.get(Conversation, conversation_id)
        assert stored is not None
        assert stored.user_id == TEST_USER_ID

    def test_the_title_comes_from_the_first_question(self, client, db_session, stub_ask):
        response = client.post(
            "/chat/ask", json={"question": "What is the cancellation fee?"}
        )

        stored = db_session.get(Conversation, response.json()["conversation_id"])
        assert stored.title == "What is the cancellation fee?"

    def test_a_long_question_makes_a_truncated_title(self, client, db_session, stub_ask):
        response = client.post("/chat/ask", json={"question": "word " * 200})

        stored = db_session.get(Conversation, response.json()["conversation_id"])
        assert len(stored.title) <= 120
        assert stored.title.endswith("…")


class TestContinuingAConversation:
    def test_own_conversation_can_be_continued(self, client, db_session, stub_ask):
        make_conversation(db_session, "mine", TEST_USER_ID)

        response = client.post(
            "/chat/ask", json={"question": "And 20 hours?", "conversation_id": "mine"}
        )

        assert response.status_code == 200
        assert stub_ask[0]["conversation_id"] == "mine"

    def test_continuing_updates_last_message_at(self, client, db_session, stub_ask):
        """So the sidebar can sort by most recently used."""
        make_conversation(
            db_session,
            "mine",
            TEST_USER_ID,
            last_message_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        # Read both ends from the database: SQLite drops the timezone that Postgres
        # keeps, so a value from the test and one from the database cannot be compared.
        before = db_session.get(Conversation, "mine").last_message_at

        client.post(
            "/chat/ask", json={"question": "And 20 hours?", "conversation_id": "mine"}
        )

        db_session.expire_all()
        assert db_session.get(Conversation, "mine").last_message_at > before

    def test_someone_elses_conversation_is_refused(self, client, db_session, stub_ask):
        make_conversation(db_session, "theirs", OTHER_USER_ID)

        response = client.post(
            "/chat/ask", json={"question": "Anything?", "conversation_id": "theirs"}
        )

        assert response.status_code == 404
        assert stub_ask == [], "the agent must not run on someone else's conversation"

    def test_unknown_conversation_is_refused(self, client, stub_ask):
        response = client.post(
            "/chat/ask", json={"question": "Anything?", "conversation_id": "does-not-exist"}
        )

        assert response.status_code == 404

    def test_refusal_does_not_reveal_that_it_exists(self, client, db_session, stub_ask):
        """Someone else's conversation and a missing one must look identical."""
        make_conversation(db_session, "theirs", OTHER_USER_ID)

        theirs = client.post(
            "/chat/ask", json={"question": "x", "conversation_id": "theirs"}
        )
        missing = client.post(
            "/chat/ask", json={"question": "x", "conversation_id": "no-such-id"}
        )

        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()


class TestListingConversations:
    def test_lists_only_your_own(self, client, db_session):
        make_conversation(db_session, "mine-1", TEST_USER_ID)
        make_conversation(db_session, "theirs", OTHER_USER_ID)

        response = client.get("/chat/conversations")

        assert response.status_code == 200
        assert [c["id"] for c in response.json()] == ["mine-1"]

    def test_most_recent_first(self, client, db_session):
        now = datetime.now(timezone.utc)
        make_conversation(db_session, "older", TEST_USER_ID, last_message_at=now - timedelta(days=2))
        make_conversation(db_session, "newest", TEST_USER_ID, last_message_at=now)
        make_conversation(db_session, "middle", TEST_USER_ID, last_message_at=now - timedelta(days=1))

        ids = [c["id"] for c in client.get("/chat/conversations").json()]

        assert ids == ["newest", "middle", "older"]

    def test_no_conversations_is_an_empty_list(self, client):
        assert client.get("/chat/conversations").json() == []


class TestReadingOneConversation:
    @pytest.fixture
    def stub_history(self, monkeypatch):
        async def fake_load_history(agent, conversation_id):
            return [
                HumanMessage(content="What is the fee?"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search_travel_policies", "args": {}, "id": "c1"}],
                ),
                ToolMessage(content="policy chunk text", tool_call_id="c1"),
                AIMessage(content="20% of the fare."),
            ]

        monkeypatch.setattr("app.api.routes.chat.load_history", fake_load_history)

    def test_returns_the_conversation_with_its_messages(
        self, client, db_session, stub_history
    ):
        make_conversation(db_session, "mine", TEST_USER_ID, title="Fees")

        body = client.get("/chat/conversations/mine").json()

        assert body["title"] == "Fees"
        assert body["messages"] == [
            {"role": "user", "content": "What is the fee?"},
            {"role": "assistant", "content": "20% of the fare."},
        ]

    def test_internal_agent_steps_are_hidden(self, client, db_session, stub_history):
        """Tool calls and retrieved chunks are not part of the conversation a person had."""
        make_conversation(db_session, "mine", TEST_USER_ID)

        contents = [m["content"] for m in client.get("/chat/conversations/mine").json()["messages"]]

        assert "policy chunk text" not in contents

    def test_someone_elses_conversation_is_refused(self, client, db_session, stub_history):
        make_conversation(db_session, "theirs", OTHER_USER_ID)

        assert client.get("/chat/conversations/theirs").status_code == 404


class TestDeletingAConversation:
    @pytest.fixture
    def spy_agent(self, client):
        """An agent whose checkpointer records which threads were deleted."""
        from app.api.routes.chat import get_agent
        from app.main import app

        deleted = []

        class Checkpointer:
            async def adelete_thread(self, thread_id):
                deleted.append(thread_id)

        class Agent:
            checkpointer = Checkpointer()

        app.dependency_overrides[get_agent] = lambda: Agent()
        return deleted

    def test_deletes_the_row_and_the_stored_messages(self, client, db_session, spy_agent):
        make_conversation(db_session, "mine", TEST_USER_ID)

        response = client.delete("/chat/conversations/mine")

        assert response.status_code == 204
        assert db_session.get(Conversation, "mine") is None
        assert spy_agent == ["mine"], "orphaned messages would be unreachable but still stored"

    def test_someone_elses_conversation_is_refused(self, client, db_session, spy_agent):
        make_conversation(db_session, "theirs", OTHER_USER_ID)

        response = client.delete("/chat/conversations/theirs")

        assert response.status_code == 404
        assert db_session.get(Conversation, "theirs") is not None
        assert spy_agent == []


class TestAuthentication:
    @pytest.fixture
    def anonymous(self, client):
        from app.api.deps import get_current_user
        from app.main import app

        app.dependency_overrides.pop(get_current_user)
        return client

    def test_listing_requires_login(self, anonymous):
        assert anonymous.get("/chat/conversations").status_code == 401

    def test_reading_requires_login(self, anonymous):
        assert anonymous.get("/chat/conversations/anything").status_code == 401

    def test_deleting_requires_login(self, anonymous):
        assert anonymous.delete("/chat/conversations/anything").status_code == 401
