from __future__ import annotations

import sqlite3
import time
from typing import Any

from .database import Database
from .models import ServerActionRequest, ServerActionResult


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
            elif token["consumed_at"] is not None:
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
                connection.execute(
                    """
                    UPDATE operator_voice_auth_tokens
                    SET consumed_at = CURRENT_TIMESTAMP WHERE jti = ?
                    """,
                    (request.token_jti,),
                )
                result = self._evaluate(connection, request)

            self._record(connection, request, result)
            return result

    def reject_unverified(
        self, request_id: str, server_id: str, action: str, message: str
    ) -> ServerActionResult:
        request = ServerActionRequest(request_id, "", "", "", "", server_id, action, "")
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
        if request.action not in {"start", "stop"}:
            return self._blocked(
                request, "ACTION_NOT_SUPPORTED", "I can only start or stop a server."
            )
        if "server:control" not in request.scope.split():
            return self._blocked(
                request,
                "INSUFFICIENT_SCOPE",
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
            "SELECT status FROM servers WHERE id = ?", (request.server_id,)
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

        desired_status = "running" if request.action == "start" else "stopped"
        if server["status"] == desired_status:
            return self._blocked(
                request,
                "SERVER_ALREADY_IN_STATE",
                f"Server {request.server_id} is already {desired_status}.",
                server["status"],
            )

        connection.execute(
            "UPDATE servers SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (desired_status, request.server_id),
        )
        action_word = "started" if request.action == "start" else "stopped"
        return ServerActionResult(
            request.request_id,
            True,
            "SERVER_ACTION_APPROVED",
            f"Approved. Server {request.server_id} has been {action_word}.",
            request.server_id,
            desired_status,
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
