"""Tests for turning parse.bot's scraped responses into our hotel models.

The payloads below are trimmed copies of real parse.bot responses, so these run with
no network and no API key.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.schemas.hotel import HotelSearchRequest
from app.services.hotel_service import (
    _build_query_params,
    _pick_destination,
    map_parsebot_hotels,
)

# Four of the ten suggestions a real "Paris" autocomplete returns. Note the order: the
# first entry is the city we want, but the list also carries a neighbourhood, an airport
# and a second, very different city called Paris.
AUTOCOMPLETE_PAYLOAD = {
    "status": "success",
    "data": {
        "destinations": [
            {
                "id": "2734",
                "name": "Paris, France",
                "type": "CITY",
                "lat": "48.853564",
                "long": "2.348095",
            },
            {
                "id": "6200422",
                "name": "Paris City Center, Paris, France",
                "type": "NEIGHBORHOOD",
                "lat": "48.862383",
                "long": "2.339074",
            },
            {
                "id": "4670531",
                "name": "Paris, France (CDG-Roissy-Charles de Gaulle)",
                "type": "AIRPORT",
                "lat": "49.004061",
                "long": "2.571006",
            },
            {
                "id": "9474",
                "name": "Paris, Texas, United States of America",
                "type": "CITY",
                "lat": "33.660938",
                "long": "-95.555511",
            },
        ]
    },
}

# Two of the twenty listings a real search returns. Prices are display text, not
# numbers, and reviews_text comes back empty far more often than not.
SEARCH_PAYLOAD = {
    "status": "success",
    "data": {
        "hotels": [
            {
                "id": "5951861",
                "name": "Grand Hotel Leveque",
                "location": "Paris",
                "rating": "9.4",
                "reviews_text": "",
                "price_per_night": "$492 nightly",
                "total_price": "$1,661 total",
                "image_url": "https://images.trvl-media.com/lodging/5951861/ebf81ef1.jpg",
                "url": (
                    "https://www.hotels.com/ho429281/grand-hotel-leveque-paris-france/"
                    "?chkin=2026-10-15&chkout=2026-10-18&regionId=2734"
                    "&sort=RECOMMENDED&top_dp=1661&top_cur=USD"
                ),
            },
            {
                "id": "3703",
                "name": "Libertel Montmartre Opéra",
                "location": "Montmartre",
                "rating": "8.6",
                "reviews_text": "Excellent location",
                "price_per_night": "$244 nightly",
                "total_price": "$844 total",
                "image_url": "https://images.trvl-media.com/lodging/3703/64f196c0.jpg",
                "url": (
                    "https://www.hotels.com/ho130479/libertel-montmartre-opera-paris-france/"
                    "?chkin=2026-10-15&chkout=2026-10-18&regionId=2734"
                    "&sort=RECOMMENDED&top_dp=844&top_cur=USD"
                ),
            },
        ]
    },
}


def test_maps_hotels_from_real_payload():
    hotels = map_parsebot_hotels(SEARCH_PAYLOAD)

    assert len(hotels) == 2
    first = hotels[0]
    assert first.hotel_id == "5951861"
    assert first.name == "Grand Hotel Leveque"
    assert first.location == "Paris"
    assert first.rating == 9.4
    assert first.price_per_night == Decimal("492")
    assert first.total_price == Decimal("1661")
    assert first.currency == "USD"
    assert first.booking_url.startswith("https://www.hotels.com/")


def test_recommended_order_is_preserved():
    """The source ranks by its own recommendation, and we do not re-sort by price."""
    hotels = map_parsebot_hotels(SEARCH_PAYLOAD)

    assert [h.hotel_id for h in hotels] == ["5951861", "3703"]
    # Deliberately not cheapest-first: the pricier hotel is ranked above the cheaper one.
    assert hotels[0].total_price > hotels[1].total_price


def test_prices_are_exact_decimals_not_floats():
    hotel = map_parsebot_hotels(SEARCH_PAYLOAD)[0]

    # "$1,661 total" -> Decimal("1661"): symbol, thousands separator and suffix stripped.
    assert isinstance(hotel.total_price, Decimal)
    assert str(hotel.total_price) == "1661"


def test_empty_reviews_text_becomes_none():
    """The scraper sends "" for a missing review summary; None is the honest value."""
    hotels = map_parsebot_hotels(SEARCH_PAYLOAD)

    assert hotels[0].review_summary is None
    assert hotels[1].review_summary == "Excellent location"


def test_currency_comes_from_the_booking_url_not_the_symbol():
    """"$" alone could be USD, CAD or AUD. The URL's top_cur says which it was."""
    payload = {
        "status": "success",
        "data": {
            "hotels": [
                {
                    **SEARCH_PAYLOAD["data"]["hotels"][0],
                    "url": "https://www.hotels.com/ho1/?top_cur=CAD",
                }
            ]
        },
    }

    assert map_parsebot_hotels(payload)[0].currency == "CAD"


