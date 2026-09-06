from unittest.mock import MagicMock

import pytest

from export_pipeline.common.models import ValidationError
from export_pipeline.finalize_export.handler import (
    _manifest_key,
    _summarize_slices,
    process_finalize_export,
)


def create_event() -> dict:
    return {
        "requestId": "request-123",
        "exportId": "export-123",
        "indexName": "customers",
        "bucket": "exports-bucket",
        "outputPrefix": "exports/export-123/",
        "startedAt": "2026-09-06T08:00:00+00:00",
        "sliceCount": 2,
        "sliceResults": [
            {
                "sliceId": 0,
                "totalDocuments": 1_000,
                "totalFiles": 2,
                "hasMore": False,
            },
            {
                "sliceId": 1,
                "totalDocuments": 1_500,
                "totalFiles": 3,
                "hasMore": False,
            },
        ],
    }


def test_builds_manifest_key() -> None:
    assert _manifest_key(
        "exports/export-123/"
    ) == "exports/export-123/manifest.json"


def test_summarizes_slices() -> None:
    documents, files = _summarize_slices(
        slice_results=create_event()["sliceResults"],
        expected_slice_count=2,
    )

    assert documents == 2_500
    assert files == 5


def test_rejects_duplicate_slice() -> None:
    event = create_event()
    event["sliceResults"][1]["sliceId"] = 0

    with pytest.raises(
        ValidationError,
        match="Duplicate sliceId",
    ):
        _summarize_slices(
            slice_results=event["sliceResults"],
            expected_slice_count=2,
        )


def test_rejects_incomplete_slice() -> None:
    event = create_event()
    event["sliceResults"][1]["hasMore"] = True

    with pytest.raises(
        ValidationError,
        match="not complete",
    ):
        _summarize_slices(
            slice_results=event["sliceResults"],
            expected_slice_count=2,
        )


def test_rejects_missing_slice_result() -> None:
    event = create_event()
    event["sliceResults"].pop()

    with pytest.raises(
        ValidationError,
        match="does not match",
    ):
        _summarize_slices(
            slice_results=event["sliceResults"],
            expected_slice_count=2,
        )


def test_finalizes_export() -> None:
    s3_client = MagicMock()
    job_store = MagicMock()

    result = process_finalize_export(
        event=create_event(),
        s3_client=s3_client,
        job_store=job_store,
        now_factory=lambda: (
            "2026-09-06T08:10:00+00:00"
        ),
    )

    assert result == {
        "requestId": "request-123",
        "exportId": "export-123",
        "status": "COMPLETED",
        "documentCount": 2_500,
        "fileCount": 5,
        "manifestKey": (
            "exports/export-123/manifest.json"
        ),
        "outputLocation": (
            "s3://exports-bucket/"
            "exports/export-123/data/"
        ),
        "completedAt": (
            "2026-09-06T08:10:00+00:00"
        ),
    }

    s3_client.write_json.assert_called_once()

    write_arguments = (
        s3_client.write_json.call_args.kwargs
    )

    assert write_arguments["bucket"] == (
        "exports-bucket"
    )
    assert write_arguments["key"] == (
        "exports/export-123/manifest.json"
    )
    assert (
        write_arguments["value"]["documentCount"]
        == 2_500
    )
    assert (
        write_arguments["value"]["status"]
        == "COMPLETED"
    )

    job_store.mark_completed.assert_called_once_with(
        request_id="request-123",
        export_id="export-123",
        document_count=2_500,
        file_count=5,
        manifest_key=(
            "exports/export-123/manifest.json"
        ),
        completed_at=(
            "2026-09-06T08:10:00+00:00"
        ),
    )


def test_rejects_incorrect_output_prefix() -> None:
    event = create_event()
    event["outputPrefix"] = "exports/another-export/"

    with pytest.raises(
        ValidationError,
        match="does not match exportId",
    ):
        process_finalize_export(
            event=event,
            s3_client=MagicMock(),
            job_store=MagicMock(),
        )