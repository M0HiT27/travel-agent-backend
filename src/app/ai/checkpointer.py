"""The Postgres connection the agent's memory is saved through.

A checkpointer needs a live database connection for as long as the app runs, so it is
opened once at startup and closed at shutdown rather than per request.

Conversations are stored in tables LangGraph creates itself (`checkpoints`,
`checkpoint_writes`, ...), the same arrangement as PGVector — they are deliberately not
managed by Alembic.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings


def psycopg_dsn(database_url: str) -> str:
    """SQLAlchemy needs `postgresql+psycopg://`; psycopg itself rejects the `+psycopg`."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncGenerator[AsyncPostgresSaver]:
    """Open the pool, make sure the tables exist, and hand back the checkpointer."""
    async with AsyncConnectionPool(
        conninfo=psycopg_dsn(settings.database_url),
        max_size=10,
        open=False,
        # autocommit and dict_row are what the checkpointer expects; prepare_threshold=0
        # avoids prepared-statement clashes when connections are recycled by the pool.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # creates its tables on first run, no-op afterwards
        yield checkpointer
