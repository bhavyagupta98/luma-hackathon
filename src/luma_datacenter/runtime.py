from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .administration import UserAdministrationService
from .config import (
    database_path,
    voice_match_threshold,
    voice_model_path,
    voice_signing_key_path,
    voice_token_audience,
    voice_token_issuer,
    voice_token_ttl_seconds,
)
from .database import Database
from .service import ServerControlService
from .voice_auth import VoiceAuthService
from .voice_embeddings import SpeechBrainECAPAEmbedder, VoiceEmbedder
from .voice_tokens import VoiceTokenSigner


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    database: Database
    actions: ServerControlService
    administration: UserAdministrationService
    voice: VoiceAuthService
    signer: VoiceTokenSigner


def build_runtime(
    path: str | Path | None = None,
    *,
    voice_embedder: VoiceEmbedder | None = None,
    voice_signer: VoiceTokenSigner | None = None,
) -> RuntimeServices:
    configured_database_path = Path(path) if path is not None else database_path()
    database = Database(configured_database_path)
    signer = voice_signer or VoiceTokenSigner(
        (
            configured_database_path.with_suffix(".voice-auth.pem")
            if path is not None
            else voice_signing_key_path()
        ),
        issuer=voice_token_issuer(),
        audience=voice_token_audience(),
        ttl_seconds=voice_token_ttl_seconds(),
    )
    voice = VoiceAuthService(
        database,
        voice_embedder or SpeechBrainECAPAEmbedder(voice_model_path()),
        signer,
        default_threshold=voice_match_threshold(),
    )
    return RuntimeServices(
        database,
        ServerControlService(database),
        UserAdministrationService(database),
        voice,
        signer,
    )
