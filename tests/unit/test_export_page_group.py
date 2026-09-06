from unittest.mock import MagicMock

import pytest

from export_pipeline.common.config import Settings
from export_pipeline.common.opensearch_client import (
    SearchPage,
)
from export_pipeline.common.s3_client import S3ObjectInfo
from export_pipeline.export_page_group.handler import (
    InsufficientExecutionTimeError,
    process_page_group,
)


def create_settings(
    *,
    max_pages: int = 5,
    safety_margin_ms: int = 30_000,
) -> Settings:
    return Settings(
        opensearch_endpoint=("https://search.example.com"),
        export_bucket="exports-bucket",
        export_table="export-jobs",
        aws_region="eu-central-1",
        pit_keep_alive="10m",
        default_page_size=1_000,
        default_slice_count=4,
        max_pages_per_invocation=max_pages,
        lambda_safety_margin_ms=safety_margin_ms,
    )


def create_event() -> dict:
    return {
        "exportId": "export-123",
        "pitId": "pit-123",
        "sliceId": 2,
        "sliceCount": 4,
        "pageNumber": 0,
        "searchAfter": None,
        "pageSize": 2,
        "bucket": "exports-bucket",
        "query": {"match_all": {}},
        "totalDocuments": 0,
        "totalFiles": 0,
    }


def create_s3_result(
    page_number: int,
    document_count: int,
) -> S3ObjectInfo:
    return S3ObjectInfo(
        bucket="exports-bucket",
        key=(f"exports/export-123/data/slice=0002/part-{page_number:06d}.jsonl.gz"),
        document_count=document_count,
        compressed_size=100,
        etag='"etag-123"',
    )


def test_processes_multiple_pages() -> None:
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 120_000

    opensearch_client = MagicMock()
    opensearch_client.search_page.side_effect = [
        SearchPage(
            documents=[
                {"_id": "1"},
                {"_id": "2"},
            ],
            next_search_after=[2],
            has_more=True,
        ),
        SearchPage(
            documents=[
                {"_id": "3"},
                {"_id": "4"},
            ],
            next_search_after=[4],
            has_more=True,
        ),
    ]

    s3_client = MagicMock()
    s3_client.write_page.side_effect = [
        create_s3_result(0, 2),
        create_s3_result(1, 2),
    ]

    result = process_page_group(
        event=create_event(),
        context=context,
        settings=create_settings(max_pages=2),
        opensearch_client=opensearch_client,
        s3_client=s3_client,
    )

    assert result["pageNumber"] == 2
    assert result["searchAfter"] == [4]
    assert result["totalDocuments"] == 4
    assert result["totalFiles"] == 2
    assert result["documentsProcessed"] == 4
    assert result["filesWritten"] == 2
    assert result["hasMore"] is True

    assert opensearch_client.search_page.call_count == 2
    assert s3_client.write_page.call_count == 2


def test_stops_after_final_partial_page() -> None:
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 120_000

    opensearch_client = MagicMock()
    opensearch_client.search_page.return_value = SearchPage(
        documents=[
            {"_id": "1"},
        ],
        next_search_after=[1],
        has_more=False,
    )

    s3_client = MagicMock()
    s3_client.write_page.return_value = create_s3_result(0, 1)

    result = process_page_group(
        event=create_event(),
        context=context,
        settings=create_settings(),
        opensearch_client=opensearch_client,
        s3_client=s3_client,
    )

    assert result["pageNumber"] == 1
    assert result["searchAfter"] == [1]
    assert result["totalDocuments"] == 1
    assert result["totalFiles"] == 1
    assert result["hasMore"] is False

    opensearch_client.search_page.assert_called_once()
    s3_client.write_page.assert_called_once()


def test_stops_on_empty_page_without_writing_s3() -> None:
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 120_000

    opensearch_client = MagicMock()
    opensearch_client.search_page.return_value = SearchPage(
        documents=[],
        next_search_after=None,
        has_more=False,
    )

    s3_client = MagicMock()

    result = process_page_group(
        event=create_event(),
        context=context,
        settings=create_settings(),
        opensearch_client=opensearch_client,
        s3_client=s3_client,
    )

    assert result["pageNumber"] == 0
    assert result["searchAfter"] is None
    assert result["totalDocuments"] == 0
    assert result["totalFiles"] == 0
    assert result["documentsProcessed"] == 0
    assert result["filesWritten"] == 0
    assert result["hasMore"] is False

    s3_client.write_page.assert_not_called()


def test_stops_before_timeout_after_completed_page() -> None:
    context = MagicMock()
    context.get_remaining_time_in_millis.side_effect = [
        120_000,
        20_000,
    ]

    opensearch_client = MagicMock()
    opensearch_client.search_page.return_value = SearchPage(
        documents=[
            {"_id": "1"},
            {"_id": "2"},
        ],
        next_search_after=[2],
        has_more=True,
    )

    s3_client = MagicMock()
    s3_client.write_page.return_value = create_s3_result(0, 2)

    result = process_page_group(
        event=create_event(),
        context=context,
        settings=create_settings(
            max_pages=5,
            safety_margin_ms=30_000,
        ),
        opensearch_client=opensearch_client,
        s3_client=s3_client,
    )

    assert result["pageNumber"] == 1
    assert result["searchAfter"] == [2]
    assert result["hasMore"] is True

    opensearch_client.search_page.assert_called_once()
    s3_client.write_page.assert_called_once()


def test_fails_if_no_page_can_be_started() -> None:
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 20_000

    opensearch_client = MagicMock()
    s3_client = MagicMock()

    with pytest.raises(
        InsufficientExecutionTimeError,
        match="does not have enough",
    ):
        process_page_group(
            event=create_event(),
            context=context,
            settings=create_settings(
                safety_margin_ms=30_000,
            ),
            opensearch_client=opensearch_client,
            s3_client=s3_client,
        )

    opensearch_client.search_page.assert_not_called()
    s3_client.write_page.assert_not_called()


def test_continues_from_existing_checkpoint() -> None:
    event = create_event()
    event.update(
        {
            "pageNumber": 10,
            "searchAfter": [100],
            "totalDocuments": 20,
            "totalFiles": 10,
        }
    )

    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 120_000

    opensearch_client = MagicMock()
    opensearch_client.search_page.return_value = SearchPage(
        documents=[
            {"_id": "21"},
        ],
        next_search_after=[101],
        has_more=False,
    )

    s3_client = MagicMock()
    s3_client.write_page.return_value = create_s3_result(10, 1)

    result = process_page_group(
        event=event,
        context=context,
        settings=create_settings(),
        opensearch_client=opensearch_client,
        s3_client=s3_client,
    )

    assert result["pageNumber"] == 11
    assert result["totalDocuments"] == 21
    assert result["totalFiles"] == 11

    search_arguments = opensearch_client.search_page.call_args.kwargs

    assert search_arguments["search_after"] == [100]

    write_arguments = s3_client.write_page.call_args.kwargs

    assert write_arguments["page_number"] == 10
