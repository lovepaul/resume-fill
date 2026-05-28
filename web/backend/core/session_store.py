from __future__ import annotations

import secrets
import threading
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException


def parse_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return ""
    return authorization[len(prefix) :].strip()


def parse_iso_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()


class SessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, str] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, str]:
        expires_at = datetime.now() + timedelta(seconds=self._ttl_seconds)
        token = secrets.token_urlsafe(24)
        expires_text = expires_at.isoformat(timespec="seconds")
        with self._lock:
            self._sessions[token] = expires_text
        return token, expires_text

    def is_valid(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            expires_at = self._sessions.get(token)
            if not expires_at:
                return False
            if parse_iso_time(expires_at) <= datetime.now():
                self._sessions.pop(token, None)
                return False
            return True

    def ensure_auth(self, authorization: Optional[str]) -> None:
        token = parse_bearer_token(authorization)
        if not self.is_valid(token):
            raise HTTPException(status_code=401, detail="未登录或会话已过期")

