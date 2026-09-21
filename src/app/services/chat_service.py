"""Runs one chat turn through the LangGraph agent and streams it as SSE.

Persistence (loading history, saving the turn) lives here rather than in the graph or
the route: the graph only ever sees `BaseMessage` objects, and the route only ever
sees text/JSON lines, so which store backs "conversation history" can change without
touching either.
"""

import json
import logging
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.graphs.travel_chat import build_agent
from app.models.conversation import Conversation
from app.models.user import User
from app.repositories import conversation_repository, message_repository
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

_ROLE_TO_MESSAGE_CLS = {"user": HumanMessage, "assistant": AIMessage}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def resolve_conversation(db: Session, user: User, conversation_id: int | None) -> Conversation:
    """Look up or create the conversation. Called from the route, before the
    streaming response starts -- once streaming begins, the HTTP status is already
    committed and a raised NotFoundError can no longer become a real 404."""
    if conversation_id is None:
        conversation = conversation_repository.create(db, user_id=user.id)
        db.commit()
        return conversation

    conversation = conversation_repository.get(db, conversation_id, user.id)
    if conversation is None:
        raise NotFoundError(f"Conversation {conversation_id} was not found.")
    return conversation


async def stream_chat(
    settings: Settings, db: Session, conversation: Conversation, request: ChatRequest
) -> AsyncIterator[str]:
    history = message_repository.list_for_conversation(db, conversation.id)
    langchain_history = [
        _ROLE_TO_MESSAGE_CLS[m.role](content=m.content)
        for m in history
        if m.role in _ROLE_TO_MESSAGE_CLS
    ]

    message_repository.add(db, conversation.id, "user", request.message)
    db.commit()

    yield _sse("conversation", {"conversation_id": conversation.id})

    agent = build_agent(settings, db)
    messages = [*langchain_history, HumanMessage(content=request.message)]

    final_answer_parts: list[str] = []
    try:
        async for event in agent.astream_events({"messages": messages}, version="v2"):
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                content = getattr(chunk, "content", None) if chunk is not None else None
                if content:
                    final_answer_parts.append(content)
                    yield _sse("token", {"content": content})

            elif kind == "on_tool_start":
                yield _sse(
                    "tool_start",
                    {"tool": event.get("name"), "input": event.get("data", {}).get("input")},
                )

            elif kind == "on_tool_end":
                yield _sse("tool_end", {"tool": event.get("name")})
    except Exception:
        logger.exception("Chat agent run failed for conversation %s", conversation.id)
        yield _sse("error", {"detail": "The assistant hit an error. Please try again."})
        db.rollback()
        return

    final_answer = "".join(final_answer_parts).strip()
    if final_answer:
        message_repository.add(db, conversation.id, "assistant", final_answer)
        db.commit()

    yield _sse("done", {})
