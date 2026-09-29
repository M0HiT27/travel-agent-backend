import pytest

from app.core.exceptions import NotFoundError
from app.models.user import User
from app.services.chat_service import resolve_conversation


def _user(user_id: int = 1) -> User:
    return User(id=user_id, name="Test", email="t@example.com", hashed_password="x", role_id=1)


def test_resolve_conversation_creates_new_when_none_given(db_session):
    conversation = resolve_conversation(db_session, _user(), None, "hello there")

    assert conversation.id is not None
    assert conversation.user_id == 1


def test_resolve_conversation_titles_a_new_conversation_from_the_message(db_session):
    conversation = resolve_conversation(db_session, _user(), None, "  buses from Mumbai  to Pune ")

    assert conversation.title == "buses from Mumbai to Pune"


def test_resolve_conversation_truncates_a_long_first_message(db_session):
    message = "a" * 100
    conversation = resolve_conversation(db_session, _user(), None, message)

    assert conversation.title == "a" * 60 + "..."


def test_resolve_conversation_returns_existing(db_session):
    created = resolve_conversation(db_session, _user(), None, "hello there")

    fetched = resolve_conversation(db_session, _user(), created.id, "irrelevant")

    assert fetched.id == created.id
    assert fetched.title == created.title


def test_resolve_conversation_404s_for_missing_conversation(db_session):
    with pytest.raises(NotFoundError):
        resolve_conversation(db_session, _user(), 999, "hi")


def test_resolve_conversation_404s_for_another_users_conversation(db_session):
    created = resolve_conversation(db_session, _user(user_id=1), None, "hi")

    with pytest.raises(NotFoundError):
        resolve_conversation(db_session, _user(user_id=2), created.id, "hi")
