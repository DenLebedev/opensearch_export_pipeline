import gzip
import json
from unittest.mock import MagicMock

import pytest

from export_pipeline.common.s3_client import (
    ExportS3Client,
    build_page_key,
    compress_gzip,
    serialize_json_lines,
)


def test_build_page_key() -> None:
    result = build_page_key(
        export_id="export-123",
        slice_id=2,
        page_number=15,
    )

    assert result == (
        "exports/export-123/data/"
        "slice=0002/"
        "part-000015.jsonl.gz"
    )


def test_build_page_key_rejects_negative_page() -> None:
    with pytest.raises(
        ValueError,
        match="page_number",
    ):
        build_page_key(
            export_id="export-123",
            slice_id=2,
            page_number=-1,
        )


def test_serialize_json_lines() -> None:
    documents = [
        {
            "_id": "1",
            "_source": {
                "name": "Alice",
            },
        },
        {
            "_id": "2",
            "_source": {
                "name": "Боб",
            },
        },
    ]

    result = serialize_json_lines(documents)
    lines = result.decode("utf-8").splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0]) == documents[0]
    assert json.loads(lines[1]) == documents[1]


def test_gzip_is_deterministic() -> None:
    content = b'{"id":"1"}\n'

    first = compress_gzip(content)
    second = compress_gzip(content)

    assert first == second
    assert gzip.decompress(first) == content


def test_write_page_uploads_gzip_object() -> None:
    client = MagicMock()
    client.put_object.return_value = {
        "ETag": '"etag-123"',
    }

    export_client = ExportS3Client(client)

    documents = [
        {
            "_id": "customer-1",
            "_index": "customers",
            "_source": {
                "name": "Alice",
            },
        }
    ]

    result = export_client.write_page(
        bucket="exports-bucket",
        export_id="export-123",
        slice_id=2,
        page_number=5,
        documents=documents,
    )

    assert result.bucket == "exports-bucket"
    assert result.key == (
        "exports/export-123/data/"
        "slice=0002/"
        "part-000005.jsonl.gz"
    )
    assert result.document_count == 1
    assert result.etag == '"etag-123"'

    arguments = client.put_object.call_args.kwargs

    assert arguments["Bucket"] == "exports-bucket"
    assert arguments["Key"] == result.key
    assert arguments["ContentEncoding"] == "gzip"

    decompressed = gzip.decompress(arguments["Body"])
    exported_document = json.loads(
        decompressed.decode("utf-8")
    )

    assert exported_document == documents[0]


def test_write_page_rejects_empty_documents() -> None:
    client = MagicMock()
    export_client = ExportS3Client(client)

    with pytest.raises(
        ValueError,
        match="documents",
    ):
        export_client.write_page(
            bucket="exports-bucket",
            export_id="export-123",
            slice_id=0,
            page_number=0,
            documents=[],
        )

    client.put_object.assert_not_called()

def test_write_json_object() -> None:
    client = MagicMock()
    client.put_object.return_value = {
        "ETag": '"manifest-etag"',
    }

    export_client = ExportS3Client(client)

    value = {
        "exportId": "export-123",
        "status": "COMPLETED",
    }

    result = export_client.write_json(
        bucket="exports-bucket",
        key="exports/export-123/manifest.json",
        value=value,
        metadata={
            "export-id": "export-123",
        },
    )

    assert result.bucket == "exports-bucket"
    assert result.key == (
        "exports/export-123/manifest.json"
    )
    assert result.etag == '"manifest-etag"'

    arguments = client.put_object.call_args.kwargs

    assert arguments["ContentType"] == (
        "application/json"
    )
    assert arguments["Metadata"] == {
        "export-id": "export-123",
    }

    stored_value = json.loads(
        arguments["Body"].decode("utf-8")
    )

    assert stored_value == value