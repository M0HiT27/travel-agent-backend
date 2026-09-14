"""The LangGraph agent.

`create_react_agent` builds the whole loop for us: send the question to Gemini, let it
pick a tool, run the tool, feed the result back, repeat until it has an answer.

Two pieces are wired in around that loop:

- a **checkpointer**, which saves each conversation in Postgres so a follow-up question
  ("what about 20 hours?") can see what came before. HTTP is stateless, so without this
  every request would start from nothing.
- a **pre_model_hook**, which trims that history before each call so a long conversation
  does not keep getting more expensive.
"""

from collections.abc import AsyncGenerator
from datetime import date

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import create_react_agent

from app.ai.history import trim_history
from app.ai.tools import ALL_TOOLS, label_for_tool
from app.core.config import Settings

SYSTEM_PROMPT = """You are a travel assistant for an airline booking service.

You have two tools:
- search_travel_policies: for questions about rules, cancellation, refunds, fees.
- search_flight_offers: for finding actual flights between two airports.

Rules:
- Answer policy questions ONLY from what search_travel_policies returns. Never invent a
  fee, percentage, or timeframe. If the documents do not cover it, say so plainly.
- Quote the specific numbers from the policy when they are relevant.
- For flight searches, convert city names to IATA codes yourself (Delhi = DEL,
  Mumbai = BOM, Goa = GOI, Bangalore = BLR). Ask the user if a city is ambiguous.
- Today's date is {today}. Use it to resolve phrases like "next Friday".
- Earlier messages are the same conversation. Resolve follow-up questions against them.
- Be brief and direct. No filler openings.
"""


def _trim_before_model(state: dict) -> dict:
    """Runs before every model call.

    Returning `llm_input_messages` rather than `messages` is the important part: it
    changes what this one call receives without editing the saved conversation.
    """
    return {"llm_input_messages": trim_history(state["messages"])}


def build_agent(settings: Settings, checkpointer: AsyncPostgresSaver | None):
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value().strip():
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    # No temperature is set: the gemini-3.x flash models use fixed sampling and warn
    # loudly on every call if one is passed. Grounding the answers in retrieved text is
    # what keeps them consistent here, not the sampling setting.
    model = ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.gemini_api_key,
    )

    return create_react_agent(
        model,
        ALL_TOOLS,
        prompt=SYSTEM_PROMPT.format(today=date.today().isoformat()),
        pre_model_hook=_trim_before_model,
        checkpointer=checkpointer,
    )


def _as_text(content: object) -> str:
    """Flatten a message's content into plain text.

    LangChain v1 returns a list of typed blocks (text, reasoning, tool calls) rather
    than a bare string, so pull out the text blocks and drop the rest.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        ]
        return "\n".join(parts).strip()
    return str(content)


async def ask(agent, question: str, conversation_id: str) -> str:
    """Ask a question within a conversation and return the answer as plain text.

    `conversation_id` is the drawer the history is filed under: the same id continues a
    conversation, a new id starts a fresh one.
    """
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": conversation_id}},
    )
    return _as_text(result["messages"][-1].content)


def _chunk_text(message: object) -> str:
    """The user-facing text of one streamed chunk, or "" if it carries none.

    Only the assistant's own words qualify. The `messages` stream also carries tool
    results — the retrieved policy chunks, the raw flight listing — and streaming those
    to the user would dump the search results into the chat instead of the answer.
    Chunks that merely request a tool have no text content and contribute nothing.
    """
    if not isinstance(message, AIMessage):
        return ""
    content = getattr(message, "content", None)
    if not content:
        return ""
    # Deliberately not `_as_text`, which strips: correct for a whole message, wrong for
    # a fragment. A chunk ending "returned " followed by one starting "to" needs that
    # space, or the words fuse into "returnedto". Text blocks inside one chunk are
    # pieces of the same run of text, so they join with nothing in between.
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        )
    return ""


def _tool_events(update: dict) -> list[dict]:
    """Turn one graph update into tool_start / tool_end events.

    Detected from the message types rather than the node names, which are an internal
    detail of `create_react_agent` and could change between versions.
    """
    events: list[dict] = []
    for node_state in update.values():
        if not isinstance(node_state, dict):
            continue
        for message in node_state.get("messages", []):
            if isinstance(message, AIMessage) and message.tool_calls:
                events.extend(
                    {
                        "event": "tool_start",
                        "tool": call["name"],
                        "label": label_for_tool(call["name"]),
                    }
                    for call in message.tool_calls
                )
            elif isinstance(message, ToolMessage):
                event: dict = {"event": "tool_end", "tool": message.name or ""}
                # Structured data for the screen — flight offers, the documents a
                # policy answer came from — rides on the same event. Gemini only ever
                # saw the text content; this part exists for the UI.
                if message.artifact is not None:
                    event["result"] = message.artifact
                events.append(event)
    return events


async def ask_streaming(
    agent, question: str, conversation_id: str
) -> AsyncGenerator[dict]:
    """Ask a question, yielding events as the answer is produced.

    Same conversation, same memory and same tools as `ask()` — only the delivery
    differs. `ask()` is left in place for callers that want the whole answer at once:
    the tests, and any future MCP server.
    """
    answer_parts: list[str] = []

    async for mode, chunk in agent.astream(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": conversation_id}},
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            message, _metadata = chunk
            text = _chunk_text(message)
            if text:
                answer_parts.append(text)
                yield {"event": "token", "delta": text}

        elif mode == "updates":
            for event in _tool_events(chunk):
                # Anything said before a tool ran was the model thinking aloud, not
                # the answer. Only text after the last tool call belongs in `answer`.
                if event["event"] == "tool_start":
                    answer_parts.clear()
                yield event

    yield {
        "event": "done",
        "conversation_id": conversation_id,
        "answer": "".join(answer_parts).strip(),
    }


async def load_history(agent, conversation_id: str) -> list[AnyMessage]:
    """Every message stored for a conversation, untrimmed — for the UI to display."""
    state = await agent.aget_state({"configurable": {"thread_id": conversation_id}})
    return state.values.get("messages", []) if state.values else []
