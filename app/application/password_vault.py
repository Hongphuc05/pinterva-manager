"""Reversible, server-side storage for passwords shown to system administrators.

Authentication continues to use bcrypt hashes.  This module stores a separate
ciphertext strictly for the administrator account-management screen; it never
leaves the API unless the caller has passed the admin authorization check.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    secret = get_settings().secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_password(raw_password: str) -> str:
    return _fernet().encrypt(raw_password.encode("utf-8")).decode("ascii")


def decrypt_password(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError):
        # A rotated SECRET_KEY or corrupt historic value must not turn a list
        # operation into a 500.  The admin can set a replacement password.
        return None
