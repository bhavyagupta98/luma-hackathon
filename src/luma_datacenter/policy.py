from __future__ import annotations

from dataclasses import dataclass

AUTHENTICATION_TASK = "authenticate"
SERVER_START_TASK = "server.start"
SERVER_STOP_TASK = "server.stop"
USER_ADD_TASK = "user.add"

FUNCTIONAL_TASKS = frozenset({SERVER_START_TASK, SERVER_STOP_TASK, USER_ADD_TASK})


@dataclass(frozen=True, slots=True)
class TaskAuthorization:
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    tasks: tuple[str, ...]


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "org_admin": frozenset(
        {
            "organization:admins:create",
            "organization:members:create",
            "server:control",
        }
    ),
    "operator": frozenset({"server:control"}),
}

TASK_PERMISSION: dict[str, str] = {
    SERVER_START_TASK: "server:control",
    SERVER_STOP_TASK: "server:control",
    USER_ADD_TASK: "organization:members:create",
}


def authorize_task(role: str, task: str) -> TaskAuthorization | None:
    """Return the task-scoped signed grants for one requested task."""
    permission = TASK_PERMISSION.get(task)
    role_permissions = ROLE_PERMISSIONS.get(role, frozenset())
    if permission is None or permission not in role_permissions:
        return None

    permissions = {permission}
    # user.add may create either supported role. The service still applies the
    # stronger admin permission when the requested new role is org_admin.
    if task == USER_ADD_TASK and "organization:admins:create" in role_permissions:
        permissions.add("organization:admins:create")
    return TaskAuthorization((role,), tuple(sorted(permissions)), (task,))
