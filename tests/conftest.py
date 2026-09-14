from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routes.chat import get_agent
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Role, User  # noqa: F401  registers every table on Base.metadata

TEST_USER_ID = 1
OTHER_USER_ID = 2


@pytest.fixture
def future_date() -> str:
    return (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def future_dates() -> tuple[str, str]:
    """A valid future check-in / check-out pair."""
    start = date.today() + timedelta(days=30)
    return start.isoformat(), (start + timedelta(days=3)).isoformat()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A real SQLite database, in memory, thrown away after each test.

    Real rather than stubbed on purpose: the conversation ownership check is a security
    rule expressed as a WHERE clause, and a fake session would not exercise it.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection, so the schema survives
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    session.add_all(
        [
            Role(id=1, name="user"),
            User(
                id=TEST_USER_ID,
                name="Test",
                email="test@example.com",
                hashed_password="x",
                role_id=1,
            ),
            User(
                id=OTHER_USER_ID,
                name="Somebody Else",
                email="other@example.com",
                hashed_password="x",
                role_id=1,
            ),
        ]
    )
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A test client with a stub logged-in user and a throwaway database.

    The route, validation and error handling under test are all the real ones.
    """
    app.dependency_overrides[get_current_user] = lambda: db_session.get(User, TEST_USER_ID)
    app.dependency_overrides[get_db] = lambda: db_session
    # A stand-in for the agent built at startup. Tests that exercise /chat/ask stub the
    # `ask` function itself, so this only has to exist.
    app.dependency_overrides[get_agent] = lambda: object()

    # Deliberately not used as a context manager: that would run the app's lifespan,
    # which opens a real Postgres pool for the agent's memory. Tests stay off Postgres.
    yield TestClient(app)

    app.dependency_overrides.clear()
