"""The chat agent: one chat model, bound to the current list of domain tools.

This is the shared surface a colleague plugs into: add your own `make_*_tool(...)`
from `app/tools/`, append it to `_build_tools`, and it's available in the same chat
without touching persistence, the route, or the LLM factory.
"""

from datetime import date

from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm.factory import get_chat_model
from app.tools.bus_policy_tool import make_bus_policy_tool
from app.tools.bus_search_tool import make_bus_search_tool

_SYSTEM_PROMPT = """You are the TravelAgent assistant. You help travellers find bus \
routes and answer questions about bus travel policy (cancellations, refunds, \
luggage, boarding, etc.).

Today's date is {today}. When the user gives a relative date (e.g. "next Friday", \
"tomorrow"), resolve it to an absolute date yourself before calling a tool.

Use `search_buses` to find actual bus routes and schedules. Use `search_bus_policy` \
for questions about rules, refunds, cancellations, luggage or similar -- never guess \
policy answers yourself. If a city name is ambiguous or a search returns nothing \
useful, ask the user to clarify rather than guessing."""


def _build_tools(settings: Settings, db: Session) -> list:
    return [
        make_bus_search_tool(settings),
        make_bus_policy_tool(settings, db),
    ]


def build_agent(settings: Settings, db: Session) -> CompiledStateGraph:
    """Build a fresh agent bound to this request's DB session and configured LLM."""
    model = get_chat_model(settings)
    tools = _build_tools(settings, db)
    prompt = _SYSTEM_PROMPT.format(today=date.today().isoformat())
    return create_react_agent(model, tools, prompt=prompt)
