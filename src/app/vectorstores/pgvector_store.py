"""Similarity search over `document_chunks`, scoped by domain.

A plain module of functions taking a `Session`, not a class -- there is nothing
stateful here, and it mirrors how `services/*.py` are plain functions rather than
objects. Each domain's policy tool (e.g. `tools/bus_policy_tool.py`) calls `search`
pinned to its own `domain`, so a bus question never surfaces a hotel policy chunk.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk


@dataclass
class ScoredChunk:
    content: str
    source: str
    distance: float


def add_chunks(
    db: Session,
    *,
    domain: str,
    source: str,
    contents: list[str],
    embeddings: list[list[float]],
) -> None:
    """Insert one embedded row per chunk. Caller commits."""
    if len(contents) != len(embeddings):
        raise ValueError("contents and embeddings must be the same length")

    db.add_all(
        DocumentChunk(domain=domain, source=source, content=content, embedding=embedding)
        for content, embedding in zip(contents, embeddings, strict=True)
    )


def search(
    db: Session,
    *,
    domain: str,
    query_embedding: list[float],
    k: int = 5,
) -> list[ScoredChunk]:
    """Return the `k` chunks in `domain` closest to `query_embedding`, nearest first."""
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    rows = db.execute(
        select(DocumentChunk.content, DocumentChunk.source, distance.label("distance"))
        .where(DocumentChunk.domain == domain)
        .order_by(distance)
        .limit(k)
    ).all()
    return [ScoredChunk(content=row.content, source=row.source, distance=row.distance) for row in rows]
