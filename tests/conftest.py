from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
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
