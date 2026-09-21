"""Tests for the bus policy RAG tool.

Both the embedding call and the pgvector search are monkeypatched, so these run
offline with no API key and no database.
"""

import pytest

import app.tools.bus_policy_tool as bus_policy_tool
from app.core.config import Settings
from app.vectorstores.pgvector_store import ScoredChunk


def _settings() -> Settings:
    return Settings(
        jwt_secret_key="x", parsebot_hotel_scraper_id="h", parsebot_redbus_scraper_id="r"
    )


class _FakeEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 768


@pytest.fixture
def stub_embeddings(monkeypatch):
    monkeypatch.setattr(bus_policy_tool, "get_embeddings", lambda settings: _FakeEmbeddings())


async def test_tool_searches_only_the_bus_domain(monkeypatch, stub_embeddings):
    calls = []

    def fake_search(db, *, domain, query_embedding, k):
        calls.append(domain)
        return [ScoredChunk(content="Cancel 24h before for a 90% refund.", source="bus_policy.pdf", distance=0.1)]

    monkeypatch.setattr(bus_policy_tool, "search", fake_search)
    tool = bus_policy_tool.make_bus_policy_tool(_settings(), db=object())

    result = await tool.ainvoke({"query": "what's the cancellation refund"})

    assert calls == ["bus"]
    assert "90% refund" in result
    assert "bus_policy.pdf" in result


async def test_tool_reports_no_results(monkeypatch, stub_embeddings):
    monkeypatch.setattr(bus_policy_tool, "search", lambda db, **kwargs: [])
    tool = bus_policy_tool.make_bus_policy_tool(_settings(), db=object())

    result = await tool.ainvoke({"query": "can I bring my elephant"})

    assert "No bus policy information" in result
