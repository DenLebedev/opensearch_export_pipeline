from unittest.mock import MagicMock

import pytest

from export_pipeline.cleanup_export.handler import (
    _extract_error,
    process_cleanup_export,
)
from export_pipeline.common.models import ValidationError


def create_success_event() -> dict:
    return {
        "requestId": "request-123",
        "exportId": "export-123",
        "pitId": "pit-123",
        "outcome": "SUCCESS",
    }


def create_failure_event() -> dict:
    return {
        "requestId": "request-123",
        "exportId": "export-123",
        "pitId": "pit-123",
        "outcome": "FAILURE",
        "error": {
            "Error": "TemporaryOpenSearchError",
            "Cause": ('{"errorMessage":"OpenSearch unavailable"}'),
        },
    }


def test_successful_cleanup_closes_pit() -> None:
    opensearch_client = MagicMock()
    opensearch_client.close_pit.return_value = True

    job_store = MagicMock()

    result = process_cleanup_export(
        event=create_success_event(),
        opensearch_client=opensearch_client,
        job_store=job_store,
    )

    assert result == {
        "requestId": "request-123",
        "exportId": "export-123",
        "outcome": "SUCCESS",
        "pitClosed": True,
        "status": "READY_TO_FINALIZE",
    }

    opensearch_client.close_pit.assert_called_once_with("pit-123")
    job_store.mark_failed.assert_not_called()


def test_failed_cleanup_records_error_and_closes_pit() -> None:
    opensearch_client = MagicMock()
    opensearch_client.close_pit.return_value = True

    job_store = MagicMock()

    result = process_cleanup_export(
        event=create_failure_event(),
        opensearch_client=opensearch_client,
        job_store=job_store,
        now_factory=lambda: "2026-09-06T10:00:00+00:00",
    )

    assert result["status"] == "FAILED"
    assert result["pitClosed"] is True

    job_store.mark_failed.assert_called_once_with(
        request_id="request-123",
        export_id="export-123",
        error_code="TemporaryOpenSearchError",
        error_message="OpenSearch unavailable",
        updated_at="2026-09-06T10:00:00+00:00",
    )

    opensearch_client.close_pit.assert_called_once_with("pit-123")


def test_missing_error_uses_safe_defaults() -> None:
    event = create_failure_event()
    event.pop("error")

    opensearch_client = MagicMock()
    opensearch_client.close_pit.return_value = True

    job_store = MagicMock()

    process_cleanup_export(
        event=event,
        opensearch_client=opensearch_client,
        job_store=job_store,
        now_factory=lambda: "2026-09-06T10:00:00+00:00",
    )

    arguments = job_store.mark_failed.call_args.kwargs

    assert arguments["error_code"] == "ExportFailed"
    assert arguments["error_message"] == ("Export failed without error details")


def test_invalid_outcome_is_rejected() -> None:
    event = create_success_event()
    event["outcome"] = "UNKNOWN"

    with pytest.raises(
        ValidationError,
        match="SUCCESS or FAILURE",
    ):
        process_cleanup_export(
            event=event,
            opensearch_client=MagicMock(),
            job_store=MagicMock(),
        )


def test_cleanup_is_idempotent_when_pit_is_missing() -> None:
    opensearch_client = MagicMock()

    # close_pit returns False when the PIT was already
    # closed or no longer exists.
    opensearch_client.close_pit.return_value = False

    job_store = MagicMock()

    result = process_cleanup_export(
        event=create_success_event(),
        opensearch_client=opensearch_client,
        job_store=job_store,
    )

    assert result["pitClosed"] is False
    assert result["status"] == "READY_TO_FINALIZE"


def test_failure_is_recorded_before_pit_cleanup() -> None:
    call_order = []

    opensearch_client = MagicMock()

    def close_pit(pit_id: str) -> bool:
        call_order.append(f"close:{pit_id}")
        return True

    opensearch_client.close_pit.side_effect = close_pit

    job_store = MagicMock()

    def mark_failed(**kwargs: object) -> None:
        call_order.append(f"failed:{kwargs['export_id']}")

    job_store.mark_failed.side_effect = mark_failed

    process_cleanup_export(
        event=create_failure_event(),
        opensearch_client=opensearch_client,
        job_store=job_store,
        now_factory=lambda: "2026-09-06T10:00:00+00:00",
    )

    assert call_order == [
        "failed:export-123",
        "close:pit-123",
    ]


def test_extracts_plain_text_error() -> None:
    result = _extract_error(
        {
            "error": {
                "Error": "ExportError",
                "Cause": "Plain text failure",
            }
        }
    )

    assert result == (
        "ExportError",
        "Plain text failure",
    )
