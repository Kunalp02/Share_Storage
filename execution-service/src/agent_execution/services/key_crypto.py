from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret: str) -> Fernet:
    material = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_key(secret: str, api_key: str) -> str:
    return _fernet(secret).encrypt(api_key.encode()).decode()


def decrypt_key(secret: str, token: str | None) -> str | None:
    if not token or not secret:
        return None
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
