"""create conversations table

Revision ID: 9ffa574cc1b4
Revises: b4f09fba75f6
Create Date: 2026-09-09 11:43:53.903982

Autogenerate also proposed dropping the langchain_pg_* and checkpoint_* tables, because
those are created and owned by LangChain/LangGraph rather than by our models. Running
that would have destroyed the vector store and every saved conversation, so the drops
were removed by hand and alembic/env.py now filters those tables out of autogenerate.

The proposed index changes on `roles` and `users` were also dropped: they are cosmetic
churn from the original migration declaring both a unique constraint and an index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9ffa574cc1b4"
down_revision: Union[str, Sequence[str], None] = "b4f09fba75f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_last_message_at"),
        "conversations",
        ["last_message_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_last_message_at"), table_name="conversations")
    op.drop_table("conversations")
