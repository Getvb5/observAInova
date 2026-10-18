from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    object_storage_endpoint: str
    object_storage_bucket: str
    object_storage_access_key: str = "pci"
    object_storage_secret_key: str = "change-me-in-development"

    app_env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["oidc", "local"] = "local"
    oidc_issuer: str = ""
    oidc_audience: str = "observainova-api"
    oidc_jwks_url: str = ""
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_roles_claim: str = "roles"
    oidc_role_map: dict[str, str] = Field(default_factory=dict)
    local_auth_secret: str = "change-me-in-development"
    local_auth_issuer: str = "observainova-local"

    claims_provider: Literal["deterministic", "http"] = "deterministic"
    claims_endpoint_url: str = "https://example.invalid/extract"
    claims_api_key: str = ""
    claims_model: str = "provider-model"
    claims_timeout: float = 30.0
    claims_schema_version: str = "v1"
    claims_instruction_version: str = "v1"

    publication_relay_interval_seconds: float = Field(default=5.0, gt=0, le=300)
    publication_lease_seconds: int = Field(default=300, ge=10, le=3600)
    document_max_bytes: int = Field(default=100 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    document_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    @model_validator(mode="after")
    def validate_authentication_mode(self) -> "Settings":
        if self.app_env == "production" and self.auth_mode == "local":
            raise ValueError("local authentication is forbidden in production")
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_jwks_url):
            raise ValueError("OIDC authentication requires issuer and JWKS URL")
        return self
