"""Lambda handler that finalizes an OpenSearch export."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import boto3

from export_pipeline.common.config import Settings
from export_pipeline.common.job_store import ExportJobStore
from export_pipeline.common.models import (
    ExportManifest,
    ValidationError,
)
from export_pipeline.common.s3_client import ExportS3Client

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def _utc_now() -> str:
    """Return the current UTC time in ISO 8601 format."""

    return datetime.now(UTC).isoformat()


def _required_string(
    event: dict[str, Any],
    field_name: str,
) -> str:
    value = event.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")

    return value.strip()


def _required_positive_integer(
    event: dict[str, Any],
    field_name: str,
) -> int:
    value = event.get(field_name)

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer")

    return value


def _non_negative_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{field_name} must be a non-negative integer")

    return value


def _summarize_slices(
    *,
    slice_results: Any,
    expected_slice_count: int,
) -> tuple[int, int]:
    """Validate slice results and calculate export totals."""

    if not isinstance(slice_results, list):
        raise ValidationError("sliceResults must be an array")

    if len(slice_results) != expected_slice_count:
        raise ValidationError("sliceResults count does not match sliceCount")

    observed_slice_ids: set[int] = set()
    document_count = 0
    file_count = 0

    for position, result in enumerate(slice_results):
        if not isinstance(result, dict):
            raise ValidationError(f"sliceResults[{position}] must be an object")

        slice_id = result.get("sliceId")

        if (
            isinstance(slice_id, bool)
            or not isinstance(slice_id, int)
            or slice_id < 0
            or slice_id >= expected_slice_count
        ):
            raise ValidationError(f"sliceResults[{position}].sliceId is invalid")

        if slice_id in observed_slice_ids:
            raise ValidationError(f"Duplicate sliceId: {slice_id}")

        if result.get("hasMore") is not False:
            raise ValidationError(f"Slice {slice_id} is not complete")

        observed_slice_ids.add(slice_id)

        document_count += _non_negative_integer(
            result.get("totalDocuments"),
            (f"sliceResults[{position}].totalDocuments"),
        )

        file_count += _non_negative_integer(
            result.get("totalFiles"),
            f"sliceResults[{position}].totalFiles",
        )

    expected_slice_ids = set(range(expected_slice_count))

    if observed_slice_ids != expected_slice_ids:
        raise ValidationError("sliceResults do not contain every expected slice")

    return document_count, file_count


def _manifest_key(output_prefix: str) -> str:
    """Build the final manifest S3 key."""

    return f"{output_prefix.rstrip('/')}/manifest.json"


@lru_cache(maxsize=1)
def _create_dependencies() -> tuple[
    ExportS3Client,
    ExportJobStore,
]:
    """Create and cache AWS dependencies."""

    settings = Settings.from_env()

    s3_client = ExportS3Client(
        boto3.client(
            "s3",
            region_name=settings.aws_region,
        )
    )

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
    )

    job_store = ExportJobStore(dynamodb.Table(settings.export_table))

    return (
        s3_client,
        job_store,
    )


def process_finalize_export(
    *,
    event: dict[str, Any],
    s3_client: ExportS3Client,
    job_store: ExportJobStore,
    now_factory: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    """Validate and publish a completed export."""

    request_id = _required_string(
        event,
        "requestId",
    )
    export_id = _required_string(
        event,
        "exportId",
    )
    index_name = _required_string(
        event,
        "indexName",
    )
    bucket = _required_string(
        event,
        "bucket",
    )
    output_prefix = _required_string(
        event,
        "outputPrefix",
    )
    started_at = _required_string(
        event,
        "startedAt",
    )
    slice_count = _required_positive_integer(
        event,
        "sliceCount",
    )

    expected_output_prefix = f"exports/{export_id}/"

    if output_prefix != expected_output_prefix:
        raise ValidationError("outputPrefix does not match exportId")

    document_count, file_count = _summarize_slices(
        slice_results=event.get("sliceResults"),
        expected_slice_count=slice_count,
    )

    completed_at = now_factory()
    manifest_key = _manifest_key(output_prefix)

    manifest = ExportManifest(
        export_id=export_id,
        status="COMPLETED",
        index_name=index_name,
        document_count=document_count,
        file_count=file_count,
        slice_count=slice_count,
        output_prefix=f"{output_prefix}data/",
        started_at=started_at,
        completed_at=completed_at,
    )

    manifest_data = manifest.to_dict()

    s3_client.write_json(
        bucket=bucket,
        key=manifest_key,
        value=manifest_data,
        metadata={
            "export-id": export_id,
            "status": "COMPLETED",
        },
    )

    job_store.mark_completed(
        request_id=request_id,
        export_id=export_id,
        document_count=document_count,
        file_count=file_count,
        manifest_key=manifest_key,
        completed_at=completed_at,
    )

    LOGGER.info(
        json.dumps(
            {
                "event": "export_finalized",
                "requestId": request_id,
                "exportId": export_id,
                "documentCount": document_count,
                "fileCount": file_count,
                "manifestKey": manifest_key,
            }
        )
    )

    return {
        "requestId": request_id,
        "exportId": export_id,
        "status": "COMPLETED",
        "documentCount": document_count,
        "fileCount": file_count,
        "manifestKey": manifest_key,
        "outputLocation": (f"s3://{bucket}/{output_prefix}data/"),
        "completedAt": completed_at,
    }


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """AWS Lambda entry point."""

    del context

    s3_client, job_store = _create_dependencies()

    LOGGER.info(
        json.dumps(
            {
                "event": "export_finalization_started",
                "requestId": event.get("requestId"),
                "exportId": event.get("exportId"),
            }
        )
    )

    return process_finalize_export(
        event=event,
        s3_client=s3_client,
        job_store=job_store,
    )
