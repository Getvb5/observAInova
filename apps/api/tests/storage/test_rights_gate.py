import base64
from dataclasses import replace
from typing import Any, cast

import pytest
from botocore.exceptions import ClientError

from pci.ingestion.contracts import HarvestedRecord
from pci.models.enums import RightsPolicy
from pci.storage import objects
from pci.storage.objects import S3ObjectStore, store_full_text_if_permitted


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        self.objects[key] = (content, media_type, metadata)

    def keys(self) -> list[str]:
        return list(self.objects)


@pytest.fixture
def object_store() -> MemoryObjectStore:
    return MemoryObjectStore()


@pytest.fixture
def harvested_record() -> HarvestedRecord:
    return HarvestedRecord(
        source_identifier="oai:sample:1",
        payload={"title": "Sample"},
        source_url="https://repo.example/items/1",
        rights="CC BY 4.0",
        full_text=b"full text",
        media_type="text/plain",
    )


@pytest.mark.parametrize("policy", [RightsPolicy.METADATA_ONLY, RightsPolicy.LINK_ONLY])
def test_full_text_is_not_stored_without_permission(
    object_store: MemoryObjectStore, harvested_record: HarvestedRecord, policy: RightsPolicy
) -> None:
    """Opening either closed policy must copy bytes that policy forbids."""
    stored = store_full_text_if_permitted(
        harvested_record, policy, object_store=object_store
    )

    assert stored is None
    assert object_store.keys() == []


def test_unknown_policy_never_resolves_or_writes_an_object_store(
    monkeypatch: pytest.MonkeyPatch, harvested_record: HarvestedRecord
) -> None:
    """Treating an unknown policy as open must attempt to resolve storage."""
    def fail_if_resolved() -> Any:
        raise AssertionError("object storage must remain untouched")

    monkeypatch.setattr(objects, "_default_object_store", fail_if_resolved)

    stored = store_full_text_if_permitted(
        harvested_record, cast(RightsPolicy, "unknown-policy")
    )

    assert stored is None


@pytest.mark.parametrize(
    "policy",
    [RightsPolicy.OPEN_COPY, RightsPolicy.INSTITUTION_AUTHORIZED_COPY],
)
def test_permitted_copy_records_content_and_rights_metadata(
    object_store: MemoryObjectStore, harvested_record: HarvestedRecord, policy: RightsPolicy
) -> None:
    """Omitting bytes or provenance metadata must make a permitted copy unverifiable."""
    stored = store_full_text_if_permitted(
        harvested_record, policy, object_store=object_store
    )

    assert stored is not None
    assert stored.key.endswith(
        "/6e3da9a2a9be2af0b044c01a4da34343f7f5371a0ffa67eb4b49d6bcebcd2683"
    )
    assert stored.checksum == "6e3da9a2a9be2af0b044c01a4da34343f7f5371a0ffa67eb4b49d6bcebcd2683"
    assert stored.media_type == "text/plain"
    assert stored.byte_length == 9
    assert stored.rights_snapshot == "CC BY 4.0"
    assert stored.source_url == "https://repo.example/items/1"
    assert object_store.objects[stored.key] == (
        b"full text",
        "text/plain",
        {
            "checksum": stored.checksum,
            "byte_length": "9",
            "metadata_encoding": "base64url-utf8",
            "rights_snapshot": "Q0MgQlkgNC4w",
            "source_url": "aHR0cHM6Ly9yZXBvLmV4YW1wbGUvaXRlbXMvMQ==",
        },
    )


def test_same_bytes_from_distinct_provenances_use_distinct_keys(
    object_store: MemoryObjectStore, harvested_record: HarvestedRecord
) -> None:
    """A content-only key must overwrite provenance metadata for equal bytes."""
    other_record = replace(
        harvested_record,
        source_identifier="oai:sample:2",
        source_url="https://repo.example/items/2",
        rights="Cópia autorizada",
    )

    first = store_full_text_if_permitted(
        harvested_record, RightsPolicy.OPEN_COPY, object_store=object_store
    )
    second = store_full_text_if_permitted(
        other_record, RightsPolicy.OPEN_COPY, object_store=object_store
    )

    assert first is not None
    assert second is not None
    assert first.key != second.key
    assert len(object_store.objects) == 2


