"""Lambda handler that cleans up an OpenSearch export."""

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
from export_pipeline.common.models import ValidationError
from export_pipeline.common.opensearch_client import (
    OpenSearchExportClient,
    create_aws_opensearch_client,
)

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

_SUCCESS = "SUCCESS"
_FAILURE = "FAILURE"
_ALLOWED_OUTCOMES = {
    _SUCCESS,
    _FAILURE,
}


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


def _extract_error(
    event: dict[str, Any],
) -> tuple[str, str]:
    """Extract a safe error code and message from Catch output."""

    error = event.get("error")

    if not isinstance(error, dict):
        return (
            "ExportFailed",
            "Export failed without error details",
        )

    error_code = error.get(
        "Error",
        "ExportFailed",
    )
    cause = error.get(
        "Cause",
        "Export failed without error details",
    )

    if not isinstance(error_code, str):
        error_code = str(error_code)

    if not isinstance(cause, str):
        cause = json.dumps(
            cause,
            ensure_ascii=False,
            default=str,
        )

    # Step Functions frequently stores Lambda errors as
    # a JSON string in the Cause property.
    try:
        parsed_cause = json.loads(cause)
    except (json.JSONDecodeError, TypeError):
        parsed_cause = None

    if isinstance(parsed_cause, dict):
        parsed_message = parsed_cause.get("errorMessage")

        if isinstance(parsed_message, str):
            cause = parsed_message

    return (
        error_code[:200],
        cause[:500],
    )


@lru_cache(maxsize=1)
def _create_dependencies() -> tuple[
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
        opensearch_client,
        job_store,
    )


def process_cleanup_export(
    *,
    event: dict[str, Any],
    opensearch_client: OpenSearchExportClient,
    job_store: ExportJobStore,
    now_factory: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    """Close the PIT and record a failed export if necessary."""

    request_id = _required_string(
        event,
        "requestId",
    )
    export_id = _required_string(
        event,
        "exportId",
    )
    pit_id = _required_string(
        event,
        "pitId",
    )
    outcome = _required_string(
        event,
        "outcome",
    ).upper()

    if outcome not in _ALLOWED_OUTCOMES:
        raise ValidationError("outcome must be SUCCESS or FAILURE")

    if outcome == _FAILURE:
        error_code, error_message = _extract_error(event)

        # Mark the job first. If PIT cleanup fails, the job
        # must still be visible as failed.
        job_store.mark_failed(
            request_id=request_id,
            export_id=export_id,
            error_code=error_code,
            error_message=error_message,
            updated_at=now_factory(),
        )

    pit_was_closed = opensearch_client.close_pit(pit_id)

    result = {
        "requestId": request_id,
        "exportId": export_id,
        "outcome": outcome,
        "pitClosed": pit_was_closed,
    }

    if outcome == _FAILURE:
        result["status"] = "FAILED"
    else:
        # The successful export is finalized only after
        # its PIT has been closed.
        result["status"] = "READY_TO_FINALIZE"

    return result


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """AWS Lambda entry point."""

    del context

    opensearch_client, job_store = _create_dependencies()

    LOGGER.info(
        json.dumps(
            {
                "event": "export_cleanup_started",
                "requestId": event.get("requestId"),
                "exportId": event.get("exportId"),
                "outcome": event.get("outcome"),
            }
        )
    )

    result = process_cleanup_export(
        event=event,
        opensearch_client=opensearch_client,
        job_store=job_store,
    )

    LOGGER.info(
        json.dumps(
            {
                "event": "export_cleanup_completed",
                "requestId": result["requestId"],
                "exportId": result["exportId"],
                "outcome": result["outcome"],
                "pitClosed": result["pitClosed"],
            }
        )
    )

    return result
