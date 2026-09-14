from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Conversation(Base):
    """Who owns a chat thread, and enough about it to list one in a sidebar.

    The messages themselves live in LangGraph's checkpoint tables, keyed by this row's
    `id` — so this `id` is the LangGraph thread id, and no mapping table is needed.

    Those checkpoint tables have no foreign key back here, so deleting a row does not
    delete its messages. Both have to be removed together.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Sorted on for "most recent first", so it is updated on every message, not just
    # when the conversation is created.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped["User"] = relationship()
