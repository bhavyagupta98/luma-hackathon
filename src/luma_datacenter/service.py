from __future__ import annotations

import sqlite3
import time
from typing import Any

from .database import Database
from .models import ServerActionRequest, ServerActionResult
from .policy import SERVER_FIX_TASK, SERVER_RESTART_TASK


class ServerControlService:
    """Consumes voice identity tokens and controls simulated server power state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def execute(self, request: ServerActionRequest) -> ServerActionResult:
        with self.database.transaction() as connection:
            previous = connection.execute(
                "SELECT * FROM server_action_events WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
            if previous is not None:
                return self._result_from_audit(previous)

            token = connection.execute(
                """
                SELECT operator_id, device_id, organization_id, expires_at, consumed_at
                FROM operator_voice_auth_tokens WHERE jti = ?
                """,
                (request.token_jti,),
            ).fetchone()
            if token is None:
                result = self._blocked(
                    request,
                    "AUTHENTICATION_REQUIRED",
                    "I couldn't verify your authentication. Please verify your voice again.",
                )
            elif token["consumed_at"] is not None and len(request.authorized_tasks) == 1:
                result = self._blocked(
                    request,
                    "AUTHENTICATION_ALREADY_USED",
                    "That voice verification was already used. Please verify your voice again.",
                )
            elif token["expires_at"] < int(time.time()):
                result = self._blocked(
                    request,
                    "AUTHENTICATION_EXPIRED",
                    "Your voice verification expired. Please verify your voice again.",
                )
            elif (
                token["operator_id"] != request.operator_id
                or token["device_id"] != request.device_id
                or token["organization_id"] != request.organization_id
            ):
                result = self._blocked(
                    request,
                    "AUTHENTICATION_MISMATCH",
                    "I couldn't verify your authentication. Please verify your voice again.",
                )
            else:
                if len(request.authorized_tasks) == 1:
                    connection.execute(
                        """UPDATE operator_voice_auth_tokens
                           SET consumed_at=CURRENT_TIMESTAMP WHERE jti=?""",
                        (request.token_jti,),
                    )
                result = self._evaluate(connection, request)

            self._record(connection, request, result)
            return result

    def reject_unverified(
        self, request_id: str, server_id: str, action: str, message: str
    ) -> ServerActionResult:
        request = ServerActionRequest(
            request_id=request_id,
            operator_id="",
            device_id="",
            organization_id="",
            roles=(),
            permissions=(),
            authorized_tasks=(),
            server_id=server_id,
            action=action,
            token_jti="",
        )
        result = self._blocked(request, "AUTHENTICATION_REQUIRED", message)
        with self.database.transaction() as connection:
            previous = connection.execute(
                "SELECT * FROM server_action_events WHERE request_id = ?", (request_id,)
            ).fetchone()
            if previous is not None:
                return self._result_from_audit(previous)
            self._record(connection, request, result)
        return result

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT request_id, attempted_at, operator_id, device_id, server_id,
                       action, authorized, code, spoken_message, server_status, token_jti
                FROM server_action_events
                ORDER BY id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) | {"authorized": bool(row["authorized"])} for row in rows]

    def _evaluate(
        self, connection: sqlite3.Connection, request: ServerActionRequest
    ) -> ServerActionResult:
        if request.action not in {"restart", "fix"}:
            return self._blocked(
                request, "ACTION_NOT_SUPPORTED", "I can only restart or fix a server."
            )
        required_task = SERVER_RESTART_TASK if request.action == "restart" else SERVER_FIX_TASK
        if required_task not in request.authorized_tasks:
            return self._blocked(
                request,
                "TASK_NOT_AUTHORIZED",
                "Your voice verification was not authorized for that task.",
            )
        required_permission = "server:restart" if request.action == "restart" else "server:repair"
        if required_permission not in request.permissions:
            return self._blocked(
                request,
                "INSUFFICIENT_PERMISSION",
                "You are not authorized to control datacenter servers.",
            )

        operator = connection.execute(
            "SELECT active FROM operators WHERE id = ?", (request.operator_id,)
        ).fetchone()
        if operator is None or not operator["active"]:
            return self._blocked(
                request,
                "OPERATOR_NOT_AUTHORIZED",
                "You are not authorized to control datacenter servers.",
            )

        assignment = connection.execute(
            """
            SELECT server_assignments.can_control
            FROM server_assignments
            JOIN server_organizations
              ON server_organizations.server_id = server_assignments.server_id
            WHERE server_assignments.operator_id = ?
              AND server_assignments.server_id = ?
              AND server_organizations.organization_id = ?
            """,
            (request.operator_id, request.server_id, request.organization_id),
        ).fetchone()
        server = connection.execute(
            "SELECT status, health FROM servers WHERE id = ?", (request.server_id,)
        ).fetchone()
        if server is None:
            return self._blocked(request, "SERVER_NOT_FOUND", "I couldn't find that server.")
        if assignment is None or not assignment["can_control"]:
            return self._blocked(
                request,
                "SERVER_NOT_ASSIGNED",
                "You are not authorized to control that server.",
                server["status"],
            )

        if request.action == "restart":
            connection.execute(
                "UPDATE servers SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (request.server_id,),
            )
            message = f"Task successful. Server {request.server_id} has been restarted."
        else:
            connection.execute(
                "UPDATE servers SET health='healthy', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (request.server_id,),
            )
            message = f"Task successful. Server {request.server_id} has been fixed."
        return ServerActionResult(
            request.request_id,
            True,
            "SERVER_ACTION_APPROVED",
            message,
            request.server_id,
            "running" if request.action == "restart" else server["status"],
        )

    @staticmethod
    def _blocked(
        request: ServerActionRequest,
        code: str,
        message: str,
        server_status: str | None = None,
    ) -> ServerActionResult:
        return ServerActionResult(
            request.request_id, False, code, message, request.server_id, server_status
        )

    @staticmethod
    def _record(
        connection: sqlite3.Connection,
        request: ServerActionRequest,
        result: ServerActionResult,
    ) -> None:
        connection.execute(
            """
            INSERT INTO server_action_events (
                request_id, operator_id, device_id, server_id, action,
                authorized, code, spoken_message, server_status, token_jti
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.operator_id or None,
                request.device_id or None,
                request.server_id,
                request.action,
                int(result.authorized),
                result.code,
                result.spoken_message,
                result.server_status,
                request.token_jti or None,
            ),
        )

    @staticmethod
    def _result_from_audit(row: sqlite3.Row) -> ServerActionResult:
        return ServerActionResult(
            row["request_id"],
            bool(row["authorized"]),
            row["code"],
            row["spoken_message"],
            row["server_id"],
            row["server_status"],
        )
