from __future__ import annotations

import hashlib
import math
from array import array
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from .database import Database
from .policy import authorize_session, authorize_task
from .voice_embeddings import VoiceEmbedder, VoiceEmbeddingError
from .voice_tokens import VoiceTokenError, VoiceTokenSigner


@dataclass(frozen=True, slots=True)
class VoiceEnrollmentResult:
    enrolled: bool
    code: str
    operator_id: str
    sample_count: int
    spoken_message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VoiceAuthenticationResult:
    auth_id: str
    authenticated: bool
    code: str
    spoken_message: str
    operator_id: str | None
    device_id: str
    organization_id: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    similarity_score: float | None = None
    authorization_signature: str | None = None
    expires_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceAuthService:
    def __init__(
        self,
        database: Database,
        embedder: VoiceEmbedder,
        signer: VoiceTokenSigner,
        *,
        default_threshold: float = 0.25,
    ) -> None:
        if not -1 <= default_threshold <= 1:
            raise ValueError("Voice threshold must be between -1 and 1")
        self.database = database
        self.embedder = embedder
        self.signer = signer
        self.default_threshold = default_threshold

    def enroll(self, operator_id: str, audio_samples: list[bytes]) -> VoiceEnrollmentResult:
        if not audio_samples:
            return VoiceEnrollmentResult(
                False, "NO_ENROLLMENT_AUDIO", operator_id, 0, "No enrollment audio was provided."
            )
        with self.database.connect() as connection:
            operator = connection.execute(
                "SELECT active FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        if operator is None or not operator["active"]:
            return VoiceEnrollmentResult(
                False,
                "OPERATOR_NOT_AUTHORIZED",
                operator_id,
                0,
                "The operator cannot be enrolled because they are not authorized.",
            )

        try:
            embeddings = [self._normalize(self.embedder.embed(sample)) for sample in audio_samples]
            dimensions = len(embeddings[0])
            if any(len(embedding) != dimensions for embedding in embeddings):
                raise VoiceEmbeddingError("Enrollment embeddings have inconsistent dimensions")
            averaged = self._normalize(
                [sum(values) / len(embeddings) for values in zip(*embeddings, strict=True)]
            )
        except VoiceEmbeddingError as exc:
            return VoiceEnrollmentResult(False, "INVALID_AUDIO", operator_id, 0, str(exc))

        blob = array("f", averaged).tobytes()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO operator_voice_profiles (
                    operator_id, embedding, embedding_dimensions, model_name, threshold
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(operator_id) DO UPDATE SET
                    embedding = excluded.embedding,
                    embedding_dimensions = excluded.embedding_dimensions,
                    model_name = excluded.model_name,
                    threshold = excluded.threshold,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (operator_id, blob, dimensions, self.embedder.model_name, self.default_threshold),
            )
        return VoiceEnrollmentResult(
            True,
            "VOICE_ENROLLED",
            operator_id,
            len(audio_samples),
            f"Voice enrollment completed for operator {operator_id}.",
        )

    def authenticate(
        self, device_id: str, audio: bytes, requested_task: str = ""
    ) -> VoiceAuthenticationResult:
        auth_id = str(uuid4())
        audio_sha256 = hashlib.sha256(audio).hexdigest() if audio else None
        with self.database.connect() as connection:
            device = connection.execute(
                """
                SELECT datacenter_devices.operator_id, datacenter_devices.trusted,
                       operators.active, device_contexts.organization_id,
                       organization_memberships.role,
                       organizations.active AS organization_active
                FROM datacenter_devices
                JOIN operators ON operators.id = datacenter_devices.operator_id
                JOIN device_contexts ON device_contexts.device_id = datacenter_devices.id
                JOIN organizations ON organizations.id = device_contexts.organization_id
                JOIN organization_memberships
                  ON organization_memberships.organization_id = device_contexts.organization_id
                 AND organization_memberships.operator_id = datacenter_devices.operator_id
                WHERE datacenter_devices.id = ?
                """,
                (device_id,),
            ).fetchone()
            profile = (
                connection.execute(
                    "SELECT * FROM operator_voice_profiles WHERE operator_id = ?",
                    (device["operator_id"],),
                ).fetchone()
                if device is not None
                else None
            )

        if (
            device is None
            or not device["trusted"]
            or not device["active"]
            or not device["organization_active"]
        ):
            return self._record_refusal(
                auth_id,
                device_id,
                None,
                "DEVICE_NOT_AUTHORIZED",
                "I can't verify your voice because this device is not authorized.",
                audio_sha256,
            )
        operator_id = str(device["operator_id"])
        organization_id = str(device["organization_id"])
        role = str(device["role"])
        if profile is None:
            return self._record_refusal(
                auth_id,
                device_id,
                operator_id,
                "VOICE_NOT_ENROLLED",
                "Your voice is not enrolled. Please contact a supervisor.",
                audio_sha256,
            )
        if profile["model_name"] != self.embedder.model_name:
            return self._record_refusal(
                auth_id,
                device_id,
                operator_id,
                "VOICE_MODEL_MISMATCH",
                "Your voice profile needs to be enrolled again before continuing.",
                audio_sha256,
            )

        try:
            candidate = self._normalize(self.embedder.embed(audio))
            enrolled = self._embedding_from_row(profile)
            if len(candidate) != len(enrolled):
                raise VoiceEmbeddingError("Voice embedding dimensions do not match")
            score = sum(left * right for left, right in zip(candidate, enrolled, strict=True))
        except VoiceEmbeddingError as exc:
            return self._record_refusal(
                auth_id, device_id, operator_id, "INVALID_AUDIO", str(exc), audio_sha256
            )

        if score < float(profile["threshold"]):
            return self._record_refusal(
                auth_id,
                device_id,
                operator_id,
                "VOICE_NOT_MATCHED",
                "I couldn't verify your voice. Please try again.",
                audio_sha256,
                score,
            )

        authorization = (
            authorize_task(role, requested_task) if requested_task else authorize_session(role)
        )
        if authorization is None:
            return self._record_refusal(
                auth_id,
                device_id,
                operator_id,
                "TASK_NOT_AUTHORIZED",
                "Your voice was verified, but you are not authorized to perform that task.",
                audio_sha256,
                score,
            )

        issued = self.signer.issue(
            auth_id=auth_id,
            operator_id=operator_id,
            device_id=device_id,
            organization_id=organization_id,
            roles=list(authorization.roles),
            permissions=list(authorization.permissions),
            tasks=list(authorization.tasks),
            audio_sha256=audio_sha256 or "",
            similarity_score=score,
        )
        result = VoiceAuthenticationResult(
            auth_id=auth_id,
            authenticated=True,
            code="VOICE_AUTHENTICATED",
            spoken_message=(
                f"{self._operator_name(operator_id)}, you are authenticated. Proceed inside."
            ),
            operator_id=operator_id,
            device_id=device_id,
            organization_id=organization_id,
            roles=authorization.roles,
            permissions=authorization.permissions,
            tasks=authorization.tasks,
            similarity_score=round(score, 6),
            authorization_signature=issued.token,
            expires_at=issued.expires_at,
        )
        with self.database.transaction() as connection:
            self._insert_event(connection, result, audio_sha256)
            connection.execute(
                """
                INSERT INTO operator_voice_auth_tokens (
                    jti, auth_id, operator_id, device_id, organization_id, role,
                    issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issued.jti,
                    auth_id,
                    operator_id,
                    device_id,
                    organization_id,
                    role,
                    issued.issued_at,
                    issued.expires_at,
                ),
            )
        return result

    def enroll_embedding(
        self, operator_id: str, embedding: list[float], model_name: str, *, threshold: float = 0.86
    ) -> VoiceEnrollmentResult:
        """Import one normalized browser-model centroid without storing raw audio."""
        try:
            normalized = self._normalize(embedding)
        except VoiceEmbeddingError as exc:
            return VoiceEnrollmentResult(False, "INVALID_EMBEDDING", operator_id, 0, str(exc))
        with self.database.connect() as connection:
            operator = connection.execute(
                "SELECT active FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        if operator is None or not operator["active"]:
            return VoiceEnrollmentResult(
                False, "OPERATOR_NOT_AUTHORIZED", operator_id, 0, "The operator is not authorized."
            )
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO operator_voice_profiles
                   (operator_id, embedding, embedding_dimensions, model_name, threshold)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(operator_id) DO UPDATE SET embedding=excluded.embedding,
                   embedding_dimensions=excluded.embedding_dimensions,
                   model_name=excluded.model_name,
                   threshold=excluded.threshold, updated_at=CURRENT_TIMESTAMP""",
                (
                    operator_id, array("f", normalized).tobytes(), len(normalized),
                    model_name, threshold,
                ),
            )
        return VoiceEnrollmentResult(
            True, "VOICE_ENROLLED", operator_id, 1,
            f"Voice enrollment completed for operator {operator_id}.",
        )

    def authenticate_embedding(
        self, device_id: str, embedding: list[float], model_name: str
    ) -> VoiceAuthenticationResult:
        """Authenticate a browser-computed speaker embedding for a 60-second session."""
        auth_id = str(uuid4())
        with self.database.connect() as connection:
            device = connection.execute(
                """SELECT d.operator_id, d.trusted, o.active, c.organization_id, m.role,
                          organizations.active AS organization_active
                   FROM datacenter_devices d JOIN operators o ON o.id=d.operator_id
                   JOIN device_contexts c ON c.device_id=d.id
                   JOIN organizations ON organizations.id=c.organization_id
                   JOIN organization_memberships m ON m.organization_id=c.organization_id
                    AND m.operator_id=d.operator_id WHERE d.id=?""",
                (device_id,),
            ).fetchone()
            profile = (
                connection.execute(
                    "SELECT * FROM operator_voice_profiles WHERE operator_id=?",
                    (device["operator_id"],),
                ).fetchone()
                if device else None
            )
        if device is None or not all(
            (device["trusted"], device["active"], device["organization_active"])
        ):
            return self._record_refusal(
                auth_id, device_id, None, "DEVICE_NOT_AUTHORIZED",
                "I can't verify your voice because this device is not authorized.", None,
            )
        operator_id = str(device["operator_id"])
        if profile is None:
            return self._record_refusal(
                auth_id, device_id, operator_id, "VOICE_NOT_ENROLLED",
                "Your voice is not enrolled. Please contact an administrator.", None,
            )
        if profile["model_name"] != model_name:
            return self._record_refusal(
                auth_id, device_id, operator_id, "VOICE_MODEL_MISMATCH",
                "Your voice profile needs to be enrolled again before continuing.", None,
            )
        try:
            candidate = self._normalize(embedding)
            enrolled = self._embedding_from_row(profile)
            if len(candidate) != len(enrolled):
                raise VoiceEmbeddingError("Voice embedding dimensions do not match")
            score = sum(a * b for a, b in zip(candidate, enrolled, strict=True))
        except VoiceEmbeddingError as exc:
            return self._record_refusal(
                auth_id, device_id, operator_id, "INVALID_AUDIO", str(exc), None
            )
        if score < float(profile["threshold"]):
            return self._record_refusal(
                auth_id, device_id, operator_id, "VOICE_NOT_MATCHED",
                "I couldn't verify your voice. Please try again.", None, score,
            )
        authorization = authorize_session(str(device["role"]))
        if authorization is None:
            return self._record_refusal(
                auth_id, device_id, operator_id, "TASK_NOT_AUTHORIZED",
                "You are not authorized to use this system.", None, score,
            )
        issued = self.signer.issue(
            auth_id=auth_id, operator_id=operator_id, device_id=device_id,
            organization_id=str(device["organization_id"]), roles=list(authorization.roles),
            permissions=list(authorization.permissions), tasks=list(authorization.tasks),
            audio_sha256="browser-embedding", similarity_score=score,
        )
        result = VoiceAuthenticationResult(
            auth_id, True, "VOICE_AUTHENTICATED",
            f"{self._operator_name(operator_id)}, you are authenticated. Proceed inside.",
            operator_id, device_id, str(device["organization_id"]), authorization.roles,
            authorization.permissions, authorization.tasks, round(score, 6), issued.token,
            issued.expires_at,
        )
        with self.database.transaction() as connection:
            self._insert_event(connection, result, None)
            connection.execute(
                """INSERT INTO operator_voice_auth_tokens
                   (jti, auth_id, operator_id, device_id, organization_id, role,
                    issued_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (issued.jti, auth_id, operator_id, device_id, device["organization_id"],
                 device["role"], issued.issued_at, issued.expires_at),
            )
        return result

    def _operator_name(self, operator_id: str) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT name FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        return str(row["name"]) if row else operator_id

    def reject_invalid_audio(self, device_id: str, message: str) -> VoiceAuthenticationResult:
        return self.reject_request(device_id, "INVALID_AUDIO", message)

    def reject_request(
        self, device_id: str, code: str, message: str
    ) -> VoiceAuthenticationResult:
        with self.database.connect() as connection:
            device = connection.execute(
                "SELECT operator_id FROM datacenter_devices WHERE id = ?", (device_id,)
            ).fetchone()
        return self._record_refusal(
            str(uuid4()),
            device_id,
            str(device["operator_id"]) if device is not None else None,
            code,
            message,
            None,
        )

    def verify_token(self, token: str) -> dict[str, Any]:
        claims = self.signer.verify(token)
        with self.database.connect() as connection:
            stored = connection.execute(
                """
                SELECT operator_id, device_id, organization_id, role, expires_at
                FROM operator_voice_auth_tokens
                WHERE jti = ? AND auth_id = ?
                """,
                (claims["jti"], claims["auth_id"]),
            ).fetchone()
        if stored is None:
            raise VoiceTokenError("Voice authentication token is not recognized")
        if stored["operator_id"] != claims["sub"] or stored["device_id"] != claims["device_id"]:
            raise VoiceTokenError("Voice authentication token claims do not match")
        if stored["organization_id"] != claims["organization_id"]:
            raise VoiceTokenError("Voice authentication organization claims do not match")
        expected = (
            authorize_session(str(stored["role"]))
            if len(claims["tasks"]) > 1
            else authorize_task(str(stored["role"]), str(claims["tasks"][0]))
        )
        if (
            expected is None
            or tuple(claims["roles"]) != expected.roles
            or tuple(claims["permissions"]) != expected.permissions
            or tuple(claims["tasks"]) != expected.tasks
        ):
            raise VoiceTokenError("Voice authorization policy claims do not match")
        return claims

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT auth_id, attempted_at, operator_id, device_id, authenticated,
                       code, similarity_score, audio_sha256, spoken_message
                FROM operator_voice_auth_events
                ORDER BY id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) | {"authenticated": bool(row["authenticated"])} for row in rows]

    def _record_refusal(
        self,
        auth_id: str,
        device_id: str,
        operator_id: str | None,
        code: str,
        message: str,
        audio_sha256: str | None,
        score: float | None = None,
    ) -> VoiceAuthenticationResult:
        result = VoiceAuthenticationResult(
            auth_id=auth_id,
            authenticated=False,
            code=code,
            spoken_message=message,
            operator_id=operator_id,
            device_id=device_id,
            similarity_score=round(score, 6) if score is not None else None,
        )
        with self.database.transaction() as connection:
            self._insert_event(connection, result, audio_sha256)
        return result

    @staticmethod
    def _insert_event(
        connection, result: VoiceAuthenticationResult, audio_sha256: str | None
    ) -> None:
        connection.execute(
            """
            INSERT INTO operator_voice_auth_events (
                auth_id, operator_id, device_id, authenticated, code,
                similarity_score, audio_sha256, spoken_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.auth_id,
                result.operator_id,
                result.device_id,
                int(result.authenticated),
                result.code,
                result.similarity_score,
                audio_sha256,
                result.spoken_message,
            ),
        )

    @staticmethod
    def _embedding_from_row(row) -> list[float]:
        values = array("f")
        values.frombytes(row["embedding"])
        if len(values) != row["embedding_dimensions"]:
            raise VoiceEmbeddingError("Stored voice profile is corrupt")
        return list(values)

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        if not values or not all(math.isfinite(value) for value in values):
            raise VoiceEmbeddingError("Voice embedding is empty or invalid")
        magnitude = math.sqrt(sum(value * value for value in values))
        if magnitude == 0:
            raise VoiceEmbeddingError("Voice embedding has zero magnitude")
        return [value / magnitude for value in values]
