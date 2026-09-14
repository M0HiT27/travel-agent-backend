"""Hotel search against the hotels.com scraper hosted on parse.bot.

Read this file top to bottom: `search_hotels` is the whole story, and everything below
it is one of the steps it names.

Like `flight_service`, this is a plain async function rather than anything tied to
FastAPI, so it can be called directly from a route today and from a LangGraph/LangChain
tool later, without the agent having to make an HTTP call back into our own API.

The one structural difference from flights: the scraper needs a numeric `region_id`,
not a place name, so a search is *two* upstream calls -- resolve, then search.
"""

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.schemas.hotel import Hotel, HotelSearchRequest, HotelSearchResponse
from app.services._parsebot import call_parsebot

logger = logging.getLogger(__name__)


async def search_hotels(
    settings: Settings, search: HotelSearchRequest
) -> HotelSearchResponse:
    """Search hotels for a destination name, in the source's recommended order."""
    region_id, resolved_name = await _resolve_destination(settings, search.destination)
    payload = await _call_parsebot(
        settings, "search_hotels", _build_query_params(search, region_id, resolved_name)
    )
    return HotelSearchResponse(
        destination=resolved_name,
        region_id=region_id,
        nights=search.nights,
        hotels=map_parsebot_hotels(payload),
    )


# --------------------------------------------------------------------------------------
# Step 1: turn a destination name into a region id
# --------------------------------------------------------------------------------------

# "Paris" -> ("2734", "Paris, France") never changes, and every miss costs a billable
# scrape, so resolutions are remembered for the life of the process. Cleared wholesale
# rather than evicted one by one: the map is tiny and correctness does not depend on it.
_region_cache: dict[str, tuple[str, str]] = {}
_REGION_CACHE_MAX = 512


async def _resolve_destination(settings: Settings, destination: str) -> tuple[str, str]:
    """Return `(region_id, canonical_name)` for a destination name."""
    key = destination.casefold()
    cached = _region_cache.get(key)
    if cached is not None:
        return cached

    payload = await _call_parsebot(
        settings, "autocomplete_destination", {"query": destination}
    )
    match = _pick_destination(payload)
    if match is None:
        raise NotFoundError(f"No destination matching '{destination}' was found.")

    if len(_region_cache) >= _REGION_CACHE_MAX:
        _region_cache.clear()
    _region_cache[key] = match
    return match


def _pick_destination(payload: Any) -> tuple[str, str] | None:
    """Choose one suggestion out of the autocomplete response.

    The list mixes cities, neighbourhoods, airports and points of interest, so a plain
    "first result" is wrong for a query like "Eiffel". A CITY is what someone searching
    for hotels almost always means; anything else is only used when no city matched.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return None
    raw = payload["data"].get("destinations")
    if not isinstance(raw, list):
        return None

    candidates = [
        (item["id"], item["name"], item.get("type"))
        for item in raw
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"]
        and isinstance(item.get("name"), str)
        and item["name"]
    ]
    if not candidates:
        return None

    for region_id, name, kind in candidates:
        if kind == "CITY":
            return region_id, name

    region_id, name, _ = candidates[0]
    return region_id, name


# --------------------------------------------------------------------------------------
# Step 2: build the query the scraper expects
# --------------------------------------------------------------------------------------


def _build_query_params(
    search: HotelSearchRequest, region_id: str, resolved_name: str
) -> dict[str, str]:
    # The scraper wants both: region_id selects the place, query is echoed into the
    # hotels.com URL it builds. Sending the resolved name rather than the user's raw
    # text keeps the two consistent.
    return {
        "query": resolved_name,
        "region_id": region_id,
        "start_date": search.start_date.isoformat(),
        "end_date": search.end_date.isoformat(),
        "rooms": str(search.rooms),
        "adults": str(search.adults),
    }


# --------------------------------------------------------------------------------------
# Step 3: call parse.bot
# --------------------------------------------------------------------------------------


async def _call_parsebot(
    settings: Settings, operation: str, params: dict[str, str]
) -> Any:
    """GET one hotels.com scraper operation. Both operations share this envelope."""
    return await call_parsebot(
        settings,
        settings.parsebot_hotel_scraper_id,
        operation,
        params,
        label="Hotel search",
    )


# --------------------------------------------------------------------------------------
# Step 4: turn the scraped rows into our Hotel list
# --------------------------------------------------------------------------------------


def map_parsebot_hotels(payload: Any) -> list[Hotel]:
    """Map a raw search_hotels response into Hotel objects.

    Order is preserved: the source ranks by its own "recommended" blend of price,
    rating and location, which is more useful than a raw price sort.

    A single unusable listing is skipped rather than failing the whole search: a
    partial list of hotels is far more useful to a traveller than an error.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return []
    raw_hotels = payload["data"].get("hotels")
    if not isinstance(raw_hotels, list):
        return []

    hotels: list[Hotel] = []
    skipped = 0
    for raw in raw_hotels:
        hotel = _map_hotel(raw) if isinstance(raw, dict) else None
        if hotel is None:
            skipped += 1
        else:
            hotels.append(hotel)

    if skipped:
        logger.info("Skipped %s unmappable hotel(s) from parse.bot", skipped)
    return hotels


