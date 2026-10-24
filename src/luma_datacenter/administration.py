from __future__ import annotations

import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .database import Database
from .models import UserRegistrationRequest, UserRegistrationResult
from .policy import USER_ADD_TASK


class UserAdministrationService:
    """Adds organization-scoped users through a one-use admin voice signature."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_user(self, request: UserRegistrationRequest) -> UserRegistrationResult:
        with self.database.transaction() as connection:
            previous = connection.execute(
                "SELECT * FROM user_admin_events WHERE request_id = ?", (request.request_id,)
            ).fetchone()
            if previous is not None:
                return self._from_audit(previous)

            result = self._validate_and_add(connection, request)
            self._record(connection, request, result)
            return result

    def reject_unverified(
        self,
        *,
        request_id: str,
        organization_id: str,
        user_id: str,
        display_name: str,
        role: str,
        device_id: str,
        server_ids: tuple[str, ...],
    ) -> UserRegistrationResult:
        request = UserRegistrationRequest(
            request_id=request_id,
            actor_operator_id="",
            actor_device_id="",
            actor_organization_id="",
            actor_roles=(),
            actor_permissions=(),
            actor_authorized_tasks=(),
            token_jti="",
            organization_id=organization_id,
            user_id=user_id,
            display_name=display_name,
            role=role,
            device_id=device_id,
            server_ids=server_ids,
        )
        result = self._blocked(
            request,
            "AUTHENTICATION_REQUIRED",
            "Your admin voice verification was invalid. Please verify your voice again.",
        )
        with self.database.transaction() as connection:
            previous = connection.execute(
                "SELECT * FROM user_admin_events WHERE request_id = ?", (request_id,)
            ).fetchone()
            if previous is not None:
                return self._from_audit(previous)
            self._record(connection, request, result)
        return result

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT request_id, attempted_at, actor_operator_id, organization_id,
                       target_operator_id, display_name, requested_role, device_id,
                       server_ids, approved, code, spoken_message, token_jti
                FROM user_admin_events ORDER BY id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            dict(row)
            | {
                "approved": bool(row["approved"]),
                "server_ids": json.loads(row["server_ids"]),
            }
            for row in rows
        ]

    def _validate_and_add(
        self, connection: sqlite3.Connection, request: UserRegistrationRequest
    ) -> UserRegistrationResult:
        token = connection.execute(
            """
            SELECT operator_id, device_id, organization_id, role, expires_at, consumed_at
            FROM operator_voice_auth_tokens WHERE jti = ?
            """,
            (request.token_jti,),
        ).fetchone()
        if token is None:
            return self._blocked(
                request,
                "AUTHENTICATION_REQUIRED",
                "Your admin voice verification was not recognized. Please try again.",
            )
        if token["consumed_at"] is not None:
            return self._blocked(
                request,
                "AUTHENTICATION_ALREADY_USED",
                "That admin voice verification was already used. Please verify again.",
            )
        if token["expires_at"] < int(time.time()):
            return self._blocked(
                request,
                "AUTHENTICATION_EXPIRED",
                "Your admin voice verification expired. Please verify again.",
            )
        if (
            token["operator_id"] != request.actor_operator_id
            or token["device_id"] != request.actor_device_id
            or token["organization_id"] != request.actor_organization_id
        ):
            return self._blocked(
                request,
                "AUTHENTICATION_MISMATCH",
                "Your admin authentication did not match this organization.",
            )

        connection.execute(
            "UPDATE operator_voice_auth_tokens SET consumed_at = CURRENT_TIMESTAMP WHERE jti = ?",
            (request.token_jti,),
        )

        values = (
            request.organization_id,
            request.user_id,
            request.display_name,
            request.role,
            request.device_id,
        )
        if any(not value.strip() for value in values):
            return self._blocked(
                request,
                "INVALID_USER_DETAILS",
                "I need the organization, user ID, name, role, and device ID.",
            )
        if request.role not in {"org_admin", "operator"}:
            return self._blocked(
                request,
                "ROLE_NOT_SUPPORTED",
                "The role must be organization administrator or operator.",
            )
        if request.actor_organization_id != request.organization_id:
            return self._blocked(
                request,
                "ORGANIZATION_MISMATCH",
                "You can only add users to your own organization.",
            )

        required_permission = (
            "organization:admins:create"
            if request.role == "org_admin"
            else "organization:members:create"
        )
        if (
            USER_ADD_TASK not in request.actor_authorized_tasks
            or required_permission not in request.actor_permissions
            or "org_admin" not in request.actor_roles
            or token["role"] != "org_admin"
        ):
            return self._blocked(
                request,
                "INSUFFICIENT_PERMISSION",
                "You are not authorized to add a user with that role.",
            )

        organization = connection.execute(
            "SELECT active FROM organizations WHERE id = ?", (request.organization_id,)
        ).fetchone()
        if organization is None or not organization["active"]:
            return self._blocked(
                request, "ORGANIZATION_NOT_FOUND", "I couldn't find an active organization."
            )
        if connection.execute(
            "SELECT 1 FROM operators WHERE id = ?", (request.user_id,)
        ).fetchone():
            return self._blocked(
                request, "USER_ALREADY_EXISTS", "A user with that ID already exists."
            )
        if connection.execute(
            "SELECT 1 FROM datacenter_devices WHERE id = ?", (request.device_id,)
        ).fetchone():
            return self._blocked(
                request, "DEVICE_ALREADY_EXISTS", "That device ID is already registered."
            )

        for server_id in request.server_ids:
            server = connection.execute(
                """
                SELECT 1 FROM server_organizations
                WHERE server_id = ? AND organization_id = ?
                """,
                (server_id, request.organization_id),
            ).fetchone()
            if server is None:
                return self._blocked(
                    request,
                    "SERVER_NOT_IN_ORGANIZATION",
                    f"Server {server_id} does not belong to this organization.",
                )

        connection.execute(
            "INSERT INTO operators (id, name, active) VALUES (?, ?, 1)",
            (request.user_id, request.display_name),
        )
        connection.execute(
            """
            INSERT INTO organization_memberships (organization_id, operator_id, role)
            VALUES (?, ?, ?)
            """,
            (request.organization_id, request.user_id, request.role),
        )
        connection.execute(
            "INSERT INTO datacenter_devices (id, operator_id, trusted) VALUES (?, ?, 1)",
            (request.device_id, request.user_id),
        )
        connection.execute(
            "INSERT INTO device_contexts (device_id, organization_id) VALUES (?, ?)",
            (request.device_id, request.organization_id),
        )
        for server_id in dict.fromkeys(request.server_ids):
            connection.execute(
                """
                INSERT INTO server_assignments (operator_id, server_id, can_control)
                VALUES (?, ?, 1)
                """,
                (request.user_id, server_id),
            )

        role_words = "organization administrator" if request.role == "org_admin" else "operator"
        return UserRegistrationResult(
            request.request_id,
            True,
            "USER_ADDED_VOICE_ENROLLMENT_REQUIRED",
            (
                f"{request.display_name} was added as an {role_words}. "
                "They must enroll their voice before signing in."
            ),
            request.organization_id,
            request.user_id,
            request.role,
            request.device_id,
        )

    @staticmethod
    def _blocked(
        request: UserRegistrationRequest, code: str, message: str
    ) -> UserRegistrationResult:
        return UserRegistrationResult(
            request.request_id,
            False,
            code,
            message,
            request.organization_id,
            request.user_id,
            request.role,
            request.device_id,
        )

    @staticmethod
    def _record(
        connection: sqlite3.Connection,
        request: UserRegistrationRequest,
        result: UserRegistrationResult,
    ) -> None:
        connection.execute(
            """
            INSERT INTO user_admin_events (
                request_id, actor_operator_id, organization_id, target_operator_id,
                display_name, requested_role, device_id, server_ids, approved,
                code, spoken_message, token_jti
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.actor_operator_id or None,
                request.organization_id,
                request.user_id,
                request.display_name,
                request.role,
                request.device_id,
                json.dumps(list(request.server_ids)),
                int(result.approved),
                result.code,
                result.spoken_message,
                request.token_jti or None,
            ),
        )

    @staticmethod
    def _from_audit(row: sqlite3.Row) -> UserRegistrationResult:
        return UserRegistrationResult(
            row["request_id"],
            bool(row["approved"]),
            row["code"],
            row["spoken_message"],
            row["organization_id"],
            row["target_operator_id"],
            row["requested_role"],
            row["device_id"],
        )


