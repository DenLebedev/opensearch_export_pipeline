from unittest.mock import MagicMock

import pytest

from export_pipeline.common.config import Settings
from export_pipeline.initialize_export.handler import (
    _build_slices,
    _calculate_query_hash,
    process_initialize_export,
)


def create_settings() -> Settings:
    return Settings(
        opensearch_endpoint=(
            "https://search.example.com"
        ),
        export_bucket="exports-bucket",
        export_table="export-jobs",
        aws_region="eu-central-1",
        pit_keep_alive="10m",
        default_page_size=1_000,
        default_slice_count=4,
        max_pages_per_invocation=5,
        lambda_safety_margin_ms=30_000,
    )


def create_event() -> dict:
    return {
        "requestId": "request-123",
        "indexName": "customers",
        "query": {
            "term": {
                "country": "TR",
            }
        },
        "pageSize": 500,
        "sliceCount": 4,
    }


def test_builds_slice_list() -> None:
    assert _build_slices(3) == [
        {
            "sliceId": 0,
            "sliceCount": 3,
        },
        {
            "sliceId": 1,
            "sliceCount": 3,
        },
        {
            "sliceId": 2,
            "sliceCount": 3,
        },
    ]


def test_query_hash_is_stable() -> None:
    first_query = {
        "bool": {
            "filter": [
                {
                    "term": {
                        "country": "TR",
                    }
                }
            ]
        }
    }

    second_query = {
        "bool": {
            "filter": [
                {
                    "term": {
                        "country": "TR",
                    }
                }
            ]
        }
    }

    assert _calculate_query_hash(
        first_query
    ) == _calculate_query_hash(second_query)


def test_initializes_new_export() -> None:
    opensearch_client = MagicMock()
    opensearch_client.create_pit.return_value = (
        "pit-123"
    )

    job_store = MagicMock()
    job_store.try_create_job.return_value = True

    timestamps = iter(
        [
            "2026-09-06T08:00:00+00:00",
            "2026-09-06T08:00:01+00:00",
        ]
    )

    result = process_initialize_export(
        event=create_event(),
        settings=create_settings(),
        opensearch_client=opensearch_client,
        job_store=job_store,
        now_factory=lambda: next(timestamps),
        id_factory=lambda: "export-123",
    )

    assert result["alreadyExists"] is False
    assert result["exportId"] == "export-123"
    assert result["pitId"] == "pit-123"
    assert result["pageSize"] == 500
    assert result["sliceCount"] == 4
    assert len(result["slices"]) == 4

    job_store.try_create_job.assert_called_once()
    job_store.mark_running.assert_called_once()

    opensearch_client.create_pit.assert_called_once_with(
        index_name="customers",
        keep_alive="10m",
    )


def test_returns_existing_export() -> None:
    opensearch_client = MagicMock()

    job_store = MagicMock()
    job_store.try_create_job.return_value = False
    job_store.get_job.return_value = {
        "requestId": "request-123",
        "exportId": "existing-export",
        "status": "RUNNING",
        "outputPrefix": (
            "exports/existing-export/"
        ),
    }

    result = process_initialize_export(
        event=create_event(),
        settings=create_settings(),
        opensearch_client=opensearch_client,
        job_store=job_store,
        now_factory=lambda: (
            "2026-09-06T08:00:00+00:00"
        ),
        id_factory=lambda: "unused-export",
    )

    assert result == {
        "alreadyExists": True,
        "requestId": "request-123",
        "exportId": "existing-export",
        "status": "RUNNING",
        "outputPrefix": (
            "exports/existing-export/"
        ),
    }

    opensearch_client.create_pit.assert_not_called()
    job_store.mark_running.assert_not_called()


def test_marks_job_failed_when_pit_creation_fails() -> None:
    opensearch_client = MagicMock()
    opensearch_client.create_pit.side_effect = (
        RuntimeError("OpenSearch unavailable")
    )

    job_store = MagicMock()
    job_store.try_create_job.return_value = True

    timestamps = iter(
        [
            "2026-09-06T08:00:00+00:00",
            "2026-09-06T08:00:01+00:00",
        ]
    )

    with pytest.raises(
        RuntimeError,
        match="OpenSearch unavailable",
    ):
        process_initialize_export(
            event=create_event(),
            settings=create_settings(),
            opensearch_client=opensearch_client,
            job_store=job_store,
            now_factory=lambda: next(timestamps),
            id_factory=lambda: "export-123",
        )

    job_store.mark_failed.assert_called_once()

    failure_arguments = (
        job_store.mark_failed.call_args.kwargs
    )

    assert (
        failure_arguments["request_id"]
        == "request-123"
    )
    assert (
        failure_arguments["export_id"]
        == "export-123"
    )
    assert (
        failure_arguments["error_code"]
        == "RuntimeError"
    )


def test_closes_pit_when_mark_running_fails() -> None:
    opensearch_client = MagicMock()
    opensearch_client.create_pit.return_value = (
        "pit-123"
    )

    job_store = MagicMock()
    job_store.try_create_job.return_value = True
    job_store.mark_running.side_effect = RuntimeError(
        "DynamoDB unavailable"
    )

    timestamps = iter(
        [
            "2026-09-06T08:00:00+00:00",
            "2026-09-06T08:00:01+00:00",
            "2026-09-06T08:00:02+00:00",
        ]
    )

    with pytest.raises(
        RuntimeError,
        match="DynamoDB unavailable",
    ):
        process_initialize_export(
            event=create_event(),
            settings=create_settings(),
            opensearch_client=opensearch_client,
            job_store=job_store,
            now_factory=lambda: next(timestamps),
            id_factory=lambda: "export-123",
        )

    opensearch_client.close_pit.assert_called_once_with(
        "pit-123"
    )

    job_store.mark_failed.assert_called_once()