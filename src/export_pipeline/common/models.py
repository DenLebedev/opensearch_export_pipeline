"""Validated data contracts used between Lambda and Step Functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ValidationError(ValueError):
    """Raised when a workflow input does not satisfy its contract."""


def _required_string(
    data: dict[str, Any],
    field_name: str,
) -> str:
    value = data.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"{field_name} must be a non-empty string"
        )

    return value.strip()


def _positive_integer(
    data: dict[str, Any],
    field_name: str,
    default: int,
) -> int:
    value = data.get(field_name, default)

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValidationError(
            f"{field_name} must be a positive integer"
        )

    return value


def _non_negative_integer(
    data: dict[str, Any],
    field_name: str,
    default: int = 0,
) -> int:
    value = data.get(field_name, default)

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValidationError(
            f"{field_name} must be a non-negative integer"
        )

    return value


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """External request that starts one complete export."""

    request_id: str
    index_name: str
    query: dict[str, Any] = field(
        default_factory=lambda: {"match_all": {}}
    )
    page_size: int = 1_000
    slice_count: int = 16

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        default_page_size: int = 1_000,
        default_slice_count: int = 16,
    ) -> ExportRequest:
        query = data.get(
            "query",
            {"match_all": {}},
        )

        if not isinstance(query, dict) or not query:
            raise ValidationError(
                "query must be a non-empty object"
            )

        return cls(
            request_id=_required_string(
                data,
                "requestId",
            ),
            index_name=_required_string(
                data,
                "indexName",
            ),
            query=query,
            page_size=_positive_integer(
                data,
                "pageSize",
                default_page_size,
            ),
            slice_count=_positive_integer(
                data,
                "sliceCount",
                default_slice_count,
            ),
        )


@dataclass(frozen=True, slots=True)
class SliceState:
    """Checkpoint passed between child-workflow Lambda invocations."""

    export_id: str
    pit_id: str
    slice_id: int
    slice_count: int
    page_number: int
    search_after: list[Any] | None
    page_size: int
    bucket: str
    query: dict[str, Any]
    total_documents: int = 0
    total_files: int = 0

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> SliceState:
        slice_id = data.get("sliceId")

        if (
            isinstance(slice_id, bool)
            or not isinstance(slice_id, int)
            or slice_id < 0
        ):
            raise ValidationError(
                "sliceId must be a non-negative integer"
            )

        slice_count = _positive_integer(
            data,
            "sliceCount",
            1,
        )

        if slice_id >= slice_count:
            raise ValidationError(
                "sliceId must be less than sliceCount"
            )

        page_number = _non_negative_integer(
            data,
            "pageNumber",
        )

        search_after = data.get("searchAfter")

        if (
            search_after is not None
            and not isinstance(search_after, list)
        ):
            raise ValidationError(
                "searchAfter must be an array or null"
            )

        query = data.get(
            "query",
            {"match_all": {}},
        )

        if not isinstance(query, dict) or not query:
            raise ValidationError(
                "query must be a non-empty object"
            )

        return cls(
            export_id=_required_string(
                data,
                "exportId",
            ),
            pit_id=_required_string(
                data,
                "pitId",
            ),
            slice_id=slice_id,
            slice_count=slice_count,
            page_number=page_number,
            search_after=search_after,
            page_size=_positive_integer(
                data,
                "pageSize",
                1_000,
            ),
            bucket=_required_string(
                data,
                "bucket",
            ),
            query=query,
            total_documents=_non_negative_integer(
                data,
                "totalDocuments",
            ),
            total_files=_non_negative_integer(
                data,
                "totalFiles",
            ),
        )

    def to_workflow_dict(self) -> dict[str, Any]:
        """Serialize state using Step Functions field names."""

        return {
            "exportId": self.export_id,
            "pitId": self.pit_id,
            "sliceId": self.slice_id,
            "sliceCount": self.slice_count,
            "pageNumber": self.page_number,
            "searchAfter": self.search_after,
            "pageSize": self.page_size,
            "bucket": self.bucket,
            "query": self.query,
            "totalDocuments": self.total_documents,
            "totalFiles": self.total_files,
        }


@dataclass(frozen=True, slots=True)
class PageGroupResult:
    """Result of one bounded page-group Lambda invocation."""

    state: SliceState
    documents_processed: int
    files_written: int
    has_more: bool

    def to_workflow_dict(self) -> dict[str, Any]:
        result = self.state.to_workflow_dict()

        result.update(
            {
                "documentsProcessed": self.documents_processed,
                "filesWritten": self.files_written,
                "hasMore": self.has_more,
            }
        )

        return result


@dataclass(frozen=True, slots=True)
class ExportManifest:
    """Description of a successfully completed export."""

    export_id: str
    status: str
    index_name: str
    document_count: int
    file_count: int
    slice_count: int
    output_prefix: str
    started_at: str
    completed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "exportId": self.export_id,
            "status": self.status,
            "indexName": self.index_name,
            "documentCount": self.document_count,
            "fileCount": self.file_count,
            "sliceCount": self.slice_count,
            "outputPrefix": self.output_prefix,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
        }