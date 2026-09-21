import pytest

from app.core.exceptions import NotFoundError
from app.models.user import User
from app.services.chat_service import resolve_conversation


def _user(user_id: int = 1) -> User:
    return User(id=user_id, name="Test", email="t@example.com", hashed_password="x", role_id=1)


def test_resolve_conversation_creates_new_when_none_given(db_session):
    conversation = resolve_conversation(db_session, _user(), None)

    assert conversation.id is not None
    assert conversation.user_id == 1


def test_resolve_conversation_returns_existing(db_session):
    created = resolve_conversation(db_session, _user(), None)

    fetched = resolve_conversation(db_session, _user(), created.id)

    assert fetched.id == created.id


def test_resolve_conversation_404s_for_missing_conversation(db_session):
    with pytest.raises(NotFoundError):
        resolve_conversation(db_session, _user(), 999)


def test_resolve_conversation_404s_for_another_users_conversation(db_session):
    created = resolve_conversation(db_session, _user(user_id=1), None)

    with pytest.raises(NotFoundError):
        resolve_conversation(db_session, _user(user_id=2), created.id)
