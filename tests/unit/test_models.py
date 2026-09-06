import pytest

from export_pipeline.common.models import (
    ExportManifest,
    ExportRequest,
    SliceState,
    ValidationError,
)


def test_export_request_uses_defaults() -> None:
    request = ExportRequest.from_dict(
        {
            "requestId": "monthly-export",
            "indexName": "customers",
        }
    )

    assert request.query == {"match_all": {}}
    assert request.page_size == 1_000
    assert request.slice_count == 16


def test_export_request_rejects_empty_request_id() -> None:
    with pytest.raises(
        ValidationError,
        match="requestId",
    ):
        ExportRequest.from_dict(
            {
                "requestId": "",
                "indexName": "customers",
            }
        )


def test_export_request_rejects_boolean_page_size() -> None:
    with pytest.raises(
        ValidationError,
        match="pageSize",
    ):
        ExportRequest.from_dict(
            {
                "requestId": "monthly-export",
                "indexName": "customers",
                "pageSize": True,
            }
        )


def test_slice_state_round_trip() -> None:
    source = {
        "exportId": "export-123",
        "pitId": "pit-123",
        "sliceId": 2,
        "sliceCount": 4,
        "pageNumber": 5,
        "searchAfter": [100, "doc-100"],
        "pageSize": 1_000,
        "bucket": "exports-bucket",
        "query": {"match_all": {}},
        "totalDocuments": 5_000,
        "totalFiles": 5,
    }

    state = SliceState.from_dict(source)

    assert state.to_workflow_dict() == source


def test_slice_id_must_be_inside_slice_count() -> None:
    with pytest.raises(
        ValidationError,
        match="less than sliceCount",
    ):
        SliceState.from_dict(
            {
                "exportId": "export-123",
                "pitId": "pit-123",
                "sliceId": 4,
                "sliceCount": 4,
                "bucket": "exports-bucket",
            }
        )


def test_manifest_uses_workflow_field_names() -> None:
    manifest = ExportManifest(
        export_id="export-123",
        status="COMPLETED",
        index_name="customers",
        document_count=10_000,
        file_count=10,
        slice_count=4,
        output_prefix="exports/export-123/data/",
        started_at="2026-09-06T08:00:00Z",
        completed_at="2026-09-06T08:05:00Z",
    )

    result = manifest.to_dict()

    assert result["exportId"] == "export-123"
    assert result["indexName"] == "customers"
    assert result["documentCount"] == 10_000
    assert result["outputPrefix"] == "exports/export-123/data/"
