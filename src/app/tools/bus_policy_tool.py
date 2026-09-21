"""LangChain tool for bus policy questions (cancellation, refunds, luggage, ...).

Pinned to `domain="bus"` -- a colleague adding hotel or flight policy support later
writes their own `hotel_policy_tool.py`/`flight_policy_tool.py` the same way, each
pinned to their own domain, rather than one tool guessing which domain to search.
"""

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from langchain_core.tools import StructuredTool

from app.core.config import Settings
from app.llm.embeddings import get_embeddings
from app.vectorstores.pgvector_store import search

_DOMAIN = "bus"
_TOP_K = 4


class PolicySearchArgs(BaseModel):
    query: str = Field(description="The policy question to search for, in plain language.")


def make_bus_policy_tool(settings: Settings, db: Session) -> StructuredTool:
    async def run(query: str) -> str:
        query_embedding = get_embeddings(settings).embed_query(query)
        chunks = search(db, domain=_DOMAIN, query_embedding=query_embedding, k=_TOP_K)

        if not chunks:
            return "No bus policy information was found for that question."

        parts = [f"[{chunk.source}] {chunk.content}" for chunk in chunks]
        return "\n\n".join(parts)

    return StructuredTool.from_function(
        coroutine=run,
        name="search_bus_policy",
        description=(
            "Search the bus travel policy documents (cancellation, refunds, "
            "rescheduling, luggage, boarding, pets, delays) for an answer to a "
            "policy question. Not for searching actual bus routes or schedules."
        ),
        args_schema=PolicySearchArgs,
    )
