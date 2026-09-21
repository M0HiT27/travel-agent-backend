from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.role import Role
from app.models.user import User


@pytest.fixture
def future_date() -> str:
    return (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def future_dates() -> tuple[str, str]:
    """A valid future check-in / check-out pair."""
    start = date.today() + timedelta(days=30)
    return start.isoformat(), (start + timedelta(days=3)).isoformat()


@pytest.fixture
def client() -> TestClient:
    """A test client with a stub logged-in user.

    Only authentication is stubbed. The route, validation and error handling under test
    are all the real ones.
    """
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, name="Test", email="test@example.com", hashed_password="x", role_id=1
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_session() -> Session:
    """An in-memory SQLite session with the SQLite-compatible tables created.

    `document_chunks` is excluded: it uses Postgres-only types (pgvector, JSONB) that
    SQLite cannot compile. Tests touching that table run against a stubbed
    vectorstore instead (see test_bus_policy_tool.py).
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(
        engine,
        tables=[Role.__table__, User.__table__, Conversation.__table__, Message.__table__],
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def chat_client(db_session: Session) -> TestClient:
    """Like `client`, but also backs `get_db` with a real (in-memory) session --
    for routes that touch the database directly rather than only calling out to an
    external API."""
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, name="Test", email="test@example.com", hashed_password="x", role_id=1
    )
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
