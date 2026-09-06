from app.application.operations import run_idempotent


def test_run_idempotent_executes_once_for_same_key(db_session):
    calls = {"count": 0}

    def side_effect():
        calls["count"] += 1
        return {"value": calls["count"]}

    result1 = run_idempotent(db_session, "key-1", "test_command", side_effect)
    result2 = run_idempotent(db_session, "key-1", "test_command", side_effect)

    assert calls["count"] == 1
    assert result1 == {"value": 1}
    assert result2 == {"value": 1}


def test_run_idempotent_executes_again_for_different_key(db_session):
    calls = {"count": 0}

    def side_effect():
        calls["count"] += 1
        return {"value": calls["count"]}

    run_idempotent(db_session, "key-a", "test_command", side_effect)
    run_idempotent(db_session, "key-b", "test_command", side_effect)

    assert calls["count"] == 2
