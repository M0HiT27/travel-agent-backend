from sqlalchemy.orm import Session

from app.models.conversation import Conversation


def get(db: Session, conversation_id: int, user_id: int) -> Conversation | None:
    """Return the conversation only if it belongs to `user_id` -- never another user's."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        return None
    return conversation


def create(db: Session, user_id: int, title: str | None = None) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    db.flush()
    return conversation
