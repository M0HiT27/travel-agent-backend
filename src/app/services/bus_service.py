"""Bus search against the redBus scraper hosted on parse.bot.

Read this file top to bottom: `search_buses` is the whole story, and everything below
it is one of the steps it names.

Like `hotel_service`, this is a plain async function rather than anything tied to
FastAPI, so it can be called directly from a route today and from a LangGraph/LangChain
tool later, without the agent having to make an HTTP call back into our own API. The
structure mirrors hotels too: the scraper needs numeric city ids, not names, so a
search is *three* upstream calls -- resolve origin, resolve destination, then search.

Field names below are verified against a real search_buses / get_city_suggestions
response (2026-09-08), not inferred. Both endpoints wrap their payload in a `data`
envelope, `ID`/`routeId`/`operatorId` arrive as integers (converted to strings here
for consistency with the rest of the API), and `fareList` is a list of one price per
seat class, not a dict -- all of that differs from what parse.bot's own docs describe
(query parameters only, no response shape), so it was confirmed by an actual call
rather than guessed.
"""

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.schemas.bus import Bus, BusSearchRequest, BusSearchResponse
from app.services._parsebot import call_parsebot

logger = logging.getLogger(__name__)

# parse.bot's `doj` parameter wants "26-Jun-2026", not ISO 8601.
_DOJ_FORMAT = "%d-%b-%Y"


async def search_buses(settings: Settings, search: BusSearchRequest) -> BusSearchResponse:
    """Search buses between two city names, in the source's own order."""
    origin_id, origin_name = await _resolve_city(settings, search.origin)
    destination_id, destination_name = await _resolve_city(settings, search.destination)

    payload = await _call_parsebot(
        settings,
        "search_buses",
        _build_query_params(search, origin_id, destination_id),
    )
    return BusSearchResponse(
        origin=origin_name,
        origin_city_id=origin_id,
        destination=destination_name,
        destination_city_id=destination_id,
        departure_date=search.departure_date,
        buses=map_parsebot_buses(payload),
    )


# --------------------------------------------------------------------------------------
# Step 1: turn a city name into a city id
# --------------------------------------------------------------------------------------

# "Mumbai" -> ("462", "Mumbai") never changes, and every miss costs a billable scrape,
# so resolutions are remembered for the life of the process. Cleared wholesale rather
# than evicted one by one: the map is tiny and correctness does not depend on it.
_city_cache: dict[str, tuple[str, str]] = {}
_CITY_CACHE_MAX = 512


async def _resolve_city(settings: Settings, city: str) -> tuple[str, str]:
    """Return `(city_id, canonical_name)` for a city name."""
    key = city.casefold()
    cached = _city_cache.get(key)
    if cached is not None:
        return cached

    payload = await _call_parsebot(
        settings, "get_city_suggestions", {"query": city, "limit": "5"}
    )
    match = _pick_city(payload)
    if match is None:
        raise NotFoundError(f"No city matching '{city}' was found.")

    if len(_city_cache) >= _CITY_CACHE_MAX:
        _city_cache.clear()
    _city_cache[key] = match
    return match


