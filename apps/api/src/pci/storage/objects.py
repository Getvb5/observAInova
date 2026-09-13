import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from pci.ingestion.contracts import HarvestedRecord
from pci.models.enums import RightsPolicy
from pci.settings import Settings

COPY_POLICIES = frozenset(
    {RightsPolicy.OPEN_COPY, RightsPolicy.INSTITUTION_AUTHORIZED_COPY}
)


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    checksum: str
    media_type: str
    byte_length: int
    rights_snapshot: str | None
    source_url: str | None


class ObjectStore(Protocol):
    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None: ...


class S3ObjectStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        self.bucket = bucket
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def put_object(
        self, key: str, content: bytes, media_type: str, metadata: dict[str, str]
    ) -> None:
        self._ensure_bucket()
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=media_type,
            Metadata=metadata,
        )

    def _ensure_bucket(self) -> None:
        """Idempotently make the configured MinIO/S3 bucket available before a write."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            if not _bucket_not_found(error):
                raise
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except ClientError as create_error:
                if not _bucket_already_owned(create_error):
                    raise


def store_full_text_if_permitted(
    record: HarvestedRecord,
    policy: RightsPolicy,
    *,
    object_store: ObjectStore | None = None,
    object_key: str | None = None,
) -> StoredObject | None:
    stored = describe_full_text_if_permitted(record, policy, object_key=object_key)
    if stored is None or record.full_text is None:
        return None

    target = object_store if object_store is not None else _default_object_store()
    target.put_object(
        stored.key,
        record.full_text,
        stored.media_type,
        _object_metadata(stored),
    )
    return stored


def describe_full_text_if_permitted(
    record: HarvestedRecord,
    policy: RightsPolicy,
    *,
    object_key: str | None = None,
) -> StoredObject | None:
    if policy not in COPY_POLICIES or record.full_text is None:
        return None

    checksum = hashlib.sha256(record.full_text).hexdigest()
    media_type = record.media_type or "application/octet-stream"
    key = object_key or _provenance_object_key(record, checksum)
    return StoredObject(
        key=key,
        checksum=checksum,
        media_type=media_type,
        byte_length=len(record.full_text),
        rights_snapshot=record.rights,
        source_url=record.source_url,
    )


def _provenance_object_key(record: HarvestedRecord, checksum: str) -> str:
    provenance = json.dumps(
        {
            "rights": record.rights,
            "source_identifier": record.source_identifier,
            "source_url": record.source_url,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    provenance_checksum = hashlib.sha256(provenance).hexdigest()
    return f"full-text/{provenance_checksum}/{checksum}"


def _object_metadata(stored: StoredObject) -> dict[str, str]:
    return {
        "checksum": stored.checksum,
        "byte_length": str(stored.byte_length),
        "metadata_encoding": "base64url-utf8",
        "rights_snapshot": _base64url_utf8(stored.rights_snapshot),
        "source_url": _base64url_utf8(stored.source_url),
    }


def _base64url_utf8(value: str | None) -> str:
    return base64.urlsafe_b64encode((value or "").encode("utf-8")).decode("ascii")


def _bucket_not_found(error: ClientError) -> bool:
    response = error.response
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchBucket", "NotFound"} or status == 404


def _bucket_already_owned(error: ClientError) -> bool:
    return str(error.response.get("Error", {}).get("Code", "")) == "BucketAlreadyOwnedByYou"


def _default_object_store() -> ObjectStore:
    settings = Settings()  # type: ignore[call-arg]
    return S3ObjectStore(
        endpoint_url=settings.object_storage_endpoint,
        bucket=settings.object_storage_bucket,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
    )
