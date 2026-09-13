from pci.settings import Settings


def test_settings_read_service_locations_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://pci:pci@postgres:5432/pci")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "pci-objects")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://pci:pci@postgres:5432/pci"
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.object_storage_endpoint == "http://minio:9000"
    assert settings.object_storage_bucket == "pci-objects"
