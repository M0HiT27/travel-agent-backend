"""Shared parse.bot HTTP client.

Every parse.bot-backed service (hotels, buses, ...) makes the same call: GET one
scraper operation, with the same auth header, timeout and error envelope. Pulled out
here once a second caller (bus_service) made the duplication real rather than
hypothetical.
"""

import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import UpstreamError, UpstreamTimeoutError

logger = logging.getLogger(__name__)


async def call_parsebot(
    settings: Settings,
    scraper_id: str,
    operation: str,
    params: dict[str, str],
    *,
    label: str,
) -> Any:
    """GET one scraper operation.

    `label` names the feature in error/log messages (e.g. "Hotel search", "Bus
    search"), so a caller's error messages read naturally without this module
    knowing what it's being used for.
    """
    if (
        settings.parsebot_api_key is None
        or not settings.parsebot_api_key.get_secret_value().strip()
    ):
        raise UpstreamError(f"{label} is not configured (PARSEBOT_API_KEY is missing).")

    url = f"{settings.parsebot_api_url.rstrip('/')}/scraper/{scraper_id}/{operation}"
    headers = {
        "x-api-key": settings.parsebot_api_key.get_secret_value(),
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.parsebot_timeout_seconds) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError(f"{label} timed out. Please try again.") from exc
    except httpx.RequestError as exc:
        logger.warning("parse.bot request failed: %s", type(exc).__name__)
        raise UpstreamError(f"{label} is temporarily unavailable.") from exc

    if response.is_error:
        # Status only. The body is not logged because our API key travels in a header
        # and some error paths echo request headers back.
        logger.warning("parse.bot %s returned HTTP %s", operation, response.status_code)
        raise UpstreamError(f"{label} is temporarily unavailable.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(f"{label} returned an unreadable response.") from exc

    # A scrape can fail with HTTP 200 and status "error" in the envelope.
    if isinstance(payload, dict) and payload.get("status") not in (None, "success"):
        logger.warning("parse.bot %s reported status %r", operation, payload.get("status"))
        raise UpstreamError(f"{label} is temporarily unavailable.")

    return payload
