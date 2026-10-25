from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

SESSION_TTL_SECONDS = 60.0

ExpiryCallback = Callable[["Session"], Awaitable[None]]


@dataclass(slots=True)
class Session:
    """A voice-authenticated worker, valid until `expires_at` (monotonic seconds)."""

    id: str
    operator_id: str
    name: str
    device_id: str
    organization_id: str
    role: str
    scopes: list[str]
    servers: list[str]
    expires_at: float
    _timer: asyncio.Task[None] | None = field(default=None, repr=False)

    def remaining(self, now: float | None = None) -> float:
        return max(0.0, self.expires_at - (time.monotonic() if now is None else now))


class SessionStore:
    """Holds active sessions and clears each one `ttl` seconds after authentication.

    One session per operator: authenticating again replaces the earlier one.
    Expiry is enforced both by a timer (which also notifies the worker) and on
    every lookup, so a session can never be used after its deadline.
    """

    def __init__(
        self,
        ttl_seconds: float = SESSION_TTL_SECONDS,
        on_expire: ExpiryCallback | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._on_expire = on_expire
        self._sessions: dict[str, Session] = {}

    def create(
        self,
        *,
        operator_id: str,
        name: str,
        device_id: str,
        organization_id: str,
        role: str,
        scopes: list[str],
        servers: list[str],
    ) -> Session:
        for existing in [s for s in self._sessions.values() if s.operator_id == operator_id]:
            self._discard(existing)
        session = Session(
            id=secrets.token_urlsafe(24),
            operator_id=operator_id,
            name=name,
            device_id=device_id,
            organization_id=organization_id,
            role=role,
            scopes=scopes,
            servers=servers,
            expires_at=time.monotonic() + self.ttl_seconds,
        )
        self._sessions[session.id] = session
        session._timer = asyncio.get_running_loop().create_task(self._expire_later(session))
        return session

    def get(self, session_id: str | None) -> Session | None:
        """Return the live session, or None if unknown or past its deadline."""
        session = self._sessions.get(session_id or "")
        if session is None:
            return None
        if session.remaining() <= 0:
            self._discard(session)
            return None
        return session

    def for_device(self, device_id: str) -> Session | None:
        """The live session of whoever signed in on this device, if any."""
        for session in list(self._sessions.values()):
            if session.device_id == device_id and self.get(session.id) is not None:
                return session
        return None

    def end(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            self._discard(session)

    def active_count(self) -> int:
        return sum(1 for s in list(self._sessions.values()) if self.get(s.id) is not None)

    def _discard(self, session: Session) -> None:
        self._sessions.pop(session.id, None)
        timer, session._timer = session._timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()

    async def _expire_later(self, session: Session) -> None:
        await asyncio.sleep(session.remaining())
        if self._sessions.get(session.id) is not session:
            return
        self._discard(session)
        if self._on_expire is not None:
            await self._on_expire(session)
