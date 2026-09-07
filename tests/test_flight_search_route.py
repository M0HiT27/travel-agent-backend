"""Tests for POST /flights/search.

Duffel itself is never called: `search_flights` is replaced with a stub, so these tests
run offline and cost nothing.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.flight import FlightOffer, FlightSegment


def make_offer(offer_id: str, amount: str, airline: str) -> FlightOffer:
    departure = datetime(2026, 9, 15, 10, 50)
    arrival = datetime(2026, 9, 15, 13, 25)
    return FlightOffer(
        offer_id=offer_id,
        airline_name=airline,
        airline_code="AI",
        total_amount=Decimal(amount),
        currency="INR",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=155,
        stops=0,
        segments=[
            FlightSegment(
                origin="DEL",
                destination="GOI",
                departure_at=departure,
                arrival_at=arrival,
                carrier_code="AI",
                carrier_name=airline,
                flight_number="100",
                duration_minutes=155,
            )
        ],
    )


@pytest.fixture
def stub_search(monkeypatch):
    """Replace the real Duffel call with a stub that records what it was asked for."""
    calls = []

    async def fake_search_flights(settings, search):
        calls.append(search)
        return [
            make_offer("off_cheap", "4500.50", "Air India"),
            make_offer("off_pricey", "7200.00", "IndiGo"),
        ]

    monkeypatch.setattr(
        "app.api.routes.flights.search_flights", fake_search_flights
    )
    return calls


def test_search_returns_offers(client, stub_search, future_date):
    response = client.post(
        "/flights/search",
        json={"origin": "DEL", "destination": "GOI", "departure_date": future_date},
    )

    assert response.status_code == 200
    offers = response.json()
    assert len(offers) == 2
    assert offers[0]["offer_id"] == "off_cheap"
    assert offers[0]["currency"] == "INR"
    assert offers[0]["stops"] == 0
    assert offers[0]["segments"][0]["origin"] == "DEL"


def test_lowercase_iata_codes_are_normalised(client, stub_search, future_date):
    response = client.post(
        "/flights/search",
        json={"origin": "del", "destination": " goi ", "departure_date": future_date},
    )

    assert response.status_code == 200
    # The service receives the cleaned-up values, not the raw ones.
    assert stub_search[0].origin == "DEL"
    assert stub_search[0].destination == "GOI"


def test_adults_default_to_one(client, stub_search, future_date):
    client.post(
        "/flights/search",
        json={"origin": "DEL", "destination": "GOI", "departure_date": future_date},
    )

    assert stub_search[0].adults == 1


def test_past_departure_date_is_rejected(client, stub_search):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    response = client.post(
        "/flights/search",
        json={"origin": "DEL", "destination": "GOI", "departure_date": yesterday},
    )

    assert response.status_code == 422
    assert stub_search == [], "Duffel must not be called for an invalid request"


def test_identical_origin_and_destination_is_rejected(client, stub_search, future_date):
    response = client.post(
        "/flights/search",
        json={"origin": "DEL", "destination": "DEL", "departure_date": future_date},
    )

    assert response.status_code == 422
    assert stub_search == []


def test_invalid_iata_code_is_rejected(client, stub_search, future_date):
    response = client.post(
        "/flights/search",
        json={"origin": "DELHI", "destination": "GOI", "departure_date": future_date},
    )

    assert response.status_code == 422
    assert stub_search == []


def test_adults_outside_supported_range_is_rejected(client, stub_search, future_date):
    response = client.post(
        "/flights/search",
        json={
            "origin": "DEL",
            "destination": "GOI",
            "departure_date": future_date,
            "adults": 0,
        },
    )

    assert response.status_code == 422
    assert stub_search == []


def test_search_requires_authentication(stub_search, future_date):
    """Without the auth override, the endpoint must reject the request."""
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides.clear()
    with TestClient(app) as anonymous_client:
        response = anonymous_client.post(
            "/flights/search",
            json={"origin": "DEL", "destination": "GOI", "departure_date": future_date},
        )

    assert response.status_code == 401
    assert stub_search == []
