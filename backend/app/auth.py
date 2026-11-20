"""本地账号认证：口令哈希（PBKDF2）+ HMAC 令牌（含 password_version 吊销补偿）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from .config import get_settings

_ITERATIONS = 120_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return base64.b64encode(dk).decode(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    dk, _ = hash_password(password, salt)
    return hmac.compare_digest(dk, stored_hash)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def generate_token(user_id: int, password_version: int) -> str:
    settings = get_settings()
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps(
            {
                "sub": user_id,
                "pv": password_version,
                "exp": int(time.time()) + settings.token_ttl_hours * 3600,
            }
        ).encode()
    )
    signing = f"{header}.{payload}"
    sig = _b64url(hmac.new(settings.secret_key.encode(), signing.encode(), hashlib.sha256).digest())
    return f"{signing}.{sig}"


def verify_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        signing, sig = token.rsplit(".", 1)
        header, payload = signing.split(".", 1)
    except ValueError:
        return None
    expected = _b64url(hmac.new(settings.secret_key.encode(), signing.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data
