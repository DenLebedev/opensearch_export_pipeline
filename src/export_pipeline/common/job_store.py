"""DynamoDB storage for OpenSearch export jobs."""

from __future__ import annotations

from typing import Any, Protocol

from botocore.exceptions import ClientError


class DynamoDBTable(Protocol):
    """Subset of DynamoDB Table operations used by the pipeline."""

    def put_item(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create an item."""

    def get_item(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get an item."""

    def update_item(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update an item."""


class ExportJobStore:
    """Stores and updates export job information in DynamoDB."""

    def __init__(self, table: DynamoDBTable) -> None:
        self._table = table

    def try_create_job(
        self,
        *,
        request_id: str,
        export_id: str,
        index_name: str,
        query_hash: str,
        output_prefix: str,
        started_at: str,
        execution_id: str = "direct-execution",
        expires_at: int | None = None,
    ) -> bool:
        """Create a job unless the request ID already exists."""

        item = {
            "requestId": request_id,
            "exportId": export_id,
            "executionId": execution_id,
            "status": "STARTING",
            "indexName": index_name,
            "queryHash": query_hash,
            "outputPrefix": output_prefix,
            "startedAt": started_at,
            "updatedAt": started_at,
        }

        if expires_at is not None:
            item["expiresAt"] = expires_at

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=("attribute_not_exists(requestId)"),
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "ConditionalCheckFailedException":
                return False

            raise

        return True

    def get_job(
        self,
        request_id: str,
    ) -> dict[str, Any] | None:
        """Get a job by its idempotency request ID."""

        response = self._table.get_item(
            Key={
                "requestId": request_id,
            },
            ConsistentRead=True,
        )

        item = response.get("Item")

        if not isinstance(item, dict):
            return None

        return item

    def mark_running(
        self,
        *,
        request_id: str,
        export_id: str,
        pit_id: str,
        updated_at: str,
    ) -> None:
        """Mark an initialized export as running."""

        self._table.update_item(
            Key={
                "requestId": request_id,
            },
            UpdateExpression=(
                "SET #status = :status, "
                "pitId = :pit_id, "
                "updatedAt = :updated_at"
                "REMOVE errorCode, errorMessage"
            ),
            ConditionExpression=("exportId = :export_id"),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":status": "RUNNING",
                ":pit_id": pit_id,
                ":updated_at": updated_at,
                ":export_id": export_id,
            },
        )

    def mark_failed(
        self,
        *,
        request_id: str,
        export_id: str,
        error_code: str,
        error_message: str,
        updated_at: str,
    ) -> None:
        """Mark an export as failed."""

        self._table.update_item(
            Key={
                "requestId": request_id,
            },
            UpdateExpression=(
                "SET #status = :status, "
                "errorCode = :error_code, "
                "errorMessage = :error_message, "
                "updatedAt = :updated_at"
            ),
            ConditionExpression=("exportId = :export_id"),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":status": "FAILED",
                ":error_code": error_code,
                ":error_message": error_message,
                ":updated_at": updated_at,
                ":export_id": export_id,
            },
        )

    def mark_completed(
        self,
        *,
        request_id: str,
        export_id: str,
        document_count: int,
        file_count: int,
        manifest_key: str,
        completed_at: str,
    ) -> None:
        """Mark an export as successfully completed."""

        self._table.update_item(
            Key={
                "requestId": request_id,
            },
            UpdateExpression=(
                "SET #status = :completed, "
                "documentCount = :document_count, "
                "fileCount = :file_count, "
                "manifestKey = :manifest_key, "
                "completedAt = :completed_at, "
                "updatedAt = :completed_at "
                "REMOVE errorCode, errorMessage"
            ),
            ConditionExpression=("exportId = :export_id AND #status IN (:running, :completed)"),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":completed": "COMPLETED",
                ":running": "RUNNING",
                ":document_count": document_count,
                ":file_count": file_count,
                ":manifest_key": manifest_key,
                ":completed_at": completed_at,
                ":export_id": export_id,
            },
        )
