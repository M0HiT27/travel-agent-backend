"""Tests for turning parse.bot's redbus scraper responses into our bus models.

The payloads below are trimmed copies of real parse.bot responses (captured
2026-09-08), so these run with no network and no API key -- same approach as
test_hotel_service.py.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.bus import BusSearchRequest
from app.services.bus_service import (
    _build_query_params,
    _format_doj,
    _pick_city,
    map_parsebot_buses,
)

# A get_city_suggestions response for "Bhopal". Unlike hotels' autocomplete, this
# endpoint returns one doc per matched city (with its boarding points nested inside),
# not a mixed list of cities/neighbourhoods/airports.
CITY_SUGGESTIONS_PAYLOAD = {
    "status": "success",
    "data": {
        "numFound": 1,
        "docs": [
            {
                "ID": 979,
                "locationType": "CITY",
                "locationName": "Bhopal (All Locations)",
                "region": "Madhya Pradesh",
                "Name": "Bhopal",
            }
        ],
    },
}

# Two of the 28 inventories a real Bhopal -> Guna search_buses response returns.
SEARCH_PAYLOAD = {
    "status": "success",
    "data": {
        "metaData": {"totalCount": 28},
        "inventories": [
            {
                "operatorId": 27561,
                "travelsName": "Chartered Bus",
                "routeId": 54760308,
                "busType": "Volvo AC Seater (2+2)",
                "totalRatings": 4.7,
                "departureTime": "2026-09-18 08:15:00",
                "arrivalTime": "2026-09-18 12:34:00",
                "journeyDurationMin": 259,
                "fareList": [333.33, 404.76],
                "availableSeats": 47,
            },
            {
                "operatorId": 19850,
                "travelsName": "Rayeen Bus (Sutra Sewa)",
                "routeId": 14473338,
                "busType": "A/C Seater (2+2)",
                "totalRatings": 3.4,
                "departureTime": "2026-09-18 19:40:00",
                "arrivalTime": "2026-09-18 23:20:00",
                "journeyDurationMin": 220,
                "fareList": [399],
                "availableSeats": 31,
            },
        ],
        "parentSrcCityId": 979,
        "parentDstCityId": 1365,
    },
}


def test_maps_buses_from_real_payload():
    buses = map_parsebot_buses(SEARCH_PAYLOAD)

    assert len(buses) == 2
    first = buses[0]
    # Integers in the raw payload become strings, for consistency with the rest of
    # the API (ids are always strings elsewhere, e.g. FlightOffer.offer_id).
    assert first.route_id == "54760308"
    assert first.operator_id == "27561"
    assert first.travels_name == "Chartered Bus"
    assert first.bus_type == "Volvo AC Seater (2+2)"
    assert first.available_seats == 47
    assert first.rating == 4.7
    assert first.duration_minutes == 259
    assert first.departure_time == datetime(2026, 9, 18, 8, 15)
    assert first.arrival_time == datetime(2026, 9, 18, 12, 34)


def test_order_is_preserved():
    buses = map_parsebot_buses(SEARCH_PAYLOAD)

    assert [b.route_id for b in buses] == ["54760308", "14473338"]


def test_fare_is_exact_decimal_not_float():
    buses = map_parsebot_buses(SEARCH_PAYLOAD)

    # fareList has one price per seat class; the lowest is picked.
    assert isinstance(buses[0].fare, Decimal)
    assert buses[0].fare == Decimal("333.33")
    # A single-entry fareList is still a list.
    assert buses[1].fare == Decimal("399")


def test_out_of_range_rating_is_dropped():
    payload = {
        "status": "success",
        "data": {"inventories": [{**SEARCH_PAYLOAD["data"]["inventories"][0], "totalRatings": 9.9}]},
    }

    assert map_parsebot_buses(payload)[0].rating is None


def test_unparseable_departure_time_keeps_the_bus():
    """A bus with an unreadable time is still worth showing; only a missing route id
    or travels name is unusable."""
    payload = {
        "status": "success",
        "data": {
            "inventories": [
                {**SEARCH_PAYLOAD["data"]["inventories"][0], "departureTime": "not-a-datetime"}
            ]
        },
    }

    bus = map_parsebot_buses(payload)[0]
    assert bus.departure_time is None
    assert bus.route_id == "54760308"


def test_unmappable_buses_are_skipped_not_fatal():
    payload = {
        "status": "success",
        "data": {
            "inventories": [
                {"travelsName": "No route id here"},
                SEARCH_PAYLOAD["data"]["inventories"][0],
                {"routeId": 1, "travelsName": "   "},
                "not-a-dict",
            ]
        },
    }

    buses = map_parsebot_buses(payload)

    assert len(buses) == 1
    assert buses[0].route_id == "54760308"


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": None}, {"data": {}}, {"data": {"inventories": None}}, "not-a-dict", None],
)
def test_malformed_payloads_return_empty_list(payload):
    assert map_parsebot_buses(payload) == []


# --------------------------------------------------------------------------------------
# City resolution
# --------------------------------------------------------------------------------------


def test_picks_the_city_out_of_a_real_payload():
    assert _pick_city(CITY_SUGGESTIONS_PAYLOAD) == ("979", "Bhopal")


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "success", "data": {"docs": []}},
        {"status": "success", "data": {"docs": [{"Name": "no id"}]}},
        {"data": {}},
        {},
        None,
    ],
)
def test_no_resolvable_city_returns_none(payload):
    """`search_buses` turns this into a 404: a typo'd city is the client's mistake,
    not an upstream failure."""
    assert _pick_city(payload) is None


# --------------------------------------------------------------------------------------
# Request building
# --------------------------------------------------------------------------------------


def test_query_params_use_resolved_ids_and_doj_format():
    departure = date.today() + timedelta(days=30)
    search = BusSearchRequest(origin="mumbai", destination="pune", departure_date=departure)

    params = _build_query_params(search, "462", "130")

    assert params == {
        "from_city_id": "462",
        "to_city_id": "130",
        "doj": _format_doj(departure),
    }


def test_doj_format_matches_parse_bot_example():
    # Confirmed against a real request: `doj=18-Sep-2026`.
    assert _format_doj(date(2026, 9, 18)) == "18-Sep-2026"
