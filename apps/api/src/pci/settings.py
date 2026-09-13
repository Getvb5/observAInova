from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    object_storage_endpoint: str
    object_storage_bucket: str
    object_storage_access_key: str = "pci"
    object_storage_secret_key: str = "change-me-in-development"
