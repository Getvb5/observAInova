import importlib
from typing import get_type_hints

from dramatiq.brokers.redis import RedisBroker


def test_worker_bootstrap_registers_an_actor_on_the_redis_broker(monkeypatch) -> None:
    """Replacing the Redis broker or omitting the bootstrap actor must fail this test."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://pci:pci@postgres:5432/pci")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "pci-objects")

    worker = importlib.import_module("pci.worker")

    assert isinstance(worker.broker, RedisBroker)
    assert worker.broker.client.connection_pool.connection_kwargs["host"] == "redis"
    assert worker.bootstrap_worker.broker is worker.broker
    assert worker.bootstrap_worker.queue_name == "bootstrap"


def test_worker_registers_serializable_ingestion_actor(monkeypatch) -> None:
    """Fail if the real Dramatiq process cannot discover the source-id actor."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://pci:pci@postgres:5432/pci")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "pci-objects")

    worker = importlib.import_module("pci.worker")

    assert worker.harvest_source_task.broker is worker.broker
    assert worker.harvest_source_task.queue_name == "ingestion"
    assert get_type_hints(worker.harvest_source_task.fn)["source_id"] is str
