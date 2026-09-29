from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.user import User
from app.repositories import conversation_repository, message_repository
from app.schemas.chat import ChatMessageOut, ChatRequest, ConversationOut
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/conversations")
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationOut]:
    """The current user's conversations, most recent first -- for a sidebar."""
    conversations = conversation_repository.list_for_user(db, current_user.id)
    return [ConversationOut(id=c.id, title=c.title) for c in conversations]


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ChatMessageOut]:
    """A conversation's messages in order -- for reopening it in the UI."""
    conversation = conversation_repository.get(db, conversation_id, current_user.id)
    if conversation is None:
        raise NotFoundError(f"Conversation {conversation_id} was not found.")

    messages = message_repository.list_for_conversation(db, conversation.id)
    return [
        ChatMessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
        for m in messages
    ]


@router.post("/")
def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Send a chat message and stream the assistant's reply as Server-Sent Events.

    Resolving/creating the conversation happens here, before the stream starts: once
    streaming begins the HTTP status is already committed, so a bad conversation_id
    must 404 before that point, not inside the generator.
    """
    conversation = chat_service.resolve_conversation(
        db, current_user, payload.conversation_id, payload.message
    )

    return StreamingResponse(
        chat_service.stream_chat(get_settings(), db, conversation, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
