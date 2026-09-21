from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Dimension of Gemini's "models/text-embedding-004", pinned explicitly (rather than
# trusting the provider's default) so the column width can never silently drift out
# from under a fixed-size vector column.
EMBEDDING_DIM = 768


class DocumentChunk(Base):
    """One chunk of a policy document, embedded for similarity search.

    `domain` tags which area a chunk belongs to (e.g. "bus", "hotel", "flight") --
    each area owns its own ingestion and its own policy-search tool, scoped to its
    own domain, the same way flight/hotel/bus search are already separate services.
    `source` is the document a chunk came from (e.g. a filename), so an answer can
    cite which policy it's quoting.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_document_chunks_domain", "domain"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    chunk_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
