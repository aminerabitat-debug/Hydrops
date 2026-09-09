"""Configuration de l'API, cf. docs/architecture/08-sessions-confidentialite.md."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HYDROPS_")

    software_version: str = "0.1.0"

    # TTL de session ephemere (§8.2). 4h glissantes par defaut, prolongees par heartbeat.
    session_ttl_seconds: int = 4 * 60 * 60
    # Frequence du balayage des sessions expirees (§8.2).
    session_purge_interval_seconds: int = 300

    # "cascade" (reel, Open-Meteo -> OpenTopoData ASTER30m -> Open-Elevation), "open_elevation" /
    # "open_meteo" / "opentopodata" (un seul fournisseur reel) ou "synthetic" (deterministe, hors
    # reseau — tests/CI/dev offline). Voir hydrops_api/services/dem.py.
    dem_provider: str = "cascade"

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
