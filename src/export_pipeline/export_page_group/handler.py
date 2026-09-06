"""Lambda handler that exports a bounded group of pages to S3."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from functools import lru_cache
from typing import Any, Protocol

import boto3

from export_pipeline.common.config import Settings
from export_pipeline.common.models import (
    PageGroupResult,
    SliceState,
)
from export_pipeline.common.opensearch_client import (
    OpenSearchExportClient,
    create_aws_opensearch_client,
)
from export_pipeline.common.s3_client import ExportS3Client

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


class LambdaContext(Protocol):
    """Part of the AWS Lambda context used by this handler."""

    def get_remaining_time_in_millis(self) -> int:
        """Return the remaining Lambda execution time."""


class InsufficientExecutionTimeError(RuntimeError):
    """Raised when Lambda cannot safely start another page."""


@lru_cache(maxsize=1)
def _create_dependencies() -> tuple[
    Settings,
    OpenSearchExportClient,
    ExportS3Client,
]:
    """Create and cache clients for Lambda environment reuse."""

    settings = Settings.from_env()

    low_level_opensearch_client = (
        create_aws_opensearch_client(
            endpoint=settings.opensearch_endpoint,
            region=settings.aws_region,
        )
    )

    opensearch_client = OpenSearchExportClient(
        low_level_opensearch_client
    )

    s3_client = ExportS3Client(
        boto3.client(
            "s3",
            region_name=settings.aws_region,
        )
    )

    return (
        settings,
        opensearch_client,
        s3_client,
    )


def _has_enough_execution_time(
    context: LambdaContext,
    safety_margin_ms: int,
) -> bool:
    """Check whether Lambda can safely start another page."""

    remaining_time = (
        context.get_remaining_time_in_millis()
    )

    return remaining_time > safety_margin_ms


def process_page_group(
    *,
    event: dict[str, Any],
    context: LambdaContext,
    settings: Settings,
    opensearch_client: OpenSearchExportClient,
    s3_client: ExportS3Client,
) -> dict[str, Any]:
    """Export a bounded number of pages for one slice."""

    state = SliceState.from_dict(event)

    invocation_documents = 0
    invocation_files = 0
    has_more = True

    for _ in range(
        settings.max_pages_per_invocation
    ):
        if not _has_enough_execution_time(
            context,
            settings.lambda_safety_margin_ms,
        ):
            if invocation_files == 0:
                raise InsufficientExecutionTimeError(
                    "Lambda does not have enough remaining "
                    "time to process a page"
                )

            LOGGER.info(
                json.dumps(
                    {
                        "event": "page_group_stopped",
                        "reason": "lambda_time_limit",
                        "exportId": state.export_id,
                        "sliceId": state.slice_id,
                        "nextPageNumber": state.page_number,
                    }
                )
            )

            break

        page = opensearch_client.search_page(
            pit_id=state.pit_id,
            keep_alive=settings.pit_keep_alive,
            query=state.query,
            slice_id=state.slice_id,
            slice_count=state.slice_count,
            page_size=state.page_size,
            search_after=state.search_after,
        )

        if not page.documents:
            has_more = False

            state = replace(
                state,
                search_after=None,
            )

            break

        object_info = s3_client.write_page(
            bucket=state.bucket,
            export_id=state.export_id,
            slice_id=state.slice_id,
            page_number=state.page_number,
            documents=page.documents,
        )

        document_count = len(page.documents)

        invocation_documents += document_count
        invocation_files += 1

        state = replace(
            state,
            page_number=state.page_number + 1,
            search_after=page.next_search_after,
            total_documents=(
                state.total_documents
                + document_count
            ),
            total_files=state.total_files + 1,
        )

        has_more = page.has_more

        LOGGER.info(
            json.dumps(
                {
                    "event": "page_exported",
                    "exportId": state.export_id,
                    "sliceId": state.slice_id,
                    "pageNumber": state.page_number - 1,
                    "documentCount": document_count,
                    "s3Key": object_info.key,
                    "compressedSize": (
                        object_info.compressed_size
                    ),
                }
            )
        )

        if not has_more:
            break

    result = PageGroupResult(
        state=state,
        documents_processed=invocation_documents,
        files_written=invocation_files,
        has_more=has_more,
    )

    return result.to_workflow_dict()


def lambda_handler(
    event: dict[str, Any],
    context: LambdaContext,
) -> dict[str, Any]:
    """AWS Lambda entry point."""

    settings, opensearch_client, s3_client = (
        _create_dependencies()
    )

    LOGGER.info(
        json.dumps(
            {
                "event": "page_group_started",
                "exportId": event.get("exportId"),
                "sliceId": event.get("sliceId"),
                "pageNumber": event.get("pageNumber"),
            }
        )
    )

    result = process_page_group(
        event=event,
        context=context,
        settings=settings,
        opensearch_client=opensearch_client,
        s3_client=s3_client,
    )

    LOGGER.info(
        json.dumps(
            {
                "event": "page_group_completed",
                "exportId": result["exportId"],
                "sliceId": result["sliceId"],
                "documentsProcessed": (
                    result["documentsProcessed"]
                ),
                "filesWritten": result["filesWritten"],
                "hasMore": result["hasMore"],
            }
        )
    )

    return result