"""S3 storage operations for exported OpenSearch pages."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from typing import Any, Protocol


class S3PutObjectClient(Protocol):
    """Subset of the boto3 S3 client used by this module."""

    def put_object(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Write an object to S3."""


@dataclass(frozen=True, slots=True)
class S3ObjectInfo:
    """Information about a successfully written S3 object."""

    bucket: str
    key: str
    document_count: int
    compressed_size: int
    etag: str | None


@dataclass(frozen=True, slots=True)
class S3JsonObjectInfo:
    """Information about a JSON object written to S3."""

    bucket: str
    key: str
    size: int
    etag: str | None


def build_page_key(
    *,
    export_id: str,
    slice_id: int,
    page_number: int,
) -> str:
    """Build a deterministic key for an exported page."""

    if not export_id:
        raise ValueError("export_id must not be empty")

    if slice_id < 0:
        raise ValueError("slice_id must be non-negative")

    if page_number < 0:
        raise ValueError("page_number must be non-negative")

    return f"exports/{export_id}/data/slice={slice_id:04d}/part-{page_number:06d}.jsonl.gz"


def serialize_json_lines(
    documents: list[dict[str, Any]],
) -> bytes:
    """Serialize documents as UTF-8 JSON Lines."""

    lines = [
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for document in documents
    ]

    content = "\n".join(lines)

    if content:
        content += "\n"

    return content.encode("utf-8")


def compress_gzip(content: bytes) -> bytes:
    """Compress bytes using deterministic gzip metadata."""

    return gzip.compress(
        content,
        compresslevel=6,
        mtime=0,
    )


class ExportS3Client:
    """Writes exported page files to S3."""

    def __init__(
        self,
        client: S3PutObjectClient,
    ) -> None:
        self._client = client

    def write_page(
        self,
        *,
        bucket: str,
        export_id: str,
        slice_id: int,
        page_number: int,
        documents: list[dict[str, Any]],
    ) -> S3ObjectInfo:
        """Serialize, compress and store one page."""

        if not bucket:
            raise ValueError("bucket must not be empty")

        if not documents:
            raise ValueError("documents must not be empty")

        key = build_page_key(
            export_id=export_id,
            slice_id=slice_id,
            page_number=page_number,
        )

        json_lines = serialize_json_lines(documents)
        compressed_content = compress_gzip(json_lines)

        response = self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=compressed_content,
            ContentType="application/x-ndjson",
            ContentEncoding="gzip",
            Metadata={
                "export-id": export_id,
                "slice-id": str(slice_id),
                "page-number": str(page_number),
                "document-count": str(len(documents)),
            },
        )

        etag = response.get("ETag")

        if not isinstance(etag, str):
            etag = None

        return S3ObjectInfo(
            bucket=bucket,
            key=key,
            document_count=len(documents),
            compressed_size=len(compressed_content),
            etag=etag,
        )

    def write_json(
        self,
        *,
        bucket: str,
        key: str,
        value: dict[str, Any],
        metadata: dict[str, str] | None = None,
    ) -> S3JsonObjectInfo:
        """Serialize and write a JSON object to S3."""

        if not bucket:
            raise ValueError("bucket must not be empty")

        if not key:
            raise ValueError("key must not be empty")

        content = (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        response = self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType="application/json",
            Metadata=metadata or {},
        )

        etag = response.get("ETag")

        if not isinstance(etag, str):
            etag = None

        return S3JsonObjectInfo(
            bucket=bucket,
            key=key,
            size=len(content),
            etag=etag,
        )