def bootstrap_admin(
    database: Database,
    *,
    organization_id: str,
    organization_name: str,
    user_id: str,
    display_name: str,
    device_id: str,
) -> None:
    values = (organization_id, organization_name, user_id, display_name, device_id)
    if any(not value.strip() for value in values):
        raise ValueError("All organization, admin, and device details are required")
    with database.transaction() as connection:
        if connection.execute(
            "SELECT 1 FROM organizations WHERE id = ?", (organization_id,)
        ).fetchone():
            raise ValueError("Organization ID already exists")
        if connection.execute("SELECT 1 FROM operators WHERE id = ?", (user_id,)).fetchone():
            raise ValueError("User ID already exists")
        if connection.execute(
            "SELECT 1 FROM datacenter_devices WHERE id = ?", (device_id,)
        ).fetchone():
            raise ValueError("Device ID already exists")

        connection.execute(
            "INSERT INTO organizations (id, name, active) VALUES (?, ?, 1)",
            (organization_id, organization_name),
        )
        connection.execute(
            "INSERT INTO operators (id, name, active) VALUES (?, ?, 1)",
            (user_id, display_name),
        )
        connection.execute(
            """
            INSERT INTO organization_memberships (organization_id, operator_id, role)
            VALUES (?, ?, 'org_admin')
            """,
            (organization_id, user_id),
        )
        connection.execute(
            "INSERT INTO datacenter_devices (id, operator_id, trusted) VALUES (?, ?, 1)",
            (device_id, user_id),
        )
        connection.execute(
            "INSERT INTO device_contexts (device_id, organization_id) VALUES (?, ?)",
            (device_id, organization_id),
        )
        connection.execute(
            """
            INSERT INTO user_admin_events (
                request_id, actor_operator_id, organization_id, target_operator_id,
                display_name, requested_role, device_id, server_ids, approved,
                code, spoken_message, token_jti
            ) VALUES (?, ?, ?, ?, ?, 'org_admin', ?, '[]', 1, ?, ?, NULL)
            """,
            (
                f"bootstrap-{uuid4()}",
                user_id,
                organization_id,
                user_id,
                display_name,
                device_id,
                "ADMIN_BOOTSTRAPPED",
                f"Bootstrapped {display_name} as the first organization administrator.",
            ),
        )
