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


def test_message_add_and_list_preserves_order(db_session):
    conv = conversation_repository.create(db_session, user_id=1)
    db_session.commit()

    message_repository.add(db_session, conv.id, "user", "hello")
    message_repository.add(db_session, conv.id, "assistant", "hi there")
    db_session.commit()

    messages = message_repository.list_for_conversation(db_session, conv.id)

    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.content for m in messages] == ["hello", "hi there"]
