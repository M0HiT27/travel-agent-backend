"""LangChain tool wrapping the existing bus search.

`bus_service.search_buses` was already written to be called directly by a future
LangGraph tool (see its own docstring), so this is a thin wrapper: it turns the
model's extracted arguments into a `BusSearchRequest`, calls the service, and turns
the result into text the model can read. All city resolution, date formatting and the
actual parse.bot call happen inside `search_buses` itself -- nothing is duplicated
here.
"""

from langchain_core.tools import StructuredTool

from app.core.config import Settings
from app.core.exceptions import AppError
from app.schemas.bus import BusSearchRequest
from app.services.bus_service import search_buses


async def _run(origin: str, destination: str, departure_date, settings: Settings) -> str:
    try:
        result = await search_buses(
            settings,
            BusSearchRequest(origin=origin, destination=destination, departure_date=departure_date),
        )
    except AppError as exc:
        # Surfaced as a tool result, not an exception: the agent can react to it (e.g.
        # ask the user to spell the city differently) instead of the whole turn failing.
        return f"Bus search failed: {exc.message}"

    if not result.buses:
        return f"No buses found from {result.origin} to {result.destination} on {result.departure_date}."

    lines = [
        f"Buses from {result.origin} to {result.destination} on {result.departure_date}:",
    ]
    for bus in result.buses:
        fare = f"₹{bus.fare}" if bus.fare is not None else "fare unavailable"
        seats = f"{bus.available_seats} seats left" if bus.available_seats is not None else ""
        departure = bus.departure_time.strftime("%H:%M") if bus.departure_time else "?"
        arrival = bus.arrival_time.strftime("%H:%M") if bus.arrival_time else "?"
        lines.append(
            f"- {bus.travels_name} ({bus.bus_type or 'type unknown'}): "
            f"departs {departure}, arrives {arrival}, {fare}, {seats}".rstrip(", ")
        )
    return "\n".join(lines)


def make_bus_search_tool(settings: Settings) -> StructuredTool:
    async def run(origin: str, destination: str, departure_date) -> str:
        return await _run(origin, destination, departure_date, settings)

    return StructuredTool.from_function(
        coroutine=run,
        name="search_buses",
        description=(
            "Search for available buses between two Indian cities on a given date. "
            "origin and destination are city names (e.g. 'Mumbai', 'Pune'), not ids. "
            "departure_date must be resolved to an ISO date (YYYY-MM-DD) before calling."
        ),
        args_schema=BusSearchRequest,
    )
