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
    # Tamper the payload, not the signature's last character: the signature is
    # base64 of 20 HMAC bytes, so its final char carries 2 unused bits and 4 of the
    # 64 substitutions decode to the same signature (a ~6% flake). The payload is
    # part of the signed *string*, so any change there always breaks the HMAC.
    payload, rest = token.split(".", 1)
    tampered = payload[:-1] + ("a" if payload[-1] != "a" else "b") + "." + rest
    assert read_session_token(tampered) is None
