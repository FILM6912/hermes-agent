"""FastAPI settings wrapper around legacy api.config env resolution."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """HERMES_WEBUI_* settings; runtime paths delegate to api.config."""

    model_config = SettingsConfigDict(
        env_prefix="HERMES_WEBUI_",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = 8787
    csp_connect_extra: str = ""
    test_network_block: bool = False
    # Phase 5: legacy /api catch-alls off by default (see docs/phase5-decommission.md).
    legacy_api: bool = False

    @property
    def bind_host(self) -> str:
        from app.domain.config import HOST

        return HOST

    @property
    def bind_port(self) -> int:
        from app.domain.config import PORT

        return PORT

    @property
    def tls_enabled(self) -> bool:
        from app.domain.config import TLS_ENABLED

        return TLS_ENABLED

    @property
    def tls_cert(self) -> str | None:
        from app.domain.config import TLS_CERT

        return TLS_CERT

    @property
    def tls_key(self) -> str | None:
        from app.domain.config import TLS_KEY

        return TLS_KEY

    @property
    def state_dir(self):
        from app.domain.config import STATE_DIR

        return STATE_DIR

    @property
    def session_dir(self):
        from app.domain.config import SESSION_DIR

        return SESSION_DIR

    @property
    def default_workspace(self):
        from app.domain.config import DEFAULT_WORKSPACE

        return DEFAULT_WORKSPACE


@lru_cache
def get_settings() -> Settings:
    return Settings()
