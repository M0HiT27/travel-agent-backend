"""Tests for POST /hotels/search.

parse.bot is never called: `search_hotels` is replaced with a stub, so these tests run
offline and cost nothing.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.schemas.hotel import Hotel, HotelSearchResponse


def make_response() -> HotelSearchResponse:
    return HotelSearchResponse(
        destination="Paris, France",
        region_id="2734",
        nights=3,
        hotels=[
            Hotel(
                hotel_id="5951861",
                name="Grand Hotel Leveque",
                location="Paris",
                rating=9.4,
                price_per_night=Decimal("492"),
                total_price=Decimal("1661"),
                currency="USD",
                booking_url="https://www.hotels.com/ho429281/",
            ),
            Hotel(
                hotel_id="3703",
                name="Libertel Montmartre Opera",
                location="Montmartre",
                rating=8.6,
                price_per_night=Decimal("244"),
                total_price=Decimal("844"),
                currency="USD",
            ),
        ],
    )


@pytest.fixture
def stub_search(monkeypatch):
    """Replace the real parse.bot calls with a stub that records what it was asked for."""
    calls = []

    async def fake_search_hotels(settings, search):
        calls.append(search)
        return make_response()

    monkeypatch.setattr("app.api.routes.hotels.search_hotels", fake_search_hotels)
    return calls


def body(start: str, end: str, **overrides) -> dict:
    return {"destination": "Paris", "start_date": start, "end_date": end, **overrides}


def test_search_returns_hotels(client, stub_search, future_dates):
    start, end = future_dates
    response = client.post("/hotels/search", json=body(start, end))

    assert response.status_code == 200
    data = response.json()
    assert data["region_id"] == "2734"
    assert data["nights"] == 3
    assert len(data["hotels"]) == 2
    assert data["hotels"][0]["name"] == "Grand Hotel Leveque"
    # Decimal serialises as a string, never a float.
    assert data["hotels"][0]["total_price"] == "1661"


def test_response_reports_which_destination_was_resolved(client, stub_search, future_dates):
    """"Paris" also matches Paris, Texas, so the caller must be able to see the pick."""
    start, end = future_dates
    response = client.post("/hotels/search", json=body(start, end))

    assert response.json()["destination"] == "Paris, France"


def test_destination_whitespace_is_normalised(client, stub_search, future_dates):
    start, end = future_dates
    response = client.post(
        "/hotels/search", json=body(start, end, destination="  new    york ")
    )

    assert response.status_code == 200
    # The service receives the cleaned-up value, not the raw one.
    assert stub_search[0].destination == "new york"


def test_rooms_and_adults_default(client, stub_search, future_dates):
    start, end = future_dates
    client.post("/hotels/search", json=body(start, end))

    assert stub_search[0].rooms == 1
    assert stub_search[0].adults == 2


def test_past_check_in_is_rejected(client, stub_search, future_dates):
    _, end = future_dates
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    response = client.post("/hotels/search", json=body(yesterday, end))

    assert response.status_code == 422
    assert stub_search == [], "parse.bot must not be called for an invalid request"


def test_check_out_on_the_check_in_date_is_rejected(client, stub_search, future_dates):
    start, _ = future_dates
    response = client.post("/hotels/search", json=body(start, start))

    assert response.status_code == 422
    assert stub_search == []


def test_check_out_before_check_in_is_rejected(client, stub_search, future_dates):
    start, end = future_dates
    response = client.post("/hotels/search", json=body(end, start))

    assert response.status_code == 422
    assert stub_search == []


def test_overlong_stay_is_rejected(client, stub_search, future_dates):
    start, _ = future_dates
    too_far = (date.fromisoformat(start) + timedelta(days=99)).isoformat()
    response = client.post("/hotels/search", json=body(start, too_far))

    assert response.status_code == 422
    assert stub_search == []


def test_blank_destination_is_rejected(client, stub_search, future_dates):
    start, end = future_dates
    response = client.post("/hotels/search", json=body(start, end, destination="   "))

    assert response.status_code == 422
    assert stub_search == []


@pytest.mark.parametrize("overrides", [{"rooms": 0}, {"rooms": 99}, {"adults": 0}])
def test_room_and_guest_counts_outside_range_are_rejected(
    client, stub_search, future_dates, overrides
):
    start, end = future_dates
    response = client.post("/hotels/search", json=body(start, end, **overrides))

    assert response.status_code == 422
    assert stub_search == []


def test_search_requires_authentication(stub_search, future_dates):
    """Without the auth override, the endpoint must reject the request."""
    from fastapi.testclient import TestClient

    from app.main import app

    start, end = future_dates
    app.dependency_overrides.clear()
    with TestClient(app) as anonymous_client:
        response = anonymous_client.post("/hotels/search", json=body(start, end))

    assert response.status_code == 401
    assert stub_search == []
