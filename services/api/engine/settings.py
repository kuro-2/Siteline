"""Single source of configuration for the API and the engine.

Values come from environment variables, then the repo-root `.env`. Nothing here has a
made-up default for a secret: secrets default to empty and callers must check them with
`require()` so the owner gets a clear message naming the exact variable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[1]
# In the repo: services/api → repo root. In the Docker image (/app) there is no repo root.
REPO_ROOT = API_DIR.parents[1] if len(API_DIR.parents) > 1 else API_DIR


class MissingSetting(RuntimeError):
    """Raised when a required env var is empty."""

    def __init__(self, name: str, why: str) -> None:
        super().__init__(f"{name} is not set. {why} Add it to .env (see .env.example).")
        self.name = name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(API_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Nukkad"
    app_env: str = "local"
    web_origin: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    contact_email: str = ""

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    database_url: str = ""

    pilot_area_slug: str = "pilot"
    pilot_area_name: str = ""
    pilot_boundary_path: str = "data/pilot_boundary.geojson"

    worldpop_raster_path: str = ""
    worldpop_year: int = 2020
    wards_geojson_path: str = ""
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    ohsome_url: str = "https://api.ohsome.org/v1"

    google_places_api_key: str = ""
    google_monthly_call_cap: int = 4500
    google_cache_days: int = 30
    google_ingest_confirmed: bool = False
    google_ratings_enabled: bool = False
    google_reviews_enabled: bool = False
    google_refresh_enabled: bool = False

    llm_provider: str = "template"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""

    kobo_base_url: str = "https://kf.kobotoolbox.org"
    kobo_api_token: str = ""
    kobo_asset_uid: str = ""
    consent_version: str = "2026-11-v1"
    device_hash_salt: str = ""

    sentry_dsn: str = ""

    def require(self, field: str, why: str = "") -> str:
        value = getattr(self, field)
        if value in ("", None):
            raise MissingSetting(field.upper(), why)
        return str(value)

    def repo_path(self, value: str) -> Path:
        """Resolve a path from .env relative to the repo root."""
        p = Path(value)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def user_agent(self) -> str:
        contact = self.contact_email or "contact-not-set"
        return f"{self.app_name}/0.1 (+{self.web_origin}; {contact})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
