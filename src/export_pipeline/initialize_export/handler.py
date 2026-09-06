"""Lambda handler that initializes an OpenSearch export."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import uuid4

import boto3

from export_pipeline.common.config import Settings
from export_pipeline.common.job_store import ExportJobStore
from export_pipeline.common.models import (
    ExportRequest,
    ValidationError,
)
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

    return hashlib.sha256(serialized_query.encode("utf-8")).hexdigest()


def _expiration_timestamp(
    started_at: str,
    retention_days: int,
) -> int:
    """Calculate the DynamoDB TTL timestamp."""

    started = datetime.fromisoformat(started_at)

    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)

    expires_at = started + timedelta(days=retention_days)

    return int(expires_at.timestamp())


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


def _existing_export_response(
    *,
    request_id: str,
    existing_job: dict[str, Any],
) -> dict[str, Any]:
    """Create a response for another existing execution."""

    export_id = existing_job.get("exportId")
    status = existing_job.get("status")
    output_prefix = existing_job.get("outputPrefix")

    if not isinstance(export_id, str):
        raise RuntimeError("Existing job has no valid exportId")

    if not isinstance(status, str):
        raise RuntimeError("Existing job has no valid status")

    if not isinstance(output_prefix, str):
        raise RuntimeError("Existing job has no valid outputPrefix")

    result = {
        "alreadyExists": True,
        "requestId": request_id,
        "exportId": export_id,
        "status": status,
        "outputPrefix": output_prefix,
    }

    manifest_key = existing_job.get("manifestKey")

    if isinstance(manifest_key, str):
        result["manifestKey"] = manifest_key

    return result


def _initialized_export_response(
    *,
    request: ExportRequest,
    settings: Settings,
    export_id: str,
    pit_id: str,
    output_prefix: str,
    started_at: str,
) -> dict[str, Any]:
    """Create the complete initialization result."""

    return {
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
        "slices": _build_slices(request.slice_count),
    }


@lru_cache(maxsize=1)
def _create_dependencies() -> tuple[
    Settings,
    OpenSearchExportClient,
    ExportJobStore,
]:
    """Create and cache AWS dependencies."""

    settings = Settings.from_env()

    low_level_opensearch_client = create_aws_opensearch_client(
        endpoint=settings.opensearch_endpoint,
        region=settings.aws_region,
    )

    opensearch_client = OpenSearchExportClient(low_level_opensearch_client)

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
    )

    job_store = ExportJobStore(dynamodb.Table(settings.export_table))

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
    execution_id: str = "direct-execution",
    now_factory: Callable[[], str] = _utc_now,
    id_factory: Callable[[], str] = _new_export_id,
) -> dict[str, Any]:
    """Validate and initialize one export operation."""

    if not execution_id:
        raise ValidationError("executionId must not be empty")

    request = ExportRequest.from_dict(
        event,
        default_page_size=settings.default_page_size,
        default_slice_count=(settings.default_slice_count),
    )

    proposed_export_id = id_factory()
    proposed_started_at = now_factory()
    proposed_output_prefix = f"exports/{proposed_export_id}/"

    query_hash = _calculate_query_hash(request.query)

    expires_at = _expiration_timestamp(
        proposed_started_at,
        settings.job_retention_days,
    )

    created = job_store.try_create_job(
        request_id=request.request_id,
        export_id=proposed_export_id,
        index_name=request.index_name,
        query_hash=query_hash,
        output_prefix=proposed_output_prefix,
        started_at=proposed_started_at,
        execution_id=execution_id,
        expires_at=expires_at,
    )

    if created:
        export_id = proposed_export_id
        started_at = proposed_started_at
        output_prefix = proposed_output_prefix
    else:
        existing_job = job_store.get_job(request.request_id)

        if existing_job is None:
            raise RuntimeError("Export request already exists but its job record cannot be read")

        existing_execution_id = existing_job.get("executionId")

        # A different State Machine execution owns
        # this request, so it must not start another export.
        if existing_execution_id != execution_id:
            return _existing_export_response(
                request_id=request.request_id,
                existing_job=existing_job,
            )

        existing_query_hash = existing_job.get("queryHash")

        if existing_query_hash != query_hash:
            raise ValidationError("The retried request query does not match the original query")

        existing_status = existing_job.get("status")

        if existing_status == "COMPLETED":
            return _existing_export_response(
                request_id=request.request_id,
                existing_job=existing_job,
            )

        export_id = existing_job.get("exportId")
        started_at = existing_job.get("startedAt")
        output_prefix = existing_job.get("outputPrefix")

        if not all(
            isinstance(value, str) and value
            for value in (
                export_id,
                started_at,
                output_prefix,
            )
        ):
            raise RuntimeError("Existing job cannot be resumed")

        # The previous Lambda invocation may have created
        # the PIT and then lost its response.
        if existing_status == "RUNNING":
            existing_pit_id = existing_job.get("pitId")

            if not isinstance(existing_pit_id, str):
                raise RuntimeError("Running job has no valid pitId")

            return _initialized_export_response(
                request=request,
                settings=settings,
                export_id=export_id,
                pit_id=existing_pit_id,
                output_prefix=output_prefix,
                started_at=started_at,
            )

        if existing_status not in {
            "STARTING",
            "FAILED",
        }:
            return _existing_export_response(
                request_id=request.request_id,
                existing_job=existing_job,
            )

    pit_id: str | None = None

    try:
        pit_id = opensearch_client.create_pit(
            index_name=request.index_name,
            keep_alive=settings.pit_keep_alive,
        )

        job_store.mark_running(
            request_id=request.request_id,
            export_id=export_id,
            pit_id=pit_id,
            updated_at=now_factory(),
        )
    except Exception as exc:
        if pit_id is not None:
            try:
                opensearch_client.close_pit(pit_id)
            except Exception:
                LOGGER.exception("Failed to close PIT after initialization failure")

        try:
            job_store.mark_failed(
                request_id=request.request_id,
                export_id=export_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                updated_at=now_factory(),
            )
        except Exception:
            LOGGER.exception("Failed to mark export as failed")

        raise

    return _initialized_export_response(
        request=request,
        settings=settings,
        export_id=export_id,
        pit_id=pit_id,
        output_prefix=output_prefix,
        started_at=started_at,
    )


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """AWS Lambda entry point."""

    del context

    request_event = event.get("request")
    execution_id = event.get("executionId")

    if not isinstance(request_event, dict):
        raise ValidationError("request must be an object")

    if not isinstance(execution_id, str) or not execution_id:
        raise ValidationError("executionId must be a non-empty string")

    settings, opensearch_client, job_store = _create_dependencies()

    LOGGER.info(
        json.dumps(
            {
                "event": "export_initialization_started",
                "requestId": request_event.get("requestId"),
                "indexName": request_event.get("indexName"),
            }
        )
    )

    result = process_initialize_export(
        event=request_event,
        execution_id=execution_id,
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
                "alreadyExists": result["alreadyExists"],
            }
        )
    )

    return result
