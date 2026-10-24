from __future__ import annotations

from dataclasses import dataclass

AUTHENTICATION_TASK = "authenticate"
SERVER_RESTART_TASK = "server.restart"
SERVER_FIX_TASK = "server.fix"
USER_ADD_TASK = "user.add"

SERVER_TASKS = frozenset({SERVER_RESTART_TASK, SERVER_FIX_TASK})
FUNCTIONAL_TASKS = frozenset({*SERVER_TASKS, USER_ADD_TASK})


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
            "server:restart",
            "server:repair",
        }
    ),
    "operator": frozenset({"server:restart", "server:repair"}),
}

TASK_PERMISSION: dict[str, str] = {
    SERVER_RESTART_TASK: "server:restart",
    SERVER_FIX_TASK: "server:repair",
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


def authorize_session(role: str) -> TaskAuthorization | None:
    """Return all grants available during one short authenticated session."""
    role_permissions = ROLE_PERMISSIONS.get(role)
    if role_permissions is None:
        return None
    tasks = set(SERVER_TASKS)
    if role == "org_admin":
        tasks.add(USER_ADD_TASK)
    permissions = {TASK_PERMISSION[task] for task in tasks}
    if role == "org_admin":
        permissions.add("organization:admins:create")
    return TaskAuthorization((role,), tuple(sorted(permissions)), tuple(sorted(tasks)))
