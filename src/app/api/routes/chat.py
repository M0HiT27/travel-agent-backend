from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


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
    conversation = chat_service.resolve_conversation(db, current_user, payload.conversation_id)

    return StreamingResponse(
        chat_service.stream_chat(get_settings(), db, conversation, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
