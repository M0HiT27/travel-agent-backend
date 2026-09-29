from app.repositories import conversation_repository, message_repository


def test_create_and_get_conversation(db_session):
    conv = conversation_repository.create(db_session, user_id=1)
    db_session.commit()

    fetched = conversation_repository.get(db_session, conv.id, user_id=1)

    assert fetched is not None
    assert fetched.id == conv.id


def test_get_returns_none_for_another_users_conversation(db_session):
    conv = conversation_repository.create(db_session, user_id=1)
    db_session.commit()

    assert conversation_repository.get(db_session, conv.id, user_id=2) is None


def test_get_returns_none_for_missing_conversation(db_session):
    assert conversation_repository.get(db_session, 999, user_id=1) is None


def test_list_for_user_returns_only_that_users_conversations_most_recent_first(db_session):
    first = conversation_repository.create(db_session, user_id=1, title="first")
    second = conversation_repository.create(db_session, user_id=1, title="second")
    conversation_repository.create(db_session, user_id=2, title="someone else's")
    db_session.commit()

    conversations = conversation_repository.list_for_user(db_session, user_id=1)

    assert [c.id for c in conversations] == [second.id, first.id]


def test_list_for_user_returns_empty_list_when_user_has_no_conversations(db_session):
    assert conversation_repository.list_for_user(db_session, user_id=1) == []


def test_message_add_and_list_preserves_order(db_session):
    conv = conversation_repository.create(db_session, user_id=1)
    db_session.commit()

    message_repository.add(db_session, conv.id, "user", "hello")
    message_repository.add(db_session, conv.id, "assistant", "hi there")
    db_session.commit()

    messages = message_repository.list_for_conversation(db_session, conv.id)

    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.content for m in messages] == ["hello", "hi there"]
