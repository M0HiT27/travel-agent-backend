"""Tests for the LangChain tool wrapping bus_service.search_buses.

search_buses itself is never called: it is monkeypatched, so these tests run offline.
The interesting behaviour here is (a) BusSearchRequest's validators are enforced via
the tool's args_schema, exactly as they are on the HTTP route, and (b) the result is
formatted into text an LLM can read.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

import app.tools.bus_search_tool as bus_search_tool
from app.core.config import Settings
from app.schemas.bus import Bus, BusSearchResponse


def _settings() -> Settings:
    return Settings(
        jwt_secret_key="x", parsebot_hotel_scraper_id="h", parsebot_redbus_scraper_id="r"
    )


def _future_date() -> str:
    return (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def stub_search_buses(monkeypatch):
    calls = []

    async def fake(settings, search):
        calls.append(search)
        return BusSearchResponse(
            origin="Mumbai",
            origin_city_id="462",
            destination="Pune",
            destination_city_id="130",
            departure_date=search.departure_date,
            buses=[
                Bus(
                    route_id="r1",
                    operator_id="o1",
                    travels_name="Neeta Travels",
                    bus_type="AC Sleeper",
                    departure_time=datetime(2026, 9, 18, 22, 30),
                    arrival_time=datetime(2026, 9, 19, 6, 15),
                    duration_minutes=465,
                    available_seats=14,
                    fare=Decimal("650"),
                    rating=4.2,
                )
            ],
        )

    monkeypatch.setattr(bus_search_tool, "search_buses", fake)
    return calls


@pytest.mark.asyncio
async def test_tool_formats_results_as_readable_text(stub_search_buses):
    tool = bus_search_tool.make_bus_search_tool(_settings())

    result = await tool.ainvoke(
        {"origin": "Mumbai", "destination": "Pune", "departure_date": _future_date()}
    )

    assert "Neeta Travels" in result
    assert "650" in result
    assert "14" in result
    assert stub_search_buses[0].origin == "Mumbai"


@pytest.mark.asyncio
async def test_tool_reports_no_buses_found(monkeypatch):
    async def fake(settings, search):
        return BusSearchResponse(
            origin="Mumbai",
            origin_city_id="462",
            destination="Pune",
            destination_city_id="130",
            departure_date=search.departure_date,
            buses=[],
        )

    monkeypatch.setattr(bus_search_tool, "search_buses", fake)
    tool = bus_search_tool.make_bus_search_tool(_settings())

    result = await tool.ainvoke(
        {"origin": "Mumbai", "destination": "Pune", "departure_date": _future_date()}
    )

    assert "No buses found" in result


@pytest.mark.asyncio
async def test_tool_turns_app_errors_into_a_tool_message_not_an_exception(monkeypatch):
    from app.core.exceptions import NotFoundError

    async def fake(settings, search):
        raise NotFoundError("No city matching 'Nowhereville' was found.")

    monkeypatch.setattr(bus_search_tool, "search_buses", fake)
    tool = bus_search_tool.make_bus_search_tool(_settings())

    result = await tool.ainvoke(
        {"origin": "Nowhereville", "destination": "Pune", "departure_date": _future_date()}
    )

    assert "Bus search failed" in result
    assert "Nowhereville" in result


def test_args_schema_reuses_bus_search_request_validation():
    """Past dates and identical cities are rejected the same way as the HTTP route,
    since the tool's args_schema IS BusSearchRequest -- not a re-implementation."""
    tool = bus_search_tool.make_bus_search_tool(_settings())

    with pytest.raises(ValidationError, match="cannot be in the past"):
        tool.args_schema(origin="Mumbai", destination="Pune", departure_date="2020-01-01")

    with pytest.raises(ValidationError, match="must be different"):
        tool.args_schema(origin="Pune", destination="pune", departure_date=_future_date())
