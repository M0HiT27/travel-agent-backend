"""Tests for turning Duffel's response into FlightOffer objects.

The payload below is a trimmed copy of a real Duffel test-mode response, so these run
with no network and no API key.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.flight import FlightSearchRequest
from app.services.flight_service import _build_request_body, map_duffel_offers

# Two offers from a live Duffel test-mode response: a direct Duffel Airways fare, and a
# codeshare (Air India marketing, Air India Express operating) whose
# operating_carrier_flight_number is null.
DUFFEL_PAYLOAD = {
    "data": {
        "offers": [
            {
                "id": "off_0000BA3TGI3Iv8ouTVvSrq",
                "total_amount": "81.70",
                "total_currency": "AUD",
                "expires_at": "2026-09-04T05:36:05.262562Z",
                "owner": {"iata_code": "ZZ", "name": "Duffel Airways"},
                "slices": [
                    {
                        "duration": "PT2H35M",
                        "segments": [
                            {
                                "departing_at": "2026-09-15T10:50:00",
                                "arriving_at": "2026-09-15T13:25:00",
                                "duration": "PT2H35M",
                                "marketing_carrier": {
                                    "iata_code": "ZZ",
                                    "name": "Duffel Airways",
                                },
                                "marketing_carrier_flight_number": "2120",
                                "origin": {"iata_code": "DEL"},
                                "destination": {"iata_code": "GOI"},
                            }
                        ],
                    }
                ],
            },
            {
                "id": "off_0000BA3TGh7PizxiDV2bFY",
                "total_amount": "104.30",
                "total_currency": "AUD",
                "expires_at": "2026-09-04T06:06:09.570510Z",
                "owner": {"iata_code": "AI", "name": "Air India"},
                "slices": [
                    {
                        "duration": "PT2H35M",
                        "segments": [
                            {
                                "departing_at": "2026-09-15T11:55:00",
                                "arriving_at": "2026-09-15T14:30:00",
                                "duration": "PT2H35M",
                                "operating_carrier": {
                                    "iata_code": "IX",
                                    "name": "Air India Express",
                                },
                                "marketing_carrier": {
                                    "iata_code": "AI",
                                    "name": "Air India",
                                },
                                "operating_carrier_flight_number": None,
                                "marketing_carrier_flight_number": "9722",
                                "origin": {"iata_code": "DEL"},
                                "destination": {"iata_code": "GOI"},
                            }
                        ],
                    }
                ],
            },
        ]
    }
}


def test_maps_offers_from_real_payload():
    offers = map_duffel_offers(DUFFEL_PAYLOAD)

    assert len(offers) == 2
    first = offers[0]
    assert first.offer_id == "off_0000BA3TGI3Iv8ouTVvSrq"
    assert first.airline_name == "Duffel Airways"
    assert first.airline_code == "ZZ"
    assert first.total_amount == Decimal("81.70")
    assert first.currency == "AUD"
    assert first.duration_minutes == 155  # "PT2H35M"
    assert first.stops == 0
    assert first.departure_at == datetime(2026, 9, 15, 10, 50)
    assert first.arrival_at == datetime(2026, 9, 15, 13, 25)


def test_total_amount_keeps_exact_decimal_precision():
    offer = map_duffel_offers(DUFFEL_PAYLOAD)[0]

    # Decimal, not float: 81.70 has no exact binary representation.
    assert isinstance(offer.total_amount, Decimal)
    assert str(offer.total_amount) == "81.70"


def test_codeshare_uses_marketing_carrier():
    """The operating carrier is Air India Express with a null flight number, but the
    traveller booked Air India, so that is what we show."""
    segment = map_duffel_offers(DUFFEL_PAYLOAD)[1].segments[0]

    assert segment.carrier_code == "AI"
    assert segment.carrier_name == "Air India"
    assert segment.flight_number == "9722"


def test_unmappable_offers_are_skipped_not_fatal():
    payload = {
        "data": {
            "offers": [
                {"id": "off_broken"},  # no slices
                DUFFEL_PAYLOAD["data"]["offers"][0],
                {"slices": []},  # no id
            ]
        }
    }

    offers = map_duffel_offers(payload)

    assert len(offers) == 1
    assert offers[0].offer_id == "off_0000BA3TGI3Iv8ouTVvSrq"


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": None}, {"data": {}}, {"data": {"offers": None}}, "not-a-dict", None],
)
def test_malformed_payloads_return_empty_list(payload):
    assert map_duffel_offers(payload) == []


def test_request_body_has_one_passenger_per_adult():
    # Computed rather than hard-coded, so this test does not start failing once some
    # fixed date slips into the past.
    departure = date.today() + timedelta(days=30)
    search = FlightSearchRequest(
        origin="DEL", destination="GOI", departure_date=departure, adults=3
    )

    body = _build_request_body(search)

    assert body["data"]["passengers"] == [{"type": "adult"}] * 3
    assert body["data"]["slices"] == [
        {
            "origin": "DEL",
            "destination": "GOI",
            "departure_date": departure.isoformat(),
        }
    ]
