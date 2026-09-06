from unittest.mock import MagicMock

import pytest
from opensearchpy.exceptions import TransportError

from export_pipeline.common.opensearch_client import (
    OpenSearchExportClient,
    PermanentOpenSearchError,
    TemporaryOpenSearchError,
)


def create_mock_client() -> MagicMock:
    client = MagicMock()
    client.transport = MagicMock()
    return client


def test_create_pit_returns_pit_id() -> None:
    client = create_mock_client()
    client.transport.perform_request.return_value = {
        "pit_id": "pit-123"
    }

    export_client = OpenSearchExportClient(client)

    result = export_client.create_pit(
        index_name="customers",
        keep_alive="10m",
    )

    assert result == "pit-123"

    client.transport.perform_request.assert_called_once_with(
        method="POST",
        url="/customers/_search/point_in_time",
        params={
            "keep_alive": "10m",
        },
    )


def test_create_pit_rejects_invalid_index_name() -> None:
    client = create_mock_client()
    export_client = OpenSearchExportClient(client)

    with pytest.raises(
        ValueError,
        match="unsupported characters",
    ):
        export_client.create_pit(
            index_name="../customers",
            keep_alive="10m",
        )


def test_create_pit_requires_pit_id_in_response() -> None:
    client = create_mock_client()
    client.transport.perform_request.return_value = {}

    export_client = OpenSearchExportClient(client)

    with pytest.raises(
        PermanentOpenSearchError,
        match="does not contain pit_id",
    ):
        export_client.create_pit(
            index_name="customers",
            keep_alive="10m",
        )


def test_search_first_page() -> None:
    client = create_mock_client()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "customer-1",
                    "_index": "customers",
                    "_source": {
                        "name": "Alice",
                    },
                    "sort": [101],
                },
                {
                    "_id": "customer-2",
                    "_index": "customers",
                    "_source": {
                        "name": "Bob",
                    },
                    "sort": [102],
                },
            ]
        }
    }

    export_client = OpenSearchExportClient(client)

    result = export_client.search_page(
        pit_id="pit-123",
        keep_alive="10m",
        query={"match_all": {}},
        slice_id=1,
        slice_count=4,
        page_size=2,
        search_after=None,
    )

    assert result.documents == [
        {
            "_id": "customer-1",
            "_index": "customers",
            "_source": {
                "name": "Alice",
            },
        },
        {
            "_id": "customer-2",
            "_index": "customers",
            "_source": {
                "name": "Bob",
            },
        },
    ]
    assert result.next_search_after == [102]
    assert result.has_more is True

    request_body = client.search.call_args.kwargs["body"]

    assert "search_after" not in request_body
    assert request_body["slice"] == {
        "id": 1,
        "max": 4,
    }
    assert request_body["pit"]["id"] == "pit-123"


def test_search_next_page_uses_search_after() -> None:
    client = create_mock_client()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "customer-3",
                    "_index": "customers",
                    "_source": {
                        "name": "Charlie",
                    },
                    "sort": [103],
                }
            ]
        }
    }

    export_client = OpenSearchExportClient(client)

    result = export_client.search_page(
        pit_id="pit-123",
        keep_alive="10m",
        query={"match_all": {}},
        slice_id=1,
        slice_count=4,
        page_size=2,
        search_after=[102],
    )

    request_body = client.search.call_args.kwargs["body"]

    assert request_body["search_after"] == [102]
    assert result.next_search_after == [103]
    assert result.has_more is False


def test_search_empty_page() -> None:
    client = create_mock_client()
    client.search.return_value = {
        "hits": {
            "hits": []
        }
    }

    export_client = OpenSearchExportClient(client)

    result = export_client.search_page(
        pit_id="pit-123",
        keep_alive="10m",
        query={"match_all": {}},
        slice_id=0,
        slice_count=4,
        page_size=1000,
        search_after=None,
    )

    assert result.documents == []
    assert result.next_search_after is None
    assert result.has_more is False


def test_search_maps_429_to_temporary_error() -> None:
    client = create_mock_client()
    client.search.side_effect = TransportError(
        429,
        "too_many_requests",
        {},
    )

    export_client = OpenSearchExportClient(client)

    with pytest.raises(TemporaryOpenSearchError):
        export_client.search_page(
            pit_id="pit-123",
            keep_alive="10m",
            query={"match_all": {}},
            slice_id=0,
            slice_count=4,
            page_size=1000,
            search_after=None,
        )


def test_search_maps_400_to_permanent_error() -> None:
    client = create_mock_client()
    client.search.side_effect = TransportError(
        400,
        "parsing_exception",
        {},
    )

    export_client = OpenSearchExportClient(client)

    with pytest.raises(PermanentOpenSearchError):
        export_client.search_page(
            pit_id="pit-123",
            keep_alive="10m",
            query={"match_all": {}},
            slice_id=0,
            slice_count=4,
            page_size=1000,
            search_after=None,
        )


def test_close_pit() -> None:
    client = create_mock_client()
    client.transport.perform_request.return_value = {
        "succeeded": True,
    }

    export_client = OpenSearchExportClient(client)

    result = export_client.close_pit("pit-123")

    assert result is True

    client.transport.perform_request.assert_called_once_with(
        method="DELETE",
        url="/_search/point_in_time",
        body={
            "pit_id": ["pit-123"],
        },
    )