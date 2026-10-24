from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS operators (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS organization_memberships (
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    operator_id TEXT NOT NULL REFERENCES operators(id),
    role TEXT NOT NULL CHECK (role IN ('org_admin', 'operator')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organization_id, operator_id)
);

CREATE TABLE IF NOT EXISTS datacenter_devices (
    id TEXT PRIMARY KEY,
    operator_id TEXT NOT NULL REFERENCES operators(id),
    trusted INTEGER NOT NULL CHECK (trusted IN (0, 1))
);

CREATE TABLE IF NOT EXISTS device_contexts (
    device_id TEXT PRIMARY KEY REFERENCES datacenter_devices(id),
    organization_id TEXT NOT NULL REFERENCES organizations(id)
);

CREATE TABLE IF NOT EXISTS servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'stopped')),
    health TEXT NOT NULL DEFAULT 'healthy' CHECK (health IN ('healthy', 'needs_repair')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS server_organizations (
    server_id TEXT PRIMARY KEY REFERENCES servers(id),
    organization_id TEXT NOT NULL REFERENCES organizations(id)
);

CREATE TABLE IF NOT EXISTS server_assignments (
    operator_id TEXT NOT NULL REFERENCES operators(id),
    server_id TEXT NOT NULL REFERENCES servers(id),
    can_control INTEGER NOT NULL CHECK (can_control IN (0, 1)),
    PRIMARY KEY (operator_id, server_id)
);

CREATE TABLE IF NOT EXISTS server_action_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operator_id TEXT,
    device_id TEXT,
    server_id TEXT NOT NULL,
    action TEXT NOT NULL,
    authorized INTEGER NOT NULL CHECK (authorized IN (0, 1)),
    code TEXT NOT NULL,
    spoken_message TEXT NOT NULL,
    server_status TEXT,
    token_jti TEXT
);

CREATE INDEX IF NOT EXISTS server_action_events_attempted_at_idx
ON server_action_events(attempted_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS user_admin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_operator_id TEXT,
    organization_id TEXT NOT NULL,
    target_operator_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    requested_role TEXT NOT NULL,
    device_id TEXT NOT NULL,
    server_ids TEXT NOT NULL,
    approved INTEGER NOT NULL CHECK (approved IN (0, 1)),
    code TEXT NOT NULL,
    spoken_message TEXT NOT NULL,
    token_jti TEXT
);

CREATE INDEX IF NOT EXISTS user_admin_events_attempted_at_idx
ON user_admin_events(attempted_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS operator_voice_profiles (
    operator_id TEXT PRIMARY KEY REFERENCES operators(id),
    embedding BLOB NOT NULL,
    embedding_dimensions INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    threshold REAL NOT NULL,
    enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operator_voice_auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auth_id TEXT NOT NULL UNIQUE,
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operator_id TEXT REFERENCES operators(id),
    device_id TEXT NOT NULL,
    authenticated INTEGER NOT NULL CHECK (authenticated IN (0, 1)),
    code TEXT NOT NULL,
    similarity_score REAL,
    audio_sha256 TEXT,
    spoken_message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_voice_auth_tokens (
    jti TEXT PRIMARY KEY,
    auth_id TEXT NOT NULL UNIQUE REFERENCES operator_voice_auth_events(auth_id),
    operator_id TEXT NOT NULL REFERENCES operators(id),
    device_id TEXT NOT NULL REFERENCES datacenter_devices(id),
    organization_id TEXT REFERENCES organizations(id),
    role TEXT,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed_at TEXT
);

CREATE INDEX IF NOT EXISTS operator_voice_auth_events_attempted_at_idx
ON operator_voice_auth_events(attempted_at DESC, id DESC);
"""

SEED = """
INSERT OR IGNORE INTO organizations (id, name, active) VALUES
    ('ORG-DEMO', 'Luma Demo Datacenter', 1);

INSERT OR IGNORE INTO operators (id, name, active) VALUES
    ('OP-100', 'Avery Chen', 1),
    ('OP-200', 'Jordan Patel', 1),
    ('OP-300', 'Morgan Diaz', 0);

INSERT OR IGNORE INTO datacenter_devices (id, operator_id, trusted) VALUES
    ('DC-D-100', 'OP-100', 1),
    ('DC-D-200', 'OP-200', 1),
    ('DC-D-INACTIVE', 'OP-100', 0);

INSERT OR IGNORE INTO organization_memberships (organization_id, operator_id, role) VALUES
    ('ORG-DEMO', 'OP-100', 'org_admin'),
    ('ORG-DEMO', 'OP-200', 'operator'),
    ('ORG-DEMO', 'OP-300', 'operator');

INSERT OR IGNORE INTO device_contexts (device_id, organization_id) VALUES
    ('DC-D-100', 'ORG-DEMO'),
    ('DC-D-200', 'ORG-DEMO'),
    ('DC-D-INACTIVE', 'ORG-DEMO');

INSERT OR IGNORE INTO servers (id, name, status, health) VALUES
    ('SRV-100', 'Compute Server One Hundred', 'running', 'healthy'),
    ('SRV-200', 'Compute Server Two Hundred', 'running', 'needs_repair'),
    ('SRV-300', 'Restricted Server Three Hundred', 'running', 'healthy');

INSERT OR IGNORE INTO server_organizations (server_id, organization_id) VALUES
    ('SRV-100', 'ORG-DEMO'),
    ('SRV-200', 'ORG-DEMO'),
    ('SRV-300', 'ORG-DEMO');

INSERT OR IGNORE INTO server_assignments (operator_id, server_id, can_control) VALUES
    ('OP-100', 'SRV-100', 1),
    ('OP-100', 'SRV-200', 1),
    ('OP-200', 'SRV-300', 1);
"""


class Database:
    """Owns schema creation, deterministic datacenter seeding, and connections."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            connection.executescript(SEED)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Add organization claims to databases created by the earlier pilot."""
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(operator_voice_auth_tokens)")
        }
        if "organization_id" not in columns:
            connection.execute(
                "ALTER TABLE operator_voice_auth_tokens ADD COLUMN organization_id TEXT"
            )
        if "role" not in columns:
            connection.execute("ALTER TABLE operator_voice_auth_tokens ADD COLUMN role TEXT")
        server_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(servers)")
        }
        if "health" not in server_columns:
            connection.execute(
                "ALTER TABLE servers ADD COLUMN health TEXT NOT NULL DEFAULT 'healthy'"
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
