from unittest.mock import MagicMock

from export_pipeline.cleanup_export.handler import (
    process_cleanup_export,
)
from export_pipeline.common.config import Settings
from export_pipeline.common.opensearch_client import (
    SearchPage,
)
from export_pipeline.common.s3_client import S3ObjectInfo
from export_pipeline.export_page_group.handler import (
    process_page_group,
)
from export_pipeline.finalize_export.handler import (
    process_finalize_export,
)
from export_pipeline.initialize_export.handler import (
    process_initialize_export,
)


class LambdaContextStub:
    """Lambda context with sufficient execution time."""

    def get_remaining_time_in_millis(self) -> int:
        return 120_000


def create_settings() -> Settings:
    return Settings(
        opensearch_endpoint=("https://search.example.com"),
        export_bucket="exports-bucket",
        export_table="export-jobs",
        aws_region="eu-central-1",
        pit_keep_alive="10m",
        default_page_size=2,
        default_slice_count=2,
        max_pages_per_invocation=5,
        lambda_safety_margin_ms=30_000,
    )


def create_s3_result(
    *,
    slice_id: int,
    page_number: int,
    document_count: int,
) -> S3ObjectInfo:
    return S3ObjectInfo(
        bucket="exports-bucket",
        key=(f"exports/export-123/data/slice={slice_id:04d}/part-{page_number:06d}.jsonl.gz"),
        document_count=document_count,
        compressed_size=100,
        etag='"etag-123"',
    )


def test_successful_pipeline_contract() -> None:
    settings = create_settings()
    job_store = MagicMock()

    initialization_opensearch = MagicMock()
    initialization_opensearch.create_pit.return_value = "pit-123"

    job_store.try_create_job.return_value = True

    timestamps = iter(
        [
            "2026-09-06T08:00:00+00:00",
            "2026-09-06T08:00:01+00:00",
        ]
    )

    initialized = process_initialize_export(
        event={
            "requestId": "request-123",
            "indexName": "customers",
            "query": {"match_all": {}},
            "pageSize": 2,
            "sliceCount": 2,
        },
        settings=settings,
        opensearch_client=initialization_opensearch,
        job_store=job_store,
        now_factory=lambda: next(timestamps),
        id_factory=lambda: "export-123",
    )

    assert initialized["alreadyExists"] is False
    assert initialized["pitId"] == "pit-123"
    assert len(initialized["slices"]) == 2

    slice_documents = {
        0: [
            {
                "_id": "customer-1",
                "_index": "customers",
                "_source": {
                    "name": "Alice",
                },
            }
        ],
        1: [
            {
                "_id": "customer-2",
                "_index": "customers",
                "_source": {
                    "name": "Bob",
                },
            },
            {
                "_id": "customer-3",
                "_index": "customers",
                "_source": {
                    "name": "Charlie",
                },
            },
        ],
    }

    slice_results = []

    for slice_definition in initialized["slices"]:
        slice_id = slice_definition["sliceId"]
        documents = slice_documents[slice_id]

        worker_opensearch = MagicMock()
        worker_opensearch.search_page.side_effect = [
            SearchPage(
                documents=documents,
                next_search_after=[f"slice-{slice_id}-last"],
                has_more=False,
            )
        ]

        worker_s3 = MagicMock()
        worker_s3.write_page.return_value = create_s3_result(
            slice_id=slice_id,
            page_number=0,
            document_count=len(documents),
        )

        slice_event = {
            "requestId": initialized["requestId"],
            "exportId": initialized["exportId"],
            "pitId": initialized["pitId"],
            "indexName": initialized["indexName"],
            "query": initialized["query"],
            "pageSize": initialized["pageSize"],
            "bucket": initialized["bucket"],
            "sliceId": slice_id,
            "sliceCount": slice_definition["sliceCount"],
            "pageNumber": 0,
            "searchAfter": None,
            "totalDocuments": 0,
            "totalFiles": 0,
        }

        slice_result = process_page_group(
            event=slice_event,
            context=LambdaContextStub(),
            settings=settings,
            opensearch_client=worker_opensearch,
            s3_client=worker_s3,
        )

        assert slice_result["hasMore"] is False

        slice_results.append(slice_result)

    cleanup_opensearch = MagicMock()
    cleanup_opensearch.close_pit.return_value = True

    cleanup_result = process_cleanup_export(
        event={
            "requestId": initialized["requestId"],
            "exportId": initialized["exportId"],
            "pitId": initialized["pitId"],
            "outcome": "SUCCESS",
        },
        opensearch_client=cleanup_opensearch,
        job_store=job_store,
    )

    assert cleanup_result["status"] == ("READY_TO_FINALIZE")
    assert cleanup_result["pitClosed"] is True

    finalize_s3 = MagicMock()

    final_result = process_finalize_export(
        event={
            "requestId": initialized["requestId"],
            "exportId": initialized["exportId"],
            "indexName": initialized["indexName"],
            "bucket": initialized["bucket"],
            "outputPrefix": initialized["outputPrefix"],
            "startedAt": initialized["startedAt"],
            "sliceCount": initialized["sliceCount"],
            "sliceResults": slice_results,
        },
        s3_client=finalize_s3,
        job_store=job_store,
        now_factory=lambda: "2026-09-06T08:10:00+00:00",
    )

    assert final_result["status"] == "COMPLETED"
    assert final_result["documentCount"] == 3
    assert final_result["fileCount"] == 2
    assert final_result["manifestKey"] == ("exports/export-123/manifest.json")

    initialization_opensearch.create_pit.assert_called_once()
    cleanup_opensearch.close_pit.assert_called_once_with("pit-123")
    finalize_s3.write_json.assert_called_once()
    job_store.mark_completed.assert_called_once()
