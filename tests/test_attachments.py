"""Tests for the structured results that travel alongside an answer.

Flight offers become cards and retrieved policy passages become citations. Both come
from the tool's real data rather than the model's retelling, both must leave the text
the model reads unchanged, and both must survive a conversation being reopened.
"""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ai.graph import _tool_events
from app.ai.tools import search_flight_offers, search_travel_policies
from app.models.conversation import Conversation
from app.schemas.flight import FlightOffer, FlightSegment
from conftest import TEST_USER_ID


def tool_call(name: str, args: dict) -> dict:
    """The shape the agent hands a tool — the only way to get its artifact back."""
    return {"type": "tool_call", "name": name, "args": args, "id": "call-1"}


class FakeVectorStore:
    def __init__(self, documents: list[Document]):
        self.documents = documents

    def similarity_search(self, question: str, k: int) -> list[Document]:
        return self.documents[:k]


def make_offer(offer_id: str, amount: str) -> FlightOffer:
    departure = datetime(2026, 10, 1, 20, 54)
    arrival = datetime(2026, 10, 1, 23, 29)
    return FlightOffer(
        offer_id=offer_id,
        airline_name="Air India",
        airline_code="AI",
        total_amount=Decimal(amount),
        currency="INR",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=155,
        stops=0,
        segments=[
            FlightSegment(
                origin="DEL", destination="GOI", departure_at=departure, arrival_at=arrival
            )
        ],
    )


@pytest.fixture
def future_date() -> str:
    return (date.today() + timedelta(days=30)).isoformat()


class TestPolicySources:
    @pytest.fixture
    def documents(self, monkeypatch):
        documents = [
            Document(
                page_content="Refunds take 7-10 business days.",
                metadata={"source_file": "flight_cancellation_policy.pdf", "page": 1},
            ),
            Document(
                page_content="No-shows are generally non-refundable.",
                metadata={"source_file": "flight_cancellation_policy.pdf", "page": 1},
            ),
            Document(
                page_content="Checked baggage allowance.",
                metadata={"source_file": "baggage_policy.pdf", "page": 3},
            ),
        ]
        monkeypatch.setattr(
            "app.ai.tools.get_vector_store", lambda: FakeVectorStore(documents)
        )
        return documents

    def ask(self) -> ToolMessage:
        return search_travel_policies.invoke(
            tool_call("search_travel_policies", {"question": "How long do refunds take?"})
        )

    def test_sources_are_attached_once_each(self, documents):
        """Two chunks from the same page are one source, not two."""
        assert self.ask().artifact == {
            "kind": "sources",
            "sources": [
                {"file": "flight_cancellation_policy.pdf", "page": 1},
                {"file": "baggage_policy.pdf", "page": 3},
            ],
        }

    def test_the_model_still_reads_the_same_text(self, documents):
        """Adding citations must not change what Gemini is given, or answers would shift."""
        content = self.ask().content

        assert content.startswith(
            "[from flight_cancellation_policy.pdf, page 1]\nRefunds take 7-10 business days."
        )
        assert content.count("\n\n---\n\n") == 2

    def test_no_matches_means_no_sources(self, monkeypatch):
        monkeypatch.setattr("app.ai.tools.get_vector_store", lambda: FakeVectorStore([]))

        message = self.ask()

        assert message.artifact is None
        assert message.content == "No policy documents matched that question."


