"""Flight search against the Duffel API.

Read this file top to bottom: `search_flights` is the whole story, and everything
below it is one of the three steps it names.

This is a plain async function rather than anything tied to FastAPI, so it can be
called directly from a route today and from a LangGraph/LangChain tool later, without
the agent having to make an HTTP call back into our own API.
"""

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import UpstreamError, UpstreamTimeoutError
from app.schemas.flight import FlightOffer, FlightSearchRequest, FlightSegment

logger = logging.getLogger(__name__)


async def search_flights(
    settings: Settings, search: FlightSearchRequest
) -> list[FlightOffer]:
    """Search one-way flights and return them cheapest first."""
    payload = await _call_duffel(settings, _build_request_body(search))
    offers = map_duffel_offers(payload)
    return sorted(offers, key=lambda offer: offer.total_amount)


# --------------------------------------------------------------------------------------
# Step 1: build the request Duffel expects
# --------------------------------------------------------------------------------------


def _build_request_body(search: FlightSearchRequest) -> dict[str, Any]:
    return {
        "data": {
            "slices": [
                {
                    "origin": search.origin,
                    "destination": search.destination,
                    "departure_date": search.departure_date.isoformat(),
                }
            ],
            # Duffel wants one entry per traveller, not a count.
            "passengers": [{"type": "adult"} for _ in range(search.adults)],
        }
    }


# --------------------------------------------------------------------------------------
# Step 2: call Duffel
# --------------------------------------------------------------------------------------


async def _call_duffel(settings: Settings, body: dict[str, Any]) -> Any:
    if settings.duffel_api_key is None or not settings.duffel_api_key.get_secret_value().strip():
        raise UpstreamError("Flight search is not configured (DUFFEL_API_KEY is missing).")

    url = f"{settings.duffel_api_url.rstrip('/')}/air/offer_requests"
    headers = {
        "Authorization": f"Bearer {settings.duffel_api_key.get_secret_value()}",
        "Duffel-Version": settings.duffel_api_version,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.duffel_timeout_seconds) as client:
            response = await client.post(
                url, params={"return_offers": "true"}, json=body, headers=headers
            )
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError("Flight search timed out. Please try again.") from exc
    except httpx.RequestError as exc:
        logger.warning("Duffel request failed: %s", type(exc).__name__)
        raise UpstreamError("Flight search is temporarily unavailable.") from exc

    if response.is_error:
        # Log the status only. The response body is not logged because some error paths
        # echo request headers back, and our API key lives in a header.
        logger.warning(
            "Duffel returned HTTP %s (request id: %s)",
            response.status_code,
            response.headers.get("x-request-id", "unknown"),
        )
        raise UpstreamError("Flight search is temporarily unavailable.")

    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError("Flight search returned an unreadable response.") from exc


# --------------------------------------------------------------------------------------
# Step 3: turn Duffel's very large response into our small FlightOffer list
# --------------------------------------------------------------------------------------


def map_duffel_offers(payload: Any) -> list[FlightOffer]:
    """Map a raw Duffel offer-request response into FlightOffer objects.

    A single unusable offer is skipped rather than failing the whole search: a partial
    list of flights is far more useful to a traveller than an error.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return []
    raw_offers = payload["data"].get("offers")
    if not isinstance(raw_offers, list):
        return []

    offers: list[FlightOffer] = []
    skipped = 0
    for raw in raw_offers:
        offer = _map_offer(raw) if isinstance(raw, dict) else None
        if offer is None:
            skipped += 1
        else:
            offers.append(offer)

    if skipped:
        logger.info("Skipped %s unmappable offer(s) from Duffel", skipped)
    return offers


def _map_offer(raw: dict[str, Any]) -> FlightOffer | None:
    offer_id = raw.get("id")
    slices = raw.get("slices")
    if not isinstance(offer_id, str) or not isinstance(slices, list) or not slices:
        return None

    # A one-way search produces exactly one slice, which is all this endpoint asks for.
    # Round trips will need this generalised to a list of slices.
    first_slice = slices[0]
    if not isinstance(first_slice, dict) or not isinstance(first_slice.get("segments"), list):
        return None

    segments = [
        segment
        for segment in (
            _map_segment(item) for item in first_slice["segments"] if isinstance(item, dict)
        )
        if segment is not None
    ]
    if not segments:
        return None

    total_amount = _parse_decimal(raw.get("total_amount"))
    currency = raw.get("total_currency")
    if total_amount is None or not isinstance(currency, str) or not currency:
        return None

    owner = raw["owner"] if isinstance(raw.get("owner"), dict) else {}

    return FlightOffer(
        offer_id=offer_id,
        airline_name=owner.get("name"),
        airline_code=owner.get("iata_code"),
        total_amount=total_amount,
        currency=currency,
        departure_at=segments[0].departure_at,
        arrival_at=segments[-1].arrival_at,
        duration_minutes=_parse_duration_minutes(first_slice.get("duration")),
        stops=len(segments) - 1,
        segments=segments,
        expires_at=_parse_datetime(raw.get("expires_at")),
    )


def _map_segment(raw: dict[str, Any]) -> FlightSegment | None:
    origin = raw["origin"] if isinstance(raw.get("origin"), dict) else {}
    destination = raw["destination"] if isinstance(raw.get("destination"), dict) else {}
    departure_at = _parse_datetime(raw.get("departing_at"))
    arrival_at = _parse_datetime(raw.get("arriving_at"))

    if (
        not isinstance(origin.get("iata_code"), str)
        or not isinstance(destination.get("iata_code"), str)
        or departure_at is None
        or arrival_at is None
    ):
        return None

    # The marketing carrier is the airline the ticket is sold under, which is what a
    # traveller recognises. On codeshares the operating carrier differs and its flight
    # number is sometimes null.
    carrier = raw["marketing_carrier"] if isinstance(raw.get("marketing_carrier"), dict) else {}

    return FlightSegment(
        origin=origin["iata_code"],
        destination=destination["iata_code"],
        departure_at=departure_at,
        arrival_at=arrival_at,
        carrier_code=carrier.get("iata_code"),
        carrier_name=carrier.get("name"),
        flight_number=raw.get("marketing_carrier_flight_number"),
        duration_minutes=_parse_duration_minutes(raw.get("duration")),
    )


# --------------------------------------------------------------------------------------
# Small parsing helpers
# --------------------------------------------------------------------------------------

# Duffel reports durations as ISO 8601 durations, e.g. "PT2H35M". Python has no built-in
# parser for these, so we handle the day/hour/minute/second subset Duffel actually sends.
_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _parse_duration_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _ISO_DURATION_RE.match(value)
    if match is None:
        return None
    parts = match.groupdict()
    return (
        int(parts["days"] or 0) * 1440
        + int(parts["hours"] or 0) * 60
        + int(parts["minutes"] or 0)
        + int(float(parts["seconds"] or 0) // 60)
    )


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a Duffel timestamp.

    Segment times arrive with no UTC offset ("2026-09-15T10:50:00") and are local to the
    airport, while `expires_at` is UTC with a trailing "Z". Both are kept as sent rather
    than coerced, so no timezone is invented.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    if not isinstance(value, (str, int)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
