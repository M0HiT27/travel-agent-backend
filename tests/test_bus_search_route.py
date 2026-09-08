"""Tests for POST /buses/search.

parse.bot is never called: `search_buses` is replaced with a stub, so these tests run
offline and cost nothing.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.schemas.bus import Bus, BusSearchResponse


def make_response() -> BusSearchResponse:
    return BusSearchResponse(
        origin="Mumbai",
        origin_city_id="462",
        destination="Pune",
        destination_city_id="130",
        departure_date=date.today() + timedelta(days=30),
        buses=[
            Bus(
                route_id="r1",
                operator_id="op1",
                travels_name="Neeta Travels",
                bus_type="AC Sleeper (2+1)",
                available_seats=14,
                fare=Decimal("450"),
                rating=4.2,
            ),
            Bus(
                route_id="r2",
                travels_name="VRL Travels",
                bus_type="Non AC Seater",
                available_seats=0,
                fare=Decimal("350"),
            ),
        ],
    )


@pytest.fixture
def stub_search(monkeypatch):
    """Replace the real parse.bot calls with a stub that records what it was asked for."""
    calls = []

    async def fake_search_buses(settings, search):
        calls.append(search)
        return make_response()

    monkeypatch.setattr("app.api.routes.buses.search_buses", fake_search_buses)
    return calls


def body(departure_date: str, **overrides) -> dict:
    return {
        "origin": "Mumbai",
        "destination": "Pune",
        "departure_date": departure_date,
        **overrides,
    }


def test_search_returns_buses(client, stub_search, future_date):
    response = client.post("/buses/search", json=body(future_date))

    assert response.status_code == 200
    data = response.json()
    assert data["origin_city_id"] == "462"
    assert data["destination_city_id"] == "130"
    assert len(data["buses"]) == 2
    assert data["buses"][0]["travels_name"] == "Neeta Travels"
    # Decimal serialises as a string, never a float.
    assert data["buses"][0]["fare"] == "450"


def test_response_reports_which_cities_were_resolved(client, stub_search, future_date):
    response = client.post("/buses/search", json=body(future_date))

    data = response.json()
    assert data["origin"] == "Mumbai"
    assert data["destination"] == "Pune"


def test_city_whitespace_is_normalised(client, stub_search, future_date):
    response = client.post(
        "/buses/search", json=body(future_date, origin="  mumbai   central ")
    )

    assert response.status_code == 200
    assert stub_search[0].origin == "mumbai central"


def test_past_departure_date_is_rejected(client, stub_search):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    response = client.post("/buses/search", json=body(yesterday))

    assert response.status_code == 422
    assert stub_search == [], "parse.bot must not be called for an invalid request"


def test_identical_origin_and_destination_is_rejected(client, stub_search, future_date):
    response = client.post(
        "/buses/search", json=body(future_date, origin="Pune", destination="pune")
    )

    assert response.status_code == 422
    assert stub_search == []


def test_blank_city_is_rejected(client, stub_search, future_date):
    response = client.post("/buses/search", json=body(future_date, origin="  "))

    assert response.status_code == 422
    assert stub_search == []


def test_search_requires_authentication(stub_search, future_date):
    """Without the auth override, the endpoint must reject the request."""
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides.clear()
    with TestClient(app) as anonymous_client:
        response = anonymous_client.post("/buses/search", json=body(future_date))

    assert response.status_code == 401
    assert stub_search == []
