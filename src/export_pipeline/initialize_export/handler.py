"""Lambda handler that initializes an OpenSearch export."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

import boto3

from export_pipeline.common.config import Settings
from export_pipeline.common.job_store import ExportJobStore
from export_pipeline.common.models import ExportRequest
from export_pipeline.common.opensearch_client import (
    OpenSearchExportClient,
    create_aws_opensearch_client,
)

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def _utc_now() -> str:
    """Return the current UTC time in ISO 8601 format."""

    return datetime.now(UTC).isoformat()


def _new_export_id() -> str:
    """Create a unique export identifier."""

    return str(uuid4())


def _calculate_query_hash(
    query: dict[str, Any],
) -> str:
    """Create a stable hash of an OpenSearch query."""

    serialized_query = json.dumps(
        query,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    return hashlib.sha256(
        serialized_query.encode("utf-8")
    ).hexdigest()


def _build_slices(
    slice_count: int,
) -> list[dict[str, int]]:
    """Create input items for Distributed Map."""

    return [
        {
            "sliceId": slice_id,
            "sliceCount": slice_count,
        }
        for slice_id in range(slice_count)
    ]


@lru_cache(maxsize=1)
def _create_dependencies() -> tuple[
    Settings,
    OpenSearchExportClient,
    ExportJobStore,
]:
    """Create and cache AWS dependencies."""

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

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
    )

    job_store = ExportJobStore(
        dynamodb.Table(settings.export_table)
    )

    return (
        settings,
        opensearch_client,
        job_store,
    )


def process_initialize_export(
    *,
    event: dict[str, Any],
    settings: Settings,
    opensearch_client: OpenSearchExportClient,
    job_store: ExportJobStore,
    now_factory: Callable[[], str] = _utc_now,
    id_factory: Callable[[], str] = _new_export_id,
) -> dict[str, Any]:
    """Validate and initialize one export operation."""

    request = ExportRequest.from_dict(
        event,
        default_page_size=settings.default_page_size,
        default_slice_count=(
            settings.default_slice_count
        ),
    )

    export_id = id_factory()
    started_at = now_factory()

    output_prefix = f"exports/{export_id}/"

    query_hash = _calculate_query_hash(
        request.query
    )

    created = job_store.try_create_job(
        request_id=request.request_id,
        export_id=export_id,
        index_name=request.index_name,
        query_hash=query_hash,
        output_prefix=output_prefix,
        started_at=started_at,
    )

    if not created:
        existing_job = job_store.get_job(
            request.request_id
        )

        if existing_job is None:
            raise RuntimeError(
                "Export request already exists but "
                "its job record cannot be read"
            )

        return {
            "alreadyExists": True,
            "requestId": request.request_id,
            "exportId": existing_job["exportId"],
            "status": existing_job["status"],
            "outputPrefix": existing_job[
                "outputPrefix"
            ],
        }

    pit_id: str | None = None

    try:
        pit_id = opensearch_client.create_pit(
            index_name=request.index_name,
            keep_alive=settings.pit_keep_alive,
        )

        updated_at = now_factory()

        job_store.mark_running(
            request_id=request.request_id,
            export_id=export_id,
            pit_id=pit_id,
            updated_at=updated_at,
        )
    except Exception as exc:
        if pit_id is not None:
            try:
                opensearch_client.close_pit(pit_id)
            except Exception:
                LOGGER.exception(
                    "Failed to close PIT after "
                    "initialization failure"
                )

        try:
            job_store.mark_failed(
                request_id=request.request_id,
                export_id=export_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                updated_at=now_factory(),
            )
        except Exception:
            LOGGER.exception(
                "Failed to mark export as failed"
            )

        raise

    result = {
        "alreadyExists": False,
        "requestId": request.request_id,
        "exportId": export_id,
        "pitId": pit_id,
        "indexName": request.index_name,
        "query": request.query,
        "pageSize": request.page_size,
        "sliceCount": request.slice_count,
        "bucket": settings.export_bucket,
        "outputPrefix": output_prefix,
        "startedAt": started_at,
        "slices": _build_slices(
            request.slice_count
        ),
    }

    return result


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """AWS Lambda entry point."""

    del context

    settings, opensearch_client, job_store = (
        _create_dependencies()
    )

    LOGGER.info(
        json.dumps(
            {
                "event": "export_initialization_started",
                "requestId": event.get("requestId"),
                "indexName": event.get("indexName"),
            }
        )
    )

    result = process_initialize_export(
        event=event,
        settings=settings,
        opensearch_client=opensearch_client,
        job_store=job_store,
    )

    LOGGER.info(
        json.dumps(
            {
                "event": "export_initialization_completed",
                "requestId": result["requestId"],
                "exportId": result["exportId"],
                "alreadyExists": result[
                    "alreadyExists"
                ],
            }
        )
    )

    return result