class TestFlightCards:
    @pytest.fixture
    def offers(self, monkeypatch):
        found = [make_offer(f"off_{i}", f"{4000 + i * 100}.50") for i in range(7)]

        async def fake_search_flights(settings, request):
            return found

        monkeypatch.setattr("app.ai.tools.search_flights", fake_search_flights)
        return found

    def search(self, **args) -> ToolMessage:
        return asyncio.run(
            search_flight_offers.ainvoke(tool_call("search_flight_offers", args))
        )

    def test_cards_carry_the_real_offer_data(self, offers, future_date):
        artifact = self.search(origin="DEL", destination="GOI", departure_date=future_date).artifact

        assert artifact["offers"][0] == {
            "offer_id": "off_0",
            "airline_name": "Air India",
            "airline_code": "AI",
            "total_amount": "4000.50",
            "currency": "INR",
            "departure_at": "2026-10-01T20:54:00",
            "arrival_at": "2026-10-01T23:29:00",
            "duration_minutes": 155,
            "stops": 0,
            "origin": "DEL",
            "destination": "GOI",
        }

    def test_the_price_stays_an_exact_string(self, offers, future_date):
        """It is saved with the conversation; a float would turn 4000.50 into 4000.5."""
        card = self.search(origin="DEL", destination="GOI", departure_date=future_date).artifact[
            "offers"
        ][0]

        assert card["total_amount"] == "4000.50"

    def test_only_the_offers_the_model_saw_become_cards(self, offers, future_date):
        artifact = self.search(origin="DEL", destination="GOI", departure_date=future_date).artifact

        assert len(artifact["offers"]) == 5
        assert artifact["total_found"] == 7

    def test_the_model_still_reads_the_same_text(self, offers, future_date):
        content = self.search(origin="DEL", destination="GOI", departure_date=future_date).content

        assert content.startswith(
            "Cheapest 5 of 7 offers:\nAir India: 4000.50 INR, departs 20:54, arrives 23:29, direct"
        )

    def test_an_invalid_search_has_no_cards(self, offers, future_date):
        message = self.search(origin="DELHI", destination="GOI", departure_date=future_date)

        assert message.artifact is None
        assert message.content.startswith("That search is not valid")


class TestStreamCarriesResults:
    def test_a_tool_result_with_data_puts_it_on_tool_end(self):
        artifact = {"kind": "sources", "sources": [{"file": "a.pdf", "page": 1}]}
        update = {
            "tools": {
                "messages": [
                    ToolMessage(
                        content="...",
                        tool_call_id="c1",
                        name="search_travel_policies",
                        artifact=artifact,
                    )
                ]
            }
        }

        assert _tool_events(update) == [
            {"event": "tool_end", "tool": "search_travel_policies", "result": artifact}
        ]


class TestReplayKeepsAttachments:
    CARDS = {
        "kind": "flights",
        "total_found": 1,
        "offers": [{"offer_id": "off_1", "total_amount": "4500.50", "currency": "INR"}],
    }

    @pytest.fixture
    def replayed(self, client, db_session, monkeypatch):
        async def fake_load_history(agent, conversation_id):
            return [
                HumanMessage(content="Flights to Goa?"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search_flight_offers", "args": {}, "id": "c1"}],
                ),
                ToolMessage(
                    content="Cheapest 1 of 1 offers:\nAir India: 4500.50 INR",
                    tool_call_id="c1",
                    name="search_flight_offers",
                    artifact=self.CARDS,
                ),
                AIMessage(content="The cheapest is Air India."),
                HumanMessage(content="Thanks"),
                AIMessage(content="You're welcome."),
            ]

        monkeypatch.setattr("app.api.routes.chat.load_history", fake_load_history)
        db_session.add(Conversation(id="mine", user_id=TEST_USER_ID, title="Goa"))
        db_session.commit()
        return client.get("/chat/conversations/mine").json()["messages"]

    def test_results_are_attached_to_the_answer_that_used_them(self, replayed):
        assert replayed[1] == {
            "role": "assistant",
            "content": "The cheapest is Air India.",
            "attachments": [self.CARDS],
        }

    def test_messages_without_results_have_no_attachments_key(self, replayed):
        """Unchanged for every message that has nothing to attach."""
        assert replayed[0] == {"role": "user", "content": "Flights to Goa?"}
        assert replayed[3] == {"role": "assistant", "content": "You're welcome."}

    def test_the_tool_output_itself_is_still_hidden(self, replayed):
        assert len(replayed) == 4
        assert all("Cheapest 1 of 1" not in message["content"] for message in replayed)