def _map_hotel(raw: dict[str, Any]) -> Hotel | None:
    hotel_id = raw.get("id")
    name = raw.get("name")
    if not isinstance(hotel_id, str) or not hotel_id:
        return None
    if not isinstance(name, str) or not name.strip():
        return None

    booking_url = raw.get("url") if isinstance(raw.get("url"), str) else None
    price_per_night = _parse_price(raw.get("price_per_night"))
    total_price = _parse_price(raw.get("total_price"))

    return Hotel(
        hotel_id=hotel_id,
        name=name.strip(),
        location=_clean_text(raw.get("location")),
        rating=_parse_rating(raw.get("rating")),
        review_summary=_clean_text(raw.get("reviews_text")),
        price_per_night=price_per_night,
        total_price=total_price,
        # The scraper never states a currency. The booking URL carries the one the
        # prices were rendered in, which beats guessing from a "$" that could be
        # USD, CAD or AUD; the symbol is only a fallback.
        currency=(
            _currency_from_url(booking_url)
            or _currency_from_symbol(raw.get("total_price"))
            or _currency_from_symbol(raw.get("price_per_night"))
        )
        if (price_per_night is not None or total_price is not None)
        else None,
        image_url=raw.get("image_url") if isinstance(raw.get("image_url"), str) else None,
        booking_url=booking_url,
    )


# --------------------------------------------------------------------------------------
# Small parsing helpers
# --------------------------------------------------------------------------------------

# Prices arrive as display text, e.g. "$492 nightly" or "$1,661 total".
_PRICE_RE = re.compile(r"(?P<amount>\d[\d,]*(?:\.\d+)?)")

_SYMBOL_CURRENCY = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
    "₩": "KRW",
    "R$": "BRL",
    "CHF": "CHF",
}


def _parse_price(value: Any) -> Decimal | None:
    if not isinstance(value, str):
        return None
    match = _PRICE_RE.search(value)
    if match is None:
        return None
    try:
        return Decimal(match.group("amount").replace(",", ""))
    except InvalidOperation:
        return None


def _currency_from_symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for symbol, code in _SYMBOL_CURRENCY.items():
        if symbol in value:
            return code
    return None


def _currency_from_url(url: str | None) -> str | None:
    """Read the currency out of the booking URL's `top_cur` query parameter."""
    if not url:
        return None
    try:
        codes = parse_qs(urlparse(url).query).get("top_cur")
    except ValueError:
        return None
    if not codes or not isinstance(codes[0], str):
        return None
    code = codes[0].strip().upper()
    return code if len(code) == 3 and code.isalpha() else None


def _parse_rating(value: Any) -> float | None:
    """Guest score out of 10, sent as a string like "9.4"."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rating = float(value)
    elif isinstance(value, str):
        try:
            rating = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return rating if 0 <= rating <= 10 else None


def _clean_text(value: Any) -> str | None:
    """Empty strings are the scraper's way of saying "nothing here"; make that a None."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None