def test_non_ascii_rights_are_reversibly_encoded_for_s3_metadata(
    object_store: MemoryObjectStore, harvested_record: HarvestedRecord
) -> None:
    """Passing UTF-8 rights directly to S3 metadata must fail parameter validation."""
    record = replace(harvested_record, rights="Cópia autorizada")

    stored = store_full_text_if_permitted(
        record, RightsPolicy.OPEN_COPY, object_store=object_store
    )

    assert stored is not None
    metadata = object_store.objects[stored.key][2]
    assert all(value.isascii() for value in metadata.values())
    assert metadata["metadata_encoding"] == "base64url-utf8"
    assert base64.urlsafe_b64decode(metadata["rights_snapshot"]).decode("utf-8") == (
        "Cópia autorizada"
    )


def test_default_store_uses_configured_minio_credentials(
    monkeypatch: pytest.MonkeyPatch, harvested_record: HarvestedRecord
) -> None:
    """Dropping configured credentials must leave the Compose MinIO store inaccessible."""
    captured: dict[str, Any] = {}

    class CapturingClient:
        def head_bucket(self, **kwargs: Any) -> None:
            captured["head_bucket"] = kwargs

        def put_object(self, **kwargs: Any) -> None:
            captured["put_object"] = kwargs

    def capture_client(service_name: str, **kwargs: Any) -> CapturingClient:
        captured["service_name"] = service_name
        captured["client_options"] = kwargs
        return CapturingClient()

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "pci-objects")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "minio-user")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "minio-secret")
    monkeypatch.setattr(objects.boto3, "client", capture_client)

    store_full_text_if_permitted(harvested_record, RightsPolicy.OPEN_COPY)

    assert captured["service_name"] == "s3"
    assert captured["client_options"] == {
        "endpoint_url": "http://minio:9000",
        "aws_access_key_id": "minio-user",
        "aws_secret_access_key": "minio-secret",
    }
    assert cast(dict[str, Any], captured["put_object"])["Bucket"] == "pci-objects"


class BucketClient:
    def __init__(self, *, missing: bool = False, error_code: str | None = None) -> None:
        self.missing = missing
        self.error_code = error_code
        self.head_calls = 0
        self.create_calls = 0
        self.put_calls = 0

    def head_bucket(self, **kwargs: Any) -> None:
        del kwargs
        self.head_calls += 1
        if self.error_code is not None:
            raise _client_error(self.error_code, 403)
        if self.missing:
            raise _client_error("NoSuchBucket", 404)

    def create_bucket(self, **kwargs: Any) -> None:
        del kwargs
        self.create_calls += 1
        self.missing = False

    def put_object(self, **kwargs: Any) -> None:
        del kwargs
        self.put_calls += 1


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "HeadBucket"
    )


@pytest.mark.parametrize("missing", [False, True])
def test_s3_store_provisions_the_bucket_idempotently_before_each_put(
    monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    """Both existing and newly created buckets must be checked before each write."""
    client = BucketClient(missing=missing)
    monkeypatch.setattr(objects.boto3, "client", lambda *args, **kwargs: client)
    store = S3ObjectStore(
        endpoint_url="http://minio:9000",
        bucket="pci-objects",
        access_key="pci",
        secret_key="secret",
    )

    store.put_object("one", b"one", "text/plain", {})
    store.put_object("two", b"two", "text/plain", {})

    assert client.head_calls == 2
    assert client.create_calls == int(missing)
    assert client.put_calls == 2


def test_s3_store_does_not_mask_non_not_found_bucket_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authentication and permission failures must not be converted into create attempts."""
    client = BucketClient(error_code="AccessDenied")
    monkeypatch.setattr(objects.boto3, "client", lambda *args, **kwargs: client)
    store = S3ObjectStore(
        endpoint_url="http://minio:9000",
        bucket="pci-objects",
        access_key="pci",
        secret_key="secret",
    )

    with pytest.raises(ClientError):
        store.put_object("denied", b"body", "text/plain", {})

    assert client.head_calls == 1
    assert client.create_calls == 0
    assert client.put_calls == 0
