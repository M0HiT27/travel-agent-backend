import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from langchain_google_genai.chat_models import GoogleRateLimitError
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.graph import ask, ask_streaming, load_history
from app.api.deps import get_current_user
from app.core.exceptions import NotFoundError, RateLimitedError, UpstreamError
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationDetailOut,
    ConversationOut,
    MessageOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

TITLE_MAX_LENGTH = 120


def get_agent(request: Request):
    """The agent built at startup, with its database-backed conversation memory."""
    return request.app.state.agent


def _own_conversation(conversation_id: str, user: User, db: Session) -> Conversation:
    """Fetch a conversation, or refuse if it is not this user's.

    Someone else's conversation is reported as 404 rather than 403 on purpose: a 403
    would confirm that a conversation with that id exists.
    """
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    if conversation is None:
        raise NotFoundError("Conversation not found")
    return conversation


def _make_title(question: str) -> str:
    """Name the conversation after its opening question.

    Deliberately not asked of the model: a nicer title is not worth an extra request
    against the rate limit for something purely cosmetic.
    """
    title = " ".join(question.split())
    if len(title) > TITLE_MAX_LENGTH:
        title = title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title


@router.post("/ask", response_model=ChatResponse)
async def ask_question(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent=Depends(get_agent),
) -> ChatResponse:
    """Ask the travel assistant a question.

    The agent decides for itself whether to search the policy documents or look up real
    flights — there is no routing logic here.

    Omit `conversation_id` to start fresh; send back the one you were given to continue,
    and follow-ups like "what about 20 hours?" will resolve against what came before.
    """
    if payload.conversation_id:
        conversation = _own_conversation(payload.conversation_id, current_user, db)
    else:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            title=_make_title(payload.question),
        )
        db.add(conversation)

    try:
        answer = await ask(agent, payload.question, conversation.id)
    except GoogleRateLimitError as exc:
        # The Gemini free tier allows only a few requests per minute. Worth its own
        # status code: the caller should wait and retry, not conclude we are broken.
        logger.warning("Gemini rate limit reached")
        raise RateLimitedError(
            "The assistant is busy (AI rate limit reached). Please try again in a minute."
        ) from exc
    except Exception as exc:
        # The model or a tool failed. Log the type only: prompts and tool output can
        # contain user data, and the Gemini key travels with the client.
        logger.exception("Agent failed to answer", exc_info=exc)
        raise UpstreamError("The assistant is temporarily unavailable.") from exc

    conversation.last_message_at = datetime.now(timezone.utc)
    db.commit()

    return ChatResponse(answer=answer, conversation_id=conversation.id)


def _sse(payload: dict) -> str:
    """Format one dict as a server-sent event.

    The event name is duplicated inside the JSON so a client reading the raw body — the
    fetch reader the frontend uses — does not have to parse SSE field lines.
    """
    return f"event: {payload['event']}\ndata: {json.dumps(payload)}\n\n"


@router.post("/stream")
async def ask_question_streaming(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent=Depends(get_agent),
) -> StreamingResponse:
    """The same answer as POST /chat/ask, delivered as it is produced.

    `/chat/ask` is unchanged and still available — it is what the tests and any
    non-streaming client use. The ownership rules here are identical: the check runs
    before the response starts, so an unauthorised request still fails as a clean 404.
    """
    if payload.conversation_id:
        conversation = _own_conversation(payload.conversation_id, current_user, db)
    else:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            title=_make_title(payload.question),
        )
        db.add(conversation)

    conversation_id = conversation.id

    async def events() -> AsyncGenerator[str]:
        try:
            async for event in ask_streaming(agent, payload.question, conversation_id):
                yield _sse(event)
        except GoogleRateLimitError:
            logger.warning("Gemini rate limit reached")
            yield _sse(
                {
                    "event": "error",
                    "status": 429,
                    "detail": (
                        "The assistant is busy (AI rate limit reached). "
                        "Please try again in a minute."
                    ),
                }
            )
            return
        except Exception as exc:
            logger.exception("Agent failed while streaming", exc_info=exc)
            yield _sse(
                {
                    "event": "error",
                    "status": 502,
                    "detail": "The assistant is temporarily unavailable.",
                }
            )
            return

        # Only on success. A conversation that produced no answer should not jump to
        # the top of the user's list.
        conversation.last_message_at = datetime.now(timezone.utc)
        db.commit()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells a reverse proxy not to buffer, which would collect the whole
            # answer and defeat the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Conversation]:
    """This user's conversations, most recently used first."""
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.last_message_at.desc())
        )
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailOut,
    # Leaves `attachments` off answers that have none, rather than sending
    # `"attachments": null` on every message.
    response_model_exclude_none=True,
)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent=Depends(get_agent),
) -> ConversationDetailOut:
    """One conversation with its full message history, for replaying it in the UI.

    The history is untrimmed — trimming only ever applied to what was sent to the model.
    Flight cards and cited sources come back attached to the answer they belong to.
    """
    conversation = _own_conversation(conversation_id, current_user, db)
    stored = await load_history(agent, conversation_id)

    messages: list[MessageOut] = []
    # A tool's structured result is saved on its tool message, which sits between a
    # question and the answer that used it. Hold it until that answer arrives.
    pending: list[dict] = []
    for message in stored:
        if isinstance(message, HumanMessage):
            pending = []
            messages.append(MessageOut(role="user", content=message.text))
        elif message.type == "tool":
            # The tool's raw output stays hidden; only its structured data is kept.
            artifact = getattr(message, "artifact", None)
            if isinstance(artifact, dict):
                pending.append(artifact)
        elif isinstance(message, AIMessage) and not message.tool_calls:
            messages.append(
                MessageOut(
                    role="assistant", content=message.text, attachments=pending or None
                )
            )
            pending = []
        # An assistant message that only requested a tool is an internal step: skipped.

    return ConversationDetailOut(
        **ConversationOut.model_validate(conversation).model_dump(), messages=messages
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent=Depends(get_agent),
) -> Response:
    """Delete a conversation and the messages behind it.

    Both halves matter: LangGraph's checkpoint tables have no foreign key to ours, so
    dropping only our row would strand the messages where nothing can reach them.
    """
    conversation = _own_conversation(conversation_id, current_user, db)

    await agent.checkpointer.adelete_thread(conversation_id)
    db.delete(conversation)
    db.commit()

    return Response(status_code=204)
