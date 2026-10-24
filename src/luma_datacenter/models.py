from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ServerAction = Literal["start", "stop"]


@dataclass(frozen=True, slots=True)
class ServerActionRequest:
    request_id: str
    operator_id: str
    device_id: str
    organization_id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    authorized_tasks: tuple[str, ...]
    server_id: str
    action: str
    token_jti: str


@dataclass(frozen=True, slots=True)
class ServerActionResult:
    request_id: str
    authorized: bool
    code: str
    spoken_message: str
    server_id: str
    server_status: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UserRegistrationRequest:
    request_id: str
    actor_operator_id: str
    actor_device_id: str
    actor_organization_id: str
    actor_roles: tuple[str, ...]
    actor_permissions: tuple[str, ...]
    actor_authorized_tasks: tuple[str, ...]
    token_jti: str
    organization_id: str
    user_id: str
    display_name: str
    role: str
    device_id: str
    server_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UserRegistrationResult:
    request_id: str
    approved: bool
    code: str
    spoken_message: str
    organization_id: str
    user_id: str
    role: str
    device_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
