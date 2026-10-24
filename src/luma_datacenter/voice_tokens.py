from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class VoiceTokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedVoiceToken:
    token: str
    jti: str
    issued_at: int
    expires_at: int


class VoiceTokenSigner:
    """Issues and verifies short-lived Ed25519 operator authentication tokens."""

    def __init__(
        self,
        key_path: str | Path,
        *,
        issuer: str,
        audience: str,
        ttl_seconds: int = 60,
    ) -> None:
        if ttl_seconds < 1 or ttl_seconds > 300:
            raise ValueError("Voice token TTL must be between 1 and 300 seconds")
        self.key_path = Path(key_path)
        self.issuer = issuer
        self.audience = audience
        self.ttl_seconds = ttl_seconds
        self._private_key = self._load_or_create_key()
        public_der = self._private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.key_id = hashlib.sha256(public_der).hexdigest()[:16]

    def issue(
        self,
        *,
        auth_id: str,
        operator_id: str,
        device_id: str,
        organization_id: str,
        roles: list[str],
        permissions: list[str],
        tasks: list[str],
        audio_sha256: str,
        similarity_score: float,
    ) -> IssuedVoiceToken:
        issued_at = int(time.time())
        expires_at = issued_at + self.ttl_seconds
        jti = str(uuid4())
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": operator_id,
            "device_id": device_id,
            "organization_id": organization_id,
            "roles": sorted(set(roles)),
            "permissions": sorted(set(permissions)),
            "tasks": sorted(set(tasks)),
            "auth_id": auth_id,
            "audio_sha256": audio_sha256,
            "similarity_score": round(similarity_score, 6),
            "jti": jti,
            "iat": issued_at,
            "exp": expires_at,
        }
        token = jwt.encode(
            payload,
            self._private_key,
            algorithm="EdDSA",
            headers={"kid": self.key_id, "typ": "JWT"},
        )
        return IssuedVoiceToken(token, jti, issued_at, expires_at)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            claims = dict(
                jwt.decode(
                    token,
                    self._private_key.public_key(),
                    algorithms=["EdDSA"],
                    audience=self.audience,
                    issuer=self.issuer,
                    options={
                        "require": [
                            "iss",
                            "aud",
                            "sub",
                            "device_id",
                            "organization_id",
                            "roles",
                            "auth_id",
                            "permissions",
                            "tasks",
                            "jti",
                            "iat",
                            "exp",
                        ]
                    },
                )
            )
        except jwt.PyJWTError as exc:
            raise VoiceTokenError("Invalid or expired voice authentication token") from exc
        for claim_name in ("roles", "permissions", "tasks"):
            values = claims.get(claim_name)
            if not isinstance(values, list) or not values or not all(
                isinstance(value, str) and value for value in values
            ):
                raise VoiceTokenError(f"Voice authorization {claim_name} claim is invalid")
        if len(claims["tasks"]) > 3:
            raise VoiceTokenError("Voice authorization contains too many tasks")
        return claims

    def public_key_pem(self) -> str:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def _load_or_create_key(self) -> Ed25519PrivateKey:
        if self.key_path.exists():
            key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("Voice signing key is not an Ed25519 private key")
            return key

        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(pem)
        return key
