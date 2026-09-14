"""The tools the agent can choose between.

Each tool is a thin wrapper around code that already exists. The agent decides which to
call from the user's question — there is no routing `if/else` anywhere in this project.

Every tool returns two things. The text is what Gemini reads and answers from. The
artifact is structured data for the screen — flight cards, the documents a policy answer
came from — which Gemini never sees. Keeping them apart means the UI shows real numbers
rather than whatever the model retyped, without changing what the model is given.

Adding a capability later (hotels, buses) means one function here, one entry in
ALL_TOOLS, and one label in TOOL_LABELS. Nothing else changes.
"""

import logging
from datetime import date

from langchain_core.tools import tool

from app.ai.vector_store import get_vector_store
from app.core.config import get_settings
from app.schemas.flight import FlightSearchRequest
from app.services.flight_service import search_flights

logger = logging.getLogger(__name__)

# How many chunks to feed the model. Enough to cover a clause plus its qualifier,
# few enough that the answer stays grounded rather than drowning in context.
POLICY_CHUNKS_TO_RETRIEVE = 4

# How many of the cheapest offers the model reads and the UI shows as cards.
FLIGHT_OFFERS_TO_SHOW = 5


@tool(response_format="content_and_artifact")
def search_travel_policies(question: str) -> tuple[str, dict | None]:
    """Look up airline policy documents (cancellation, refunds, no-shows, fees).

    Use this for any question about rules, charges, refunds, or terms — not for
    finding actual flights.
    """
    matches = get_vector_store().similarity_search(question, k=POLICY_CHUNKS_TO_RETRIEVE)
    if not matches:
        return "No policy documents matched that question.", None

    content = "\n\n---\n\n".join(
        f"[from {doc.metadata.get('source_file', 'unknown')}, "
        f"page {doc.metadata.get('page', '?')}]\n{doc.page_content}"
        for doc in matches
    )

    # Which file and page each passage came from, once each. Several chunks often come
    # from the same page, and listing it four times would read as four sources.
    sources: list[dict] = []
    seen: set[tuple] = set()
    for doc in matches:
        key = (doc.metadata.get("source_file", "unknown"), doc.metadata.get("page"))
        if key in seen:
            continue
        seen.add(key)
        sources.append({"file": key[0], "page": key[1]})

    return content, {"kind": "sources", "sources": sources}


@tool(response_format="content_and_artifact")
async def search_flight_offers(
    origin: str, destination: str, departure_date: str, adults: int = 1
) -> tuple[str, dict | None]:
    """Find real, bookable flights between two airports on a given date.

    origin and destination must be 3-letter IATA airport codes (Delhi is DEL, Goa is
    GOI, Mumbai is BOM). departure_date must be YYYY-MM-DD and cannot be in the past.
    Use this only for finding flights, not for policy questions.
    """
    try:
        request = FlightSearchRequest(
            origin=origin,
            destination=destination,
            departure_date=date.fromisoformat(departure_date),
            adults=adults,
        )
    except ValueError as exc:
        # Handed back to the model rather than raised, so it can correct itself and
        # retry instead of the whole conversation failing.
        return f"That search is not valid: {exc}", None

    offers = await search_flights(get_settings(), request)
    if not offers:
        return (
            f"No flights found from {request.origin} to {request.destination} on {departure_date}.",
            None,
        )

    shown = offers[:FLIGHT_OFFERS_TO_SHOW]
    lines = [
        f"{offer.airline_name or offer.airline_code}: {offer.total_amount} {offer.currency}, "
        f"departs {offer.departure_at:%H:%M}, arrives {offer.arrival_at:%H:%M}, "
        f"{'direct' if offer.stops == 0 else f'{offer.stops} stop(s)'}"
        for offer in shown
    ]
    content = f"Cheapest {len(lines)} of {len(offers)} offers:\n" + "\n".join(lines)

    # The same offers as data for cards. JSON-safe on purpose — the price stays an exact
    # string and times are ISO text — because this is saved with the conversation and
    # replayed when the chat is reopened.
    cards = [
        {
            "offer_id": offer.offer_id,
            "airline_name": offer.airline_name,
            "airline_code": offer.airline_code,
            "total_amount": str(offer.total_amount),
            "currency": offer.currency,
            "departure_at": offer.departure_at.isoformat(),
            "arrival_at": offer.arrival_at.isoformat(),
            "duration_minutes": offer.duration_minutes,
            "stops": offer.stops,
            "origin": offer.segments[0].origin if offer.segments else request.origin,
            "destination": (
                offer.segments[-1].destination if offer.segments else request.destination
            ),
        }
        for offer in shown
    ]

    return content, {"kind": "flights", "total_found": len(offers), "offers": cards}


ALL_TOOLS = [search_travel_policies, search_flight_offers]

# What to show a waiting user while a tool runs. Phrased by category rather than by
# document or provider, so adding a second policy PDF or a third flight source does not
# make the label wrong. A tool with no entry falls back to the generic phrase, so a new
# tool never shows a raw function name to a user.
TOOL_LABELS = {
    "search_travel_policies": "Searching policy documents",
    "search_flight_offers": "Checking flight details",
}
DEFAULT_TOOL_LABEL = "Looking that up"


def label_for_tool(tool_name: str) -> str:
    return TOOL_LABELS.get(tool_name, DEFAULT_TOOL_LABEL)
