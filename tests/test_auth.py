from app.application.auth import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_session_token_roundtrip():
    token = create_session_token("user-123", "admin")
    data = read_session_token(token)
    assert data == {"user_id": "user-123", "role": "admin"}


def test_session_token_rejects_tampered_value():
    token = create_session_token("user-123", "admin")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert read_session_token(tampered) is None
