from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.message import Message


def list_for_conversation(db: Session, conversation_id: int) -> list[Message]:
    return list(
        db.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
        )
    )


def add(db: Session, conversation_id: int, role: str, content: str) -> Message:
    message = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(message)
    db.flush()
    return message
