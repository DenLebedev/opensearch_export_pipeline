from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from export_pipeline.common.job_store import (
    ExportJobStore,
)


def test_creates_new_job() -> None:
    table = MagicMock()
    store = ExportJobStore(table)

    result = store.try_create_job(
        request_id="request-123",
        export_id="export-123",
        index_name="customers",
        query_hash="hash-123",
        output_prefix="exports/export-123/",
        started_at="2026-09-06T08:00:00+00:00",
    )

    assert result is True
    table.put_item.assert_called_once()


def test_returns_false_when_job_already_exists() -> None:
    table = MagicMock()
    table.put_item.side_effect = ClientError(
        {
            "Error": {
                "Code": (
                    "ConditionalCheckFailedException"
                ),
                "Message": "Condition failed",
            }
        },
        "PutItem",
    )

    store = ExportJobStore(table)

    result = store.try_create_job(
        request_id="request-123",
        export_id="export-123",
        index_name="customers",
        query_hash="hash-123",
        output_prefix="exports/export-123/",
        started_at="2026-09-06T08:00:00+00:00",
    )

    assert result is False


def test_does_not_hide_unexpected_dynamodb_error() -> None:
    table = MagicMock()
    table.put_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "InternalServerError",
                "Message": "DynamoDB failed",
            }
        },
        "PutItem",
    )

    store = ExportJobStore(table)

    try:
        store.try_create_job(
            request_id="request-123",
            export_id="export-123",
            index_name="customers",
            query_hash="hash-123",
            output_prefix="exports/export-123/",
            started_at=(
                "2026-09-06T08:00:00+00:00"
            ),
        )
    except ClientError as exc:
        assert (
            exc.response["Error"]["Code"]
            == "InternalServerError"
        )
    else:
        raise AssertionError(
            "ClientError was not raised"
        )


def test_gets_existing_job() -> None:
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "requestId": "request-123",
            "exportId": "export-123",
            "status": "RUNNING",
        }
    }

    store = ExportJobStore(table)

    result = store.get_job("request-123")

    assert result is not None
    assert result["exportId"] == "export-123"

    table.get_item.assert_called_once_with(
        Key={
            "requestId": "request-123",
        },
        ConsistentRead=True,
    )


def test_returns_none_when_job_does_not_exist() -> None:
    table = MagicMock()
    table.get_item.return_value = {}

    store = ExportJobStore(table)

    assert store.get_job("request-123") is None