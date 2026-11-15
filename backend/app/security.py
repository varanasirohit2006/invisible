import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

COOKIE_NAME = "iwd_session"


class SessionGate:
    def __init__(self, token: str):
        self.token = token
        self.attempts: dict[str, deque] = defaultdict(deque)

    def bearer_valid(self, request: Request) -> bool:
        header = request.headers.get("authorization", "")
        return header.startswith("Bearer ") and secrets.compare_digest(
            header[7:].encode("utf-8"), self.token.encode("utf-8")
        )

    def issue(self) -> str:
        payload = f"{int(time.time()) + 43200}.{secrets.token_hex(16)}"
        signature = hmac.new(self.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def cookie_valid(self, value: str) -> bool:
        try:
            expiry, nonce, signature = value.split(".")
            expected = hmac.new(
                self.token.encode(), f"{expiry}.{nonce}".encode(), hashlib.sha256
            ).hexdigest()
            return int(expiry) > time.time() and secrets.compare_digest(expected, signature)
        except (ValueError, TypeError):
            return False

    def pair(self, token: str, client: str):
        queue = self.attempts[client]
        while queue and queue[0] < time.monotonic() - 60:
            queue.popleft()
        if len(queue) >= 8:
            raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
        if not secrets.compare_digest(token.encode("utf-8"), self.token.encode("utf-8")):
            queue.append(time.monotonic())
            raise HTTPException(401, "The pairing token did not match.")
        queue.clear()


def authenticated(request: Request):
    gate = request.app.state.gate
    if not gate.bearer_valid(request) and not gate.cookie_valid(
        request.cookies.get(COOKIE_NAME, "")
    ):
        raise HTTPException(401, "Connect with your local pairing token.")


def agent_authenticated(request: Request):
    if not request.app.state.gate.bearer_valid(request):
        raise HTTPException(401, "An agent token is required.")


def active_agent(request: Request):
    agent_authenticated(request)
    request.app.state.service.require_agent(request.headers.get("x-iwd-agent", ""))