def _pick_city(payload: Any) -> tuple[str, str] | None:
    """Choose the best suggestion out of get_city_suggestions.

    The payload is wrapped in `data`, `ID` arrives as an int (converted to a string
    here), and the display name field is `Name` (capital N) -- all confirmed against
    a real response. The top result is used as the best match -- unlike hotels'
    autocomplete, this endpoint returns cities only, with no type to filter by.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    docs = data.get("docs")
    if not isinstance(docs, list):
        return None

    for item in docs:
        if not isinstance(item, dict):
            continue
        city_id = item.get("ID")
        name = item.get("Name")
        if city_id is None or city_id == "" or not isinstance(name, str) or not name.strip():
            continue
        return str(city_id), name.strip()
    return None


# --------------------------------------------------------------------------------------
# Step 2: build the query the scraper expects
# --------------------------------------------------------------------------------------


def _build_query_params(
    search: BusSearchRequest, origin_id: str, destination_id: str
) -> dict[str, str]:
    return {
        "from_city_id": origin_id,
        "to_city_id": destination_id,
        "doj": _format_doj(search.departure_date),
    }


def _format_doj(value: date) -> str:
    # strftime's "%b" is locale-dependent; the server's locale is not guaranteed to be
    # English, and parse.bot's example ("26-Jun-2026") is. Built by hand to be sure.
    months = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )  # fmt: skip
    return f"{value.day:02d}-{months[value.month - 1]}-{value.year}"


# --------------------------------------------------------------------------------------
# Step 3: call parse.bot
# --------------------------------------------------------------------------------------


async def _call_parsebot(
    settings: Settings, operation: str, params: dict[str, str]
) -> Any:
    """GET one redbus scraper operation. All of its operations share this envelope."""
    return await call_parsebot(
        settings,
        settings.parsebot_redbus_scraper_id,
        operation,
        params,
        label="Bus search",
    )


# --------------------------------------------------------------------------------------
# Step 4: turn the scraped rows into our Bus list
# --------------------------------------------------------------------------------------


def map_parsebot_buses(payload: Any) -> list[Bus]:
    """Map a raw search_buses response into Bus objects.

    The payload is wrapped in `data`, confirmed against a real response.

    Order is preserved: the source ranks buses by its own relevance, which is more
    useful than a raw price sort.

    A single unusable row is skipped rather than failing the whole search: a partial
    list of buses is far more useful to a traveller than an error.
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    raw_buses = data.get("inventories")
    if not isinstance(raw_buses, list):
        return []

    buses: list[Bus] = []
    skipped = 0
    for raw in raw_buses:
        bus = _map_bus(raw) if isinstance(raw, dict) else None
        if bus is None:
            skipped += 1
        else:
            buses.append(bus)

    if skipped:
        logger.info("Skipped %s unmappable bus(es) from parse.bot", skipped)
    return buses


def _map_bus(raw: dict[str, Any]) -> Bus | None:
    route_id = raw.get("routeId")
    travels_name = raw.get("travelsName")
    if route_id is None or route_id == "":
        return None
    if not isinstance(travels_name, str) or not travels_name.strip():
        return None

    operator_id = raw.get("operatorId")

    return Bus(
        route_id=str(route_id),
        operator_id=str(operator_id) if operator_id not in (None, "") else None,
        travels_name=travels_name.strip(),
        bus_type=_clean_text(raw.get("busType")),
        departure_time=_parse_datetime(raw.get("departureTime")),
        arrival_time=_parse_datetime(raw.get("arrivalTime")),
        duration_minutes=_parse_int(raw.get("journeyDurationMin")),
        available_seats=_parse_int(raw.get("availableSeats")),
        fare=_parse_fare(raw.get("fareList")),
        rating=_parse_rating(raw.get("totalRatings")),
    )


# --------------------------------------------------------------------------------------
# Small parsing helpers
# --------------------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"[\d.]+")


def _parse_fare(value: Any) -> Decimal | None:
    """`fareList` is a list with one price per seat class; the lowest is the number a
    traveller comparing buses wants first."""
    if not isinstance(value, list):
        return None
    candidates = [
        parsed for parsed in (_parse_decimal(item) for item in value) if parsed is not None
    ]
    return min(candidates) if candidates else None


def _parse_datetime(value: Any) -> datetime | None:
    """`departureTime`/`arrivalTime` are naive local datetimes ("2026-09-18 08:15:00").
    Kept as sent rather than coerced, so no timezone is invented."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        match = _DIGITS_RE.search(value)
        if match is None:
            return None
        try:
            return Decimal(match.group())
        except InvalidOperation:
            return None
    return None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_rating(value: Any) -> float | None:
    """redBus's `totalRatings` is out of 5, unlike hotels.com's out of 10."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rating = float(value)
    elif isinstance(value, str):
        try:
            rating = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return rating if 0 <= rating <= 5 else None


def _clean_text(value: Any) -> str | None:
    """Empty strings are the scraper's way of saying "nothing here"; make that a None."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None
