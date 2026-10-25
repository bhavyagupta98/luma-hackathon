from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any
from uuid import uuid4

from ..database import Database
from .commands import Command
from .sessions import Session

# Short spoken names for the seeded servers: "fix server A" works as well as "server one hundred".
SERVER_ALIASES = {"SRV-A": "SRV-100", "SRV-B": "SRV-200", "SRV-C": "SRV-300"}
SUCCESS_MESSAGE = "Task successful."
DENIED_MESSAGE = "You are not allowed to do this task."


@dataclass(frozen=True, slots=True)
class TaskResult:
    allowed: bool
    code: str
    spoken_message: str
    server_id: str | None
    task: str | None
    server_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskService:
    """Validates and runs "restart server X" / "fix server X" for an authenticated session.

    Permissions come from the backend's own tables (never from the client): the
    operator must be active and assigned to the server, within the session's
    organization. Restart and fix are simulated by leaving the server running.
    Every attempt, allowed or refused, is written to `server_action_events`.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def permissions_for(self, operator_id: str, organization_id: str) -> list[str]:
        """Server ids this operator may control."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT server_assignments.server_id
                FROM server_assignments
                JOIN server_organizations
                  ON server_organizations.server_id = server_assignments.server_id
                WHERE server_assignments.operator_id = ?
                  AND server_assignments.can_control = 1
                  AND server_organizations.organization_id = ?
                ORDER BY server_assignments.server_id
                """,
                (operator_id, organization_id),
            ).fetchall()
        return [row["server_id"] for row in rows]

    def list_servers(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, status, updated_at FROM servers ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def execute(self, session: Session, command: Command) -> TaskResult:
        if command.server_id in SERVER_ALIASES:
            command = replace(command, server_id=SERVER_ALIASES[command.server_id])
        with self.database.transaction() as connection:
            result = self._evaluate(connection, session, command)
            connection.execute(
                """
                INSERT INTO server_action_events (
                    request_id, operator_id, device_id, server_id, action,
                    authorized, code, spoken_message, server_status, token_jti
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    f"task-{uuid4()}",
                    session.operator_id,
                    session.device_id,
                    command.server_id or "",
                    command.task,
                    int(result.allowed),
                    result.code,
                    result.spoken_message,
                    result.server_status,
                ),
            )
        return result

    def _evaluate(self, connection, session: Session, command: Command) -> TaskResult:
        def refuse(code: str, message: str, status: str | None = None) -> TaskResult:
            return TaskResult(False, code, message, command.server_id, command.task, status)

        if command.server_id is None:
            return refuse(
                "SERVER_NOT_UNDERSTOOD", "Which server? Say restart or fix, then the server."
            )

        if "server:control" not in session.scopes:
            return refuse("INSUFFICIENT_SCOPE", DENIED_MESSAGE)
        operator = connection.execute(
            "SELECT active FROM operators WHERE id = ?", (session.operator_id,)
        ).fetchone()
        if operator is None or not operator["active"]:
            return refuse("OPERATOR_NOT_AUTHORIZED", DENIED_MESSAGE)

        server = connection.execute(
            "SELECT status FROM servers WHERE id = ?", (command.server_id,)
        ).fetchone()
        if server is None:
            return refuse("SERVER_NOT_FOUND", "I couldn't find that server.")

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
            (session.operator_id, command.server_id, session.organization_id),
        ).fetchone()
        if assignment is None or not assignment["can_control"]:
            return refuse("SERVER_NOT_ASSIGNED", DENIED_MESSAGE, server["status"])

        connection.execute(
            "UPDATE servers SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (command.server_id,),
        )
        return TaskResult(
            True, "TASK_SUCCESSFUL", SUCCESS_MESSAGE, command.server_id, command.task, "running"
        )
