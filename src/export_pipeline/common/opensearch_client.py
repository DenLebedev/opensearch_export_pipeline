"""Amazon OpenSearch Service client used by the export pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import boto3
from opensearchpy import (
    AWSV4SignerAuth,
    OpenSearch,
    RequestsHttpConnection,
)
from opensearchpy.exceptions import (
    ConnectionError as OpenSearchConnectionError,
)
from opensearchpy.exceptions import (
    ConnectionTimeout,
    NotFoundError,
    TransportError,
)


class OpenSearchExportError(RuntimeError):
    """Base error raised by the OpenSearch export client."""


class TemporaryOpenSearchError(OpenSearchExportError):
    """Error that can normally be retried."""


class PermanentOpenSearchError(OpenSearchExportError):
    """Error that should not normally be retried."""


@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page returned by OpenSearch."""

    documents: list[dict[str, Any]]
    next_search_after: list[Any] | None
    has_more: bool


_INDEX_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._,*-]+$")


def _validate_index_name(index_name: str) -> str:
    """Validate an index name before using it in an API path."""

    if not index_name:
        raise ValueError("index_name must not be empty")

    if not _INDEX_NAME_PATTERN.fullmatch(index_name):
        raise ValueError("index_name contains unsupported characters")

    return index_name


def create_aws_opensearch_client(
    endpoint: str,
    region: str,
) -> OpenSearch:
    """Create an OpenSearch client authenticated with AWS SigV4."""

    parsed_endpoint = urlparse(endpoint)

    if parsed_endpoint.scheme not in {"http", "https"}:
        raise ValueError("OpenSearch endpoint must use http or https")

    if not parsed_endpoint.hostname:
        raise ValueError("OpenSearch endpoint must contain a hostname")

    session = boto3.Session()
    credentials = session.get_credentials()

    if credentials is None:
        raise RuntimeError("AWS credentials are not available")

    auth = AWSV4SignerAuth(
        credentials,
        region,
        "es",
    )

    use_ssl = parsed_endpoint.scheme == "https"
    port = parsed_endpoint.port or (443 if use_ssl else 80)

    return OpenSearch(
        hosts=[
            {
                "host": parsed_endpoint.hostname,
                "port": port,
            }
        ],
        http_auth=auth,
        use_ssl=use_ssl,
        verify_certs=use_ssl,
        connection_class=RequestsHttpConnection,
        timeout=60,
        max_retries=0,
        retry_on_timeout=False,
        http_compress=True,
    )


class OpenSearchExportClient:
    """High-level operations required by the export pipeline."""

    def __init__(self, client: OpenSearch) -> None:
        self._client = client

    def create_pit(
        self,
        index_name: str,
        keep_alive: str,
    ) -> str:
        """Create a point-in-time view for an index."""

        validated_index = _validate_index_name(index_name)

        try:
            response = self._client.transport.perform_request(
                method="POST",
                url=(f"/{validated_index}/_search/point_in_time"),
                params={
                    "keep_alive": keep_alive,
                },
            )
        except Exception as exc:
            raise self._map_exception(
                exc,
                operation="create PIT",
            ) from exc

        pit_id = response.get("pit_id")

        if not isinstance(pit_id, str) or not pit_id:
            raise PermanentOpenSearchError("OpenSearch create PIT response does not contain pit_id")

        return pit_id

    def search_page(
        self,
        *,
        pit_id: str,
        keep_alive: str,
        query: dict[str, Any],
        slice_id: int,
        slice_count: int,
        page_size: int,
        search_after: list[Any] | None,
    ) -> SearchPage:
        """Read one page from one PIT search slice."""

        body: dict[str, Any] = {
            "size": page_size,
            "query": query,
            "pit": {
                "id": pit_id,
                "keep_alive": keep_alive,
            },
            "slice": {
                "id": slice_id,
                "max": slice_count,
            },
            "sort": [
                {
                    "_shard_doc": "asc",
                }
            ],
            "track_total_hits": False,
        }

        if search_after is not None:
            body["search_after"] = search_after

        try:
            response = self._client.search(body=body)
        except Exception as exc:
            raise self._map_exception(
                exc,
                operation="search page",
            ) from exc

        hits_container = response.get("hits")

        if not isinstance(hits_container, dict):
            raise PermanentOpenSearchError("OpenSearch response does not contain hits")

        hits = hits_container.get("hits")

        if not isinstance(hits, list):
            raise PermanentOpenSearchError("OpenSearch response hits.hits is not an array")

        documents = [self._convert_hit(hit) for hit in hits]

        next_search_after = self._get_next_search_after(hits)

        return SearchPage(
            documents=documents,
            next_search_after=next_search_after,
            has_more=len(hits) == page_size,
        )

    def close_pit(self, pit_id: str) -> bool:
        """Close a PIT and release OpenSearch resources."""

        if not pit_id:
            raise ValueError("pit_id must not be empty")

        try:
            response = self._client.transport.perform_request(
                method="DELETE",
                url="/_search/point_in_time",
                body={
                    "pit_id": [pit_id],
                },
            )
        except NotFoundError:
            # Cleanup is idempotent: an already missing PIT is
            # considered successfully closed.
            return False
        except Exception as exc:
            raise self._map_exception(
                exc,
                operation="close PIT",
            ) from exc

        succeeded = response.get("succeeded")

        if succeeded is None:
            return True

        return bool(succeeded)

    @staticmethod
    def _convert_hit(
        hit: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert an OpenSearch hit into an exported record."""

        if not isinstance(hit, dict):
            raise PermanentOpenSearchError("OpenSearch returned an invalid search hit")

        source = hit.get("_source", {})

        if not isinstance(source, dict):
            raise PermanentOpenSearchError("OpenSearch hit _source must be an object")

        return {
            "_id": hit.get("_id"),
            "_index": hit.get("_index"),
            "_source": source,
        }

    @staticmethod
    def _get_next_search_after(
        hits: list[dict[str, Any]],
    ) -> list[Any] | None:
        """Get the continuation token from the final hit."""

        if not hits:
            return None

        final_hit = hits[-1]
        sort_values = final_hit.get("sort")

        if not isinstance(sort_values, list):
            raise PermanentOpenSearchError("The final OpenSearch hit has no sort values")

        return sort_values

    @staticmethod
    def _map_exception(
        exception: Exception,
        *,
        operation: str,
    ) -> OpenSearchExportError:
        """Classify OpenSearch errors as retryable or permanent."""

        if isinstance(
            exception,
            (
                OpenSearchConnectionError,
                ConnectionTimeout,
            ),
        ):
            return TemporaryOpenSearchError(f"Temporary failure during {operation}")

        if isinstance(exception, TransportError):
            status_code = getattr(
                exception,
                "status_code",
                None,
            )

            if status_code == 429:
                return TemporaryOpenSearchError(f"OpenSearch throttled {operation}")

            if isinstance(status_code, int) and status_code >= 500:
                return TemporaryOpenSearchError(f"OpenSearch server failure during {operation}")

            return PermanentOpenSearchError(
                f"OpenSearch rejected {operation}; status={status_code}"
            )

        return PermanentOpenSearchError(f"Unexpected failure during {operation}")
