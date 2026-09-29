from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation


def get(db: Session, conversation_id: int, user_id: int) -> Conversation | None:
    """Return the conversation only if it belongs to `user_id` -- never another user's."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        return None
    return conversation


def list_for_user(db: Session, user_id: int) -> list[Conversation]:
    """Most recently created first -- the order a sidebar wants them in.

    Ordered by id rather than `created_at`: ids are monotonically increasing
    with creation order but don't suffer from timestamp column resolution
    (e.g. SQLite's is only to the second, which can tie two rows).
    """
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.id.desc())
        )
    )


def create(db: Session, user_id: int, title: str | None = None) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    db.flush()
    return conversation