def test_currency_falls_back_to_the_symbol_without_a_usable_url():
    payload = {
        "status": "success",
        "data": {
            "hotels": [
                {
                    **SEARCH_PAYLOAD["data"]["hotels"][0],
                    "url": "https://www.hotels.com/ho1/",
                    "price_per_night": "₹9,800 nightly",
                    "total_price": "₹29,400 total",
                }
            ]
        },
    }

    hotel = map_parsebot_hotels(payload)[0]
    assert hotel.currency == "INR"
    assert hotel.total_price == Decimal("29400")


def test_unparseable_price_keeps_the_listing():
    """A hotel with no readable price is still worth showing; only a nameless or
    id-less row is unusable."""
    payload = {
        "status": "success",
        "data": {
            "hotels": [
                {
                    **SEARCH_PAYLOAD["data"]["hotels"][0],
                    "price_per_night": "Sold out",
                    "total_price": None,
                }
            ]
        },
    }

    hotel = map_parsebot_hotels(payload)[0]
    assert hotel.name == "Grand Hotel Leveque"
    assert hotel.price_per_night is None
    assert hotel.total_price is None
    assert hotel.currency is None


def test_unmappable_hotels_are_skipped_not_fatal():
    payload = {
        "status": "success",
        "data": {
            "hotels": [
                {"name": "No id here"},
                SEARCH_PAYLOAD["data"]["hotels"][0],
                {"id": "no_name", "name": "   "},
                "not-a-dict",
            ]
        },
    }

    hotels = map_parsebot_hotels(payload)

    assert len(hotels) == 1
    assert hotels[0].hotel_id == "5951861"


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": None}, {"data": {}}, {"data": {"hotels": None}}, "not-a-dict", None],
)
def test_malformed_payloads_return_empty_list(payload):
    assert map_parsebot_hotels(payload) == []


def test_out_of_range_rating_is_dropped():
    payload = {
        "status": "success",
        "data": {
            "hotels": [{**SEARCH_PAYLOAD["data"]["hotels"][0], "rating": "not a number"}]
        },
    }

    assert map_parsebot_hotels(payload)[0].rating is None


# --------------------------------------------------------------------------------------
# Destination resolution
# --------------------------------------------------------------------------------------


def test_picks_the_city_out_of_a_mixed_suggestion_list():
    assert _pick_destination(AUTOCOMPLETE_PAYLOAD) == ("2734", "Paris, France")


def test_falls_back_to_the_first_suggestion_when_no_city_matches():
    """A query like "Eiffel" returns no CITY at all, and a POI is better than nothing."""
    payload = {
        "status": "success",
        "data": {
            "destinations": [
                {"id": "502251", "name": "Eiffel Tower, Paris, France", "type": "POI"},
                {"id": "178677", "name": "Marais, Paris, France", "type": "NEIGHBORHOOD"},
            ]
        },
    }

    assert _pick_destination(payload) == ("502251", "Eiffel Tower, Paris, France")


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "success", "data": {"destinations": []}},
        {"status": "success", "data": {"destinations": [{"name": "no id"}]}},
        {"data": {}},
        {},
        None,
    ],
)
def test_no_resolvable_destination_returns_none(payload):
    """`search_hotels` turns this into a 404: a typo'd city is the client's mistake,
    not an upstream failure."""
    assert _pick_destination(payload) is None


# --------------------------------------------------------------------------------------
# Request building
# --------------------------------------------------------------------------------------


def test_query_params_use_the_resolved_name_and_iso_dates():
    # Computed rather than hard-coded, so this test does not start failing once some
    # fixed date slips into the past.
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=3)
    search = HotelSearchRequest(
        destination="paris", start_date=start, end_date=end, rooms=2, adults=3
    )

    params = _build_query_params(search, "2734", "Paris, France")

    assert params == {
        "query": "Paris, France",
        "region_id": "2734",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "rooms": "2",
        "adults": "3",
    }
